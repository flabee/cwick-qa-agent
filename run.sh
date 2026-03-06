#!/bin/bash

# Load secrets from .env (TENANT_PASSWORD, EXCEL_FILE_ID, per-tenant vars)
if [ -f "$(dirname "$0")/.env" ]; then
    set -a
    source "$(dirname "$0")/.env"
    set +a
fi

# Tenant Routing — maps shorthand aliases to TENANT_NAME + TENANT_URL
# Credentials (TENANT_PASSWORD, DRIVE_FOLDER_ID, EXCEL_FILE_ID) come from .env
if [[ "$*" == *"test1"* ]]; then
    export TENANT_NAME="Docupilot"
    export TENANT_USERNAME="${DOCUPILOT_USERNAME:-demo1@test.it}"
    export DRIVE_FOLDER_ID="${DOCUPILOT_DRIVE_FOLDER_ID:-}"
    export TENANT_URL="${DOCUPILOT_URL:-https://knowledgebase-frontend-p55f.onrender.com/docupilot/login}"
elif [[ "$*" == *"test2"* ]]; then
    export TENANT_NAME="CFO AI"
    export TENANT_USERNAME="${CFO_USERNAME:-demo2@test.it}"
    export DRIVE_FOLDER_ID="${CFO_DRIVE_FOLDER_ID:-}"
    export TENANT_URL="${CFO_URL:-https://knowledgebase-frontend-p55f.onrender.com/cfo/login}"
elif [[ "$*" == *"test3"* ]]; then
    export TENANT_NAME="MaiHUB"
    export TENANT_USERNAME="${MAIHUB_USERNAME:-demo3@test.it}"
    export DRIVE_FOLDER_ID="${MAIHUB_DRIVE_FOLDER_ID:-}"
    export TENANT_URL="${MAIHUB_URL:-https://knowledgebase-frontend-p55f.onrender.com/maihub/login}"
elif [[ "$*" == *"test4"* ]]; then
    export TENANT_NAME="Rooms"
    export TENANT_USERNAME="${ROOMS_USERNAME:-demo4@test.it}"
    export DRIVE_FOLDER_ID="${ROOMS_DRIVE_FOLDER_ID:-}"
    export TENANT_URL="${ROOMS_URL:-https://knowledgebase-frontend-p55f.onrender.com/rooms/login}"
elif [[ "$*" == *"test5"* ]]; then
    export TENANT_NAME="Tenant Base (Cwick Core)"
    export TENANT_USERNAME="${A33_USERNAME:-demo5@test.it}"
    export DRIVE_FOLDER_ID="${A33_DRIVE_FOLDER_ID:-}"
    export TENANT_URL="${A33_URL:-https://knowledgebase-frontend-p55f.onrender.com/a33/login}"
elif [[ "$*" == *"test6"* ]]; then
    export TENANT_NAME="Tenant Base (Cwick Core)"
    export TENANT_USERNAME="${CORE_USERNAME:-demo6@test.it}"
    export DRIVE_FOLDER_ID="${CORE_DRIVE_FOLDER_ID:-}"
    export TENANT_URL="${CORE_URL:-https://knowledgebase-frontend-p55f.onrender.com/login}"
else
    echo "Usage: ./run.sh [test1|test2|test3|test4|test5|test6]"
    echo "  test1 → Docupilot"
    echo "  test2 → CFO AI"
    echo "  test3 → MaiHUB"
    echo "  test4 → Rooms"
    echo "  test5 → A33"
    echo "  test6 → Tenant Base (Cwick Core)"
    exit 1
fi

echo "Launching QA Agent for $TENANT_NAME..."
python3 ~/cwick-qa-agent/qa_agent.py
