# Integrations

## External APIs

### Google Drive API v3
- **Purpose:** Screenshot upload and file management
- **Auth Method:** OAuth2 (stored in `~/cwick-qa-agent/token.pickle`)
- **Operations:**
  - `files().create()` — upload PNG screenshots with metadata
  - `files().get()` — retrieve file info, check permissions
  - `permissions().create()` — make uploaded files shareable (type='anyone', role='reader')
- **Endpoints:**
  - Base: `https://www.googleapis.com/drive/v3`
  - Supported folders: 6 tenant-specific folder IDs (stored in env var `DRIVE_FOLDER_ID`)
- **Data Flow:** Screenshot bytes (PNG) → MediaFileUpload → Drive file → shareable link

### Google Sheets API v4
- **Purpose:** Read/write bug reports to Excel-compatible spreadsheet
- **Auth Method:** OAuth2 (same token as Drive)
- **Operations:**
  - `spreadsheets().values().get()` — read existing bugs from sheet (deduplication check)
  - `spreadsheets().values().update()` — append new bug rows (A:H columns)
  - `spreadsheets().values().append()` — write bug data
  - `spreadsheets().batchUpdate()` — formatting (wrap text, column widths, hyperlinks)
  - `spreadsheets().get()` — list all sheets in spreadsheet
- **Endpoints:**
  - Base: `https://sheets.googleapis.com/v4`
  - Spreadsheet ID: set via `EXCEL_FILE_ID` env var (see `.env.example`)
  - Sheets: 6 named sheets (Docupilot, MaiHUB, CFO AI, Rooms, A33, Tenant Base (Cwick Core))
- **Data Flow:** Bug metadata (issue title, repro steps, priority, screenshot link) → range update → Sheet cells A7:H

### Google OAuth2 Token Endpoint
- **Purpose:** Refresh expired OAuth2 credentials
- **URL:** `https://oauth2.googleapis.com/token`
- **Auth Method:** Refresh token + client secret
- **Invocation:** Automatic via `google.auth.transport.requests.Request().refresh()` when token expires
- **Credentials Config File:** `google_credentials.json` (OAuth2 client application config)

## Databases / Storage

### Google Sheets (Quasi-Database)
- **Type:** Cloud-based spreadsheet (acts as relational table for bugs)
- **Schema:**
  - Row 1-4: Legend/headers
  - Row 5: Blank
  - Row 6: Column headers [Issue Reported | How to reproduce | Tester | Prio | Dev Status | Solved Prod | Note | Screenshot]
  - Row 7+: Bug entries (8 columns A-H)
  - Rooms sheet: 9 columns A-I (extra "Reported" column at index C)
- **Access:** Sheets API v4 (read/write via HTTP)
- **Encoding:** UTF-8 (supports Italian locale characters)
- **Durability:** Google Cloud managed, automatic backups

### Google Drive (File Storage)
- **Type:** Cloud file storage
- **Purpose:** Store bug screenshots (PNG) and session logs (Markdown)
- **Folder Structure:** One folder per tenant (6 separate folder IDs in environment)
- **File Types:** image/png (bug screenshots), text/markdown (session_log.md)
- **Access Control:** Public read access via shareable link (set by qa_agent.py)
- **Retention:** No automated cleanup (manual organization expected)

### Local Session Output Directory
- **Path:** `~/cwick-qa-agent/session_output/`
- **Purpose:** Fallback storage if Google APIs unavailable
- **Files Generated:**
  - `BUG_NNN_*.png` — timestamped bug screenshots
  - `session_log.md` — detailed QA session log (markdown format)
  - `coverage_summary.json` — metrics JSON (pages, buttons, flows, bugs)
- **Cleanup:** Not automated (user must manage)

## Auth Providers

