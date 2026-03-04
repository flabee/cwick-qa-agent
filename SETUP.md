# Demo Hub QA Agent — Setup Guide

## Project Structure

Drop these files into your Claude Code project root:

```
your-project/
├── CLAUDE.md          ← main instruction file (Claude Code reads this automatically)
├── QA_SKILL.md        ← heuristic checklist (referenced by CLAUDE.md)
└── SETUP.md           ← this file
```

---

## Dependencies

Run once before your first session:

```bash
pip install playwright openpyxl google-api-python-client google-auth
playwright install chromium
```

---

## Tenant Credentials — Environment Variables

Never hardcode credentials. Pass them as env vars when invoking Claude Code:

```bash
export TENANT_URL="https://your-tenant.demo.cwick.io"
export TENANT_USERNAME="tester@yourcompany.com"
export TENANT_PASSWORD="yourpassword"
export TENANT_NAME="MaiHUB"                          # Must match Excel sheet name exactly
export DRIVE_FOLDER_ID="1v6aVtuSREguMsIzkmacEvWj_iXPSfy7P"   # Screenshots subfolder for this tenant
export EXCEL_FILE_ID="<get from Drive URL of Cwick_Demo_Test.xlsx>"
```

Then start Claude Code normally:

```bash
claude
```

---

## Google Drive Access

Claude Code will need Drive API access to:
1. Download the Excel file
2. Upload screenshots
3. Re-upload the updated Excel

**Option A — Use the Drive MCP connector** (if connected in Claude.ai)
No extra setup needed. Claude Code will use the MCP tool.

**Option B — Service Account**
1. Create a service account in Google Cloud Console
2. Share the Drive folder with the service account email
3. Download the JSON key and set: `export GOOGLE_APPLICATION_CREDENTIALS="path/to/key.json"`

---

## Running a QA Session

1. Set env vars for the tenant you want to test
2. Run `claude` in the project root
3. Claude Code will:
   - Read `CLAUDE.md` automatically on startup
   - Log in to the tenant
   - Explore all visible flows
   - Capture bugs + screenshots
   - Update the Excel sheet for that tenant
   - Upload everything to Drive
4. Check your Drive folder for `session_log.md` and the updated `Cwick_Demo_Test.xlsx`

---

## Excel Sheet Names

Each sheet name must match `TENANT_NAME` exactly:

| Sheet Name | Notes |
|-----------|-------|
| `Tenant Base (Cwick Core)` | Base platform |
| `MaiHUB` | MaiHUB tenant |
| `A33` | A33 tenant |
| `CFO AI` | CFO AI tenant |
| `Rooms` | Rooms tenant — has an extra `Reported` column |

> ⚠️ The `Rooms` sheet has columns shifted by one. Claude Code handles this automatically per `CLAUDE.md`.

---

## Adding a New Tenant

1. Add a new sheet to `Cwick_Demo_Test.xlsx` matching the new tenant name (copy an existing sheet's format)
2. Create a subfolder in the Drive folder for screenshots
3. Set `TENANT_NAME` and `DRIVE_FOLDER_ID` to the new values
4. Run as normal

---

## Output Per Session

| File | Location |
|------|---------|
| `Cwick_Demo_Test.xlsx` (updated) | Google Drive root folder |
| `BUG_NNN_*.png` screenshots | Drive subfolder for the tenant |
| `session_log.md` | Drive subfolder for the tenant |
