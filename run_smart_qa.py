import os, time, json, base64, re, pickle


def extract_json(text):
    """Extract the first valid JSON object from a string, ignoring surrounding text."""
    text = re.sub(r"^```[a-z]*\n?", "", text.strip())
    text = re.sub(r"\n?```$", "", text).strip()
    start = text.find("{")
    if start == -1:
        raise ValueError("No JSON object found")
    candidate = text[start:]
    # Try parsing the whole candidate first
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as e:
        # "Extra data" → e.pos is exactly where valid JSON ends
        if "Extra data" in str(e):
            try:
                return json.loads(candidate[:e.pos])
            except Exception:
                pass
        # Fallback: truncate at last closing brace
        last = candidate.rfind("}")
        if last != -1:
            try:
                return json.loads(candidate[:last + 1])
            except Exception:
                pass
        raise ValueError(f"Could not parse JSON: {e}")
from pathlib import Path
from playwright.sync_api import sync_playwright
import anthropic

SESSION_DIR = Path(os.path.expanduser("~/cwick-qa-agent/session_output"))
SESSION_DIR.mkdir(parents=True, exist_ok=True)

SHEET_MAP = {
    "Docupilot": "Docupilot",
    "MaiHUB": "MaiHUB",
    "CFO AI": "CFO AI",
    "Rooms": "Rooms",
    "A33": "A33",
    "Tenant Base (Cwick Core)": "Tenant Base (Cwick Core)",
}

# Token budget:
#   Recon    → 0 Claude calls  (pure DOM + interaction)
#   Plan     → 1 Claude call   (up to 10 screenshots, JPEG 70)
#   Execute  → 1 call/step     (JPEG 60, max 4 steps/test)


