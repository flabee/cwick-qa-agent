#!/bin/bash
cd "$(dirname "$0")"

clear
echo "================================"
echo "       Cwick QA Test Runner     "
echo "================================"
echo ""
echo "Select tenant:"
echo "  1) Docupilot     (demo1@test.it)"
echo "  2) CFO AI        (demo2@test.it)"
echo "  3) MaiHUB        (demo3@test.it)"
echo "  4) Rooms         (demo4@test.it)"
echo ""
read -p "Enter number (1-4): " tenant_choice

case $tenant_choice in
    1) tenant="test1" ;;
    2) tenant="test2" ;;
    3) tenant="test3" ;;
    4) tenant="test4" ;;
    *)
        echo "Invalid choice. Exiting."
        read -p "Press Enter to close..."
        exit 1
        ;;
esac

echo ""
echo "Select mode:"
echo "  1) Standard  — wrong creds, create new, KB, chat, search, logout (~2 min)"
echo "  2) Smart     — AI-guided exploration, 20 steps (~10-15 min)"
echo ""
read -p "Enter number (1-2): " mode_choice

case $mode_choice in
    1) mode="" ;;
    2) mode="smart" ;;
    *)
        echo "Invalid choice. Exiting."
        read -p "Press Enter to close..."
        exit 1
        ;;
esac

echo ""
echo "================================"
bash run.sh $tenant $mode
echo "================================"
echo ""
read -p "Done! Press Enter to close..."
