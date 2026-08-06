# Tier A — downloadable / portable packaging (CP6)

Goal: another coach can install without knowing the codebase.

## Option 1 — Zip + bootstrap (ship first)

1. Run `./packaging/make_portable.sh` (Mac/Linux) or `packaging\make_portable.bat` (Windows).
2. Deliver `packaging/out/football-epa-portable.zip`.
3. Recipient:
   - Unzip
   - Mac: double-click `Install and Run.command`
   - Windows: double-click `Install and Run.bat`
4. App opens Streamlit; first-run wizard if `season.xlsx` is missing.

This bundles **source + pinned requirements**, creates a local `.venv`, and launches. Python 3.11+ must be installed on the machine (python.org installer).

## Option 2 — Single-folder PyInstaller (later)

```bash
pip install pyinstaller
pyinstaller --noconfirm --clean packaging/football_epa.spec
```

Streamlit static assets are brittle in frozen apps; prefer Option 1 until Option 2 is soak-tested on a clean Mac and Windows laptop.

## What is included vs excluded

| Include | Exclude |
|---------|---------|
| Python modules, docs, launchers | `.venv`, OneDrive junk |
| `data/team_config.json` (PIN + aliases) | Live booth state CSV/JSON |
| Sample `opponents.csv` / empty hudl README | Full Hudl film (staff supplies) |
| Pinned `requirements.txt` | `football.db` (rebuilt on refresh) |

## Mass-produced checklist (offseason)

- [ ] Change default `booth_pin` per program
- [ ] Neutral `team_name` / strip program-specific favorites if shipping blank
- [ ] First-run wizard verified on clean machine
- [ ] Mac + Windows smoke of Install and Run
- [ ] Optional update channel (not required for Tier A)
