import os, re, time, datetime, pickle
from pathlib import Path
from playwright.sync_api import sync_playwright
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

TENANT_URL      = os.environ.get("TENANT_URL", "")
USERNAME        = os.environ.get("TENANT_USERNAME", "")
PASSWORD        = os.environ.get("TENANT_PASSWORD", "")
TENANT_NAME     = os.environ.get("TENANT_NAME", "Unknown")
DRIVE_FOLDER_ID = os.environ.get("DRIVE_FOLDER_ID", "")
EXCEL_FILE_ID   = os.environ.get("EXCEL_FILE_ID", "")

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


class StandardQA:
    def __init__(self):
        self.bugs = []
        self.drive_svc = None
        self.sheet_svc = None
        self.protected_url = ""  # a known-authenticated URL to test auth guard

    def log(self, msg):
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}")

    def init_google(self):
        tpath = Path(os.path.expanduser("~/cwick-qa-agent/token.pickle"))
        if tpath.exists():
            with open(tpath, "rb") as f:
                creds = pickle.load(f)
            self.drive_svc = build("drive", "v3", credentials=creds)
            self.sheet_svc = build("sheets", "v4", credentials=creds)
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
        self.log(f"  [BUG {prio}] {issue}")

    def nav_to(self, page, keywords):
        """Click the first nav item matching any keyword. Returns matched keyword or None."""
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
                        time.sleep(2)
                        self.log(f"  -> Navigated to '{kw}' at {page.url}")
                        return kw
                except Exception:
                    pass
        return None

    def discover_nav(self, page):
        """Return dict of {text: href} for all visible nav items."""
        found = {}
        for sel in [
            "nav :is(button,a)",
            "aside :is(button,a)",
            "[role='navigation'] :is(button,a)",
            "[class*='sidebar'] :is(button,a)",
        ]:
            for el in page.locator(sel).all():
                try:
                    text = el.inner_text().strip()
                    href = el.get_attribute("href") or ""
                    if text and 1 < len(text) < 50:
                        found[text] = href
                except Exception:
                    pass
        return found

    def run(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            page = browser.new_page()

            # --- LOGIN ---
            self.log(f"Starting session for {TENANT_NAME}")
            page.goto(TENANT_URL)
            page.locator("input[type='email']").fill(USERNAME)
            page.locator("input[type='password']").fill(PASSWORD)
            page.get_by_role("button", name=re.compile("Sign in|Login", re.I)).click()
            try:
                page.wait_for_url(lambda u: "login" not in u, timeout=15000)
            except Exception:
                self.log("Login may have failed — URL still contains 'login'")
            self.protected_url = page.url
            self.log(f"Logged in at: {self.protected_url}")
            page.wait_for_load_state("networkidle", timeout=15000)
            time.sleep(3)

            # --- DISCOVER NAV ---
            self.log("Discovering navigation...")
            nav = self.discover_nav(page)
            self.log(f"  Sections found: {list(nav.keys())}")

            # ── CHECK 1: Wrong credentials ─────────────────────────────────────
            self.log("Check 1: Wrong credentials error message")
            anon = browser.new_context()
            anon_page = anon.new_page()
            anon_page.goto(TENANT_URL)
            anon_page.locator("input[type='email']").fill("wrong@test.it")
            anon_page.locator("input[type='password']").fill("wrongpassword")
            anon_page.get_by_role("button", name=re.compile("Sign in|Login", re.I)).click()
            time.sleep(3)
            if "login" in anon_page.url:
                error_visible = anon_page.locator(
                    ":is(.error,[class*='error'],[class*='alert'],[role='alert'],"
                    "[class*='invalid'],[class*='warning']):visible"
                ).count() > 0
                if not error_visible:
                    self.capture_bug(
                        anon_page,
                        "Wrong credentials: no error message shown",
                        "1. Go to login page\n2. Enter wrong email/password\n3. Click Sign in\n4. No error appears",
                        "P0", "Security: user gets no feedback on bad credentials"
                    )
            anon_page.close()
            anon.close()

            # ── CHECK 2: Create New / document creation flow ───────────────────
            self.log("Check 2: Create new / document creation flow")
            # Start from dashboard/documents where New button is most likely
            self.nav_to(page, ["Dashboard", "Documents", "Home"])
            time.sleep(1)

            # Broad selector — catches "New", "+ New", "New Document", "New document", etc.
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
                # Try nav section called "New" or "Generate"
                matched = self.nav_to(page, ["New", "Generate", "Create", "New document"])
                if matched:
                    found_new = True

            if found_new:
                try:
                    new_btn.click(timeout=3000)
                    page.wait_for_load_state("networkidle", timeout=10000)
                    time.sleep(2)
                except Exception:
                    pass  # already navigated via nav_to
                self._test_creation_flow(page)
            else:
                # Last resort: navigate directly to /new relative to the tenant base path
                # Extract tenant prefix from protected_url (e.g. /docupilot)
                from urllib.parse import urlparse
                parsed = urlparse(self.protected_url)
                parts = parsed.path.strip("/").split("/")
                if len(parts) >= 1:
                    new_url = f"{parsed.scheme}://{parsed.netloc}/{parts[0]}/new"
                    page.goto(new_url)
                    page.wait_for_load_state("networkidle", timeout=10000)
                    time.sleep(2)
                    cards = page.locator(
                        "[class*='card'], [class*='template'], [class*='option']"
                    ).count()
                    if cards > 0:
                        self._test_creation_flow(page)
                    else:
                        self.log("  No creation cards found at /new — skipping")

            # ── CHECK 3: Knowledge Base ────────────────────────────────────────
            self.log("Check 3: Knowledge Base")
            kb = self.nav_to(page, ["Knowledge Base", "Knowledge base", "KB", "Library", "Resources"])
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
                            "P2", "May be a data-load issue"
                        )
                else:
                    # Try clicking the first item
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

                    # Look for a "Use as base" / "Generate from" action
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
                                f"Knowledge Base: 'Use as base' button opens no dialog or form",
                                f"1. Go to '{kb}'\n2. Click 'Use as base'\n3. No dialog or form appears",
                                "P1", "Cannot initiate KB-based document creation"
                            )
            else:
                self.log("  No Knowledge Base section found — skipping")

            # ── CHECK 4: Chat / AI Assistant ───────────────────────────────────
            self.log("Check 4: Chat / AI Assistant")
            chat = self.nav_to(page, ["Chat", "AI Chat", "Copilot", "Assistant", "Messages", "AI Assistant"])
            if chat:
                chat_input = page.locator(
                    "textarea, [contenteditable='true'], "
                    "input[placeholder*='message' i], input[placeholder*='ask' i], "
                    "input[placeholder*='type' i]"
                )
                if chat_input.count() == 0:
                    self.capture_bug(
                        page,
                        f"Chat: no message input found in '{chat}' section",
                        f"1. Log in\n2. Navigate to '{chat}'\n3. No text input visible to type a message",
                        "P1", "Chat section has no message input — core functionality broken"
                    )
                else:
                    chat_input.first.fill("Hello, can you give me a brief summary of your capabilities?")
                    send_btn = page.locator(
                        ":is(button,[role='button']):has-text('Send'),"
                        ":is(button,[role='button']):has-text('Submit'),"
                        "button[type='submit'], [aria-label*='send' i]"
                    )
                    if send_btn.count() > 0:
                        send_btn.first.click()
                    else:
                        chat_input.first.press("Enter")
                    time.sleep(6)
                    response_visible = page.locator(
                        "[class*='message']:not([class*='user']), [class*='response'],"
                        "[class*='assistant'], [class*='bot'], [class*='ai-message']"
                    ).count() > 0
                    still_loading = page.locator(
                        "[class*='loading'], [class*='spinner'], [class*='typing'], [class*='streaming']"
                    ).count() > 0
                    if not response_visible and not still_loading:
                        self.capture_bug(
                            page,
                            f"Chat: no response shown after sending a message",
                            f"1. Navigate to '{chat}'\n2. Type a message\n3. Press Send\n4. No AI response appears after 6s",
                            "P1", "AI chat is not responding to messages"
                        )
            else:
                self.log("  No Chat section found — skipping")

            # ── CHECK 5: Search empty state ────────────────────────────────────
            self.log("Check 5: Search empty state")
            self.nav_to(page, ["Documents", "Dashboard", "Home"])
            time.sleep(1)
            search = page.locator(
                "input[type='search'], input[placeholder*='Search' i], input[placeholder*='search' i]"
            )
            if search.count() > 0:
                search.first.fill("zzznoresultsxxx")
                time.sleep(2)
                body_text = page.locator("body").inner_text()
                if "No generated documents" in body_text:
                    self.capture_bug(
                        page,
                        "Search empty state: misleading 'No generated documents' message",
                        "1. Go to Documents\n2. Search for a non-existent term\n"
                        "3. Message reads 'No generated documents' (misleading for a search result)",
                        "P2", "Message should say 'No documents match your search'"
                    )
                elif not any(phrase in body_text.lower() for phrase in
                             ["no result", "not found", "no match", "empty", "0 result", "nessun"]):
                    self.capture_bug(
                        page,
                        "Search empty state: no feedback shown for empty search results",
                        "1. Navigate to a list page\n2. Search for a non-existent term\n"
                        "3. No empty-state message appears",
                        "P3", "UX: users should see a clear empty-state message"
                    )
                search.first.fill("")
            else:
                self.log("  No search input found — skipping")

            # ── CHECK 6: Logout + auth guard ───────────────────────────────────
            self.log("Check 6: Logout and auth guard")
            self.nav_to(page, ["Dashboard", "Home"])
            time.sleep(1)
            logout_btn = page.locator(
                ":is(button,a,[role='button']):has-text('Logout'),"
                ":is(button,a,[role='button']):has-text('Sign out'),"
                ":is(button,a,[role='button']):has-text('Log out')"
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
                        f"1. Log out\n2. Navigate directly to {self.protected_url}\n"
                        "3. Page loads without redirecting to login",
                        "P0", "Security: protected routes should redirect unauthenticated users"
                    )
            else:
                self.log("  Logout button not found — skipping auth guard check")

            # --- REPORT ---
            self.finalize_report()
            browser.close()

    def _test_creation_flow(self, page):
        """After landing on a creation page, try to fill and submit the form."""
        # Fill title/name if present
        name_input = page.locator(
            "input[placeholder*='name' i], input[placeholder*='title' i], "
            "input[placeholder*='document' i], input[type='text']:visible"
        )
        if name_input.count() > 0:
            name_input.first.fill("QA Test Document")

        # Fill prompt/topic if present
        prompt_input = page.locator(
            "textarea, input[placeholder*='prompt' i], input[placeholder*='topic' i], "
            "input[placeholder*='describe' i]"
        )
        if prompt_input.count() > 0:
            prompt_input.first.fill("Write a short document about software quality assurance.")

        # Click the first creation card (Docupilot: blank/template/existing)
        card = page.locator(
            "[class*='card']:has-text('blank'), [class*='card']:has-text('template'),"
            "[class*='card']:has-text('existing'), [class*='option']:visible"
        )
        if card.count() > 0:
            card.first.click()
            time.sleep(2)

        # Click Generate / Create / Submit
        gen_btn = page.locator(
            ":is(button,[role='button']):has-text('Generate'),"
            ":is(button,[role='button']):has-text('Create'),"
            ":is(button,[role='button']):has-text('Submit'),"
            ":is(button,[role='button']):has-text('Start')"
        )
        if gen_btn.count() == 0:
            self.capture_bug(
                page,
                "Create flow: no Generate/Create button visible after selecting a template",
                "1. Navigate to the 'New document' section\n2. Select a creation card\n"
                "3. No Generate or Create button is visible",
                "P1", "Cannot complete document creation"
            )
            return

        gen_btn.first.click()
        time.sleep(3)

        # Check for loading feedback
        loading_visible = page.locator(
            ":is([class*='loading'],[class*='spinner'],[class*='progress'],"
            "[class*='generating'],[role='progressbar']):visible"
        ).count() > 0
        if not loading_visible:
            self.capture_bug(
                page,
                "Create flow: no loading feedback during document generation",
                "1. Start document creation\n2. Click Generate\n3. No spinner or progress bar appears",
                "P2", "User has no feedback while AI is generating"
            )

        # Wait for generation to complete (URL changes to editor or generate route)
        try:
            page.wait_for_url(
                lambda u: "/editor/" in u or "/generate/" in u or u != page.url,
                timeout=30000
            )
            time.sleep(2)
        except Exception:
            self.capture_bug(
                page,
                "Create flow: generation timed out or did not navigate (30s)",
                "1. Start document creation\n2. Click Generate\n"
                "3. Page never navigates to result after 30s",
                "P1", "AI generation either failed silently or is extremely slow"
            )

    def finalize_report(self):
        if not self.init_google():
            return self.log("Google Drive not connected. Check token.pickle.")

        # Upload screenshots to Drive
        uploaded = 0
        for bug in self.bugs:
            path = SESSION_DIR / bug["screenshot"]
            if not path.exists():
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
                self.log(f"Drive upload failed for {bug['screenshot']}: {e}")
        self.log(f"Uploaded {uploaded}/{len(self.bugs)} screenshots to Drive.")

        # Write bugs to Sheets
        if self.bugs and EXCEL_FILE_ID:
            sheet_name = SHEET_MAP.get(TENANT_NAME, TENANT_NAME)
            col = "B" if TENANT_NAME == "Rooms" else "A"
            try:
                existing_res = self.sheet_svc.spreadsheets().values().get(
                    spreadsheetId=EXCEL_FILE_ID,
                    range=f"'{sheet_name}'!A7:A"
                ).execute()
                existing_issues = {
                    row[0].strip().lower()
                    for row in existing_res.get("values", [])
                    if row and row[0]
                }
                new_bugs = [b for b in self.bugs if b["issue"].strip().lower() not in existing_issues]
                skipped = len(self.bugs) - len(new_bugs)
                if skipped:
                    self.log(f"Skipped {skipped} already-reported bug(s).")
                if not new_bugs:
                    self.log("No new bugs to write.")
                    return

                rows = []
                for b in new_bugs:
                    row = [b["issue"], b["reproduce"], "QA Agent",
                           b["prio"], "", "", b["note"], b.get("link") or b["screenshot"]]
                    if col == "B":
                        row = [""] + row
                    rows.append(row)

                result = self.sheet_svc.spreadsheets().values().append(
                    spreadsheetId=EXCEL_FILE_ID,
                    range=f"'{sheet_name}'!A7",
                    valueInputOption="RAW",
                    insertDataOption="INSERT_ROWS",
                    body={"values": rows},
                ).execute()
                updated = result.get("updates", {}).get("updatedRange", "?")
                self.log(f"Wrote {len(new_bugs)} new bug(s) to '{sheet_name}' at {updated}.")
            except Exception as e:
                self.log(f"Sheets write failed: {e}")

        # Clean up uploaded screenshots
        deleted = 0
        for bug in self.bugs:
            if bug.get("link"):
                path = SESSION_DIR / bug["screenshot"]
                if path.exists():
                    path.unlink()
                    deleted += 1
        self.log(f"Cleaned up {deleted} uploaded screenshots. Session complete.")


if __name__ == "__main__":
    StandardQA().run()
