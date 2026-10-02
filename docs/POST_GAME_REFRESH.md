# Post-game refresh drill (CP2)

Target: under 10 minutes.

1. Export tonight’s film from Hudl → replace/update `data/hudl_exports/season.xlsx` (or append per your Hudl workflow).
2. If you scouted the next opponent, add `{Opponent} D.xlsx` / `O.xlsx` and tick `data/scout_opponents.csv`.
3. From project root:
   ```bash
   .venv/bin/python refresh_all.py
   # or: python refresh_all.py
   ```
4. Launch app → **Game Review** → confirm tonight’s game appears with EPA / xP.
5. **Database → Offense tags** → skim favorites; add any new install plays.
6. Append phrase misses to `data/alias_backlog.md` (promote later into `team_config.json`).
7. Optional: archive `data/live_log.csv` copy if you want a raw booth record before next game overwrite.

Smoke check (optional):
```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/audit_tags.py
```
