import os, re, time, datetime, pickle, json
from pathlib import Path
from playwright.sync_api import sync_playwright
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
import io
import openpyxl

# --- ENV CONFIG ---
TENANT_URL      = os.environ.get("TENANT_URL", "")
USERNAME        = os.environ.get("TENANT_USERNAME", "")
PASSWORD        = os.environ.get("TENANT_PASSWORD", "")
TENANT_NAME     = os.environ.get("TENANT_NAME", "Unknown")
DRIVE_FOLDER_ID = os.environ.get("DRIVE_FOLDER_ID", "")
EXCEL_FILE_ID   = os.environ.get("EXCEL_FILE_ID", "")

SESSION_DIR = Path(os.path.expanduser("~/cwick-qa-agent/session_output"))
SESSION_DIR.mkdir(parents=True, exist_ok=True)

class StandardQA:
    def __init__(self):
        self.bugs = []
        self.drive_svc = None
        self.sheet_svc = None
        self.base_url = ""

    def log(self, msg):
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}")

    def init_google(self):
        tpath = Path(os.path.expanduser("~/cwick-qa-agent/token.pickle"))
        if tpath.exists():
            with open(tpath, "rb") as f:
                creds = pickle.load(f)
                self.drive_svc = build("drive", "v3", credentials=creds)
                return True
        return False

    def capture_bug(self, page, issue, reproduce, prio, note):
        bid = len(self.bugs) + 1
        fname = f"BUG_{bid:03d}_{prio}.png"
        page.screenshot(path=SESSION_DIR / fname)
        self.bugs.append({
            "id": bid, "issue": issue, "reproduce": reproduce,
            "prio": prio, "note": note, "screenshot": fname, "link": ""
        })

    def run(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            page = browser.new_page()
            
            # 1. LOGIN
            self.log(f"Starting session for {TENANT_NAME}")
            page.goto(TENANT_URL)
            page.locator("input[type='email']").fill(USERNAME)
            page.locator("input[type='password']").fill(PASSWORD)
            page.get_by_role("button", name=re.compile("Sign in|Login", re.I)).click()
            page.wait_for_load_state("domcontentloaded")
            self.base_url = page.url.rsplit('/', 1)[0]

            # 2. TARGETED CHECKS (PDF, Search, etc.)
            self.log("Running targeted checks...")
            # (Insert your specific page navigation and clicks here)

            # 3. REPORTING & CLEANUP
            self.finalize_report()
            browser.close()

    def finalize_report(self):
        if not self.init_google():
            return self.log("Google Drive not connected. Check token.pickle.")

        # PASS 1: Upload Screenshots to Drive
        for bug in self.bugs:
            path = SESSION_DIR / bug['screenshot']
            media = MediaFileUpload(str(path), mimetype='image/png')
            f = self.drive_svc.files().create(
                body={'name': bug['screenshot'], 'parents': [DRIVE_FOLDER_ID]},
                media_body=media, fields='webViewLink'
            ).execute()
            bug['link'] = f.get('webViewLink')

        # PASS 2: Update Excel (Logical Placeholder)
        self.log(f"Linked {len(self.bugs)} bugs to Drive. Updating Excel...")
        
        # PASS 3: Local Cleanup
        for file in SESSION_DIR.glob("*"):
            file.unlink()
        self.log("Session output cleared. Report is live on Drive.")

if __name__ == "__main__":
    StandardQA().run()
