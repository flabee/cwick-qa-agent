#!/usr/bin/env python3
"""
qa_agent.py — Universal QA automation agent for cwick demo hub

Pipeline:
  Login → BFS Discovery → Universal Health Checks → Targeted Checks → YAML Tests → Report

Technology:
  Playwright browser automation — deterministic, no AI/LLM APIs.

Architecture:
  QAAgent
  ├── StateGraph       — BFS state tracking (hash-based visited set + queue)
  ├── CoverageTracker  — metrics: pages, buttons, states, flows, bugs
  ├── YAMLRunner       — executes apps/{tenant}.yaml test steps
  └── Reporter         — writes bugs to Google Sheets + optional Drive upload

Env vars:
  TENANT_URL       — login page URL (required)
  TENANT_USERNAME  — login email (required)
  TENANT_PASSWORD  — login password (required)
  TENANT_NAME      — must match Excel sheet name (required)
  DRIVE_FOLDER_ID  — Drive folder for screenshots (optional)
  EXCEL_FILE_ID    — Google Sheets file ID (optional)
"""

import collections
import datetime
import hashlib
import json
import logging
import os
import pickle
import re
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

logging.basicConfig(
    format="[%(asctime)s] %(message)s",
    datefmt="%H:%M:%S",
    level=getattr(logging, os.getenv("QA_LOG_LEVEL", "INFO").upper()),
)
logger = logging.getLogger("qa_agent")

try:
    import yaml as _yaml
    _YAML_OK = True
except ImportError:
    _YAML_OK = False

# ── Environment ───────────────────────────────────────────────────────────────

TENANT_URL      = os.environ.get("TENANT_URL", "")
USERNAME        = os.environ.get("TENANT_USERNAME", "")
PASSWORD        = os.environ.get("TENANT_PASSWORD", "")
TENANT_NAME     = os.environ.get("TENANT_NAME", "Unknown")
DRIVE_FOLDER_ID = os.environ.get("DRIVE_FOLDER_ID", "")
EXCEL_FILE_ID   = os.environ.get("EXCEL_FILE_ID", "")

SESSION_DIR = Path(os.path.expanduser("~/cwick-qa-agent/session_output"))
SESSION_DIR.mkdir(parents=True, exist_ok=True)

APPS_DIR = Path(__file__).parent / "apps"

SHEET_MAP = {
    "Docupilot":              "Docupilot",
    "MaiHUB":                 "MaiHUB",
    "CFO AI":                 "CFO AI",
    "Rooms":                  "Rooms",
    "A33":                    "A33",
    "Tenant Base (Cwick Core)": "Tenant Base (Cwick Core)",
}

# Button priority keyword sets — used to sort buttons before clicking
_BTN_HIGH_KW = {"create", "generate", "export", "upload", "submit", "save",
                "add", "new", "invite", "download"}
_BTN_MED_KW  = {"edit", "view", "details", "open", "start"}
_BTN_LOW_KW  = {"cancel", "close", "back", "help", "info"}

# Keywords that signal high-value interactive flows (explored first/deeper)
PRIORITY_KW = _BTN_HIGH_KW

# Elements that would destroy the authenticated session — skip them
SKIP_KW = {"logout", "sign out", "log out", "signout", "exit", "delete account", "esci"}

# Text patterns that are always bugs when visible anywhere in the page body.
# (literal_string, human_description, severity)
BAD_TEXT_PATTERNS = [
    ("Invalid Date",            "Invalid Date displayed — broken date formatting",            "P1"),
    ("[object Object]",         "[object Object] in UI — JS object not serialised",           "P2"),
    ("NaN",                     "NaN value displayed — broken number or date calculation",    "P2"),
    ("undefined",               "Value 'undefined' leaked to UI",                             "P2"),
    # React / JS error patterns
    ("TypeError:",              "TypeError visible in UI — unhandled JS exception",           "P1"),
    ("ReferenceError:",         "ReferenceError visible in UI — unhandled JS exception",      "P1"),
    ("Unhandled Promise",       "Unhandled Promise rejection visible in UI",                  "P1"),
    # HTTP error status patterns
    ("404 Not Found",           "HTTP 404 error message visible in UI",                       "P1"),
    ("500 Internal Server",     "HTTP 500 error message visible in UI",                       "P0"),
    ("502 Bad Gateway",         "HTTP 502 error message visible in UI",                       "P0"),
    ("503 Service Unavailable", "HTTP 503 error message visible in UI",                       "P0"),
]

# Empty-state messages that may indicate missing data explanation
_EMPTY_STATE_RE = re.compile(
    r'\b(no data available|no results found|nothing here|nessun dato|nessun risultato)\b',
    re.IGNORECASE,
)

# Regex for untranslated i18n keys — matches patterns like "pagination.next_page"
# Pattern like "pagination.next_page" — second part must contain an underscore
# to distinguish real i18n keys from email domains (demo1@test.it) and URLs
_I18N_RE = re.compile(r'\b([a-z]{3,})\.([a-z]+(?:_[a-z]+)+)\b')

# ── Config ────────────────────────────────────────────────────────────────────

class Config:
    """Central configuration — all magic numbers in one place.

    BFS limits and log level can be overridden at runtime via env vars
    (e.g. QA_MAX_BFS_STATES=3 python3 qa_agent.py).
    """

    # BFS limits
    MAX_BFS_STATES   = int(os.getenv("QA_MAX_BFS_STATES",   "60"))
    MAX_NAV_ITEMS    = int(os.getenv("QA_MAX_NAV_ITEMS",    "16"))
    MAX_BTN_PER_PAGE = int(os.getenv("QA_MAX_BTN_PER_PAGE", "15"))

    # Playwright timeouts (milliseconds)
    TIMEOUT_LOAD        = 15000
    TIMEOUT_NETWORKIDLE = 10000
    TIMEOUT_INTERACTIVE = 5000
    TIMEOUT_MODAL       = 400

    # Sleep durations (seconds)
    SLEEP_LOGIN      = 3
    SLEEP_CLICK      = 2
    SLEEP_NAV        = 1.5
    SLEEP_MODAL      = 0.8
    SLEEP_CHAT       = 15

    # Test data
    TEST_EMAIL       = "demo@test.com"
    TEST_TEXT        = "QA Test Input"
    TEST_DOC_NAME    = "QA Test Document"
    TEST_CHAT_MSG    = "Hello, can you give me a brief summary of your capabilities?"
    TEST_SEARCH_TERM = "zzznoresultsxxx"
    WRONG_EMAIL      = "wrong@test.it"
    WRONG_PASSWORD   = "wrongpassword"


# ── State Graph ───────────────────────────────────────────────────────────────

class StateGraph:
    """
    BFS state graph for UI exploration.

    Each UI state = fingerprint(url + partial_dom).
    Tracks visited states to prevent infinite loops.
    Records edges (from_state → action → to_state) for coverage analysis.

    Exploration algorithm:
      queue ← {initial_state}
      while queue not empty and states < MAX_BFS_STATES:
          state ← pop_queue
          if visited: continue
          mark visited
          find available actions
          for each action:
              perform action → new_state
              if new_state not visited: enqueue
    """

    def __init__(self):
        self.visited: set   = set()
        self.queue          = collections.deque()
        self.edges: list    = []  # (from_fp, action_label, to_fp)

    def fingerprint(self, url: str, dom_snippet: str) -> str:
        """Stable 12-char hash of (normalized_url + partial_dom)."""
        norm = url.split("?")[0].split("#")[0].rstrip("/")
        key  = norm + "|" + dom_snippet[:200]
        return hashlib.md5(key.encode()).hexdigest()[:12]

    def is_visited(self, fp: str) -> bool:
        return fp in self.visited

    def mark_visited(self, fp: str):
        self.visited.add(fp)

    def enqueue(self, fp: str):
        if fp not in self.visited:
            self.queue.append(fp)

    def dequeue(self):
        return self.queue.popleft() if self.queue else None

    def record_edge(self, from_fp: str, action: str, to_fp: str):
        self.edges.append((from_fp, action, to_fp))

    def save(self, path: Path):
        """Persist visited set + edges to disk for session recovery."""
        with open(path, "wb") as f:
            pickle.dump({"visited": self.visited, "edges": self.edges}, f)

    def load(self, path: Path) -> bool:
        """Restore from disk. Returns True on success."""
        try:
            with open(path, "rb") as f:
                data = pickle.load(f)
            self.visited = data.get("visited", set())
            self.edges   = data.get("edges", [])
            return True
        except Exception:
            return False

# ── Coverage Tracker ──────────────────────────────────────────────────────────

