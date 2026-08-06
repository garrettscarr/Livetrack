#!/bin/bash
cd "$(dirname "$0")"
echo "Football EPA — install deps (first run) and launch"
if ! command -v python3 >/dev/null 2>&1; then
  echo "Install Python 3.11+ from https://www.python.org/downloads/ then re-run."
  read -r _
  exit 1
fi
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
echo ""
echo "Opening Football EPA on http://localhost:8501"
exec .venv/bin/python -m streamlit run step4_dashboard.py --server.port 8501
