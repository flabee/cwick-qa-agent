"""
Consolidated QA Agent v2 — Efficiency & Token Optimized
Combines discovery, targeted tests, and reporting into one pass.
"""
import os, re, time, json, datetime, pickle
from pathlib import Path
from playwright.sync_api import sync_playwright
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
import io

# --- CONFIGURATION ---
TENANT_URL      = os.environ.get("TENANT_URL", "")
TENANT_USERNAME = os.environ.get("TENANT_USERNAME", "")
TENANT_PASSWORD = os.environ.get("TENANT_PASSWORD", "")
TENANT_NAME     = os.environ.get("TENANT_NAME", "Unknown")
DRIVE_FOLDER_ID = os.environ.get("DRIVE_FOLDER_ID", "")
EXCEL_FILE_ID   = os.environ.get("EXCEL_FILE_ID", "")

SESSION_DIR = Path(os.path.expanduser("~/cwick-qa-agent/session_output"))
SESSION_DIR.mkdir(parents=True, exist_ok=True)

class QAAgent:
    def __init__(self):
        self.bugs = []
        self.logs = []
        self.drive_service = None
        self.sheet_service = None
        self.base_url = ""
        self.start_time = datetime.datetime.now()

    def log(self, msg):
        t = datetime.datetime.now().strftime("%H:%M:%S")
        line = f"[{t}] {msg}"
        print(line)
        self.logs.append(line)

    def init_google_services(self):
        token_path = Path(os.path.expanduser("~/cwick-qa-agent/token.pickle"))
        if token_path.exists():
            with open(token_path, "rb") as f:
                creds = pickle.load(f)
                self.drive_service = build("drive", "v3", credentials=creds)
                self.sheet_service = build("sheets", "v4", credentials=creds)
                self.log("Google Services Initialized")
                return True
        self.log("Google Credentials not found. Local reporting only.")
        return False

    def smart_wait(self, page, timeout=5000):
        """Reduces idle time compared to 'networkidle'"""
        try:
            page.wait_for_load_state("domcontentloaded", timeout=timeout)
        except:
            pass

    def capture_bug(self, page, issue, reproduce, prio, note):
        bug_id = len(self.bugs) + 1
        safe_name = re.sub(r'\W+', '_', issue[:30]).lower()
        filename = f"BUG_{bug_id:03d}_{safe_name}.png"
        path = SESSION_DIR / filename
        page.screenshot(path=path)
        
        self.bugs.append({
            "id": bug_id, "issue": issue, "reproduce": reproduce,
            "prio": prio, "note": note, "screenshot": filename, "link": ""
        })
        self.log(f"Captured {prio}: {issue}")

    def run_targeted_checks(self, page):
        """Merges logic from qa_targeted.py and session scripts"""
        # 1. Check User Menu
        self.log("Checking User Menu...")
        page.locator("button[aria-haspopup='menu'], .user-avatar, #user-menu").first.click()
        self.smart_wait(page)
        if "Settings" not in page.content():
            self.capture_bug(page, "User menu missing items", "Click avatar", "P2", "Settings not visible")

        # 2. Check PDF Export (from qa_targeted)
        self.log("Checking PDF Export...")
        # (Insert your specific PDF selector logic here)

    def run_session(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            context = browser.new_context()
            page = context.new_page()

            # --- PHASE 1: LOGIN ---
            self.log(f"Logging into {TENANT_URL}")
            page.goto(TENANT_URL)
            page.locator("input[type='email']").fill(TENANT_USERNAME)
            page.locator("input[type='password']").fill(TENANT_PASSWORD)
            page.get_by_role("button", name=re.compile("Sign in|Login", re.I)).click()
            
            self.smart_wait(page)
            self.base_url = page.url.rsplit('/', 1)[0]

            # --- PHASE 2: TARGETED CHECKS ---
            self.run_targeted_checks(page)

            # --- PHASE 3: REPORTING ---
            self.finalize_report()
            browser.close()

    def finalize_report(self):
        self.log(f"QA Finished. Total Bugs: {len(self.bugs)}")
        # Save local log
        log_path = SESSION_DIR / "session_log.md"
        log_path.write_text("\n".join(self.logs))
        
        if self.init_google_services():
            # Batch upload screenshots and update Sheets
            self.log("Uploading to Drive...")
            # (Insert optimized batch upload/sheet update logic here)

if __name__ == "__main__":
    agent = QAAgent()
    agent.run_session()
