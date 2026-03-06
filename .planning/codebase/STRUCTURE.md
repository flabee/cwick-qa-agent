# Structure

## Directory Layout

```
/Users/fabiopia/cwick-qa-agent/
├── qa_agent.py                          # Main executable (2,151 lines) — THE ONLY SCRIPT
├── run.sh                               # Tenant routing wrapper (54 lines)
├── run_standard_qa.py                   # Legacy script (kept for reference, NOT used)
├── run_smart_qa.py                      # Legacy script (kept for reference, NOT used)
│
├── .env                                 # Secrets: TENANT_PASSWORD, EXCEL_FILE_ID (git-ignored)
├── .gitignore                           # Exclude: .env, __pycache__, session_output, token.pickle
│
├── CLAUDE.md                            # Project constraints & instructions
├── SETUP.md                             # Initial setup guide
├── QA_SKILL.md                          # Claude Code skill documentation
│
├── google_credentials.json              # OAuth app credentials (read-only, public)
├── token.pickle                         # Persisted OAuth token (git-ignored, refreshes auto)
│
├── apps/                                # Per-tenant YAML test cases
│   ├── Docupilot.yaml                  # Test cases for Docupilot tenant (demo1@test.it)
│   ├── MaiHUB.yaml                     # Test cases for MaiHUB tenant (demo3@test.it)
│   ├── CFO AI.yaml                     # Test cases for CFO AI tenant (demo2@test.it)
│   ├── Rooms.yaml                      # Test cases for Rooms tenant (demo4@test.it)
│   ├── A33.yaml                        # Test cases for A33 tenant (demo5@test.it)
│   └── Tenant Base (Cwick Core).yaml   # Test cases for base Cwick Core (demo6@test.it)
│
├── session_output/                      # QA session artifacts (generated at runtime)
│   ├── [timestamp]_*.png                # Timestamped screenshots
│   ├── coverage_summary.json            # JSON metrics from session
│   ├── session_log.md                   # Markdown log of entire session (appended per run)
│   └── ...                              # ~109 files, ~28 MB (screenshots accumulate)
│
├── .planning/                           # Planning & documentation (Claude internal)
│   ├── codebase/
│   │   ├── ARCHITECTURE.md              # This file — system design, patterns, layers
│   │   └── STRUCTURE.md                 # Directory layout, naming conventions
│   └── ...
│
├── .claude/                             # Claude Code metadata
│   └── skills/
│       └── ...
│
├── .agents/                             # Agent metadata
│   └── skills/
│       └── ...
│
├── .git/                                # Version control
├── __pycache__/                         # Python bytecode (git-ignored)
└── skills-lock.json                     # Claude Code lock file
```

---

## Key Locations

| Component | Path | Purpose |
|-----------|------|---------|
| **Main Script** | `/Users/fabiopia/cwick-qa-agent/qa_agent.py` | Entry point, all QA logic |
| **Tenant Router** | `/Users/fabiopia/cwick-qa-agent/run.sh` | Maps test1-6 to env vars + calls qa_agent.py |
| **YAML Tests** | `/Users/fabiopia/cwick-qa-agent/apps/{TENANT}.yaml` | Per-tenant test cases (optional) |
| **Secrets** | `/Users/fabiopia/cwick-qa-agent/.env` | TENANT_PASSWORD, EXCEL_FILE_ID (git-ignored) |
| **OAuth Token** | `/Users/fabiopia/cwick-qa-agent/token.pickle` | Persisted Google API credentials (git-ignored) |
| **Credentials** | `/Users/fabiopia/cwick-qa-agent/google_credentials.json` | OAuth app public config (safe to commit) |
| **Session Output** | `/Users/fabiopia/cwick-qa-agent/session_output/` | Screenshots, logs, coverage metrics |
| **Session Log** | `~/cwick-qa-agent/session_output/session_log.md` | Appended markdown log per run |

---

## Naming Conventions

### Files
- **Python scripts:** `qa_agent.py` (main), `run_standard_qa.py`, `run_smart_qa.py` (legacy)
- **Shell scripts:** `run.sh` (wrapper)
- **YAML test files:** `{TENANT_NAME}.yaml` (exact match of sheet name, e.g., "Docupilot.yaml")
- **Screenshots:** `YYYY-MM-DD_HHMMSS_{context}_{slug}.png`
  - Examples: `2026-03-05_163607_bug_P0_wrong_credentials.png`, `2026-03-05_163607_modal_kb_view.png`

### Classes
- **PascalCase:** `QAAgent`, `StateGraph`, `CoverageTracker`, `ModalHandler`, `FormHandler`

### Methods
- **snake_case:** `capture_bug()`, `bfs_explore()`, `run_targeted_checks()`, `check_page_health()`
- **Private prefix:** `_dom_snippet()`, `_goto()`, `_scan_bad_content()`, `_explore_section()`
- **Helpers in methods:** `_on_console()` (nested function), `_btn_score()` (local function in BFS)

