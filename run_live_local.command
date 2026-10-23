#!/bin/bash
cd "$(dirname "$0")"
echo "Football EPA - Local only (this computer)"
# OneDrive can turn .venv symlinks into text files — only use a venv that actually runs.
PY=""
for cand in ".venv/bin/python" "python3" "python"; do
  if "$cand" -c "import streamlit" >/dev/null 2>&1; then
    PY="$cand"
    break
  fi
done
if [ -z "$PY" ]; then
  echo "Streamlit is not installed for any Python on this Mac."
  echo "With internet, run:  python3 -m pip install -r requirements.txt"
  read -r -p "Press Enter to close..."
  exit 1
fi
exec "$PY" -m streamlit run step4_dashboard.py --server.port 8501