class CoverageTracker:
    """Accumulates coverage metrics during the QA session."""

    def __init__(self):
        self.pages_discovered:    set = set()
        self.pages_tested:        set = set()
        self.nav_links_discovered: int = 0
        self.buttons_discovered:   int = 0
        self.buttons_clicked:      int = 0
        self.modals_opened:        int = 0
        self.forms_filled:         int = 0
        self.flows_explored:       int = 0
        self.states_visited:       int = 0

    def print_report(self, bug_count: int = 0):
        logger.info("")
        logger.info("=" * 50)
        logger.info("QA Coverage Report")
        logger.info("=" * 50)
        logger.info(f"Pages discovered:    {len(self.pages_discovered)}")
        logger.info(f"Pages tested:        {len(self.pages_tested)}")
        logger.info(f"Nav links found:     {self.nav_links_discovered}")
        logger.info(f"Buttons discovered:  {self.buttons_discovered}")
        logger.info(f"Buttons clicked:     {self.buttons_clicked}")
        logger.info(f"Modals handled:      {self.modals_opened}")
        logger.info(f"Forms tested:        {self.forms_filled}")
        logger.info(f"Flows explored:      {self.flows_explored}")
        logger.info(f"Unique states:       {self.states_visited}")
        logger.info(f"Bugs detected:       {bug_count}")
        logger.info("=" * 50)
        logger.info("")

    def save_json(self, path: Path, bug_count: int = 0):
        """Write coverage summary to session_output/coverage_summary.json."""
        data = {
            "tenant":              TENANT_NAME,
            "timestamp":           datetime.datetime.now().isoformat(),
            "pages_discovered":    len(self.pages_discovered),
            "pages_tested":        len(self.pages_tested),
            "nav_links_discovered": self.nav_links_discovered,
            "buttons_discovered":  self.buttons_discovered,
            "buttons_clicked":     self.buttons_clicked,
            "modals_handled":      self.modals_opened,
            "forms_tested":        self.forms_filled,
            "flows_explored":      self.flows_explored,
            "unique_states":       self.states_visited,
            "bugs_detected":       bug_count,
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

# ── Modal Handler ─────────────────────────────────────────────────────────────

class ModalHandler:
    """
    Detects and handles modal dialogs.

    Supports: role="dialog", aria-modal="true", .modal, [data-modal]

    When a modal opens:
      1. Record modal title
      2. Take a timestamped screenshot
      3. Fill simple non-destructive fields
      4. Close the modal and return to previous state
    """

    _DETECT_SELS = [
        "[role='dialog']:visible",
        "[aria-modal='true']:visible",
        "[class*='modal']:visible",
        "[data-modal]:visible",
    ]

    _CLOSE_SELS = [
        "[role='dialog'] button:has-text('Close')",
        "[role='dialog'] button:has-text('Cancel')",
        "[role='dialog'] button:has-text('Chiudi')",
        "[role='dialog'] button:has-text('Annulla')",
        "[role='dialog'] [aria-label*='close' i]",
        "[aria-modal='true'] button:has-text('Close')",
        "[aria-modal='true'] [aria-label*='close' i]",
        "[class*='modal'] button:has-text('Close')",
        "[class*='modal'] button:has-text('Cancel')",
        "[class*='modal'] [aria-label*='close' i]",
        "[class*='overlay'] button",
    ]

    def detect(self, page) -> bool:
        for sel in self._DETECT_SELS:
            try:
                if page.locator(sel).count() > 0:
                    return True
            except Exception:
                pass
        return False

    def title(self, page) -> str:
        for sel in [
            "[role='dialog'] :is(h1,h2,h3)",
            "[aria-modal='true'] :is(h1,h2,h3)",
            "[class*='modal'] :is(h1,h2,h3,[class*='title'])",
        ]:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=400):
                    return el.inner_text().strip()[:60]
            except Exception:
                pass
        return "modal"

    def screenshot(self, page, label: str) -> str:
        ts    = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
        fname = f"{ts}_modal_{re.sub(r'[^a-z0-9]', '_', label.lower()[:30])}.png"
        try:
            page.screenshot(path=str(SESSION_DIR / fname))
        except Exception:
            fname = ""
        return fname

    def handle(self, page, coverage: "CoverageTracker") -> bool:
        """Screenshot, fill safe fields, then close. Returns True if modal found."""
        if not self.detect(page):
            return False
        lbl = self.title(page)
        self.screenshot(page, lbl)
        coverage.modals_opened += 1
        # Fill simple text / email fields inside the modal (non-destructive)
        for container in ["[role='dialog']", "[aria-modal='true']", "[class*='modal']"]:
            try:
                modal = page.locator(container).first
                if not modal.is_visible(timeout=300):
                    continue
                for inp in modal.locator("input[type='text'],input[type='email'],textarea").all():
                    try:
                        if not inp.is_visible(timeout=300):
                            continue
                        aria = (inp.get_attribute("aria-label") or "").lower()
                        name = (inp.get_attribute("name") or "").lower()
                        if any(k in aria + name for k in ("delete", "remove", "destroy")):
                            continue
                        t = inp.get_attribute("type") or "text"
                        inp.fill(Config.TEST_EMAIL if t == "email" else Config.TEST_TEXT)
                    except Exception:
                        pass
                break
            except Exception:
                pass
        self.close(page)
        return True

    def close(self, page):
        for sel in self._CLOSE_SELS:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=400):
                    el.click()
                    time.sleep(0.8)
                    return
            except Exception:
                pass
        try:
            page.keyboard.press("Escape")
            time.sleep(0.8)
        except Exception:
            pass


# ── Form Handler ──────────────────────────────────────────────────────────────

class FormHandler:
    """
    Safely fills forms with test data.

    Supported fields:
      input[type=text]   → "QA Test Input"
      input[type=email]  → "demo@test.com"
      input[type=number] → "1"
      textarea           → "Automated QA input"
      select             → first non-empty option

    Never fills fields whose label contains: delete / remove / destroy.
    """

    _DEFAULTS = {"text": Config.TEST_TEXT, "email": Config.TEST_EMAIL,
                 "number": "1", "search": "QA search"}
    _SKIP_KW  = {"delete", "remove", "destroy"}

    def fill(self, page, form_sel: str = "form", coverage: "CoverageTracker" = None) -> bool:
        """Fill all safe fields in a form. Returns True if any field was filled."""
        filled = False
        try:
            form = page.locator(form_sel).first
            if not form.is_visible(timeout=800):
                return False

            # text / email / number / search inputs
            for inp_type, default in self._DEFAULTS.items():
                for inp in form.locator(f"input[type='{inp_type}']").all():
                    try:
                        if not inp.is_visible(timeout=300):
                            continue
                        label = self._label(page, inp).lower()
                        if any(k in label for k in self._SKIP_KW):
                            continue
                        inp.fill(default)
                        filled = True
                    except Exception:
                        pass

            # bare text inputs (no type attribute)
            for inp in form.locator("input:not([type])").all():
                try:
                    if inp.is_visible(timeout=300):
                        inp.fill(Config.TEST_TEXT)
                        filled = True
                except Exception:
                    pass

            # textareas
            for ta in form.locator("textarea").all():
                try:
                    if ta.is_visible(timeout=300):
                        ta.fill(Config.TEST_TEXT)
                        filled = True
                except Exception:
                    pass

            # selects — pick first non-trivial option
            for sel_el in form.locator("select").all():
                try:
                    if not sel_el.is_visible(timeout=300):
                        continue
                    for opt in sel_el.locator("option").all():
                        val = opt.get_attribute("value") or ""
                        if val and val not in ("", "0", "null", "undefined", "none"):
                            sel_el.select_option(value=val)
                            filled = True
                            break
                except Exception:
                    pass

        except Exception:
            pass
        if filled and coverage:
            coverage.forms_filled += 1
        return filled

    def _label(self, page, inp) -> str:
        try:
            inp_id = inp.get_attribute("id")
            if inp_id:
                lbl = page.locator(f"label[for='{inp_id}']")
                if lbl.count() > 0:
                    return lbl.first.inner_text()
            return (inp.get_attribute("placeholder") or "") + \
                   (inp.get_attribute("aria-label") or "") + \
                   (inp.get_attribute("name") or "")
        except Exception:
            return ""


# ── QA Agent ──────────────────────────────────────────────────────────────────

