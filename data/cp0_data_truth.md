# CP0 — Season data truth

Checked Aug 2026 against current `football.db` + Hudl folder.

| Item | Status |
|------|--------|
| Current season EPA | Yes (`season.xlsx` → season=`current`) |
| 24-25 EPA + tagged plays | Yes; formations ignored for prior year |
| Axle alias | Canonical via `tag_normalize` + `team_config.json` |
| Week-1 scout | Farmersville D.xlsx + O.xlsx present and in DB |
| opponents.csv | 13 games mapped (Farmersville first) |
| scout_opponents.csv | Checklist of schedule + week-1 files |
| Roster vs starters | All starter names present in roster.json |
| Favorites | Axle present under run plays |

Refresh after Hudl drops: `python refresh_all.py`  
Audit: `python scripts/audit_tags.py`
