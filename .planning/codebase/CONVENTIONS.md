# Conventions

## Code Style

### Formatting
- **Python version**: Python 3 (uses modern syntax: f-strings, pathlib)
- **Line length**: Generally under 100 characters
- **Indentation**: 4 spaces
- **Imports**: Organized at module level, optional dependencies guarded with try/except
  - Core: `os`, `time`, `pickle`, `json`, `re`, `pathlib`, `urllib.parse`
  - Main external: `playwright.sync_api` (browser automation)
  - Optional: `googleapiclient` (Google Drive/Sheets), `yaml` (test config)
- **Comments and docstrings**:
  - Module and class docstrings use triple-quoted strings with detailed architecture notes
  - Inline comments use `# ──` separator lines for visual section breaks
  - Multi-phase processes documented in docstring (e.g., "Pipeline: Login → BFS → Health Checks → Targeted → YAML → Report")

### Naming Conventions

#### Variables
- **Snake case** for all variables and functions: `capture_bug()`, `page_health`, `modal_handler`
- **Constants** in UPPERCASE (environment vars, limits, config): `MAX_BFS_STATES`, `TENANT_URL`, `SKIP_KW`
- **Abbreviations** in lowercase with underscores: `fp` (fingerprint), `btn` (button), `sel` (selector)
- **Configuration dictionaries** as lowercase plurals: `SHEET_MAP`, `BAD_TEXT_PATTERNS`
- **Private methods** use leading underscore: `_dom_snippet()`, `_explore_section()`, `_scan_bad_content()`

#### Classes
- **PascalCase** for all class names: `StateGraph`, `CoverageTracker`, `ModalHandler`, `FormHandler`, `QAAgent`
- Each class has a single responsibility (state tracking, coverage metrics, modal handling, etc.)

#### Functions and Methods
- **Snake case**: `run()`, `capture_bug()`, `check_page_health()`
- **Method naming**:
  - `run_*` for main execution phases: `run_targeted_checks()`, `run_yaml_tests()`
  - `check_*` for validation/inspection: `check_page_health()`, `check_logout_auth_guard()`
  - `_click_nav()`, `_discover_nav_items()` — private navigation helpers
  - `write_report()` — data export
  - `init_google()` — initialization
  - `capture_bug()` — core bug tracking
  - `handle()` — modal/form handling

#### Boolean Variables
- Use positive naming: `found_new`, `still_on_login`, `error_visible`, `in_nav`
- Avoid negation in variable names — use `is_visited()` not `not_visited()`

#### File Naming
- **Scripts**: `qa_agent.py` (canonical), `run.sh` (launcher)
- **Legacy scripts**: `run_standard_qa.py`, `run_smart_qa.py` (kept for reference, not maintained)
- **YAML configs**: `apps/{TENANT_NAME}.yaml` (exact sheet name mapping required)
- **Output**: `session_output/{timestamp}_*.png`, `session_log.md`, `coverage_summary.json`

## Patterns

### Architecture Patterns

#### State Graph (BFS Exploration)
- **Pattern**: Hash-based visited set + deque queue
- **Fingerprinting**: `md5(normalized_url + partial_dom_snippet)[:12]`
  - Distinguishes different semantic states at the same URL
  - Used to prevent infinite loops during exploration
- **Edge tracking**: `(from_fp, action_label, to_fp)` recorded for coverage analysis
- **Key methods**: `mark_visited()`, `is_visited()`, `enqueue()`, `dequeue()`, `fingerprint()`

#### Coverage Metrics (Instrumentation)
- Accumulates statistics during a session: pages, buttons, modals, forms, flows, states
- Two phases:
  - **Discovery**: observed elements (nav_links_discovered, buttons_discovered)
  - **Tested**: interacted elements (buttons_clicked, flows_explored)
- **Report formats**:
  - Console pretty-print: `print_report()`
  - JSON export: `save_json()` (structured for dashboard aggregation)
  - Markdown log: session-level narrative with screenshots

