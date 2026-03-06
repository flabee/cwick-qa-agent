# Architecture

## Pattern

**Deterministic QA Pipeline** — Single-entry autonomous testing script (`qa_agent.py`) with no AI/LLM dependencies. Uses Playwright browser automation to execute a fixed, deterministic workflow:

```
Login → BFS State Graph Exploration → Universal Health Checks →
  Targeted Checks (6 fixed checks) → YAML Test Execution →
  Coverage Report → Bug Report (Google Sheets + Drive)
```

Architecture is **process-centric** rather than data-centric. Each phase produces artifacts (screenshots, logs, coverage metrics, bug list) that flow into the next phase. The script runs in isolation, requires no external API except Google Sheets/Drive (optional), and produces deterministic, reproducible results.

---

## Entry Points

1. **`qa_agent.py`** (2,151 lines)
   - Main executable: `python3 qa_agent.py`
   - Reads env vars: `TENANT_URL`, `TENANT_USERNAME`, `TENANT_PASSWORD`, `TENANT_NAME`, `DRIVE_FOLDER_ID`, `EXCEL_FILE_ID`
   - Entry point: `if __name__ == "__main__": QAAgent().run()`

2. **`run.sh`** (54 lines)
   - Wrapper script: `./run.sh [test1|test2|test3|test4|test5|test6]`
   - Maps tenant aliases (test1 → Docupilot, test2 → CFO AI, etc.) to environment variables
   - Sources `.env` file for secrets (username, password)
   - Delegates to `qa_agent.py`