### Constants
- **UPPER_SNAKE_CASE:** `TENANT_URL`, `USERNAME`, `PASSWORD`, `TENANT_NAME`, `SESSION_DIR`, `MAX_BFS_STATES`, `MAX_NAV_ITEMS`, `MAX_BTN_PER_PAGE`
- **Keyword sets:** `_BTN_HIGH_KW`, `_BTN_MED_KW`, `_BTN_LOW_KW`, `PRIORITY_KW`, `SKIP_KW`
- **Pattern lists:** `BAD_TEXT_PATTERNS`, `_EMPTY_STATE_RE`, `_I18N_RE`

### Environment Variables
- **Input:** `TENANT_URL`, `TENANT_USERNAME`, `TENANT_PASSWORD`, `TENANT_NAME`, `DRIVE_FOLDER_ID`, `EXCEL_FILE_ID`
- **Set by run.sh:** Tenant aliases (test1, test2, test3, test4, test5, test6)

### Data Structures
- **Bug dict:** `{"id": int, "issue": str, "reproduce": str, "prio": str, "note": str, "screenshot": str, "link": str}`
- **YAML test dict:** `{"name": str, "start_url": str, "steps": list[dict]}`
- **YAML step dict:** `{"wait": int}`, `{"click": str}`, `{"fill": [str, str]}`, `{"expect_visible": str}`, `{"expect_not_text": str}`, `{"expect_count": [str, int]}`, `{"screenshot": str}`
- **Coverage metrics:** 9 counters (pages_discovered, pages_tested, nav_links_discovered, buttons_discovered, buttons_clicked, modals_opened, forms_filled, flows_explored, states_visited)

### Google Sheets Columns (per tenant sheet)
```
A: Issue Reported       (bug issue)
B: How to reproduce     (steps to repro)
C: Tester              (always "QA Agent")
D: Prio                (P0, P1, P2, P3)
E: Dev Status          (empty at write time)
F: Solved Prod         (empty at write time)
G: Note                (additional context)
H: Screenshot          (filename or hyperlink)

Special: Rooms sheet has col A = "Reported" (extra), shifts cols +1
```

### Sheet Names (SHEET_MAP)
| Tenant Name | Sheet Name |
|---|---|
| Docupilot | Docupilot |
| MaiHUB | MaiHUB |
| CFO AI | CFO AI |
| Rooms | Rooms |
| A33 | A33 |
| Tenant Base (Cwick Core) | Tenant Base (Cwick Core) |

### URL Patterns (known routes)
- **Docupilot:** `/docupilot/login`, `/docupilot/dashboard`, `/docupilot/documents`, `/docupilot/kb`, `/docupilot/new`, `/docupilot/editor/{id}`
- **CFO AI:** `/cfo/login`, `/cfo/dashboard`, `/cfo/documents`, `/cfo/strategic-analysis`, `/cfo/news`, `/cfo/admin/*`
- **MaiHUB:** `/maihub/login`, `/maihub/courses`, `/maihub/profile`, `/maihub/leaderboard`, `/maihub/news`, `/maihub/admin/*`
- **Rooms:** `/rooms/login`, `/rooms/home`, `/rooms/chat`, `/rooms/library`, `/rooms/projects`
- **A33:** Base Cwick Core variant
- **Tenant Base (Cwick Core):** Root `/login`, `/dashboard`, etc.

### Selector Naming Patterns
- **Navigation:** `nav :is(button,a):has-text('{keyword}')`, `aside :is(button,a):has-text()`, `[role='navigation']`, `[class*='sidebar']`
- **Modal:** `[role='dialog']`, `[aria-modal='true']`, `[class*='modal']:visible`, `[data-modal]`
- **Buttons:** `button:has-text()`, `:is(button,[role='button']):has-text()`, `[type='submit']`
- **Forms:** `form`, `input[type='text']`, `input[type='email']`, `textarea`, `select`
- **Bad content:** Regex patterns in _I18N_RE, _EMPTY_STATE_RE, BAD_TEXT_PATTERNS

---

## How to Extend / Modify

### Add a New Bug Check
1. Open `/Users/fabiopia/cwick-qa-agent/qa_agent.py`
2. Find `run_targeted_checks()` method (line ~1,118)
3. Add a new check block within `if self.nav_to(page, ["..."]):` or `if self._click_nav(page, "..."):`
4. Call `self.capture_bug(page, issue, reproduce, prio, note)` when bug found
5. Re-run: `./run.sh test1` (or appropriate tenant)

### Add a New Bad Content Pattern
1. Edit `BAD_TEXT_PATTERNS` list (line ~88)
2. Add tuple: `("literal_string", "human description", "P0|P1|P2|P3")`
3. Pattern is automatically scanned in `_scan_bad_content()` after every page/click

### Add YAML Test Cases
1. Create or edit `/Users/fabiopia/cwick-qa-agent/apps/{TENANT_NAME}.yaml`
2. Format: YAML list of test objects (name, start_url, steps array)
3. Step types: wait, click, fill, press, expect_visible, expect_not_text, expect_count, screenshot
4. Run: `./run.sh test1` → executes YAML after targeted checks

