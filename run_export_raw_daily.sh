#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/Users/sumedhmore/Desktop/motion_backend"
PYTHON="/Library/Frameworks/Python.framework/Versions/3.10/bin/python3"  # change if you use a venv
LOG_DIR="$PROJECT_DIR/logs"
mkdir -p "$LOG_DIR"

LOG_FILE="$LOG_DIR/export_raw_$(date +%Y-%m-%d).log"

cd "$PROJECT_DIR"
{
  echo "[$(date)] Starting export_raw_day.py (yesterday IST)"
  "$PYTHON" "$PROJECT_DIR/export_raw_day.py"
  echo "[$(date)] Done."
} >> "$LOG_FILE" 2>&1

