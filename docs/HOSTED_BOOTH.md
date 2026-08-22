# Hosted multi-device booth (foundation)

Open one URL on the laptop + iPad(s). No stadium Wi‑Fi or hotspot required if
devices have cellular. Updates deploy to that same URL.

## What this gives you

On open, the app asks **Main** or **Tagger**:

| Choice | Gets |
|--------|------|
| **Main** | Full booth (same interface as today) |
| **Tagger** | Pick Snap log / Front / Coverage / Blitz → simplified UI for only those |

Sidebar → **Switch Main / Tagger** to change later.

Optional bookmarks still work (`?station=tag&focus=front`, etc.).

## Streamlit Community Cloud

1. Connect `garrettscarr/Livetrack` → main → `step4_dashboard.py`.
2. After deploy, the first-run **Setup** page lets you **upload `data/football.db`**
   from your Mac (fastest) or a Hudl `season.xlsx` + **Refresh database**.
3. Shared booth mode turns on automatically (`STREAMLIT_RUNTIME_ENV=cloud`).
4. Re-upload `football.db` after a full Cloud redeploy (disk is ephemeral).

## Deploy (Render example)

1. Push this repo to GitHub.
2. [Render](https://render.com) → **New** → **Blueprint** → select the repo  
   (uses `render.yaml` + `Dockerfile`).
3. Attach the disk at `/app/data` (Blueprint already defines it).
4. After deploy, copy the service URL, e.g. `https://football-epa-booth.onrender.com`.
5. Optional: set env `BOOTH_PUBLIC_URL` to that URL (shown in the app banner).
6. Set / confirm booth PIN in `data/team_config.json` (`booth_pin`) **on the
   persistent volume** after first boot (or bake it into the image carefully).

Railway / Fly.io: deploy the same `Dockerfile`, mount a volume on `/app/data`,
set `FOOTBALL_EPA_SHARED=1`, use `$PORT`.

## iPad bookmarks

- **You (everything):** `https://YOUR-HOST/`
- Tagger (pick job): `https://YOUR-HOST/?station=tag`
- Front: `https://YOUR-HOST/?station=tag&focus=front`
- Coverage: `https://YOUR-HOST/?station=tag&focus=coverage`
- Blitz: `https://YOUR-HOST/?station=tag&focus=blitz`
- Snaps: `https://YOUR-HOST/?station=tag&focus=snaps`

Unlock once with the booth PIN (shared mode).

## Game-night flow

1. Laptop opens Call → Start new game / Log as usual (skip defense if rushed).
2. iPad opens Defense → pending snaps appear under Fill Film (auto-refreshes).
3. End drive on laptop → Film mode still works on the iPad.
4. Halftime from laptop (Full or Call).

## Persistence warning

Without a **persistent disk** on `/app/data`, redeploys wipe live logs / DB.
Keep the volume attached for the season.

## Local vs hosted

| | Local shared | Hosted |
|--|--------------|--------|
| Start | `run_live_shared.command` | Cloud URL |
| Network | Same Wi‑Fi / hotspot | Cellular OK |
| PIN | Yes | Yes |
| Multi-tagger | Yes | Yes (foundation) |

Next upgrades (when you want them): parallel snap draft (Call + Defense edit
one open play before LOG), cloud DB instead of CSV.
