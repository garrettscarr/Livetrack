# Game-night SOP (CP2)

**Product surface:** Live Track is the only game-night path (log, lineup, Fill Film, End 1st Half). Do not open orphaned In-Game / Sideline pages.

## Before kickoff (booth laptop)

1. Drop latest Hudl if needed → `python refresh_all.py` (or confirm DB already current).
2. Open **Game Plan** → pin edges for tonight’s opponent.
3. Open **Database** → confirm roster / starters / favorites.
4. Start the booth:
   - **Hosted (recommended for multi-iPad):** deploy once — see [HOSTED_BOOTH.md](HOSTED_BOOTH.md).  
     Laptop: `https://YOUR-HOST/?station=call` · iPad: `?station=defense`
   - **Local shared:** Mac `run_live_shared.command` / Windows `run_live_shared.bat`  
     (same Wi‑Fi or phone hotspot; laptop-as-hotspot if client isolation blocks tablets)
5. Unlock with booth PIN (`data/team_config.json` → `booth_pin`, default `0851`).
6. Devices: open the hosted URL (or `http://<laptop-ip>:8501`) → enter PIN.
7. Live Track → select opponent → Half 1 → Call station logs; Defense fills film.

## During the half

1. Prefer phrase log → confirm card → commit.
2. Use **Undo** for last snap; do not edit CSV by hand mid-drive.
3. Lineup sheet for subs / ball touches as needed.
4. Fill Film when Sky Coach tags are pending.

## Halftime

1. Live Track → expander **Halftime / end 1st half** → **End 1st Half → Generate Halftime Report**.
2. Review Formations / Situations / Signals tabs (under 2 minutes).
3. Download / open the saved `.md` under `data/halftime_reports/` if needed for the locker room.
4. Half radio should move to 2 (auto after End Half).

## Second half

1. Continue logging on Half 2.
2. Do not Reset to 1st half unless starting a new game.

## After final whistle

See [POST_GAME_REFRESH.md](POST_GAME_REFRESH.md).
