#!/bin/bash
# Install cron job for morning digest
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${SCRIPT_DIR}/venv/bin/python"
CRON_JOB="0 5 * * * cd ${SCRIPT_DIR} && ${PYTHON} main.py >> logs/digest.log 2>&1"

# Check if cron job already exists
if crontab -l 2>/dev/null | grep -qF "morning-digest"; then
    echo "Cron job already exists. Replacing..."
    crontab -l 2>/dev/null | grep -vF "morning-digest" | crontab -
fi

# Install new cron job with identifier comment
(crontab -l 2>/dev/null; echo "# morning-digest"; echo "$CRON_JOB") | crontab -

echo "Cron job installed: runs daily at 5am Mountain Time"
echo "  Working dir: ${SCRIPT_DIR}"
echo "  Python: ${PYTHON}"
echo ""
echo "Verify with: crontab -l"