class QAAgent:
    """
    Universal QA agent. Runs completely offline — no AI/LLM APIs.

    Phases:
      1. Login
      2. BFS exploration (state-graph-driven)
      3. Universal health checks (per page)
      4. Targeted deterministic checks (6 fixed checks)
      5. YAML test cases (if apps/{tenant}.yaml exists)
      6. Report (Google Sheets + Drive, or local log)
    """

    def __init__(self):
        self.bugs:           list  = []
        self.drive_svc             = None
        self.sheet_svc             = None
        self.protected_url:  str   = ""
        self.home_url:       str   = ""
        self.tenant_domain:  str   = ""   # set from TENANT_URL at runtime
        self.state_graph           = StateGraph()
        self.coverage              = CoverageTracker()
        self.modal_handler         = ModalHandler()
        self.form_handler          = FormHandler()
        self.console_errors: list  = []

    # ── Logging ───────────────────────────────────────────────────────────────

    def log(self, msg: str):
        logger.info(msg)

    # ── Google Auth ───────────────────────────────────────────────────────────

    def init_google(self) -> bool:
        tpath = Path(os.path.expanduser("~/cwick-qa-agent/token.pickle"))
        if not tpath.exists():
            return False
        try:
            from googleapiclient.discovery import build
            with open(tpath, "rb") as f:
                creds = pickle.load(f)
            self.drive_svc = build("drive",  "v3", credentials=creds)
            self.sheet_svc = build("sheets", "v4", credentials=creds)
            return True
        except Exception as e:
            self.log(f"Google auth failed: {e}")
            return False

    # ── Bug Capture ───────────────────────────────────────────────────────────

    def capture_bug(self, page, issue: str, reproduce: str, prio: str, note: str = ""):
        """Record a bug, deduplicating by Jaccard similarity on word sets."""
        norm_new = set(re.sub(r"[^a-z0-9 ]", "", issue.lower()).split())
        for b in self.bugs:
            norm_ex = set(re.sub(r"[^a-z0-9 ]", "", b["issue"].lower()).split())
            if norm_new and norm_ex:
                jaccard = len(norm_new & norm_ex) / len(norm_new | norm_ex)
                if jaccard > 0.50:
                    return  # already reported

        bid   = len(self.bugs) + 1
        ts    = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
        slug  = re.sub(r"[^a-z0-9]", "_", issue.lower()[:30])
        fname = f"{ts}_bug_{prio}_{slug}.png"
        try:
            page.screenshot(path=str(SESSION_DIR / fname))
        except Exception:
            fname = f"BUG_{bid:03d}_{prio}.png"  # fallback name

        self.bugs.append({
            "id": bid, "issue": issue, "reproduce": reproduce,
            "prio": prio, "note": note, "screenshot": fname, "link": "",
        })
        self.log(f"  [BUG {prio}] {issue}")

    # ── URL / Selector Helpers ─────────────────────────────────────────────────

    def norm_url(self, url: str) -> str:
        return url.split("?")[0].split("#")[0].rstrip("/")

    def _dom_snippet(self, page) -> str:
        """
        Rich DOM snapshot used for state fingerprinting.
        Includes: page title, first h1/h2, visible button count, form count, body snippet.
        This lets the fingerprint distinguish semantically different states that share a URL.
        """
        try:
            title = ""
            h1    = ""
            btn_n = 0
            frm_n = 0
            body  = ""
            try:
                title = page.title()[:50]
            except Exception:
                pass
            try:
                h1 = page.locator("h1,h2").first.inner_text()[:40]
            except Exception:
                pass
            try:
                btn_n = page.locator("button:visible").count()
            except Exception:
                pass
            try:
                frm_n = page.locator("form").count()
            except Exception:
                pass
            try:
                body = page.locator("body").inner_html()[:200]
            except Exception:
                pass
            return f"{title}|{h1}|{btn_n}|{frm_n}|{body}"
        except Exception:
            return ""

    # ── Navigation ────────────────────────────────────────────────────────────

    def nav_to(self, page, keywords: list):
        """Click first nav item matching any keyword. Returns matched keyword or None."""
        for kw in keywords:
            for sel in [
                f"nav :is(button,a):has-text('{kw}')",
                f"aside :is(button,a):has-text('{kw}')",
                f"[role='navigation'] :is(button,a):has-text('{kw}')",
                f"[class*='sidebar'] :is(button,a):has-text('{kw}')",
                f"[class*='menu'] :is(button,a):has-text('{kw}')",
            ]:
                try:
                    el = page.locator(sel).first
                    if el.is_visible(timeout=1000):
                        el.click()
                        page.wait_for_load_state("networkidle", timeout=10000)
                        time.sleep(1.5)
                        self.log(f"  -> Navigated to '{kw}' at {page.url}")
                        return kw
                except Exception:
                    pass
        return None

    def _click_nav(self, page, name: str) -> bool:
        """Click a nav item by exact name. Returns True on success."""
        for sel in [
            f"nav :is(button,a):has-text('{name}')",
            f"aside :is(button,a):has-text('{name}')",
            f"[role='navigation'] :is(button,a):has-text('{name}')",
            f"[class*='sidebar'] :is(button,a):has-text('{name}')",
            f"[class*='menu'] :is(button,a):has-text('{name}')",
            f"header :is(button,a):has-text('{name}')",
        ]:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=800):
                    el.click()
                    page.wait_for_load_state("networkidle", timeout=8000)
                    time.sleep(1.5)
                    return True
            except Exception:
                pass
        return False

    # Selector covers English and Italian login/submit buttons
    _LOGIN_BTN_SEL = (
        ":is(button,[role='button'],[type='submit']):is("
        ":has-text('Sign in'),:has-text('Login'),:has-text('Log in'),"
        ":has-text('Accedi'),:has-text('Entra'),:has-text('Inizia'),"
        ":has-text('Invia'),:has-text('Continua'))"
    )

    def _login(self, page, conditional: bool = False):
        """
        Perform (or conditionally perform) login.

        conditional=False: always fill credentials and click — used at session start.
        conditional=True:  only re-login if the current URL contains 'login' and
                           the email input is visible — used before YAML tests.
        """
        if conditional:
            page.goto(TENANT_URL)
            page.wait_for_load_state("networkidle", timeout=Config.TIMEOUT_NETWORKIDLE)
            time.sleep(2)
            if not ("login" in page.url
                    and page.locator("input[type='email']").count() > 0):
                self.log("  Already authenticated — skipping re-login")
                return

        page.goto(TENANT_URL)
        page.locator("input[type='email']").fill(USERNAME)
        page.locator("input[type='password']").fill(PASSWORD)
        btn = page.locator(self._LOGIN_BTN_SEL)
        if btn.count() > 0:
            btn.first.click()
        else:
            page.locator("button[type='submit'], input[type='submit']").first.click()
        try:
            page.wait_for_url(lambda u: "login" not in u, timeout=Config.TIMEOUT_LOAD)
        except Exception:
            self.log("WARNING: URL still contains 'login' after submit — login may have failed")
        page.wait_for_load_state("networkidle", timeout=Config.TIMEOUT_LOAD)
        time.sleep(Config.SLEEP_LOGIN)

    def _discover_nav_items(self, page) -> list:
        """Return list of visible nav item labels (deduplicated)."""
        found = {}
        for sel in [
            "nav :is(button,a)",
            "aside :is(button,a)",
            "[role='navigation'] :is(button,a)",
            "[class*='sidebar'] :is(button,a)",
            "[class*='menu'] :is(button,a)",
            "header :is(button,a)",
        ]:
            for el in page.locator(sel).all():
                try:
                    text = el.inner_text().strip().split("\n")[0].strip()
                    if text and 1 < len(text) < 50 and text not in found:
                        found[text] = el
                except Exception:
                    pass
        return list(found.keys())

    def _goto(self, page, url: str) -> bool:
        """Navigate to URL, enforcing same-domain constraint. Returns True on success."""
        # Domain safety: only navigate within the tenant's domain
        if self.tenant_domain:
            dest_domain = urlparse(url).netloc
            if dest_domain and dest_domain != self.tenant_domain:
                self.log(f"  Blocked cross-domain navigation to {url}")
                return False
        try:
            page.goto(url)
            page.wait_for_load_state("networkidle", timeout=10000)
            time.sleep(1.5)
            return True
        except Exception:
            ts    = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
            fname = f"{ts}_nav_fail_{re.sub(r'[^a-z0-9]', '_', url[-30:])}.png"
            try:
                page.screenshot(path=str(SESSION_DIR / fname))
            except Exception:
                pass
            return False

    # ── Bad Content Scanner ───────────────────────────────────────────────────

    def _scan_bad_content(self, page, label: str):
        """
        Scan visible page text for patterns that are always bugs:
          - Known JS leak values: Invalid Date, [object Object], NaN, undefined
          - Untranslated i18n keys: e.g. "pagination.next_page"

        Called from check_page_health (every new state) AND after every BFS click.
        """
        try:
            body_text = page.locator("body").inner_text()
        except Exception:
            return

        # Literal bad patterns
        for literal, description, prio in BAD_TEXT_PATTERNS:
            if literal in body_text:
                self.capture_bug(
                    page,
                    f"{description} on '{label}'",
                    f"1. Navigate to {page.url}\n2. Page body contains: '{literal}'",
                    prio, f"Bad content pattern: {literal}",
                )

        # i18n key leaks — look for "word.word_word" that aren't URLs or decimals
        # Exclude lines that look like URLs (contain ://) or file paths
        for line in body_text.splitlines():
            line = line.strip()
            if "://" in line or len(line) > 120:
                continue
            for m in _I18N_RE.finditer(line):
                key = m.group(0)
                # Skip known false positives: version numbers, common abbreviations
                if re.match(r'\d', key) or key in ("e.g", "i.e", "vs.the"):
                    continue
                self.capture_bug(
                    page,
                    f"Untranslated i18n key visible on '{label}': '{key}'",
                    f"1. Navigate to {page.url}\n2. UI shows raw translation key: '{key}'",
                    "P2", "i18n key not resolved — missing translation",
                )
                break  # one i18n bug per page is enough

        # Empty state without explanation (only flag if page is otherwise thin)
        m = _EMPTY_STATE_RE.search(body_text)
        if m and len(body_text.strip()) < 300:
            self.capture_bug(
                page,
                f"Empty state without context on '{label}': '{m.group(0)}'",
                f"1. Navigate to {page.url}\n2. Page shows empty state with no action or explanation",
                "P3", "Empty state should include a helpful message or call-to-action",
            )

    # ── Universal Health Checks ───────────────────────────────────────────────

    def check_page_health(self, page, label: str):
        """
        Run deterministic health checks on the current page.
        Checks: blank page, JS errors, visible error states, infinite spinner, 404/500.
        """
        url = page.url

        # 1. Blank page (< 30 chars of text content)
        try:
            body_text = page.locator("body").inner_text().strip()
            if len(body_text) < 30:
                self.capture_bug(
                    page,
                    f"Blank page: '{label}'",
                    f"1. Navigate to {url}\n2. Page renders with almost no content",
                    "P1", "Page may have a rendering or data-load failure",
                )
        except Exception:
            pass

        # 2. Console JS errors captured during session
        js_errors = [e for e in self.console_errors if e.get("url") == url]
        for err in js_errors[:2]:
            self.capture_bug(
                page,
                f"Console error on '{label}': {err['text'][:80]}",
                f"1. Navigate to {url}\n2. Open browser console\n3. JS error: {err['text'][:120]}",
                "P2", "JavaScript error may impact functionality",
            )

        # 3. Visible error message in the UI
        try:
            err_els = page.locator(
                ":is([class*='error'],[class*='Error'],[role='alert']):visible"
            )
            if err_els.count() > 0:
                err_text = err_els.first.inner_text().strip()[:100]
                if any(w in err_text.lower() for w in ["error", "fail", "exception", "500", "404"]):
                    self.capture_bug(
                        page,
                        f"Error message visible on '{label}': {err_text}",
                        f"1. Navigate to {url}\n2. Visible error message: '{err_text}'",
                        "P1", "Unexpected error state shown to user",
                    )
        except Exception:
            pass

        # 4. Infinite loading spinner (still spinning after 3s)
        try:
            spinner = page.locator(
                ":is([class*='loading'],[class*='spinner'],[class*='skeleton']):visible"
            )
            if spinner.count() > 0:
                time.sleep(3)
                if spinner.count() > 0:
                    self.capture_bug(
                        page,
                        f"Infinite loading spinner on '{label}'",
                        f"1. Navigate to {url}\n2. Loading spinner visible after 3+ seconds",
                        "P1", "Page may be stuck in loading state",
                    )
        except Exception:
            pass

        # 5. 404 / 500 content in page body
        try:
            body_text = page.locator("body").inner_text()
            if re.search(r"\b404\b|\b500\b|page not found|server error", body_text, re.I):
                self.capture_bug(
                    page,
                    f"Error page content on '{label}'",
                    f"1. Navigate to {url}\n2. Page body contains 404/500 or error message",
                    "P1", "Page may not exist or server encountered an error",
                )
        except Exception:
            pass

        # 6. Bad content scan (JS leaks, i18n keys)
        self._scan_bad_content(page, label)

    # ── BFS Exploration ───────────────────────────────────────────────────────

    def bfs_explore(self, page, start_url: str):
        """
        BFS state-graph exploration of the app.

        Algorithm:
          1. Navigate to start_url (home after login)
          2. Discover all top-level nav items
          3. Visit each nav section, fingerprint its state
          4. Per section: explore tabs, sub-nav, first list item, action buttons
          5. Each newly discovered state → mark visited, run health checks
          6. Stop when MAX_BFS_STATES reached or all reachable states visited
        """
        self.log("=== BFS EXPLORATION ===")

        # Home state
        self._goto(page, start_url)
        fp0 = self.state_graph.fingerprint(page.url, self._dom_snippet(page))
        self.state_graph.mark_visited(fp0)
        self.coverage.states_visited += 1
        self.coverage.pages_discovered.add(self.norm_url(page.url))
        self.check_page_health(page, "home")

        # Discover nav items (skip auth-destroying ones)
        all_nav = self._discover_nav_items(page)
        nav_items = [n for n in all_nav[:Config.MAX_NAV_ITEMS]
                     if not any(s in n.lower() for s in SKIP_KW)]
        self.coverage.nav_links_discovered = len(all_nav)
        self.log(f"Nav items: {nav_items}")

        # Visit every top-level nav section
        section_urls: dict = {}
        for name in nav_items:
            if self.coverage.states_visited >= Config.MAX_BFS_STATES:
                break
            if self._click_nav(page, name):
                url = page.url
                section_urls[name] = url
                self.coverage.pages_discovered.add(self.norm_url(url))
                self.coverage.pages_tested.add(self.norm_url(url))

                fp = self.state_graph.fingerprint(url, self._dom_snippet(page))
                if not self.state_graph.is_visited(fp):
                    self.state_graph.mark_visited(fp)
                    self.coverage.states_visited += 1
                    self.check_page_health(page, name)

                # Count buttons on this page for coverage
                try:
                    self.coverage.buttons_discovered += page.locator(
                        ":is(button,[role='button']):visible"
                    ).count()
                except Exception:
                    pass

        # Deep-dive each section
        for section_name, section_url in section_urls.items():
            if self.coverage.states_visited >= Config.MAX_BFS_STATES:
                self.log(f"BFS limit ({Config.MAX_BFS_STATES} states) reached — stopping.")
                break
            self._explore_section(page, section_name, section_url)

        self.log(
            f"BFS complete — {self.coverage.states_visited} states, "
            f"{len(self.coverage.pages_discovered)} pages discovered"
        )

    def _explore_section(self, page, section_name: str, section_url: str):
        """
        Deep exploration of one app section.
        Sub-phases: (a) tabs, (b) admin sub-nav, (c) first list item detail, (d) action buttons.
        """
        if not self._goto(page, section_url):
            return

        # ── (a) Tabs / sub-nav ────────────────────────────────────────────────
        try:
            tabs = page.locator(
                "[role='tab']:visible, "
                "[class*='tab']:not([class*='table']):not([class*='tabindex']):visible"
            ).all()[:6]
            for tab in tabs:
                if self.coverage.states_visited >= Config.MAX_BFS_STATES:
                    break
                try:
                    tab_text = tab.inner_text().strip()[:30]
                    if not tab_text:
                        continue
                    tab.click()
                    time.sleep(1.5)
                    fp = self.state_graph.fingerprint(page.url, self._dom_snippet(page))
                    if not self.state_graph.is_visited(fp):
                        self.state_graph.mark_visited(fp)
                        self.coverage.states_visited += 1
                        self.coverage.pages_tested.add(self.norm_url(page.url))
                        self.check_page_health(page, f"{section_name} › {tab_text}")
                except Exception:
                    pass
        except Exception:
            pass

        # ── (b) Admin / secondary sub-nav links ───────────────────────────────
        self._goto(page, section_url)
        try:
            sub_links = page.locator(
                "[class*='sub'] :is(a,button):visible, "
                "[class*='admin'] :is(a,button):visible"
            ).all()[:6]
            for link in sub_links:
                if self.coverage.states_visited >= Config.MAX_BFS_STATES:
                    break
                try:
                    text = link.inner_text().strip()[:30]
                    if not text or any(s in text.lower() for s in SKIP_KW):
                        continue
                    link.click()
                    page.wait_for_load_state("networkidle", timeout=8000)
                    time.sleep(1.5)
                    fp = self.state_graph.fingerprint(page.url, self._dom_snippet(page))
                    if not self.state_graph.is_visited(fp):
                        self.state_graph.mark_visited(fp)
                        self.coverage.states_visited += 1
                        self.coverage.pages_discovered.add(self.norm_url(page.url))
                        self.check_page_health(page, f"{section_name} › {text}")
                    self._goto(page, section_url)
                except Exception:
                    pass
        except Exception:
            pass

        # ── (c) First list item → detail view ────────────────────────────────
        self._goto(page, section_url)
        detail_selectors = [
            "tbody tr:first-child",
            "[class*='list-item']:first-child",
            "[class*='list'] [class*='item']:first-child",
            "[class*='card']:first-child",
            "ul:not([class*='nav']) li:first-child a",
        ]
        for sel in detail_selectors:
            if self.coverage.states_visited >= MAX_BFS_STATES:
                break
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=800):
                    el.click()
                    page.wait_for_load_state("networkidle", timeout=8000)
                    time.sleep(1.5)
                    if self.norm_url(page.url) != self.norm_url(section_url):
                        fp = self.state_graph.fingerprint(page.url, self._dom_snippet(page))
                        if not self.state_graph.is_visited(fp):
                            self.state_graph.mark_visited(fp)
                            self.coverage.states_visited += 1
                            self.coverage.pages_discovered.add(self.norm_url(page.url))
                            self.check_page_health(page, f"{section_name} › detail")
                        # Check sub-tabs inside detail view
                        detail_tabs = page.locator("[role='tab']:visible").all()[:4]
                        for dt in detail_tabs:
                            if self.coverage.states_visited >= Config.MAX_BFS_STATES:
                                break
                            try:
                                dt_text = dt.inner_text().strip()[:20]
                                dt.click()
                                time.sleep(1)
                                fp2 = self.state_graph.fingerprint(page.url, self._dom_snippet(page))
                                if not self.state_graph.is_visited(fp2):
                                    self.state_graph.mark_visited(fp2)
                                    self.coverage.states_visited += 1
                                    self.check_page_health(page, f"{section_name} › detail › {dt_text}")
                            except Exception:
                                pass
                    break
            except Exception:
                pass

        # ── (d) Click all visible non-nav interactive elements ───────────────────
        # No keyword filtering — collect everything on the page that isn't a nav
        # item or a destructive action, then click each one and record the outcome.
        self._goto(page, section_url)
        try:
            seen_handles = set()
            candidates   = []

            for el in page.locator(":is(button,[role='button']):visible").all()[:30]:
                try:
                    # Skip if inside nav / sidebar
                    in_nav = el.evaluate(
                        "e => !!e.closest('nav,aside,[class*=\"sidebar\"],[class*=\"navbar\"]')"
                    )
                    if in_nav:
                        continue
                    text = (el.inner_text().strip() or el.get_attribute("aria-label") or "")
                    if any(s in text.lower() for s in SKIP_KW):
                        continue
                    # Skip hidden file inputs
                    tag = el.evaluate("e => e.tagName.toLowerCase()")
                    if tag == "input":
                        inp_type = el.evaluate("e => e.type || ''")
                        if inp_type == "file":
                            self.coverage.buttons_clicked += 1
                            self.log(f"  [{section_name}] file upload input found — skipped")
                            continue
                    h = el.evaluate("e => e.outerHTML")[:80]
                    if h not in seen_handles:
                        seen_handles.add(h)
                        candidates.append((text[:30] or tag, el))
                except Exception:
                    pass

            # Priority-sort: HIGH (create/generate/…) → MED (edit/view/…) → LOW (cancel/…)
            def _btn_score(item):
                t = item[0].lower()
                if any(k in t for k in _BTN_HIGH_KW): return 0
                if any(k in t for k in _BTN_MED_KW):  return 1
                return 2
            candidates.sort(key=_btn_score)

            self.log(f"  [{section_name}] {len(candidates)} clickable element(s) found")

            for btn_text, btn in candidates[:Config.MAX_BTN_PER_PAGE]:
                if self.coverage.states_visited >= Config.MAX_BFS_STATES:
                    break
                try:
                    # Build an actionable label: prefer text, fall back to aria-label / class
                    aria  = btn.get_attribute("aria-label") or ""
                    cls   = (btn.get_attribute("class") or "")[:30]
                    label = (btn_text or aria or cls or "button").strip()[:40]
                    full_label = f"{section_name} › {label}"

                    pre_url = page.url
                    btn.click()
                    time.sleep(2)
                    try:
                        page.wait_for_load_state("networkidle", timeout=5000)
                    except Exception:
                        pass

                    # Always scan for bad content on the resulting state
                    self._scan_bad_content(page, full_label)

                    if self.norm_url(page.url) != self.norm_url(pre_url):
                        # Navigated to a new page
                        fp = self.state_graph.fingerprint(page.url, self._dom_snippet(page))
                        if not self.state_graph.is_visited(fp):
                            self.state_graph.mark_visited(fp)
                            self.coverage.states_visited += 1
                            self.coverage.pages_discovered.add(self.norm_url(page.url))
                            self.check_page_health(page, full_label)
                        self.coverage.flows_explored += 1
                        self._goto(page, section_url)
                    else:
                        # Check for modal — use ModalHandler for screenshot + tracking
                        if self.modal_handler.detect(page):
                            modal_lbl = self.modal_handler.title(page)
                            modal_dom = ""
                            try:
                                modal_dom = page.locator(
                                    "[role='dialog']:visible,[class*='modal']:visible"
                                ).first.inner_html()[:300]
                            except Exception:
                                pass
                            fp = self.state_graph.fingerprint(
                                f"{page.url}#modal#{label}", modal_dom
                            )
                            if not self.state_graph.is_visited(fp):
                                self.state_graph.mark_visited(fp)
                                self.coverage.states_visited += 1
                                self.coverage.flows_explored += 1
                            # screenshot + fill safe fields + close
                            self.modal_handler.handle(page, self.coverage)

                    self.coverage.buttons_clicked += 1
                except Exception:
                    pass
        except Exception:
            pass

        # ── (e) User / profile menu ───────────────────────────────────────────
        self._goto(page, section_url)
        for trigger in [
            "[class*='avatar']:visible",
            "[class*='user-menu']:visible",
            "[class*='profile']:visible",
            "[aria-label*='user' i]:visible",
            "[aria-label*='account' i]:visible",
            "header button:last-child",
        ]:
            try:
                el = page.locator(trigger).first
                if el.is_visible(timeout=500):
                    el.click()
                    time.sleep(1)
                    dropdown = page.locator("[class*='dropdown']:visible, [class*='menu']:visible")
                    if dropdown.count() > 0:
                        fp = self.state_graph.fingerprint(
                            f"{page.url}#usermenu", self._dom_snippet(page)
                        )
                        if not self.state_graph.is_visited(fp):
                            self.state_graph.mark_visited(fp)
                            self.coverage.states_visited += 1
                        page.keyboard.press("Escape")
                        time.sleep(0.5)
                    break
            except Exception:
                pass

    # ── Targeted Checks ───────────────────────────────────────────────────────

    def run_targeted_checks(self, page, browser):
        """
        Six deterministic targeted checks applied to every tenant.

          1. Wrong credentials → no error message (P0)
          2. Create / New document flow (P1/P2)
          3. Knowledge Base — empty state and "Use as base" (P1/P2)
          4. Chat / AI Assistant — input present, response received (P1)
          5. Search empty state — misleading or missing message (P2/P3)
          6. Logout + auth guard bypass (P0/P1)
        """

        # ── CHECK 1: Wrong credentials ────────────────────────────────────────
        self.log("Check 1: Wrong credentials")
        try:
            anon      = browser.new_context()
            anon_page = anon.new_page()
            anon_page.goto(TENANT_URL)
            anon_page.locator("input[type='email']").fill(Config.WRONG_EMAIL)
            anon_page.locator("input[type='password']").fill(Config.WRONG_PASSWORD)
            _anon_btn = anon_page.locator(self._LOGIN_BTN_SEL)
            if _anon_btn.count() > 0:
                _anon_btn.first.click()
            else:
                anon_page.locator("button[type='submit'], input[type='submit']").first.click()
            time.sleep(3)
            still_on_login = (
                "login" in anon_page.url
                or self.norm_url(anon_page.url) == self.norm_url(TENANT_URL)
            )
            if still_on_login:
                error_visible = anon_page.locator(
                    ":is(.error,[class*='error'],[class*='alert'],[role='alert'],"
                    "[class*='invalid'],[class*='warning']):visible"
                ).count() > 0
                if not error_visible:
                    self.capture_bug(
                        anon_page,
                        "Wrong credentials: no error message shown",
                        "1. Go to login page\n2. Enter wrong email/password\n"
                        "3. Click Sign in\n4. No error message appears",
                        "P0", "Security: user gets no feedback on bad credentials",
                    )
            anon_page.close()
            anon.close()
        except Exception as e:
            self.log(f"  Check 1 error: {e}")

        # ── CHECK 2: Create / document creation flow ──────────────────────────
        self.log("Check 2: Create new / document creation flow")
        try:
            self.nav_to(page, ["Dashboard", "Documents", "Home"])
            time.sleep(1)

            new_btn = page.locator(
                ":is(button,[role='button']):has-text('New'),"
                ":is(button,[role='button']):has-text('Create'),"
                "a:has-text('New')"
            ).first
            found_new = False
            try:
                found_new = new_btn.is_visible(timeout=2000)
            except Exception:
                pass

            if not found_new:
                matched = self.nav_to(page, ["New", "Generate", "Create", "New document"])
                found_new = matched is not None

            if found_new:
                try:
                    new_btn.click(timeout=3000)
                    page.wait_for_load_state("networkidle", timeout=10000)
                    time.sleep(2)
                except Exception:
                    pass
                self._test_creation_flow(page)
            else:
                self.log("  No New/Create button found in nav — skipping creation flow check")
        except Exception as e:
            self.log(f"  Check 2 error: {e}")

        # ── CHECK 3: Knowledge Base ───────────────────────────────────────────
        self.log("Check 3: Knowledge Base")
        try:
            kb = self.nav_to(
                page, ["Knowledge Base", "Knowledge base", "KB", "Library", "Resources"]
            )
            if kb:
                items = page.locator(
                    "[class*='list'] [class*='item'], [class*='card'], "
                    "[class*='row'], li:not([class*='nav']), tbody tr"
                ).count()
                if items == 0:
                    body_text = page.locator("body").inner_text()
                    if not any(w in body_text.lower() for w in ["empty", "no ", "0 "]):
                        self.capture_bug(
                            page,
                            "Knowledge Base: section loads with no items and no empty-state message",
                            f"1. Log in\n2. Click '{kb}' in nav\n3. Section is blank with no explanation",
                            "P2", "May be a data-load issue",
                        )
                else:
                    first_item = page.locator(
                        "[class*='card']:first-child, [class*='item']:first-child, "
                        "li:first-child a, tbody tr:first-child td"
                    ).first
                    try:
                        if first_item.is_visible(timeout=2000):
                            first_item.click()
                            time.sleep(2)
                    except Exception:
                        pass

                    use_btn = page.locator(
                        ":is(button,[role='button']):has-text('Use'),"
                        ":is(button,[role='button']):has-text('Use as base'),"
                        ":is(button,[role='button']):has-text('Generate from'),"
                        ":is(button,[role='button']):has-text('Select')"
                    )
                    if use_btn.count() > 0:
                        use_btn.first.click()
                        time.sleep(2)
                        form_visible = page.locator(
                            "[class*='modal'], [class*='dialog'], form, input[type='text']:visible"
                        ).count() > 0
                        if not form_visible:
                            self.capture_bug(
                                page,
                                "Knowledge Base: 'Use as base' opens no dialog or form",
                                f"1. Go to '{kb}'\n2. Click 'Use as base'\n3. No dialog/form appears",
                                "P1", "Cannot initiate KB-based document creation",
                            )
            else:
                self.log("  No Knowledge Base section found — skipping")
        except Exception as e:
            self.log(f"  Check 3 error: {e}")

        # ── CHECK 4: Chat / AI Assistant ──────────────────────────────────────
        self.log("Check 4: Chat / AI Assistant")
        try:
            chat = self.nav_to(
                page, ["Chat", "AI Chat", "Copilot", "Assistant", "Messages", "AI Assistant"]
            )
            if chat:
                chat_input = page.locator(
                    "textarea, [contenteditable='true'], "
                    "input[placeholder*='message' i], input[placeholder*='ask' i], "
                    "input[placeholder*='type' i], input[placeholder*='search' i], "
                    "input[placeholder*='cerca' i], input[placeholder*='chiedi' i], "
                    "input[type='text']:visible, input[type='search']:visible"
                )
                if chat_input.count() == 0:
                    self.capture_bug(
                        page,
                        f"Chat: no message input found in '{chat}' section",
                        f"1. Log in\n2. Navigate to '{chat}'\n3. No text input visible",
                        "P1", "Chat section has no message input — core functionality broken",
                    )
                else:
                    chat_input.first.fill(Config.TEST_CHAT_MSG)
                    send_btn = page.locator(
                        ":is(button,[role='button']):has-text('Send'),"
                        ":is(button,[role='button']):has-text('Submit'),"
                        "button[type='submit'], [aria-label*='send' i]"
                    )
                    if send_btn.count() > 0:
                        send_btn.first.click()
                    else:
                        chat_input.first.press("Enter")
                    # Wait up to SLEEP_CHAT seconds for streaming to start or finish
                    time.sleep(Config.SLEEP_CHAT)
                    response_visible = page.locator(
                        "[class*='message']:not([class*='user']), [class*='response'],"
                        "[class*='assistant'], [class*='bot'], [class*='ai-message'],"
                        "[class*='Ricerca'], :has-text('Ricerca documenti')"
                    ).count() > 0
                    still_loading = page.locator(
                        "[class*='loading'], [class*='spinner'], [class*='typing'], [class*='streaming'],"
                        ":has-text('Generazione in corso'), :has-text('Ricerca documenti')"
                    ).count() > 0
                    if not response_visible and not still_loading:
                        self.capture_bug(
                            page,
                            f"Chat: no response after sending a message",
                            f"1. Navigate to '{chat}'\n2. Type a message\n"
                            "3. Press Send\n4. No AI response after 15s",
                            "P1", "AI chat is not responding to messages",
                        )
            else:
                self.log("  No Chat section found — skipping")
        except Exception as e:
            self.log(f"  Check 4 error: {e}")

        # ── CHECK 5: Search empty state ───────────────────────────────────────
        self.log("Check 5: Search empty state")
        try:
            self.nav_to(page, ["Documents", "Dashboard", "Home"])
            time.sleep(1)
            search = page.locator(
                "input[type='search'], input[placeholder*='Search' i], input[placeholder*='search' i]"
            )
            if search.count() > 0:
                search.first.fill(Config.TEST_SEARCH_TERM)
                time.sleep(2)
                body_text = page.locator("body").inner_text()
                if "No generated documents" in body_text:
                    self.capture_bug(
                        page,
                        "Search empty state: misleading 'No generated documents' message",
                        "1. Go to Documents\n2. Search for a non-existent term\n"
                        "3. Message reads 'No generated documents' (misleading for a search result)",
                        "P2", "Should say 'No documents match your search'",
                    )
                elif not any(
                    phrase in body_text.lower()
                    for phrase in ["no result", "not found", "no match", "empty", "0 result", "nessun"]
                ):
                    self.capture_bug(
                        page,
                        "Search empty state: no feedback shown for empty search results",
                        "1. Navigate to a list page\n2. Search for a non-existent term\n"
                        "3. No empty-state message appears",
                        "P3", "UX: users should see a clear empty-state message",
                    )
                search.first.fill("")
            else:
                self.log("  No search input found — skipping")
        except Exception as e:
            self.log(f"  Check 5 error: {e}")

        # ── CHECK 5b: Chat Widget URL ──────────────────────────────────────────
        # If the dashboard exposes a chat widget URL (e.g. Cwick Core),
        # open it in a new tab and verify the chat interface loads.
        self.log("Check 5b: Chat widget URL")
        try:
            self._goto(page, self.home_url)
            time.sleep(2)
            widget_input = page.locator(
                "input[value*='/chat/'], input[value*='/widget/'], "
                "input[readonly][value*='http']"
            )
            if widget_input.count() > 0:
                chat_url = widget_input.first.input_value()
                self.log(f"  Found chat widget URL: {chat_url}")
                chat_page = browser.new_page()
                try:
                    chat_page.goto(chat_url, timeout=15000)
                    chat_page.wait_for_load_state("networkidle", timeout=10000)
                    time.sleep(3)
                    body_text = chat_page.locator("body").inner_text()
                    # Check for bad content
                    for literal, description, prio in BAD_TEXT_PATTERNS:
                        if literal in body_text:
                            self.capture_bug(
                                chat_page,
                                f"Chat widget: {description}",
                                f"1. Copy the chat widget URL from dashboard\n"
                                f"2. Open {chat_url}\n3. {description}",
                                prio, "Chat widget has bad content",
                            )
                    # Chat interface must have an input
                    has_input = chat_page.locator(
                        "input[type='text'], textarea, [contenteditable='true']"
                    ).count() > 0
                    if not has_input:
                        self.capture_bug(
                            chat_page,
                            "Chat widget: no text input visible",
                            f"1. Open chat widget at {chat_url}\n"
                            "2. No text input is visible — users cannot start a conversation",
                            "P1", "Chat widget is not interactive",
                        )
                    # Screenshot the chat widget
                    fname = f"BUG_chat_widget.png"
                    chat_page.screenshot(path=str(SESSION_DIR / fname))
                    self.log(f"  Chat widget screenshot: {fname}")
                except Exception as e:
                    self.log(f"  Chat widget page error: {e}")
                finally:
                    chat_page.close()
            else:
                self.log("  No chat widget URL found — skipping")
        except Exception as e:
            self.log(f"  Check 5b error: {e}")

        # Check 6 (logout + auth guard) is run AFTER YAML tests — see run()

    def check_logout_auth_guard(self, page):
        """Check 6: Logout + auth guard bypass — must run AFTER YAML tests."""
        self.log("Check 6: Logout and auth guard")
        try:
            self.nav_to(page, ["Dashboard", "Home"])
            time.sleep(1)
            logout_btn = page.locator(
                ":is(button,a,[role='button']):has-text('Logout'),"
                ":is(button,a,[role='button']):has-text('Sign out'),"
                ":is(button,a,[role='button']):has-text('Log out'),"
                ":is(button,a,[role='button']):has-text('Esci')"
            )
            if logout_btn.count() == 0:
                for trigger_sel in [
                    "[class*='avatar']", "[class*='user-menu']", "[class*='profile']",
                    "[aria-label*='user' i]", "[aria-label*='account' i]",
                    "header button:last-child", "nav button:last-child",
                ]:
                    try:
                        page.locator(trigger_sel).first.click(timeout=2000)
                        time.sleep(1)
                        logout_btn = page.locator(
                            ":is(button,a,[role='button']):has-text('Logout'),"
                            ":is(button,a,[role='button']):has-text('Sign out'),"
                            ":is(button,a,[role='button']):has-text('Log out')"
                        )
                        if logout_btn.count() > 0:
                            break
                    except Exception:
                        continue

            if logout_btn.count() > 0:
                logout_btn.first.click()
                time.sleep(2)
                page.goto(self.protected_url)
                time.sleep(2)
                if "login" not in page.url:
                    self.capture_bug(
                        page,
                        "Auth guard bypass: protected route accessible after logout",
                        f"1. Log out\n2. Navigate to {self.protected_url}\n"
                        "3. Page loads without redirecting to login",
                        "P0", "Security: protected routes must redirect unauthenticated users",
                    )
            else:
                self.log("  Logout button not found — skipping auth guard check")
        except Exception as e:
            self.log(f"  Check 6 error: {e}")

    def _test_creation_flow(self, page):
        """
        Generic document creation flow test.
        Fills in title/prompt, selects a creation card, clicks Generate/Create.
        Reports bugs if: no Generate button, no loading feedback, or generation timeout.
        """
        # Fill title/name if an input is present
        name_input = page.locator(
            "input[placeholder*='name' i], input[placeholder*='title' i], "
            "input[placeholder*='document' i], input[type='text']:visible"
        )
        if name_input.count() > 0:
            name_input.first.fill(Config.TEST_DOC_NAME)

        # Fill prompt/topic textarea
        prompt_input = page.locator(
            "textarea, input[placeholder*='prompt' i], input[placeholder*='topic' i], "
            "input[placeholder*='describe' i]"
        )
        if prompt_input.count() > 0:
            prompt_input.first.fill("Write a short document about software quality assurance.")

        # Click the first creation card (blank / template / existing)
        # Try class-based selectors first, then has-text fallbacks for apps with custom components
        card = None
        for card_sel in [
            "[class*='card']:has-text('blank'), [class*='template']:has-text('blank'), [class*='option']:has-text('blank')",
            "[class*='card']:has-text('template'), [class*='template']:has-text('template')",
            "[class*='card']:has-text('existing'), [class*='option']:has-text('existing')",
            "[class*='card']:visible, [class*='template']:visible, [class*='option']:visible",
            # Broader has-text fallbacks for apps without semantic card class names (e.g. Docupilot)
            ":has-text('From existing'):visible >> nth=0",
            ":has-text('From blank'):visible >> nth=0",
            ":has-text('From template'):visible >> nth=0",
            ":has-text('blank template'):visible >> nth=0",
            ":has-text('existing document'):visible >> nth=0",
        ]:
            loc = page.locator(card_sel)
            try:
                if loc.count() > 0:
                    card = loc.first
                    break
            except Exception:
                pass
        if card:
            try:
                card.click()
                # Card click may trigger SPA navigation — wait for it to settle
                time.sleep(1)
                page.wait_for_load_state("networkidle", timeout=10000)
                time.sleep(2)
            except Exception:
                pass

        # Find and click Generate / Create / Submit — wait up to 5s for button to appear after card selection
        gen_btn = page.locator(
            ":is(button,[role='button']):has-text('Generate'),"
            ":is(button,[role='button']):has-text('Create'),"
            ":is(button,[role='button']):has-text('Submit'),"
            ":is(button,[role='button']):has-text('Start'),"
            ":is(button,[role='button']):has-text('Continue'),"
            ":is(button,[role='button']):has-text('Next')"
        )
        if gen_btn.count() == 0:
            # Button may appear after card selection — wait and retry once
            time.sleep(3)
        if gen_btn.count() == 0:
            self.capture_bug(
                page,
                "Create flow: no Generate/Create button visible after selecting a template",
                "1. Navigate to the 'New document' section\n2. Select a creation card\n"
                "3. No Generate or Create button is visible",
                "P1", "Cannot complete document creation",
            )
            return

        gen_btn.first.click()
        time.sleep(3)

        # Verify loading feedback is shown
        loading_visible = page.locator(
            ":is([class*='loading'],[class*='spinner'],[class*='progress'],"
            "[class*='generating'],[role='progressbar']):visible"
        ).count() > 0
        if not loading_visible:
            self.capture_bug(
                page,
                "Create flow: no loading feedback during document generation",
                "1. Start document creation\n2. Click Generate\n"
                "3. No spinner or progress bar appears",
                "P2", "User has no feedback while AI is generating",
            )

        # Wait for navigation to editor/generate page
        try:
            page.wait_for_url(
                lambda u: "/editor/" in u or "/generate/" in u or u != page.url,
                timeout=30000,
            )
            time.sleep(2)
        except Exception:
            self.capture_bug(
                page,
                "Create flow: generation timed out (30s)",
                "1. Start document creation\n2. Click Generate\n"
                "3. Page does not navigate to result after 30s",
                "P1", "Generation failed silently or is extremely slow",
            )

    # ── YAML Test Runner ──────────────────────────────────────────────────────

    _VALID_YAML_ACTIONS = frozenset({
        "click", "fill", "type", "navigate", "wait", "scroll", "press",
        "screenshot", "select", "set_input_files",
        "expect_visible", "expect_url", "expect_text", "expect_not_text",
        "expect_count",
    })

    def _validate_yaml_config(self, config) -> list:
        """
        Validate a loaded YAML config dict.
        Returns a list of warning strings (non-fatal — existing tests still run).
        """
        warnings = []
        if not isinstance(config, dict):
            warnings.append("YAML root must be a mapping (got non-dict)")
            return warnings
        tests = config.get("tests")
        if tests is None:
            warnings.append("YAML config missing required 'tests' key")
            return warnings
        if not isinstance(tests, list):
            warnings.append(f"YAML 'tests' must be a list (got {type(tests).__name__})")
            return warnings
        for i, test in enumerate(tests):
            if not isinstance(test, dict):
                warnings.append(f"Test #{i+1}: must be a mapping, got {type(test).__name__}")
                continue
            if "name" not in test:
                warnings.append(f"Test #{i+1}: missing 'name' key")
            if "steps" not in test:
                warnings.append(f"Test #{i+1} ({test.get('name','?')}): missing 'steps' key")
                continue
            steps = test.get("steps", [])
            if not isinstance(steps, list):
                warnings.append(f"Test '{test.get('name','?')}': 'steps' must be a list")
                continue
            for j, step in enumerate(steps):
                if not isinstance(step, dict):
                    warnings.append(
                        f"Test '{test.get('name','?')}' step {j+1}: "
                        f"must be a mapping, got {type(step).__name__}"
                    )
                    continue
                if len(step) != 1:
                    warnings.append(
                        f"Test '{test.get('name','?')}' step {j+1}: "
                        f"each step must have exactly one key, got {list(step.keys())}"
                    )
                    continue
                action = list(step.keys())[0]
                if action not in self._VALID_YAML_ACTIONS:
                    warnings.append(
                        f"Test '{test.get('name','?')}' step {j+1}: "
                        f"unknown action '{action}' — valid actions: "
                        f"{sorted(self._VALID_YAML_ACTIONS)}"
                    )
        return warnings

    def run_yaml_tests(self, page):
        """
        Load and execute YAML test cases for this tenant.

        Looks for:
          apps/{TENANT_NAME}.yaml
          apps/{tenant_name_lower}.yaml
          apps/{tenant_name_snake}.yaml

        YAML format:
          base_url: https://...  (optional)
          tests:
            - name: "create document from template"
              start_url: "https://..."  (optional)
              steps:
                - click: "text=Create Document"
                - fill: ["input[name='title']", "My Document"]
                - expect_visible: ".template-list"
                - expect_url: "/editor/"
                - screenshot: "after_create"
                - wait: 2
                - navigate: "https://..."
        """
        if not _YAML_OK:
            self.log("PyYAML not installed — skipping YAML tests (pip install pyyaml)")
            return

        yaml_path = None
        candidates = [
            APPS_DIR / f"{TENANT_NAME}.yaml",
            APPS_DIR / f"{TENANT_NAME.lower().replace(' ', '_')}.yaml",
            APPS_DIR / f"{TENANT_NAME.lower()}.yaml",
        ]
        for c in candidates:
            if c.exists():
                yaml_path = c
                break

        if not yaml_path:
            self.log(f"No YAML config for '{TENANT_NAME}' (checked {APPS_DIR}) — skipping YAML tests")
            return

        self.log(f"=== YAML TESTS: {yaml_path.name} ===")
        try:
            with open(yaml_path) as f:
                config = _yaml.safe_load(f)
        except Exception as e:
            self.log(f"YAML parse error: {e}")
            return

        for warn in self._validate_yaml_config(config):
            self.log(f"  YAML validation warning: {warn}")

        tests = config.get("tests", [])
        self.log(f"Running {len(tests)} YAML test(s)…")
        for test in tests:
            name = test.get("name", "unnamed")
            self.log(f"  YAML test: {name}")
            try:
                self._run_yaml_test(page, test)
            except Exception as e:
                self.log(f"  YAML test '{name}' crashed: {e}")

    def _run_yaml_test(self, page, test: dict):
        name      = test.get("name", "unnamed")
        start_url = test.get("start_url") or self.home_url
        if start_url:
            self._goto(page, start_url)

        for i, step in enumerate(test.get("steps", [])):
            if not isinstance(step, dict):
                continue
            action = list(step.keys())[0]
            value  = step[action]
            try:
                if action == "click":
                    page.click(str(value), timeout=5000)
                    time.sleep(1.5)

                elif action in ("fill", "type"):
                    if isinstance(value, list) and len(value) == 2:
                        page.fill(str(value[0]), str(value[1]), timeout=5000)
                    else:
                        self.log(f"  fill step needs [selector, text] list format")

                elif action == "expect_visible":
                    visible = page.locator(str(value)).first.is_visible(timeout=5000)
                    if not visible:
                        self.capture_bug(
                            page,
                            f"YAML '{name}' step {i+1}: expected element not visible — {value}",
                            f"Test: {name}\nStep: expect_visible {value}\nURL: {page.url}",
                            "P2", f"YAML assertion failed at step {i+1}",
                        )

                elif action == "expect_url":
                    if str(value) not in page.url:
                        self.capture_bug(
                            page,
                            f"YAML '{name}' step {i+1}: URL pattern not matched — {value}",
                            f"Test: {name}\nExpected URL to contain: {value}\nActual: {page.url}",
                            "P2", f"YAML assertion failed at step {i+1}",
                        )

                elif action == "expect_not_text":
                    try:
                        body_text = page.locator("body").inner_text()
                        if str(value) in body_text:
                            self.capture_bug(
                                page,
                                f"YAML '{name}': forbidden text found — '{value}'",
                                f"Test: {name}\nForbidden text '{value}' found on {page.url}\n"
                                f"This text should never appear in the UI.",
                                "P2", f"YAML assertion failed: expect_not_text '{value}'",
                            )
                    except Exception as e:
                        self.log(f"  expect_not_text error: {e}")

                elif action == "expect_count":
                    # expect_count: ["selector", minimum_count]
                    try:
                        sel, min_count = str(value[0]), int(value[1])
                        actual = page.locator(sel).count()
                        if actual < min_count:
                            self.capture_bug(
                                page,
                                f"YAML '{name}': too few elements matching '{sel}' "
                                f"(expected ≥{min_count}, got {actual})",
                                f"Test: {name}\nSelector: {sel}\n"
                                f"Expected at least {min_count} elements, found {actual}\nURL: {page.url}",
                                "P2", f"YAML assertion failed: expect_count",
                            )
                    except Exception as e:
                        self.log(f"  expect_count error: {e}")

                elif action == "select":
                    # select: {"selector": "value"}  OR  select: ["selector", "value"]
                    if isinstance(value, dict):
                        for sel, val in value.items():
                            page.select_option(sel, label=str(val))
                    elif isinstance(value, list) and len(value) == 2:
                        page.select_option(str(value[0]), label=str(value[1]))

                elif action == "expect_text":
                    # Checks that visible page text contains the given string
                    try:
                        body_text = page.locator("body").inner_text()
                        if str(value) not in body_text:
                            self.capture_bug(
                                page,
                                f"YAML '{name}' step {i+1}: expected text not found — '{value}'",
                                f"Test: {name}\nExpected text '{value}' not present on {page.url}",
                                "P2", f"YAML assertion failed at step {i+1}",
                            )
                    except Exception as e:
                        self.log(f"  expect_text error: {e}")

                elif action == "navigate":
                    self._goto(page, str(value))

                elif action == "scroll":
                    # value: pixels to scroll (positive = down)
                    page.evaluate(f"window.scrollBy(0, {int(value)})")

                elif action == "press":
                    # press: "Enter"  OR  press: ["selector", "Enter"]
                    if isinstance(value, list) and len(value) == 2:
                        page.locator(str(value[0])).press(str(value[1]))
                    else:
                        page.keyboard.press(str(value))

                elif action == "set_input_files":
                    # value: [selector, filepath]  OR  just filepath (uses input[type='file'])
                    if isinstance(value, list) and len(value) == 2:
                        sel, fpath = str(value[0]), str(value[1])
                    else:
                        sel, fpath = "input[type='file']", str(value)
                    abs_path = str(Path(fpath).expanduser().resolve())
                    page.locator(sel).first.set_input_files(abs_path)

                elif action == "screenshot":
                    fname = f"YAML_{re.sub(r'[^a-z0-9]', '_', name.lower())}_{i+1}.png"
                    page.screenshot(path=str(SESSION_DIR / fname))
                    self.log(f"  Screenshot saved: {fname}")

                elif action == "wait":
                    time.sleep(float(value) if value else 2)

                else:
                    self.log(f"  Unknown YAML action '{action}' at step {i+1}")

                try:
                    page.wait_for_load_state("networkidle", timeout=3000)
                except Exception:
                    pass

            except Exception as e:
                self.log(f"  YAML step {i+1} ({action}={value}) error: {e}")

    # ── Reporting ─────────────────────────────────────────────────────────────

    def write_report(self):
        """
        Write bug list to Google Sheets. Optionally upload screenshots to Drive.
        Falls back to a local markdown log if Google credentials are unavailable.
        """
        self._write_local_log()  # always write local copy

        if not self.bugs:
            self.log("No bugs to report.")
            return

        if not self.init_google():
            self.log("Google not connected — bugs saved to local log only.")
            return

        # Upload screenshots to Drive
        if DRIVE_FOLDER_ID and self.drive_svc:
            from googleapiclient.http import MediaFileUpload
            uploaded = 0
            for bug in self.bugs:
                if not bug.get("screenshot"):
                    continue
                path = SESSION_DIR / bug["screenshot"]
                if not path.exists() or bug.get("link"):
                    continue
                try:
                    media = MediaFileUpload(str(path), mimetype="image/png")
                    f = self.drive_svc.files().create(
                        body={"name": bug["screenshot"], "parents": [DRIVE_FOLDER_ID]},
                        media_body=media,
                        fields="webViewLink",
                        supportsAllDrives=True,
                    ).execute()
                    bug["link"] = f.get("webViewLink", "")
                    uploaded += 1
                except Exception as e:
                    self.log(f"  Drive upload failed ({bug['screenshot']}): {e}")
            self.log(f"Uploaded {uploaded}/{len(self.bugs)} screenshots to Drive.")

        # Write to Google Sheets
        if not EXCEL_FILE_ID or not self.sheet_svc:
            return

        sheet_name = SHEET_MAP.get(TENANT_NAME, TENANT_NAME)
        col_offset = 1 if TENANT_NAME == "Rooms" else 0

        try:
            # Fetch existing issue titles to deduplicate against sheet
            existing_res = self.sheet_svc.spreadsheets().values().get(
                spreadsheetId=EXCEL_FILE_ID,
                range=f"'{sheet_name}'!A7:A",
            ).execute()
            existing_issues = {
                row[0].strip().lower()
                for row in existing_res.get("values", [])
                if row and row[0]
            }

            new_bugs = [b for b in self.bugs
                        if b["issue"].strip().lower() not in existing_issues]

            skipped = len(self.bugs) - len(new_bugs)
            if skipped:
                self.log(f"Skipped {skipped} already-reported bug(s).")
            if not new_bugs:
                self.log("No new bugs to write to Sheets.")
                return

            rows = []
            for b in new_bugs:
                # Plain text label — hyperlink is set separately via batchUpdate
                # (avoids =HYPERLINK() formula which breaks on non-English locales)
                cell = "View Screenshot" if b.get("link") else b.get("screenshot", "")
                row  = [b["issue"], b["reproduce"], "QA Agent",
                        b["prio"], "", "", b["note"], cell]
                if col_offset:
                    # Rooms has extra "Reported" column at position C (index 2)
                    # Insert empty string between reproduce and tester
                    row.insert(2, "")
                rows.append(row)

            result = self.sheet_svc.spreadsheets().values().append(
                spreadsheetId=EXCEL_FILE_ID,
                range=f"'{sheet_name}'!A7",
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={"values": rows},
            ).execute()
            updated = result.get("updates", {}).get("updatedRange", "?")
            self.log(f"Wrote {len(new_bugs)} bug(s) to '{sheet_name}' at {updated}")

            # Reset cell formatting, then overlay hyperlinks on screenshot cells
            self._reset_formatting(sheet_name, updated, col_offset)
            self._set_hyperlinks(sheet_name, updated, col_offset, new_bugs)

        except Exception as e:
            self.log(f"Sheets write failed: {e}")

    def _reset_formatting(self, sheet_name: str, updated_range: str, col_offset: int):
        if not updated_range or updated_range == "?":
            return
        try:
            meta = self.sheet_svc.spreadsheets().get(
                spreadsheetId=EXCEL_FILE_ID,
                fields="sheets.properties",
            ).execute()
            sheet_id = next(
                s["properties"]["sheetId"]
                for s in meta["sheets"]
                if s["properties"]["title"] == sheet_name
            )
            range_part = updated_range.split("!")[-1]
            row_nums   = re.findall(r"\d+", range_part)
            start_row  = int(row_nums[0]) - 1   # 0-indexed
            end_row    = int(row_nums[-1])       # exclusive
            num_cols   = 9 + col_offset         # A–H (+ Rooms offset)

            self.sheet_svc.spreadsheets().batchUpdate(
                spreadsheetId=EXCEL_FILE_ID,
                body={"requests": [{
                    "repeatCell": {
                        "range": {
                            "sheetId":          sheet_id,
                            "startRowIndex":    start_row,
                            "endRowIndex":      end_row,
                            "startColumnIndex": 0,
                            "endColumnIndex":   num_cols,
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "backgroundColor": {"red": 1, "green": 1, "blue": 1},
                                "textFormat": {
                                    "foregroundColor": {"red": 0, "green": 0, "blue": 0},
                                    "bold": False,
                                },
                                "wrapStrategy": "WRAP",
                            }
                        },
                        "fields": "userEnteredFormat(backgroundColor,textFormat,wrapStrategy)",
                    }
                }]},
            ).execute()
            self.log("Cell formatting reset.")
        except Exception as e:
            self.log(f"Formatting reset failed (non-critical): {e}")

    def _set_hyperlinks(self, sheet_name: str, updated_range: str, col_offset: int, bugs: list):
        """
        Set clickable hyperlinks on screenshot cells via textFormat.link.
        Locale-safe alternative to =HYPERLINK() formula (which breaks on non-English Sheets).
        """
        if not updated_range or updated_range == "?":
            return
        links = [(i, b["link"]) for i, b in enumerate(bugs) if b.get("link")]
        if not links:
            return
        try:
            meta = self.sheet_svc.spreadsheets().get(
                spreadsheetId=EXCEL_FILE_ID,
                fields="sheets.properties",
            ).execute()
            sheet_id = next(
                s["properties"]["sheetId"]
                for s in meta["sheets"]
                if s["properties"]["title"] == sheet_name
            )
            range_part = updated_range.split("!")[-1]
            row_nums   = re.findall(r"\d+", range_part)
            start_row  = int(row_nums[0]) - 1        # 0-indexed
            screenshot_col = 7 + col_offset          # col H (idx 7), or I (idx 8) for Rooms

            requests = []
            for idx, link in links:
                requests.append({
                    "updateCells": {
                        "rows": [{"values": [{
                            "userEnteredValue": {"stringValue": "View Screenshot"},
                            "userEnteredFormat": {
                                "backgroundColor": {"red": 1, "green": 1, "blue": 1},
                                "wrapStrategy": "WRAP",
                                "textFormat": {
                                    "bold": False,
                                    "foregroundColor": {"red": 0.07, "green": 0.33, "blue": 0.80},
                                    "link": {"uri": link},
                                },
                            },
                        }]}],
                        "fields": "userEnteredValue,userEnteredFormat(backgroundColor,wrapStrategy,textFormat)",
                        "range": {
                            "sheetId":          sheet_id,
                            "startRowIndex":    start_row + idx,
                            "endRowIndex":      start_row + idx + 1,
                            "startColumnIndex": screenshot_col,
                            "endColumnIndex":   screenshot_col + 1,
                        },
                    }
                })

            self.sheet_svc.spreadsheets().batchUpdate(
                spreadsheetId=EXCEL_FILE_ID,
                body={"requests": requests},
            ).execute()
            self.log(f"Set hyperlinks on {len(requests)} screenshot cell(s).")
        except Exception as e:
            self.log(f"Hyperlink setting failed (non-critical): {e}")

    def _write_local_log(self):
        """Write a structured markdown log to session_output/session_log.md."""
        log_path = SESSION_DIR / "session_log.md"
        with open(log_path, "w") as f:
            f.write(f"# QA Session — {TENANT_NAME}\n\n")
            f.write(f"**Date:** {datetime.datetime.now().isoformat()}  \n")
            f.write(f"**URL:** {TENANT_URL}  \n")
            f.write(f"**Tenant domain:** {self.tenant_domain}  \n\n")

            # Coverage summary
            f.write("## Coverage Summary\n\n")
            f.write(f"| Metric | Value |\n|---|---|\n")
            f.write(f"| Pages discovered | {len(self.coverage.pages_discovered)} |\n")
            f.write(f"| Pages tested | {len(self.coverage.pages_tested)} |\n")
            f.write(f"| Nav links found | {self.coverage.nav_links_discovered} |\n")
            f.write(f"| Buttons discovered | {self.coverage.buttons_discovered} |\n")
            f.write(f"| Buttons clicked | {self.coverage.buttons_clicked} |\n")
            f.write(f"| Modals handled | {self.coverage.modals_opened} |\n")
            f.write(f"| Forms tested | {self.coverage.forms_filled} |\n")
            f.write(f"| Unique states | {self.coverage.states_visited} |\n")
            f.write(f"| Bugs detected | {len(self.bugs)} |\n\n")

            # Pages visited
            f.write("## Pages Visited\n\n")
            for url in sorted(self.coverage.pages_discovered):
                f.write(f"- {url}\n")
            f.write("\n")

            # Bugs found (structured)
            f.write(f"## Bugs Found ({len(self.bugs)})\n\n")
            for b in self.bugs:
                f.write(f"### [{b['prio']}] {b['issue']}\n\n")
                f.write(f"**Severity:** {b['prio']}  \n")
                f.write(f"**Steps to reproduce:**\n\n{b['reproduce']}\n\n")
                if b.get("note"):
                    f.write(f"**Note:** {b['note']}  \n")
                if b.get("screenshot"):
                    f.write(f"**Screenshot:** `{b['screenshot']}`  \n")
                if b.get("link"):
                    f.write(f"**Drive link:** {b['link']}  \n")
                f.write("\n---\n\n")
        self.log(f"Local log → {log_path}")

    # ── Main Pipeline ──────────────────────────────────────────────────────────

    def run(self):
        """
        Full QA pipeline:
          1. Validate env vars
          2. Login
          3. BFS exploration
          4. Targeted checks
          5. YAML tests
          6. Coverage report
          7. Write bugs to Sheets / local log
        """
        # Validate required environment variables
        missing = [name for name, val in [
            ("TENANT_URL",      TENANT_URL),
            ("TENANT_USERNAME", USERNAME),
            ("TENANT_PASSWORD", PASSWORD),
        ] if not val]
        if missing:
            logger.error(f"Missing required env vars: {', '.join(missing)}")
            logger.error("Set them before running, e.g.:")
            logger.error("  export TENANT_URL=https://...")
            return

        # Derive tenant domain for navigation safety
        self.tenant_domain = urlparse(TENANT_URL).netloc

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            page    = browser.new_page()

            # Capture JS console errors
            def _on_console(msg):
                if msg.type == "error":
                    self.console_errors.append({"url": page.url, "text": msg.text})
            page.on("console", _on_console)

            # ── PHASE 1: LOGIN ────────────────────────────────────────────────
            self.log(f"Starting QA session for '{TENANT_NAME}'")
            self.log(f"Login URL: {TENANT_URL}")
            self._login(page)
            self.protected_url = page.url
            self.home_url      = page.url
            self.log(f"Logged in at: {self.home_url}")

            # ── PHASE 2: BFS EXPLORATION ──────────────────────────────────────
            self.bfs_explore(page, self.home_url)

            # Return to home before targeted checks
            self._goto(page, self.home_url)

            # ── PHASE 3: TARGETED CHECKS (checks 1-5, no logout) ─────────────
            self.log("=== TARGETED CHECKS ===")
            self.run_targeted_checks(page, browser)

            # ── PHASE 4: YAML TESTS (needs active session — re-login if needed) ─
            self.log("Re-logging in before YAML tests…")
            self._login(page, conditional=True)
            self.run_yaml_tests(page)

            # ── PHASE 4b: CHECK 6 — Logout + auth guard (ends session) ───────
            self.check_logout_auth_guard(page)

            # ── PHASE 5: COVERAGE REPORT ──────────────────────────────────────
            self.coverage.states_visited = len(self.state_graph.visited)
            self.coverage.print_report(bug_count=len(self.bugs))
            # Save coverage JSON
            try:
                self.coverage.save_json(
                    SESSION_DIR / "coverage_summary.json",
                    bug_count=len(self.bugs),
                )
                self.log("Coverage summary → session_output/coverage_summary.json")
            except Exception as e:
                self.log(f"Coverage JSON write failed (non-critical): {e}")

            # ── PHASE 6: WRITE REPORT ─────────────────────────────────────────
            self.log(f"=== REPORT — {len(self.bugs)} bug(s) found ===")
            for b in self.bugs:
                self.log(f"  [{b['prio']}] {b['issue']}")
            self.write_report()

            browser.close()
            self.log("Session complete.")


# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    QAAgent().run()