#### Handler Classes (Composable Utilities)
- **ModalHandler**: Detects dialogs, takes screenshots, safely fills fields, closes via selectors or Escape key
- **FormHandler**: Fills test data (text→"QA Test Input", email→"demo@test.com", etc.), skips destructive fields
- Both return `bool` for success; exception handling is internal (log failures, don't throw)

#### Selector Strategy (Locator Robustness)
- **Multi-selector fallback** for nav clicks:
  ```
  nav :is(button,a):has-text('X')  →
  aside :is(button,a):has-text('X')  →
  [role='navigation'] :is(button,a):has-text('X')  →
  [class*='sidebar'] :is(button,a):has-text('X')
  ```
- **Keyword-based filtering**:
  - HIGH priority: `create`, `generate`, `export`, `upload`, `submit`
  - MED priority: `edit`, `view`, `details`, `open`, `start`
  - LOW priority: `cancel`, `close`, `back`, `help`
  - SKIP (destructive): `logout`, `sign out`, `delete account`

#### Content Scanning (Bug Detection)
- **Literal patterns** (BAD_TEXT_PATTERNS list):
  - JS leaks: `Invalid Date`, `[object Object]`, `NaN`, `undefined`
  - JS errors: `TypeError:`, `ReferenceError:`, `Unhandled Promise`
  - HTTP errors: `404 Not Found`, `500 Internal Server`, `502 Bad Gateway`, `503 Service Unavailable`
- **Regex patterns**:
  - i18n key leaks: `\b([a-z]{3,})\.([a-z]+(?:_[a-z]+)+)\b` (e.g., `pagination.next_page`)
  - Empty state without explanation: `no data available|no results found|nessun dato|nessun risultato`
- **Deduplication**: Bug capture uses Jaccard similarity on word sets (threshold 0.50) to avoid duplicates

#### YAML Test Format (Declarative)
- **Structure**:
  ```yaml
  tests:
    - name: "human description"
      start_url: "https://..."  (optional; defaults to home_url)
      steps:
        - click: "selector"
        - fill: ["selector", "text"]
        - expect_visible: "selector"
        - expect_url: "substring"
        - expect_text: "substring"
        - expect_not_text: "substring"
        - expect_count: ["selector", min_count]
        - screenshot: "label"
        - wait: seconds
        - navigate: "url"
        - press: "key" or ["selector", "key"]
        - select: {"selector": "option_label"}
        - scroll: pixels (positive=down)
        - set_input_files: ["selector", "path"]
  ```
- **Execution**: Step-by-step with Playwright, captures failures as bugs

### Playwright Usage

#### Page Navigation
- `page.goto(url)` with domain safety check: origin must match tenant_domain
- `page.wait_for_load_state("networkidle", timeout=10000)` before assertions
- `time.sleep(1.5-3)` after navigation/click for dynamic UI settle

#### Locators
- `.locator(selector).first` for single element
- `.locator(selector).count() > 0` for existence check
- `.is_visible(timeout=X)` for visibility assertion
- `.inner_text()`, `.inner_html()`, `.get_attribute()` for content inspection
- Exception handling around all locator operations (selectors may not exist)

#### Modal and Form Handling
- **Modal detection** tries multiple selectors: `[role='dialog']`, `[aria-modal='true']`, `[class*='modal']`
- **Modal closing** priority: Close button → Cancel button → aria-label close → Escape key
- **Form filling** type-based: `input[type='email']` → `demo@test.com`, `textarea` → `Automated QA input`
- Both use container scoping to avoid filling unrelated form fragments

### Google Sheets Integration

#### Authentication
- OAuth token stored at `~/cwick-qa-agent/token.pickle` (created by separate auth script)
- `googleapiclient.discovery.build("sheets", "v4", credentials=creds)` for API client
- Non-blocking failure: if token missing/invalid, skip Sheets write (log local markdown instead)

#### Bug Writing
- Append-style write: `append()` method with `insertDataOption="INSERT_ROWS"`
- **Rooms sheet special case**: Extra "Reported" column at A; all data shifts +1 column
- **Deduplication**: Fetch existing issue titles from sheet (case-insensitive), skip already-reported bugs
- **Screenshot linking**:
  - Never use `=HYPERLINK()` formula (breaks on non-English locale with `;` separator)
  - Use `batchUpdate` with `textFormat.link` (locale-safe, direct cell hyperlinks)
  - Hyperlink applied to screenshot cell separately via `_set_hyperlinks()`

#### Formatting
- Column widths: Applied after write via `batchUpdate`
- Text wrap: `wrapStrategy: "WRAP"` for all bug rows
- Cell background: White; text color: Black (reset before hyperlink overlay)

### Error Handling

#### Philosophy
- **Fail open**: Errors are caught, logged, and execution continues
- **No exceptions thrown** from public methods; problems logged and skipped
- **Best-effort approach**: If a selector doesn't exist or times out, move to next action

#### Patterns Used
- **Try/except around locators**:
  ```python
  try:
      el = page.locator(sel).first
      if el.is_visible(timeout=1000):
          el.click()
  except Exception:
      pass  # Selector doesn't exist or timed out
  ```
- **Guard clauses** for optional features:
  ```python
  if not _YAML_OK:
      self.log("PyYAML not installed — skipping YAML tests")
      return
  ```
- **Fallback selectors** for multi-language support:
  - Login buttons: English (`Sign in`, `Login`) + Italian (`Accedi`, `Entra`, `Inizia`)
  - Close buttons: English (`Close`, `Cancel`) + Italian (`Chiudi`, `Annulla`)
  - Modal triggers: Multiple classes + role attributes

#### Logging
- **Timestamped console output**: `[HH:MM:SS] message`
- **Flush to stdout**: All `print()` calls use `flush=True` for real-time output in headless/remote environments
- **Log levels** (implicit):
  - `self.log("...")` — informational (phases, navigation, discovery counts)
  - `self.log(f"  [BUG {prio}] ...")` — bug detection (indented for visual hierarchy)
  - `self.log(f"  Error message")` — error details (indented)

### Performance Considerations

#### Limits (Constants)
- `MAX_BFS_STATES = 60` — stop exploration after visiting 60 unique UI states
- `MAX_NAV_ITEMS = 16` — limit nav items discovered per page (top 16 only)
- `MAX_BTN_PER_PAGE = 15` — click max 15 buttons per section (priority-sorted)

#### Timeouts
- Network: `wait_for_load_state("networkidle", timeout=10000)` — 10 seconds for page settle
- Locator: `.is_visible(timeout=1000)` to `.is_visible(timeout=5000)` — varies by context
- Generation: `wait_for_url(..., timeout=30000)` — 30s max for AI doc generation

#### Optimization
- **Deduplication on fingerprint**: Don't revisit identical state (URL + DOM)
- **Priority sorting**: Click high-value buttons first (`create`, `generate`) to find flows faster
- **Keyword filtering**: Skip nav items containing destructive keywords (`logout`, `delete`)

## Security Considerations

### Session Management
- **Protected URL tracking**: `self.protected_url` set after login, used to verify auth guard
- **Domain restriction**: Navigation only allowed within `self.tenant_domain` (prevents cross-site nav)
- **Session boundary**: Logout tested at end of session; browser closed immediately after

### Input Validation
- **Test data**: Hard-coded safe values (`QA Test Input`, `demo@test.com`)
- **No user input**: Script is deterministic; no stdin/args that could inject selectors or commands
- **Selector escaping**: Playwright's `.locator()` method uses CSS/XPath validation (prevents injection)

### Credential Handling
- **Env var sourcing**: Credentials read from environment, never logged
- **No hardcoding**: All secrets in `.env` or CI/CD environment
- **Token caching**: Google OAuth token stored locally (user must set up auth script separately)
