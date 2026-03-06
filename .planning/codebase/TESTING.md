# Testing

## Framework

### Primary Framework: Playwright (Browser Automation)
- **Tool**: `playwright.sync_api` (synchronous, deterministic)
- **Browser**: Chromium (headless=False for visibility, can be set to True for CI)
- **Purpose**: End-to-end UI testing (no unit tests; black-box QA only)
- **Installation**: `pip install playwright`
- **Optional dependencies**:
  - `pyyaml` — for declarative YAML test cases (gracefully skipped if not installed)
  - `google-auth`, `google-auth-httplib2`, `google-api-python-client` — for Sheets integration

### No Unit Testing Framework
- **No pytest, unittest, or mock imports** — all testing is integration/E2E
- **No test fixtures** — stateful browser sessions drive all tests
- **No assertions library** — bugs captured as observed state deviations, not assertion failures
- **Script is deterministic** — same input (credentials + tenant) → predictable test sequence

### Manual Test Artifacts
- **YAML config files** (6 tenants):
  - `/apps/Docupilot.yaml`
  - `/apps/MaiHUB.yaml`
  - `/apps/CFO AI.yaml`
  - `/apps/Rooms.yaml`
  - `/apps/A33.yaml`
  - `/apps/Tenant Base (Cwick Core).yaml`
- **Old reference scripts** (not maintained):
  - `run_standard_qa.py` — basic 6-check template
  - `run_smart_qa.py` — earlier iteration (kept for fallback)
- **Canonical script**: `qa_agent.py` (2151 lines, all-in-one)

### No CI/CD Integration
- **No GitHub Actions, Jenkins, or GitLab CI** — script run manually or via shell wrapper
- **Launcher script**: `run.sh` loads env vars (`.env` file) and routes to correct tenant
- **Output artifacts**:
  - Screenshots: `session_output/{timestamp}_*.png`
  - Session log: `session_output/session_log.md`
  - Coverage summary: `session_output/coverage_summary.json`
  - Google Sheets: bugs written to Cwick_Demo_Test.xlsx (optional)

## Structure

### Test Organization

#### Phase 1: Login
- **Goal**: Authenticate user; establish protected URL
- **Steps**:
  1. Navigate to `TENANT_URL` (login page)
  2. Fill email input with `TENANT_USERNAME`
  3. Fill password input with `TENANT_PASSWORD`
  4. Click Sign in button (multi-language support: English + Italian)
  5. Wait for URL change (exit login page)
  6. Verify `networkidle` state reached
  7. Record `protected_url` (used later for auth guard check)
- **Success criterion**: URL no longer contains "login" AND page fully loaded
- **Failure handling**: Log warning, continue (some pages have slow auth redirects)

#### Phase 2: BFS Exploration
- **Goal**: Map all reachable UI states; discover pages, buttons, flows
- **Algorithm**: Breadth-first search with state fingerprinting
- **Steps**:
  1. Navigate to home page (post-login)
  2. Discover all nav items (top 16, skip destructive keywords)
  3. Click each nav item → record new URL
  4. For each section:
     - Find and click tabs (max 6)
     - Find and click sub-nav links (max 6)
     - Click first list item (to test detail view)
     - Click all action buttons (max 15, priority-sorted by keyword)
  5. Detect modals (take screenshot, fill safe fields, close)
  6. Stop when 60 states visited or all reachable states exhausted
- **Coverage tracked**:
  - `pages_discovered`: Unique normalized URLs
  - `buttons_discovered`: Count of all visible buttons
  - `buttons_clicked`: Buttons actually clicked
  - `states_visited`: Unique fingerprints (URL + DOM)
  - `modals_opened`: Modal count
  - `forms_filled`: Form submission attempts
  - `flows_explored`: Navigation edges

