#!/bin/bash
cd "$(dirname "$0")"
echo "Football EPA - Local only (this computer)"
if [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PY="python3"
else
  PY="python"
fi
exec "$PY" -m streamlit run step4_dashboard.py --server.port 8501