### Google OAuth2
- **Provider:** Google Cloud Console (oauth.google.com)
- **Flow:** Installed/Desktop OAuth (Redirect URI: http://localhost)
- **Credentials:**
  - Client ID: stored in `google_credentials.json` (not committed)
  - Client Secret: stored in `google_credentials.json` (not committed)
  - Project: `cwick-qa-agent`
- **Scopes Requested:**
  - `https://www.googleapis.com/auth/drive` — full Drive access
  - `https://www.googleapis.com/auth/spreadsheets` — full Sheets access
- **Token Storage:** Pickled Credentials object at `~/cwick-qa-agent/token.pickle`
- **Token Refresh:** Automatic when expired (handled by qa_agent.py.init_google())
- **User Interaction:** Minimal; credentials already obtained and stored (non-interactive)

### Demo Tenant Auth (Application Layer)
- **Type:** Web form-based login (not an API integration; tested UI behavior)
- **Test Accounts:** Set via `TENANT_USERNAME` / `TENANT_PASSWORD` env vars (see `.env.example`)
  - Tenant routing handled by `run.sh` which sources credentials from `.env`
- **Auth Endpoint:** Varies per tenant (e.g., /docupilot/login, /cfo/login, /maihub/login)
- **Testing Coverage:** Wrong credentials (P0 bug), session persistence, logout guard

## Other Services

### Render.com Hosting
- **Type:** Serverless app platform
- **Application:** knowledgebase-frontend-p55f.onrender.com (multi-tenant SPA)
- **Technologies:** React SPA with multiple tenant routes (/docupilot/*, /cfo/*, /maihub/*, /rooms/*, /a33/*)
- **Characteristics:** Free tier with cold-start delays (5-15s on first load)
- **Network Behavior:** Tests handle slow initial loads, dynamic port assignments

### YAML Test Case Files
- **Type:** Local test definition format (not an external service)
- **Location:** `./apps/{TENANT_NAME}.yaml` (6 files, one per tenant)
- **Format:** YAML describing browser automation steps (click, fill, wait, screenshot, assertions)
- **Purpose:** Deterministic, reproducible test flows for each tenant's app
- **Not an external API:** Parsed locally via PyYAML, no network calls

### Browser Runtime (Chromium via Playwright)
- **Type:** Browser process managed by Playwright
- **Distribution:** Installed via `playwright install chromium` (bundled binary)
- **Network:** Communicates with Render.com-hosted SPA over HTTPS
- **User Agent:** Chromium user agent (not spoofed by qa_agent.py)
- **Cookies/Storage:** Handled by browser context (session isolation per run)
- **Headless Mode:** Enabled for unattended execution

## Integration Points Summary

| System | Protocol | Auth | Data Type | Direction |
|--------|----------|------|-----------|-----------|
| Google Sheets API | REST (HTTPS) | OAuth2 | JSON (bugs) | Bidirectional |
| Google Drive API | REST (HTTPS) | OAuth2 | Binary (PNG) + Text (MD) | Write-only |
| OAuth2 Token Endpoint | HTTPS | Refresh token | OAuth token | Token refresh |
| Render.com SPA | HTTPS + WebSocket (optional) | Form login | HTML/JS/CSS | Read + Click/Fill |
| Demo Tenant Auth | HTTPS Form POST | Username/Password | Session cookie | Write (login) |
| Chromium Browser | IPC (local) | None | Browser state | Control |
| YAML Files | Local FS | None | YAML | Read-only |
| Local FS | POSIX | OS permissions | PNG + Markdown + JSON | Read/Write |

## API Rate Limits & Quotas
- **Sheets API:** Default quota 300 requests/minute per user
- **Drive API:** Default quota 1,000 requests/minute per user
- **QA Agent Usage:** ~10-20 API calls per session (well below limits)

## Error Handling & Fallback
- **Google APIs Unavailable:** Logs written locally to `session_output/` only
- **Drive Upload Failure:** Bug report still written to Sheets; screenshot link left empty
- **Token Expired:** Automatic refresh via `Request().refresh()`; if refresh fails, Google services disabled
- **Network Issues:** Playwright timeout handling (networkidle 3-10s waits with fallback to domcontentloaded)