#### Phase 3: Universal Health Checks (Per Page)
- **Trigger**: Runs on every new state discovered during BFS
- **Checks** (6 health check functions):
  1. **Blank page**: Body text < 30 chars → P1 bug
  2. **Console JS errors**: Captured via `page.on("console")` → P2 bug
  3. **Visible error message**: Locator `:is(.error, [role='alert'])` visible → P1 bug
  4. **Infinite spinner**: Loading indicator still visible after 3s → P1 bug
  5. **404/500 content**: Body text matches `\b404\b|\b500\b` → P1 bug
  6. **Bad content scan**:
     - Literal patterns: `Invalid Date`, `[object Object]`, `NaN`, `undefined` → P1/P2
     - i18n key leaks: `pagination.next_page` pattern → P2
     - Empty state without explanation (< 300 chars) → P3

#### Phase 4: Targeted Checks (6 Fixed Checks)
- **Goal**: Test high-value flows same way across all tenants
- **Checks**:

  1. **Wrong credentials** (P0)
     - New anonymous context
     - Login with wrong email + password
     - Verify error message appears
     - Bug if no error: "Wrong credentials: no error message shown"

  2. **Document creation flow** (P1/P2)
     - Navigate to Documents/Dashboard/Home
     - Find and click "New" button
     - Select creation template or card
     - Fill optional fields (name, prompt)
     - Click Generate/Create/Submit
     - Verify loading feedback appears
     - Wait for URL change to `/editor/` or `/generate/`
     - Capture bugs if:
       - No loading feedback
       - Generation timeout (30s)
       - No creation button visible

  3. **Knowledge Base** (P1/P2)
     - Navigate to Knowledge Base section
     - If empty: verify empty-state message
     - If has items:
       - Click first item
       - Look for "Use as base" button
       - Click it
       - Verify modal/form appears for document generation
       - Capture bugs if:
         - No empty-state message on empty KB
         - "Use as base" opens no dialog

  4. **Chat / AI Assistant** (P1)
     - Navigate to Chat/Copilot/Assistant section
     - Find message input (textarea or contenteditable)
     - Type a test prompt
     - Click Send or press Enter
     - Wait 6s for AI response
     - Capture bug if:
       - No message input found
       - No response visible after 6s (and no loading spinner)

  5. **Search empty state** (P2/P3)
     - Navigate to Documents/list view
     - Find search input
     - Search for non-existent term: `zzznoresultsxxx`
     - Wait 2s for results
     - Capture bug if:
       - No empty-state message appears
       - Wrong message (`No generated documents` instead of `No search results`)

  6. **Logout + auth guard** (P0/P1)
     - Find and click Logout button (or trigger via avatar/profile menu)
     - Navigate back to `protected_url` (the home page from login)
     - Capture bug if:
       - URL no longer contains "login" (auth guard bypass)
       - Should redirect to login

#### Phase 5: YAML Tests (Optional, Per-Tenant)
- **Goal**: Run tenant-specific declarative test scenarios
- **File location**: `apps/{TENANT_NAME}.yaml` (exact sheet name required)
- **Format**: YAML array of test objects
- **Each test object**:
  ```yaml
  - name: "human-readable test name"
    start_url: "https://..."  # optional; defaults to home_url
    steps:
      - action: value  # see Actions below
      - action: value
  ```
- **Test execution**:
  - Load YAML via `yaml.safe_load()`
  - For each test:
    - Navigate to start_url (or home if omitted)
    - Execute steps sequentially
    - Capture any assertion failures as bugs
    - Continue to next test on error

#### Phase 6: Report Writing
- **Goal**: Persist bugs to Google Sheets and/or local markdown
- **Steps**:
  1. Filter bugs: exclude already-reported (case-insensitive title match)
  2. Upload screenshots to Google Drive (optional, skipped if Drive access fails)
  3. Write bug rows to Google Sheets:
     - Columns: Issue | Reproduce | Tester | Prio | Dev Status | Solved | Note | Screenshot
     - Rooms sheet special case: extra "Reported" column (insert empty string)
  4. Apply formatting via `batchUpdate`:
     - Text wrap enabled
     - Column widths set
     - Hyperlinks added to screenshot cells (textFormat.link, not =HYPERLINK formula)
  5. Write local markdown log: `session_log.md` with coverage summary + bug list
  6. Write coverage JSON: `coverage_summary.json` for metrics aggregation

