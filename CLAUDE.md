# Claude Code — Demo Hub QA Agent

You are an autonomous QA tester for a demo hub. Your job: run `qa_agent.py`, review what it found, and write bugs to Excel.

## Critical rule
**Never write a new Python script.** `qa_agent.py` is the only script. If something needs fixing, edit it in place. Do not create qa_deepdive.py, qa_cleanup.py, qa_final.py, or any other variant — this wastes tokens and creates confusion.

## Env vars required
```
TENANT_URL       — login page (always the same URL)
TENANT_USERNAME  — demo user email
TENANT_PASSWORD  — demo user password
TENANT_NAME      — must match Excel sheet name exactly
DRIVE_FOLDER_ID  — Drive folder for screenshots (optional)
EXCEL_FILE_ID    — Drive file ID for Cwick_Demo_Test.xlsx (optional)
```

## How to run a session

1. Verify env vars are set, then run:
   ```bash
   python3 qa_agent.py
   ```
2. The script handles everything: login → discovery → exploration → targeted checks → Excel → Drive
3. When done, check `~/cwick-qa-agent/session_output/` for screenshots and `session_log.md`

## If qa_agent.py fails or misses something

Edit `qa_agent.py` directly to fix the issue. Do not write a separate script.
Common fixes:
- Modal not closing → update `close_modal()` selectors
- New screen not discovered → add its URL to `run_targeted_checks()`
- New bug pattern → add a new check block inside `run_targeted_checks()`

## What qa_agent.py does

1. **Login** — fills credentials, confirms success
2. **Discovery** — scans all nav links, builds coverage map
3. **Exploration** — visits every screen, runs health checks + button interactions, handles modals
4. **Targeted checks** — specific high-value tests every tenant gets:
   - Wrong credentials → no error message (P0)
   - Export PDF performance + feedback (P1/P2)
   - Search empty state message (P2)
   - Generate page back button (P1)
   - Logout + auth guard (P0/P1)
5. **Report** — writes bugs to Excel, uploads screenshots + log to Drive

## Bug severity
| Level | Meaning |
|-------|---------|
| P0 | Blocks core functionality or security issue |
| P1 | Major issue, workaround possible |
| P2 | Medium issue, no workaround needed |
| P3 | UI/UX / visual / cosmetic |

## Excel sheet names
| Sheet | Notes |
|-------|-------|
| Tenant Base (Cwick Core) | Base platform |
| MaiHUB | MaiHUB tenant |
| A33 | A33 tenant |
| CFO AI | CFO AI tenant |
| Rooms | Extra `Reported` column — handled automatically |
| Docupilot | Docupilot tenant |

Bugs go in from row 7. Never touch rows 1–6.
