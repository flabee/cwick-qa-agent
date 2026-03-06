# Stack

## Languages & Runtime
- **Language:** Python 3.x
- **Runtime:** CPython (native executable via `python3`)
- **Module System:** Standard library + pip packages
- **Execution:** Deterministic CLI scripts (no AI/LLM runtime)

## Frameworks & Libraries

### Browser Automation
- **Playwright** (sync_api) — Chromium-based automation for UI testing
  - Used for: login flows, button discovery, modal handling, form filling, screenshots
  - Headless mode for unattended execution
  - Locator API for element selection (CSS selectors, role selectors, text matching)

### Google Cloud Integration
- **google-api-python-client** — Sheets API v4 + Drive API v3
  - Sheets: read/write bug reports, spreadsheet metadata
  - Drive: file upload/download, folder operations, permissions management
  - Requires OAuth2 credentials (stored in `~/cwick-qa-agent/token.pickle`)

- **google-auth** — OAuth2 token refresh and credential management
  - Handles token expiration and automatic refresh
  - Supports persistent credentials via pickle serialization

### Utilities
- **openpyxl** — Excel file parsing (legacy scripts only; modern script uses Sheets API)
- **PyYAML** — Parse tenant-specific test case definitions (apps/*.yaml)

## Dependencies

### Installation
Install all required packages with:
```bash
pip install playwright openpyxl google-api-python-client google-auth
playwright install chromium
```

### Core Dependencies (from SETUP.md)
| Package | Purpose | API Level |
|---------|---------|-----------|
| `playwright` | Browser automation, screenshot capture | Sync playwright.chromium |
| `google-api-python-client` | Google Sheets + Drive API client | REST API via `build()` |
| `google-auth` | OAuth2 credential management, token refresh | `Request`, `Credentials` |
| `openpyxl` | Excel workbook parsing (legacy) | `load_workbook`, `Worksheet` |
| `pyyaml` | YAML test case parsing | `yaml.safe_load()` |

### Python Standard Library Used
- `collections` — deque (BFS queue for state exploration)
- `datetime` — timestamp generation for logs/screenshots
- `hashlib` — MD5 fingerprints for state deduplication
- `json` — coverage report serialization
- `os`, `pickle` — environment vars, OAuth token persistence
- `re` — pattern matching (i18n keys, bad text patterns, text normalization)
- `time` — sleep, timeout control
- `pathlib` — file path handling
- `urllib.parse` — URL normalization

## Configuration

### Environment Variables (Required at Runtime)
```bash
TENANT_URL            # Login page URL (e.g., https://knowledgebase-frontend-p55f.onrender.com/docupilot/login)
TENANT_USERNAME       # Demo user email (e.g., demo1@test.it)
TENANT_PASSWORD       # Demo user password
TENANT_NAME           # Must match Excel sheet name exactly (e.g., "Docupilot", "MaiHUB", "CFO AI")
DRIVE_FOLDER_ID       # (Optional) Google Drive folder ID for screenshot uploads
EXCEL_FILE_ID         # (Optional) Google Sheets file ID (Cwick_Demo_Test.xlsx)
```

### OAuth Credentials
- **Token File:** `~/cwick-qa-agent/token.pickle` (pickled OAuth2 credentials)
- **OAuth Config:** `google_credentials.json` (OAuth2 client config from Google Cloud Console)
- **Project ID:** `cwick-qa-agent` (Google Cloud project)
- **Scopes:** Drive v3 (files.create, files.get), Sheets v4 (spreadsheets.values.*, spreadsheets.batchUpdate)

### Runtime Configuration
- **Session Directory:** `~/cwick-qa-agent/session_output/` (screenshots, logs, coverage JSON)
- **Apps Directory:** `./apps/` (YAML test cases per tenant)
- **Sheet Mapping:** TENANT_NAME → Excel sheet name (6 tenants mapped in SHEET_MAP)

## Build & Deploy

### Execution Model
- **Single-threaded:** Each QA agent run is a monolithic Python process
- **Invocation:** `python3 qa_agent.py` (env vars set beforehand)
- **Helper Script:** `./run.sh [test1|test2|test3|test4|test5|test6]` routes env vars and executes the main script

### Deployment Context
- **Host:** macOS (darwin 25.3.0) / Linux compatible
- **Render.com Compatibility:** Tests a SPA on Render.com free tier (knowledgebase-frontend-p55f.onrender.com)
- **Output Artifact:** Updated Google Sheets + Drive folder with screenshots + session log
- **No CI/CD:** Runs on-demand by user via Claude Code CLI

### Script Entry Points
- **Primary:** `/Users/fabiopia/cwick-qa-agent/qa_agent.py` (universal QA agent, canonical version)
- **Runner:** `/Users/fabiopia/cwick-qa-agent/run.sh` (tenant routing + env setup)
- **Legacy:** `run_standard_qa.py`, `run_smart_qa.py` (kept for reference, not used)

### Architecture Summary
```
qa_agent.py
├── QAAgent (main orchestrator)
│   ├── StateGraph (BFS state exploration, hash-based dedup)
│   ├── CoverageTracker (metrics: pages, buttons, flows, bugs)
│   ├── ModalHandler (modal detection + screenshot)
│   ├── YAMLRunner (executes apps/{tenant}.yaml test steps)
│   └── Reporter (writes to Google Sheets + Drive)
├── Playwright sync_playwright context
├── Google Drive + Sheets service clients
└── Session logging + coverage JSON output
```

### Key Parameters
- **BFS Limits:** MAX_BFS_STATES=60, MAX_NAV_ITEMS=16, MAX_BTN_PER_PAGE=15 (prevent runaway exploration)
- **Button Priority:** Keywords like "create", "generate", "export" explored first
- **Skip Keywords:** "logout", "delete account" skipped (would destroy session)
- **Bad Text Patterns:** Invalid Date, NaN, undefined, TypeError, 404/500 errors detected automatically
