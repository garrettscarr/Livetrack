Put your Hudl Excel exports in this folder.

Required:
  season.xlsx                 → current season film (primary)

Optional prior seasons (for EPA + tagged formation/play history):
  season_24-25.xlsx           → 2024-25 film
  season_23-24.xlsx           → etc.

  Prior-year policy (e.g. season_24-25.xlsx):
    - ALL snaps with down/distance/gain → EPA / expected points model
    - Tagged play calls → play-call boards + favorites
    - Formations → IGNORED (untrusted / wrong scheme)
    - Game Review game list → current season only

Per-opponent scout (recommended):
  Farmersville D.xlsx      → their defense (for our offense)
  Farmersville O.xlsx      → their offense (for our defense)
  Gunter D.xlsx / Gunter O.xlsx  → same pattern for other teams

Naming rules:
  "{Opponent} D.xlsx"  = opponent defense scout
  "{Opponent} O.xlsx"  = opponent offense scout

Opponent name must match opponents.csv (e.g. Farmersville).

Optional for prior seasons:
  data/opponents_24-25.csv  → game_id → opponent map for that year
  (without it, prior-year opponents show as Unknown; EPA still works)

After adding/updating files:
  python refresh_all.py
