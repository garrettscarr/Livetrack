#!/bin/bash
cd "$(dirname "$0")"
echo "========================================"
echo " Football EPA - Live Assistant (shared)"
echo "========================================"
echo ""
IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}')
echo "On THIS computer open:"
echo "  http://localhost:8501"
echo ""
if [ -n "$IP" ]; then
  echo "On a TABLET / other device on the same Wi-Fi open:"
  echo "  http://${IP}:8501"
  echo ""
fi
echo "Booth PIN required (default in data/team_config.json)."
echo "Press Ctrl+C to stop."
echo ""
if [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PY="python3"
else
  PY="python"
fi
export FOOTBALL_EPA_SHARED=1
exec "$PY" -m streamlit run step4_dashboard.py --server.address 0.0.0.0 --server.port 8501
