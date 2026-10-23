#!/bin/bash
cd "$(dirname "$0")"
echo "========================================"
echo " Football EPA - Live Assistant (shared)"
echo "========================================"
echo ""

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

IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}')
echo "On THIS computer open:"
echo "  http://localhost:8501"
echo ""
if [ -n "$IP" ]; then
  echo "Phones / tablets must be on the SAME Wi-Fi. Backup links if a QR won't scan:"
  echo "  Main:                       http://${IP}:8501/?station=main"
  echo "  Tagger 1 (Front + Blitz):   http://${IP}:8501/?station=tag&focus=front,blitz"
  echo "  Tagger 2 (Coverage + Ball): http://${IP}:8501/?station=tag&focus=coverage,ball"
  echo "  Only 1 tagger:              http://${IP}:8501/?station=tag&focus=front,coverage,blitz,ball"
  echo ""
else
  echo "No Wi-Fi address found — join the press box Wi-Fi so phones can connect."
  echo ""
fi
echo "Booth PIN required (default in data/team_config.json)."
echo "Press Ctrl+C to stop."
echo ""
export FOOTBALL_EPA_SHARED=1
exec "$PY" -m streamlit run step4_dashboard.py --server.address 0.0.0.0 --server.port 8501