### Update Modal/Form Detection
1. Edit `ModalHandler._DETECT_SELS` (line ~248) to add/change modal detection selectors
2. Edit `ModalHandler._CLOSE_SELS` (line ~255) to add/change close button selectors
3. Edit `FormHandler._DEFAULTS` (line ~365) for form field defaults
4. Edit `FormHandler._SKIP_KW` (line ~367) to skip additional field types

### Change Navigation Selectors
1. Edit `_discover_nav_items()` (line ~606) to add/change nav container selectors
2. Edit `nav_to()` (line ~563) and `_click_nav()` (line ~585) for navigation logic

### Customize Per-Tenant Logic
1. In `run_targeted_checks()`, add tenant-specific checks:
   ```python
   if TENANT_NAME == "Docupilot":
       # Docupilot-specific checks
   elif TENANT_NAME == "MaiHUB":
       # MaiHUB-specific checks
   ```
2. Or define tenant-specific YAML in `apps/{TENANT_NAME}.yaml`

### Debug State Graph Issues
1. Modify `StateGraph.fingerprint()` (line ~142) to include/exclude DOM elements
2. Add logging to `bfs_explore()` to see state transitions
3. Check `state_graph.edges` after run for graph visualization

---

## Constants & Configuration

### Playwright Limits
```python
MAX_BFS_STATES   = 60       # Max states explored before stopping
MAX_NAV_ITEMS    = 16       # Cap nav discovery
MAX_BTN_PER_PAGE = 15       # Cap button clicks per page
```

### Timeouts (milliseconds)
- Page navigation: `10000` ms (10 sec)
- Wait for load state: `15000` ms (15 sec for login, 10 sec for nav)
- Selector visibility: `400–1000` ms (depending on context)
- Sleep after action: `0.8–1.5` sec (stabilize DOM)

### Text Patterns
- **Bad text:** Invalid Date, [object Object], NaN, undefined, TypeError, ReferenceError, etc.
- **i18n regex:** `\b([a-z]{3,})\.([a-z]+(?:_[a-z]+)+)\b` (matches "key.word_word" but not decimals)
- **Empty state regex:** `\b(no data available|no results found|nothing here|nessun dato|nessun risultato)\b`

### Button Priority Keywords
```python
HIGH: create, generate, export, upload, submit, save, add, new, invite, download
MED:  edit, view, details, open, start
LOW:  cancel, close, back, help, info
SKIP: logout, sign out, log out, signout, exit, delete account, esci
```

### Bug Severity Levels
| Level | Meaning | Example |
|---|---|---|
| **P0** | Blocks core functionality or security issue | Login fails, auth bypass, 500 error |
| **P1** | Major issue, workaround possible | PDF export slow, missing back button |
| **P2** | Medium issue, no workaround needed | Wrong credentials no error, search empty state, untranslated i18n |
| **P3** | UI/UX / visual / cosmetic | Button color, font size, spacing |

---

## Key File Sizes

| File | Lines | Size | Purpose |
|---|---|---|---|
| qa_agent.py | 2,151 | ~98 KB | Main executable |
| run_standard_qa.py | 824 | ~24 KB | Legacy (reference only) |
| run_smart_qa.py | 1,020 | ~33 KB | Legacy (reference only) |
| run.sh | 54 | ~2 KB | Tenant router |
| Docupilot.yaml | 80 | ~3 KB | YAML tests |
| MaiHUB.yaml | 60+ | ~2 KB | YAML tests |
| CFO AI.yaml | 35+ | ~1 KB | YAML tests |
| Rooms.yaml | 100+ | ~4 KB | YAML tests |
| session_output/ | ~109 files | ~28 MB | Screenshots + logs (accumulate) |

---

## Dependencies & Imports

**qa_agent.py imports:**
```python
import collections, datetime, hashlib, json, os, pickle, re, time
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
import yaml (optional, graceful fallback if missing)
from googleapiclient.discovery import build (optional, Google Sheets/Drive API)
```

**No external ML/AI APIs.** Deterministic logic only.

---

## Critical Constraints (from CLAUDE.md)

1. **Never write a new Python script.** Edit `qa_agent.py` in place.
2. **Single entry point:** `qa_agent.py` — all QA logic lives here.
3. **Environment variable driven:** TENANT_URL, USERNAME, PASSWORD, TENANT_NAME required.
4. **Deterministic, reproducible:** Same inputs → same outputs, no randomness or AI.
5. **Google Sheets only for reporting:** Drive uploads are optional; Sheets API required for bugs.
6. **Session output always to ~/cwick-qa-agent/session_output/:** Never hardcoded elsewhere.
7. **YAML tests optional:** If apps/{TENANT_NAME}.yaml missing, skip YAML phase.
8. **No localhost testing:** Only runs against deployed tenants (Render.com free tier).