### Test Execution Flow (Sequence Diagram)

```
┌──────────────────────────────────────────────────────────────┐
│ 1. Validate env vars (TENANT_URL, USERNAME, PASSWORD)       │
└──────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────┐
│ 2. Launch browser (Chromium, headless=False)                │
│    Set up console error listener                            │
└──────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────┐
│ 3. Login phase                                               │
│    → Navigate to login page                                 │
│    → Fill credentials                                       │
│    → Click Sign in                                          │
│    → Wait for auth (networkidle)                            │
│    → Record home_url, protected_url                         │
└──────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────┐
│ 4. BFS exploration                                           │
│    → Discover nav items                                     │
│    → Visit each section                                     │
│    → Explore tabs, sub-nav, detail views, buttons           │
│    → Run health checks on each new state                    │
│    → Detect & screenshot modals                             │
│    → Stop at 60 states or exhaustion                        │
└──────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────┐
│ 5. Targeted checks (6 fixed checks)                          │
│    → Wrong credentials                                      │
│    → Create flow                                            │
│    → Knowledge Base                                         │
│    → Chat / AI                                              │
│    → Search empty state                                     │
│    → Logout + auth guard                                    │
└──────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────┐
│ 6. Re-login (if logged out in check 6)                       │
└──────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────┐
│ 7. YAML tests (if apps/{TENANT_NAME}.yaml exists)            │
│    → Load and parse YAML                                    │
│    → For each test:                                         │
│      - Navigate to start_url                                │
│      - Execute steps (click, fill, expect_visible, etc.)    │
│      - Capture assertion failures                           │
└──────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────┐
│ 8. Coverage report (print + JSON)                            │
└──────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────┐
│ 9. Write report                                              │
│    → Upload screenshots to Drive (optional)                 │
│    → Write bugs to Google Sheets (with dedup)               │
│    → Write local markdown log                               │
│    → Close browser                                          │
└──────────────────────────────────────────────────────────────┘
```

## Mocking

### No Mocking Used
- **Rationale**: Codebase is entirely E2E; no unit tests to mock
- **All interactions are real**: Playwright controls actual browser, hits live tenants
- **Credentials are real**: Uses demo accounts on staging/production tenants
- **No API mocking**: Calls to Google Drive/Sheets use real OAuth credentials

### Modal and Form Filling as "Test Doubles"
- **ModalHandler**: Provides safe, non-destructive modal interaction pattern
  - Fills only email/text inputs (skips delete/remove fields)
  - Closes via selector priority (Close button → Escape)
  - Used to prevent session corruption during exploration
- **FormHandler**: Similar safe-fill pattern for form inputs
  - Type-based defaults: email → `demo@test.com`, text → `QA Test Input`
  - Skips destructive fields (label contains "delete", "remove", "destroy")

## Coverage

### What's Tested

#### Implicit Coverage (BFS Exploration)
- **All discoverable pages**: BFS visits max 60 unique states
- **Navigation flows**: Tracks edges; calculates flow count
- **Modal dialogs**: Detected, screenshotted, filled, closed
- **Responsive elements**: Buttons, tabs, sub-nav
- **Dynamic content**: List items, detail views, tables

#### Explicit Coverage (Targeted Checks)
- **Authentication**: Wrong credentials, auth guard, logout
- **Document creation**: Full flow from template/blank to generation
- **Knowledge Base**: Empty state, item selection, "Use as base" action
- **Chat/AI**: Message input, sending, response reception
- **Search**: Empty-state messaging for no results
- **Bad content**: JS leaks (undefined, [object Object], Invalid Date), HTTP errors, untranslated i18n keys