class SmartQAAgent:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        self.url = os.environ.get("TENANT_URL")
        self.user = os.environ.get("TENANT_USERNAME")
        self.pw = os.environ.get("TENANT_PASSWORD")
        self.tenant = os.environ.get("TENANT_NAME")
        self.excel_file_id = os.environ.get("EXCEL_FILE_ID", "")
        self.bugs = []
        self.home_url = ""

    def log(self, msg):
        print(f"[{time.strftime('%H:%M:%S')}] {msg}")

    # ── Screenshot helpers ────────────────────────────────────────────────────

    def snap(self, page, quality=None):
        """Return (base64_str, media_type). Use quality=60-70 for JPEG to save tokens."""
        if quality:
            data = page.screenshot(type="jpeg", quality=quality)
            return base64.b64encode(data).decode(), "image/jpeg"
        data = page.screenshot()
        return base64.b64encode(data).decode(), "image/png"

    def img_block(self, b64, media_type):
        return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}}

    # ── DOM helpers ───────────────────────────────────────────────────────────

    def get_page_context(self, page):
        """Compact list of visible interactive elements for accurate selectors."""
        lines = []
        for sel in ["button:visible", "a:visible", "input:visible", "textarea:visible", "[role='button']:visible"]:
            for el in page.locator(sel).all()[:12]:
                try:
                    text = (el.inner_text().strip() or "")[:40]
                    tag = el.evaluate("el => el.tagName.toLowerCase()")
                    cls = (el.get_attribute("class") or "")[:50]
                    href = el.get_attribute("href") or ""
                    aria = el.get_attribute("aria-label") or ""
                    ph = el.get_attribute("placeholder") or ""
                    lines.append(f'<{tag} class="{cls}" href="{href}" aria-label="{aria}" placeholder="{ph}">{text}</{tag}>')
                except Exception:
                    pass
        return "\n".join(lines[:35])

    def find_nav_items(self, page):
        """Return list of (text, element) for all nav-like clickable items."""
        found = {}
        for sel in [
            "nav :is(button,a)", "aside :is(button,a)",
            "[role='navigation'] :is(button,a)",
            "[class*='sidebar'] :is(button,a)",
            "[class*='nav']:not([class*='navigate']) :is(button,a)",
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

    def click_nav(self, page, name):
        """Click a nav item by name. Returns True on success."""
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

    def relogin(self, page):
        if "login" not in page.url:
            return False
        self.log("Session expired — re-authenticating...")
        page.locator("input[type='email']").fill(self.user)
        page.locator("input[type='password']").fill(self.pw)
        page.click("button[type='submit']")
        try:
            page.wait_for_url(lambda u: "login" not in u, timeout=15000)
            page.wait_for_load_state("networkidle", timeout=10000)
            time.sleep(2)
            return True
        except Exception:
            return False

    def norm_url(self, url):
        return url.split("?")[0].split("#")[0].rstrip("/")

    # ── Phase 1: Full Crawl (zero Claude calls) ───────────────────────────────

    def full_crawl(self, page) -> list:
        """
        Exhaustive sitemap discovery. No Claude calls — pure DOM + interaction.
        Explores: top-level nav → tabs/sub-nav → detail views → action modals.
        Returns list of {label, url, b64, media_type}.
        """
        screens = []
        seen = set()

        def capture(label):
            norm = self.norm_url(page.url)
            if norm in seen:
                return
            seen.add(norm)
            b64, mt = self.snap(page, quality=70)
            screens.append({"label": label, "url": page.url, "b64": b64, "media_type": mt})
            self.log(f"  + [{label}] {page.url}")

        def go(url):
            try:
                page.goto(url)
                page.wait_for_load_state("networkidle", timeout=10000)
                time.sleep(1.5)
                self.relogin(page)
                return True
            except Exception:
                return False

        def close_modal():
            for sel in [
                "[role='dialog'] button:has-text('Close')",
                "[role='dialog'] button:has-text('Cancel')",
                "[role='dialog'] [aria-label*='close' i]",
                "[class*='modal'] button:has-text('Close')",
                "[class*='modal'] button:has-text('Cancel')",
                "[class*='modal'] [aria-label*='close' i]",
            ]:
                try:
                    el = page.locator(sel).first
                    if el.is_visible(timeout=500):
                        el.click()
                        time.sleep(1)
                        return
                except Exception:
                    pass
            try:
                page.keyboard.press("Escape")
                time.sleep(1)
            except Exception:
                pass

        # ── 1. Landing ──────────────────────────────────────────────────────
        capture("home")

        # ── 2. Top-level nav ────────────────────────────────────────────────
        nav_items = self.find_nav_items(page)
        # Skip logout/auth items — clicking them kills the session
        skip = {"logout", "sign out", "log out", "signout", "exit"}
        nav_items = [n for n in nav_items if n.lower() not in skip]
        self.log(f"Top-level nav: {nav_items}")
        section_urls = {}  # name → url after clicking

        for name in nav_items[:12]:
            if self.click_nav(page, name):
                self.relogin(page)
                capture(name)
                section_urls[name] = page.url

        # ── 3. Per-section deep dive ─────────────────────────────────────────
        for section_name, section_url in section_urls.items():
            if not go(section_url):
                continue

            # a) Tabs / sub-nav
            tab_els = page.locator(
                "[role='tab']:visible, "
                "[class*='tab']:not([class*='table']):not([class*='tabindex']):visible"
            ).all()[:8]
            tab_texts = []
            for tab in tab_els:
                try:
                    t = tab.inner_text().strip()
                    if t and len(t) < 40:
                        tab_texts.append(t)
                except Exception:
                    pass

            for tab_text in tab_texts:
                try:
                    tab_el = page.locator(
                        f"[role='tab']:has-text('{tab_text}'),"
                        f"[class*='tab']:has-text('{tab_text}')"
                    ).first
                    if tab_el.is_visible(timeout=800):
                        tab_el.click()
                        time.sleep(1.5)
                        capture(f"{section_name} › {tab_text}")
                except Exception:
                    pass

            # b) Secondary / admin sub-nav links
            go(section_url)
            sub_links = page.locator(
                "[class*='sub'] :is(a,button):visible, "
                "[class*='admin'] :is(a,button):visible, "
                "[class*='sidebar'] a[href]:visible"
            ).all()[:8]
            for link in sub_links:
                try:
                    text = link.inner_text().strip()[:30]
                    href = link.get_attribute("href") or ""
                    if not text or text in [section_name] + nav_items:
                        continue
                    link.click()
                    page.wait_for_load_state("networkidle", timeout=8000)
                    time.sleep(1.5)
                    self.relogin(page)
                    if self.norm_url(page.url) not in seen:
                        capture(f"{section_name} › {text}")
                    go(section_url)
                except Exception:
                    pass

            # c) First list item → detail view
            go(section_url)
            detail_selectors = [
                "tbody tr:first-child",
                "[class*='list-item']:first-child",
                "[class*='list'] [class*='item']:first-child",
                "[class*='card']:first-child",
                "ul:not([class*='nav']) li:first-child a",
            ]
            for sel in detail_selectors:
                try:
                    el = page.locator(sel).first
                    if el.is_visible(timeout=800):
                        el.click()
                        page.wait_for_load_state("networkidle", timeout=8000)
                        time.sleep(1.5)
                        self.relogin(page)
                        if self.norm_url(page.url) != self.norm_url(section_url):
                            capture(f"{section_name} › detail")
                            # Sub-tabs inside detail view
                            detail_tabs = page.locator("[role='tab']:visible").all()[:4]
                            for dt in detail_tabs:
                                try:
                                    dt_text = dt.inner_text().strip()[:20]
                                    dt.click()
                                    time.sleep(1)
                                    capture(f"{section_name} › detail › {dt_text}")
                                except Exception:
                                    pass
                        break
                except Exception:
                    pass

            # d) Action buttons → modals / new pages
            go(section_url)
            action_btns = page.locator(
                ":is(button,[role='button']):is("
                ":has-text('New'),:has-text('Create'),:has-text('Add'),"
                ":has-text('Upload'),:has-text('Generate'),:has-text('Invite')"
                "):visible"
            ).all()[:3]
            for btn in action_btns:
                try:
                    btn_text = btn.inner_text().strip()[:20]
                    btn.click()
                    time.sleep(2)
                    if self.norm_url(page.url) != self.norm_url(section_url):
                        self.relogin(page)
                        capture(f"{section_name} › {btn_text}")
                        go(section_url)
                    else:
                        modal = page.locator("[role='dialog']:visible, [class*='modal']:visible")
                        if modal.count() > 0:
                            capture(f"{section_name} › {btn_text} modal")
                            close_modal()
                except Exception:
                    pass

            # e) User / profile menu (logout, settings, etc.)
            go(section_url)
            for trigger in [
                "[class*='avatar']:visible", "[class*='user-menu']:visible",
                "[class*='profile']:visible", "[aria-label*='user' i]:visible",
                "[aria-label*='account' i]:visible",
                "header button:last-child", "nav button:last-child",
            ]:
                try:
                    el = page.locator(trigger).first
                    if el.is_visible(timeout=500):
                        el.click()
                        time.sleep(1)
                        dropdown = page.locator("[class*='dropdown']:visible, [class*='menu']:visible")
                        if dropdown.count() > 0:
                            capture(f"user menu")
                            page.keyboard.press("Escape")
                            time.sleep(0.5)
                        break
                except Exception:
                    pass

        self.log(f"Crawl complete — {len(screens)} unique screens")
        return screens

    # ── Phase 2: Plan (1 Claude call) ────────────────────────────────────────

    def plan(self, screens) -> dict:
        """
        Send representative screenshots + sitemap text to Claude.
        Returns {app_type, app_summary, tests: [{name, goal, steps, bug_signal}]}.
        """
        # Select up to 10 representative screenshots (first + evenly spaced)
        if len(screens) <= 10:
            selected = screens
        else:
            step = len(screens) / 10
            selected = [screens[int(i * step)] for i in range(10)]

        # Build text sitemap (cheap, gives Claude the full picture)
        sitemap_text = "FULL SITEMAP DISCOVERED:\n" + "\n".join(
            f"  - [{s['label']}] {s['url']}" for s in screens
        )

        content = [{"type": "text", "text": sitemap_text + "\n\nSELECTED SCREENSHOTS:\n"}]
        for s in selected:
            content.append({"type": "text", "text": f"--- {s['label']} | {s['url']} ---"})
            content.append(self.img_block(s["b64"], s["media_type"]))

        content.append({"type": "text", "text": (
            "\nBased on the full sitemap and screenshots above:\n\n"
            "1. What kind of app is this?\n"
            "2. What are its core features?\n"
            "3. Generate exactly 10 QA test cases tailored to what you see — not generic tests.\n"
            "   Cover: core user flows, empty states, error handling, navigation, "
            "forms, search, auth, and anything that looks potentially broken.\n\n"
            "IMPORTANT: Keep each field SHORT (one sentence max). Do not write essays.\n\n"
            "Output ONLY valid JSON (no markdown fences):\n"
            "{\n"
            "  \"app_type\": \"...\",\n"
            "  \"app_summary\": \"one sentence\",\n"
            "  \"tests\": [\n"
            "    {\n"
            "      \"name\": \"short_id\",\n"
            "      \"start_url\": \"URL from sitemap\",\n"
            "      \"goal\": \"one sentence\",\n"
            "      \"steps\": \"one sentence\",\n"
            "      \"bug_signal\": \"one sentence\"\n"
            "    }\n"
            "  ]\n"
            "}"
        )})

        response = self.client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4000,
            messages=[{"role": "user", "content": content}],
        )
        raw = response.content[0].text.strip()
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)
        return extract_json(raw)

    # ── Phase 3: Execute ──────────────────────────────────────────────────────

    def execute_test(self, page, test, test_num):
        """
        Execute one test. Each step: screenshot → ask Claude → act.
        JPEG 60 for token efficiency.
        """
        # Navigate to the test's starting URL if specified
        start_url = test.get("start_url", "")
        if start_url:
            try:
                page.goto(start_url)
                page.wait_for_load_state("networkidle", timeout=10000)
                time.sleep(1.5)
            except Exception:
                pass
        self.relogin(page)
        self.log(f"  Goal: {test['goal']}")

        for step in range(4):  # max 4 steps per test
            self.relogin(page)
            b64, mt = self.snap(page, quality=60)
            ctx = self.get_page_context(page)

            prompt = (
                f"QA test: '{test['name']}'\n"
                f"Goal: {test['goal']}\n"
                f"Steps: {test['steps']}\n"
                f"Bug signal: {test['bug_signal']}\n"
                f"URL: {page.url} | Step {step+1}/4\n\n"
                "Look at the screenshot:\n"
                "1. WHERE AM I in this test?\n"
                "2. IS THE BUG SIGNAL VISIBLE? Report if yes.\n"
                "3. WHAT IS THE NEXT ACTION?\n\n"
                f"ELEMENTS:\n{ctx}\n\n"
                "SELECTOR RULES (follow strictly):\n"
                "- Use simple selectors: button:has-text('Label'), input[placeholder*='word' i], [role='tab']:has-text('Label')\n"
                "- NEVER chain Tailwind classes (e.g. button.px-4.py-2... will always fail)\n"
                "- NEVER use dark: variant classes in selectors\n"
                "- NEVER use :nth-of-type on elements without stable IDs\n\n"
                "Output ONLY valid JSON:\n"
                "  \"status\": \"in_progress\"|\"complete\"|\"blocked\"\n"
                "  \"action\": \"click\"|\"type\"|\"navigate\"|\"none\"\n"
                "  \"selector\": simple selector per rules above\n"
                "  \"value\": text to type or URL\n"
                "  \"reason\": one sentence\n"
                "  \"bug\": null OR {\"issue\":\"...\",\"severity\":\"P0|P1|P2|P3\",\"reproduce\":\"...\"}"
            )

            try:
                resp = self.client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=512,
                    messages=[{"role": "user", "content": [
                        self.img_block(b64, mt),
                        {"type": "text", "text": prompt},
                    ]}],
                )
                raw = resp.content[0].text.strip()
                raw = re.sub(r"^```[a-z]*\n?", "", raw)
                raw = re.sub(r"\n?```$", "", raw)
                d = extract_json(raw)
            except Exception as e:
                self.log(f"  AI error: {e}")
                break

            self.log(f"  Step {step+1}: {d.get('action')} — {d.get('reason')}")
            self._capture_bug(page, f"test={test['name']} step={step+1}", d)

            if d.get("status") in ("complete", "blocked"):
                self.log(f"  → {d.get('status')}")
                break

            action, selector, value = d.get("action"), d.get("selector", ""), d.get("value", "")
            if action == "click" and selector:
                try:
                    page.click(selector, timeout=5000)
                except Exception as e:
                    self.log(f"  Click failed: {e}")
            elif action == "type" and selector:
                try:
                    page.fill(selector, value or "QA Test Input")
                except Exception as e:
                    self.log(f"  Fill failed: {e}")
            elif action == "navigate" and value and "login" not in value:
                try:
                    page.goto(value)
                except Exception as e:
                    self.log(f"  Navigate failed: {e}")

            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            time.sleep(2)

        # Return home after each test
        try:
            page.goto(self.home_url)
            page.wait_for_load_state("networkidle", timeout=10000)
            time.sleep(1)
        except Exception:
            pass

    def _words(self, text):
        return set(re.sub(r"[^a-z0-9 ]", "", text.lower()).split())

    def _is_duplicate(self, issue):
        """Jaccard similarity > 0.40 on word sets = same bug, different phrasing."""
        w = self._words(issue)
        if len(w) < 5:
            return False
        for b in self.bugs:
            bw = self._words(b["issue"])
            if not bw:
                continue
            jaccard = len(w & bw) / len(w | bw)
            if jaccard > 0.40:
                return True
        return False

    def _is_false_positive(self, issue):
        """Reject bugs where Claude contradicts itself by saying no bug was found."""
        lower = issue.lower()
        return any(phrase in lower for phrase in [
            "no bug detected", "no functional bug", "no bug signal",
            "no bug found", "feature works", "working correctly", "works as expected",
        ])

    # Keep _norm for sheet-side dedup (exact prefix match against existing rows)
    def _norm(self, text):
        words = re.sub(r"[^a-z0-9 ]", "", text.lower()).split()
        return " ".join(words[:12])

    def _capture_bug(self, page, label, decision):
        bug = decision.get("bug")
        if not bug:
            return
        issue = bug.get("issue", "")
        # Reject self-contradicting "no bug" reports
        if self._is_false_positive(issue):
            return
        # Deduplicate within session using word-set similarity
        if self._is_duplicate(issue):
            return
        bid = len(self.bugs) + 1
        fname = f"BUG_{bid:03d}_{bug.get('severity','P2')}.png"
        page.screenshot(path=SESSION_DIR / fname)
        self.bugs.append({
            "issue": issue,
            "reproduce": bug.get("reproduce", label),
            "prio": bug.get("severity", "P2"),
            "note": f"AI-detected: {label}",
            "screenshot": fname,
            "link": "",
        })
        self.log(f"  [BUG {bug.get('severity')}] {issue}")

    # ── Reporting ─────────────────────────────────────────────────────────────

    def upload_screenshots(self, drive_svc):
        """Upload bug screenshots to Drive folder, store webViewLink in bug['link']."""
        folder_id = os.environ.get("DRIVE_FOLDER_ID", "")
        if not folder_id:
            self.log("No DRIVE_FOLDER_ID — skipping screenshot upload.")
            return
        from googleapiclient.http import MediaFileUpload
        uploaded = 0
        for bug in self.bugs:
            path = SESSION_DIR / bug["screenshot"]
            if not path.exists() or bug.get("link"):
                continue
            try:
                media = MediaFileUpload(str(path), mimetype="image/png")
                f = drive_svc.files().create(
                    body={"name": bug["screenshot"], "parents": [folder_id]},
                    media_body=media,
                    fields="webViewLink",
                    supportsAllDrives=True,
                ).execute()
                bug["link"] = f.get("webViewLink", "")
                uploaded += 1
            except Exception as e:
                self.log(f"  Drive upload failed ({bug['screenshot']}): {e}")
        self.log(f"Uploaded {uploaded}/{len(self.bugs)} screenshots to Drive.")

    def write_bugs_to_sheet(self):
        if not self.bugs:
            self.log("No bugs to write.")
            return
        tpath = Path(os.path.expanduser("~/cwick-qa-agent/token.pickle"))
        if not tpath.exists():
            self.log("No token.pickle — skipping Sheets write.")
            return
        try:
            from googleapiclient.discovery import build
            with open(tpath, "rb") as f:
                creds = pickle.load(f)
            sheet_svc = build("sheets", "v4", credentials=creds)
            drive_svc = build("drive", "v3", credentials=creds)

            # Upload screenshots first so links are ready
            self.upload_screenshots(drive_svc)

            sheet_name = SHEET_MAP.get(self.tenant, self.tenant)
            col_offset = 1 if self.tenant == "Rooms" else 0

            existing = sheet_svc.spreadsheets().values().get(
                spreadsheetId=self.excel_file_id,
                range=f"'{sheet_name}'!A7:A"
            ).execute()
            # Normalize for dedup against sheet (same logic as in-session dedup)
            known = {self._norm(r[0]) for r in existing.get("values", []) if r and r[0]}
            new_bugs = [b for b in self.bugs if self._norm(b["issue"]) not in known]

            if not new_bugs:
                self.log(f"No new bugs (skipped {len(self.bugs)} duplicates).")
                return

            rows = []
            for b in new_bugs:
                screenshot_cell = b.get("link") or b["screenshot"]
                row = [b["issue"], b["reproduce"], "AI Agent", b["prio"], "", "", b["note"], screenshot_cell]
                if col_offset:
                    row = [""] + row
                rows.append(row)

            result = sheet_svc.spreadsheets().values().append(
                spreadsheetId=self.excel_file_id,
                range=f"'{sheet_name}'!A7",
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={"values": rows},
            ).execute()
            updated_range = result.get("updates", {}).get("updatedRange", "")
            self.log(f"Wrote {len(new_bugs)} bug(s) → {updated_range}")

            # Reset cell formatting on written rows (clear black backgrounds)
            if updated_range:
                try:
                    # Look up the sheet's numeric ID
                    meta = sheet_svc.spreadsheets().get(
                        spreadsheetId=self.excel_file_id,
                        fields="sheets.properties"
                    ).execute()
                    sheet_id = next(
                        s["properties"]["sheetId"]
                        for s in meta["sheets"]
                        if s["properties"]["title"] == sheet_name
                    )
                    # Parse start/end rows from the range string e.g. "MaiHUB!A7:H14"
                    range_part = updated_range.split("!")[-1]
                    import re as _re
                    row_nums = _re.findall(r"\d+", range_part)
                    start_row = int(row_nums[0]) - 1  # 0-indexed
                    end_row = int(row_nums[-1])        # exclusive
                    num_cols = 9 + col_offset          # A–H (+ Rooms offset)

                    sheet_svc.spreadsheets().batchUpdate(
                        spreadsheetId=self.excel_file_id,
                        body={"requests": [{
                            "repeatCell": {
                                "range": {
                                    "sheetId": sheet_id,
                                    "startRowIndex": start_row,
                                    "endRowIndex": end_row,
                                    "startColumnIndex": 0,
                                    "endColumnIndex": num_cols,
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
                        }]}
                    ).execute()
                    self.log("Cell formatting reset to white background / black text.")
                except Exception as e:
                    self.log(f"Formatting reset failed (non-critical): {e}")
        except Exception as e:
            self.log(f"Sheets write failed: {e}")

    # ── Main ──────────────────────────────────────────────────────────────────

    def run(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            page = browser.new_page()

            # LOGIN
            self.log(f"Logging into {self.tenant} ...")
            page.goto(self.url)
            page.fill("input[type='email']", self.user)
            page.fill("input[type='password']", self.pw)
            page.click("button[type='submit']")
            page.wait_for_url(lambda u: "login" not in u, timeout=15000)
            page.wait_for_load_state("networkidle", timeout=15000)
            time.sleep(3)
            self.home_url = page.url
            self.log(f"Home: {self.home_url}")

            # PHASE 1: CRAWL
            self.log("=== PHASE 1: FULL CRAWL (no AI) ===")
            screens = self.full_crawl(page)

            # Return home
            page.goto(self.home_url)
            page.wait_for_load_state("networkidle", timeout=10000)
            time.sleep(2)

            # PHASE 2: PLAN
            self.log("=== PHASE 2: PLAN (1 AI call) ===")
            try:
                plan_data = self.plan(screens)
            except Exception as e:
                self.log(f"Planning failed: {e}")
                browser.close()
                return

            self.log(f"App: {plan_data.get('app_type')} — {plan_data.get('app_summary')}")
            tests = plan_data.get("tests", [])
            self.log(f"{len(tests)} test cases generated:")
            for i, t in enumerate(tests):
                self.log(f"  {i+1:2d}. [{t['name']}] {t['goal']}")

            # PHASE 3: EXECUTE
            self.log("=== PHASE 3: EXECUTE ===")
            for i, test in enumerate(tests):
                self.log(f"--- Test {i+1}/{len(tests)}: {test['name']} ---")
                self.execute_test(page, test, i + 1)

            # REPORT
            self.log(f"=== DONE — {len(self.bugs)} bug(s) found ===")
            for b in self.bugs:
                self.log(f"  [{b['prio']}] {b['issue']}")
            self.write_bugs_to_sheet()
            browser.close()


if __name__ == "__main__":
    SmartQAAgent().run()