3. **YAML Test Files** (apps/*.yaml)
   - Optional per-tenant test cases
   - Executed after BFS and targeted checks
   - Format: list of named tests, each with URL and steps (click, fill, wait, expect_visible, expect_not_text, expect_count, screenshot)

---

## Layers / Components

### 1. **State Graph (BFS Exploration)**
   - **Class:** `StateGraph` (lines 117–179)
   - **Purpose:** Track UI state changes during exploration, prevent infinite loops
   - **Key Methods:**
     - `fingerprint(url, dom_snippet)` → MD5 hash of normalized URL + partial DOM (12 chars)
     - `is_visited(fp)` → boolean check against visited set
     - `mark_visited(fp)` → add state to visited set
     - `enqueue(fp)` → add to BFS queue if not visited
     - `record_edge(from_fp, action, to_fp)` → track state transitions for coverage
   - **Data:** visited set, deque, edges list
   - **Limits:** MAX_BFS_STATES=60, prevents runaway on large apps

### 2. **Coverage Tracker**
   - **Class:** `CoverageTracker` (lines 182–232)
   - **Purpose:** Accumulate QA metrics during session
   - **Tracks:** pages_discovered, pages_tested, nav_links, buttons, modals, forms, flows, unique states
   - **Output:** Console report + JSON summary (coverage_summary.json)

### 3. **Modal Handler**
   - **Class:** `ModalHandler` (lines 235–347)
   - **Purpose:** Detect, screenshot, and safely close modal dialogs
   - **Key Methods:**
     - `detect(page)` → check for modal selectors (role=dialog, aria-modal, .modal, [data-modal])
     - `title(page)` → extract modal heading text
     - `screenshot(page, label)` → timestamped PNG
     - `handle(page, coverage)` → full lifecycle: detect → screenshot → fill safe fields → close
     - `close(page)` → try button click (Close, Cancel, aria-label), fallback to Escape key
   - **Design:** Non-destructive field filling (ignores delete/remove keywords)

### 4. **Form Handler**
   - **Class:** `FormHandler` (lines 351–441)
   - **Purpose:** Safely fill forms with test data
   - **Defaults:**
     - text → "QA Test Input"
     - email → "demo@test.com"
     - number → "1"
     - search → "QA search"
   - **Key Method:** `fill(page, form_sel="form", coverage=None)` → fills visible form fields, skips destructive fields
   - **Safety:** Never touches fields whose label contains delete/remove/destroy

### 5. **QA Agent (Main Class)**
   - **Class:** `QAAgent` (lines 445–2,150)
   - **Purpose:** Orchestrate the entire QA session
   - **Responsibilities:**
     - Google auth (init_google, Google Sheets/Drive API)
     - Bug capture and deduplication (Jaccard similarity on word sets)
     - URL/DOM helpers (norm_url, _dom_snippet)
     - Navigation (nav_to, _click_nav, _discover_nav_items)
     - Modal/form handling delegated to ModalHandler, FormHandler
     - Bad content scanning (BAD_TEXT_PATTERNS, i18n key regex)
     - Page health checks (blank page, JS errors, spinners, HTTP errors)

   - **Core Methods:**
     - `bfs_explore(page, start_url)` → Breadth-first state exploration, clicks discoverable nav + buttons
     - `_explore_section(page, section_name, section_url)` → Deep dive into a specific app section
     - `run_targeted_checks(page, browser)` → 6 fixed high-value checks (wrong credentials, PDF export, search, generate, logout)
     - `check_logout_auth_guard(page)` → Test logout + verify auth guard prevents re-entry
     - `run_yaml_tests(page)` → Execute YAML test cases from apps/{tenant}.yaml
     - `write_report()` → Write bugs to Google Sheets or local log
     - `run()` → Main orchestrator (login → BFS → checks → YAML → report)

---

## Data Flow

```
┌─────────────────────┐
│   Environment       │
│  (.env file)        │
│  TENANT_URL,        │
│  USERNAME, PASSWORD │
└──────────┬──────────┘
           │
           ▼
┌──────────────────────────────────────────┐
│  QAAgent.run() — Main Orchestrator       │
└──┬──────────┬─────────┬─────────┬────┬──┘
   │          │         │         │    │
   ▼          ▼         ▼         ▼    ▼
┌─────┐ ┌──────────┐ ┌──────┐ ┌─────┐┌───────┐
│Login│ │BFS       │ │Target│ │YAML │ │Report │
│     │ │Explore   │ │Checks│ │Test │ │       │
└──┬──┘ └──────┬───┘ └──┬───┘ └──┬──┘ └───┬───┘
   │           │        │        │        │
   └─────┬─────┴────────┴────────┴────────┘
         │
         ▼ (per action)
   ┌──────────────────────────────────────┐
   │ Screenshot / Modal Handle / Form Fill│
   │ DOM Snippet / State Fingerprint      │
   │ Bad Content Scan / Health Check      │
   └──────────────────────┬───────────────┘
         │                │
         │                ▼
         │         ┌──────────────────┐
         │         │ Bug Captured     │
         │         │ (deduped)        │
         │         └────────┬─────────┘
         │                  │
         └──────────────────┴──────────────┐
                                           │
                            ┌──────────────▼─────────────┐
                            │  self.bugs = []            │
                            │  (list of bug dicts)       │
                            └──────────────┬─────────────┘
                                           │
                                           ▼
                            ┌──────────────────────────────┐
                            │ write_report()               │
                            │ - Google Sheets API write    │
                            │ - (or local session_log.md)  │
                            └──────────────────────────────┘
```

**Key Artifacts:**
- `~/cwick-qa-agent/session_output/` → screenshots (.png), logs, coverage_summary.json
- Google Sheets: Tenant-specific sheet rows (7+) populated with bug columns (A–H)
- Drive (optional): screenshots uploaded to DRIVE_FOLDER_ID

---

## Key Abstractions

### 1. **State Fingerprinting**
   - **Purpose:** Distinguish UI states that share a URL but differ in DOM content
   - **Method:** MD5(normalized_url + partial_dom)[:12]
   - **Partial DOM includes:** page title, h1/h2 text, visible button count, form count, first 200 chars of body HTML
   - **Prevents:** Infinite loops on dynamic content; BFS stops when revisiting fingerprint

### 2. **Bug Deduplication**
   - **Mechanism:** Jaccard similarity on word sets (case-normalized, punctuation-stripped)
   - **Threshold:** >0.50 Jaccard → already reported, skip
   - **Prevents:** Duplicate bug entries from repeated traversal of same issue

### 3. **Bad Content Patterns**
   - **Literal strings:** Invalid Date, [object Object], NaN, undefined
   - **JS errors:** TypeError, ReferenceError, Unhandled Promise rejection
   - **HTTP errors:** 404, 500, 502, 503
   - **i18n leaks:** Regex match for "word.word_word" (excluding URLs, decimals, known false positives)
   - **Severity mapping:** BAD_TEXT_PATTERNS = (literal, description, prio) tuples
   - **Scan points:** After login, after every BFS click, after YAML test step

### 4. **Button Priority Scoring**
   - **High priority keywords:** create, generate, export, upload, submit, save, add, new, invite, download
   - **Medium:** edit, view, details, open, start
   - **Low:** cancel, close, back, help, info
   - **Skip keywords:** logout, sign out, log out, signout, exit, delete account, esci
   - **Purpose:** Explore high-value interactions first; avoid ending session early

### 5. **YAML Test Execution**
   - **Format:** YAML list of test objects with name, start_url, steps array
   - **Step types:** wait, click, fill, press, expect_visible, expect_not_text, expect_count, screenshot
   - **Engine:** Synchronous interpreter, Playwright locators, no async/await in user code
   - **Failure handling:** Step failure does NOT halt test suite; logs failure and continues
   - **Output:** Per-test screenshots, session_log.md records pass/fail

### 6. **Google Sheets Integration**
   - **APIs used:** Sheets API (read/update), Drive API (upload, optional)
   - **Authentication:** OAuth2 token from ~/cwick-qa-agent/token.pickle (persisted)
   - **Sheet mapping:** TENANT_NAME → sheet name (e.g., "Docupilot", "MaiHUB", "CFO AI")
   - **Row format:** Row 6 = headers, Row 7+ = bugs, 8 columns (A–H):
     - A: Issue Reported
     - B: How to reproduce
     - C: Tester
     - D: Prio (P0, P1, P2, P3)
     - E: Dev Status
     - F: Solved Prod
     - G: Note
     - H: Screenshot (filename or hyperlink)
   - **Special handling:** Rooms sheet has extra "Reported" column at A (shifts everything +1)
   - **Formatting:** batchUpdate for wrap, column widths, hyperlinks (uses textFormat.link to avoid locale issues)

---

## Control Flow (run method)

1. **Initialize** → Create browser context, load state graph from disk (if exists)
2. **Phase 1: Login**
   - Navigate to TENANT_URL
   - Fill email + password fields
   - Click login button (supports English + Italian labels)
   - Wait for URL to leave login page, confirm protected_url + home_url
3. **Phase 2: BFS Exploration**
   - `bfs_explore()` → queue initial state
   - While queue not empty AND states < MAX_BFS_STATES:
     - Pop state, mark visited
     - Discover nav items and buttons
     - For each item/button (sorted by priority):
       - Click → new state
       - Fingerprint new state
       - If new: enqueue, record edge
       - Health checks, bad content scan
       - Handle modals
4. **Phase 3: Targeted Checks** (6 fixed checks, no re-login)
   - Check 1: Wrong credentials → capture P0 if no error message
   - Check 2: PDF export → capture P1/P2 if slow/no feedback
   - Check 3: Search empty state → capture P2 if misleading message
   - Check 4: Generate/Create button → capture P1 if missing back button
   - Check 5: Specific per-tenant behaviors (Docupilot: KB modal, Rooms: home query, etc.)
5. **Phase 4: YAML Tests** (requires re-login if session expired)
   - Re-login if needed
   - For each test in YAML:
     - Navigate to start_url
     - Execute steps in order
     - Log pass/fail
6. **Phase 5: Check 6 — Logout + Auth Guard**
   - Click logout button
   - Attempt to navigate back to protected URL
   - Capture P0/P1 if accessible without re-login
7. **Phase 6: Reporting**
   - Print coverage report to console
   - Save coverage_summary.json
   - Call `write_report()` → Google Sheets or local log
   - Close browser

---

## Error Handling & Recovery

- **Network timeouts:** Caught in try/except, logged, continue
- **Selector failures:** Silent skip (element not found, not visible)
- **Modal stuck:** After attempts, Escape key fallback
- **Form field skipping:** Silently ignore fields that are not visible or have destructive labels
- **Google API failures:** Log warning, fall back to local JSON log
- **YAML step failures:** Log failure, continue to next step/test
- **Session loss:** Re-login before YAML tests if needed

---

## Configuration & Limits

| Setting | Value | Purpose |
|---------|-------|---------|
| MAX_BFS_STATES | 60 | Max states explored (prevent runaway) |
| MAX_NAV_ITEMS | 16 | Nav items discovered before capping |
| MAX_BTN_PER_PAGE | 15 | Buttons clicked per page before capping |
| JACCARD_THRESHOLD | 0.50 | Bug dedup similarity threshold |
| Timeouts | 10s (nav), 8s (click), 1s (load idle) | Playwright wait limits |

---

## Threading & Concurrency

**Single-threaded, synchronous.** No async/await, no background tasks. Playwright uses sync API (`sync_playwright`). Each action waits for completion before proceeding.