#### YAML-Driven Coverage (Per-Tenant)
- **Docupilot**: Dashboard, documents, KB, new document page, from-existing flow, generation chat
- **MaiHUB**: Admin panels (users, courses, teachers, news), carousel, search filters
- **CFO AI**: Chat, documents, strategic analysis, news, admin
- **Rooms**: Home, chat, data room, projects, file viewer
- **A33, Tenant Base**: Basic navigation and health checks

### What's NOT Tested

#### Out of Scope (Intentionally)
- **Performance/load testing**: No metrics on response times or stress testing
- **Accessibility (a11y)**: No WCAG or ARIA compliance checks
- **Visual regression**: No screenshot comparison or visual diff
- **Mobile/responsive**: No responsive breakpoint testing (always full desktop browser)
- **API testing**: No direct REST/GraphQL calls; only browser-level interactions
- **Database/backend**: No direct DB queries or backend state verification
- **Security scanning**: No OWASP/static analysis; only runtime observations
- **Internationalization (i18n) thoroughness**: Only flags leaked i18n keys; doesn't test all translations

#### Gaps
- **Error recovery**: Only captures first occurrence; doesn't test "retry" flows
- **Concurrent user scenarios**: Single-session only
- **Long-running tests**: 30s timeout max; doesn't stress test long operations
- **Offline/network degradation**: No network throttling or failure injection
- **Third-party integrations**: No external API mocking; assumes services are up

### Coverage Metrics (Tracked)

#### Per-Session Counters
```
pages_discovered     — Total unique URL + hash combinations
pages_tested         — Subset of pages_discovered that were interacted with
nav_links_found      — Count of all navigation items
buttons_discovered   — Total buttons on all pages (visibility-filtered)
buttons_clicked      — Buttons actually clicked during exploration
modals_handled       — Modal dialogs encountered and closed
forms_filled         — Form submission attempts
flows_explored       — State transitions (edges in state graph)
states_visited       — Unique fingerprints (URL + DOM hash)
bugs_detected        — Bug count
```

#### Aggregation
- Console output: Human-readable table
- JSON: Machine-readable structured metrics
- Markdown log: Narrative format with links to screenshots

### Test Artifact Retention
- **Screenshots**: Kept in `session_output/` until explicitly deleted after Drive upload
- **Logs**: Session markdown always written locally (`session_log.md`)
- **Coverage JSON**: Persisted for metric trending over time
- **Sheets bugs**: Deduplicated by title; not deleted (permanent issue history)

### Maintenance and Extensions

#### Adding a New Targeted Check
1. Add to `run_targeted_checks(self, page, browser)` method in QAAgent
2. Follow "Check N" pattern: log, try/except wrapper, capture_bug() on failure
3. Ensure check is idempotent (can run multiple times)
4. Document in docstring (6-check list)

#### Adding YAML Tests for a Tenant
1. Create `apps/{EXACT_SHEET_NAME}.yaml` (case-sensitive)
2. Define `tests:` array with test objects
3. Each test: name, start_url (optional), steps array
4. Use supported step actions (click, fill, expect_visible, expect_url, expect_text, expect_not_text, expect_count, select, navigate, wait, press, screenshot, scroll, set_input_files)
5. Failures auto-captured as bugs

#### Extending Health Checks
1. Modify `check_page_health(self, page, label)` method
2. Add new detection logic (e.g., regex pattern, locator count, content scan)
3. Call `capture_bug()` if condition matches
4. Ensure exception handling (try/except)

#### Adding Bad Content Patterns
1. Append to `BAD_TEXT_PATTERNS` list:
   ```python
   ("literal_string_to_detect", "human description", "P1")  # or P2/P3
   ```
2. Scanned by `_scan_bad_content()` on every page
3. Deduplication via Jaccard similarity prevents false positive spam
