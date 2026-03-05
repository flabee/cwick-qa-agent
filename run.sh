#!/bin/bash

# Fix #9: Load secrets from .env (not hardcoded)
if [ -f "$(dirname "$0")/.env" ]; then
    set -a
    source "$(dirname "$0")/.env"
    set +a
fi

# Tenant Routing — all 6 tenants
if [[ "$*" == *"test1"* ]]; then
    export TENANT_NAME="Docupilot"
    export TENANT_USERNAME="demo1@test.it"
    export DRIVE_FOLDER_ID="1v6aVtuSREguMsIzkmacEvWj_iXPSfy7P"
    export TENANT_URL="https://knowledgebase-frontend-p55f.onrender.com/docupilot/login"
elif [[ "$*" == *"test2"* ]]; then
    export TENANT_NAME="CFO AI"
    export TENANT_USERNAME="demo2@test.it"
    export DRIVE_FOLDER_ID="19mf-lv8roD0tWtVjOS3aTWYZdfzAj2tl"
    export TENANT_URL="https://knowledgebase-frontend-p55f.onrender.com/cfo/login"
elif [[ "$*" == *"test3"* ]]; then
    export TENANT_NAME="MaiHUB"
    export TENANT_USERNAME="demo3@test.it"
    export DRIVE_FOLDER_ID="1D_5Q7SMSxxNPmopSB_zBjlTT6LGSrKgj"
    export TENANT_URL="https://knowledgebase-frontend-p55f.onrender.com/maihub/login"
elif [[ "$*" == *"test4"* ]]; then
    export TENANT_NAME="Rooms"
    export TENANT_USERNAME="demo4@test.it"
    export DRIVE_FOLDER_ID="1eBc7eb8kGQ_e2LB0fLIX-myLtQqdc0jJ"
    export TENANT_URL="https://knowledgebase-frontend-p55f.onrender.com/rooms/login"
elif [[ "$*" == *"test5"* ]]; then
    export TENANT_NAME="Tenant Base (Cwick Core)"
    export TENANT_USERNAME="demo5@test.it"
    export DRIVE_FOLDER_ID="1tam5YsW8B6C0lDxnNN3__8PFdWgPqBeZ"
    export TENANT_URL="https://knowledgebase-frontend-p55f.onrender.com/a33/login"
elif [[ "$*" == *"test6"* ]]; then
    export TENANT_NAME="Tenant Base (Cwick Core)"
    export TENANT_USERNAME="demo6@test.it"
    export DRIVE_FOLDER_ID=""
    export TENANT_URL="https://knowledgebase-frontend-p55f.onrender.com/login"
else
    echo "Usage: ./run.sh [test1|test2|test3|test4|test5|test6]"
    echo "  test1 → Docupilot              (demo1@test.it)"
    echo "  test2 → CFO AI                 (demo2@test.it)"
    echo "  test3 → MaiHUB                 (demo3@test.it)"
    echo "  test4 → Rooms                  (demo4@test.it)"
    echo "  test5 → A33                    (demo5@test.it)"
    echo "  test6 → Tenant Base (Cwick Core)"
    exit 1
fi

echo "Launching QA Agent for $TENANT_NAME..."
python3 ~/cwick-qa-agent/qa_agent.py
