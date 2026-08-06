# Football EPA (Hudl → Python)

Season EPA + success rate, per-opponent scout, pre-match game plan, and booth Live Track with halftime adjustments.

**Game-night path:** Live Track only (phrase log, lineup, Fill Film, End 1st Half). See [docs/PRODUCT_SURFACE.md](docs/PRODUCT_SURFACE.md) and [docs/GAME_NIGHT_SOP.md](docs/GAME_NIGHT_SOP.md).

## Success rate

Alongside EPA:

- **1st / 2nd down:** success if yards gained ≥ half the yards to go  
- **3rd / 4th down:** success if yards gained ≥ all yards to go  
- TD = success; penalties excluded  
- **Defense:** success = opponent **fails** that test  

## Data files

| File | Purpose |
|------|---------|
| `data/hudl_exports/season.xlsx` | Your season film |
| `data/hudl_exports/{Opponent} D.xlsx` | Scout **their defense** (for our offense) |
| `data/hudl_exports/{Opponent} O.xlsx` | Scout **their offense** (for our defense) |
| `data/opponents.csv` | Game → opponent names |
| `data/scout_opponents.csv` | Scout file checklist by opponent |
| `data/team_config.json` | Aliases, booth PIN, team identity |
| `data/live_log.csv` | In-game logs (includes `half`) |
| `data/game_plans/{Opponent}.json` | Pinned pre-match plan |
| `data/game_state.json` | Game phase (`1st` / `halftime` / `2nd`) |
| `data/halftime_reports/` | Saved halftime reports (`.json` + `.md`) |
| `data/alias_backlog.md` | Mid-season STT / Hudl spelling queue |

## Refresh

```
python refresh_all.py
```

Rebuilds clean tables + EPA + `is_success`.

Tag audit:

```
python scripts/audit_tags.py
```

Smoke tests:

```
python -m unittest discover -s tests -v
```

## Dashboard

```
python -m streamlit run step4_dashboard.py
```

| Mode | Mac | Windows |
|------|-----|---------|
| Local | `run_live_local.command` | `run_live_local.bat` |
| Booth + tablet | `run_live_shared.command` | `run_live_shared.bat` |

Shared mode sets `FOOTBALL_EPA_SHARED=1` and requires the booth PIN from `data/team_config.json` (default `0851`).

**Pages:** Live Track · Game Review · Database · Game Plan · Opponent Scout

## Season docs

- [Game-night SOP](docs/GAME_NIGHT_SOP.md)
- [Post-game refresh](docs/POST_GAME_REFRESH.md)
- [Dress rehearsal](docs/DRESS_REHEARSAL.md)
- [Portable packaging](packaging/README.md)

## Portable zip (Tier A)

```
./packaging/make_portable.sh
# or packaging\make_portable.bat
```

Produces `packaging/out/football-epa-portable.zip` with Install and Run launchers.
