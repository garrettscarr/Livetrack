# Checkpoint implementation status

| CP | Meaning | Implemented in repo |
|----|---------|---------------------|
| CP0 | Season data truth | `scripts/audit_tags.py`, `data/cp0_data_truth.md`, scout checklist, `team_config` aliases, roster starter flags |
| CP1 | Booth dry-run ready | Mac `.command` / `.sh` launchers, HT half auto-advance fix, `docs/DRESS_REHEARSAL.md` |
| CP2 | Game-night v1 | `docs/GAME_NIGHT_SOP.md`, `docs/POST_GAME_REFRESH.md` |
| CP3 | Mid-season reliability | Live Track = sole HT path (`docs/PRODUCT_SURFACE.md`), `data/alias_backlog.md` |
| CP4 | District booth | Shared-mode PIN, `file_lock` on live log + game_state |
| CP5 | Product foundation | `team_config.json`, pinned `requirements.txt`, `.gitignore`, smoke tests, first-run wizard |
| CP6 | Downloadable Tier A | `packaging/make_portable.*`, Install and Run templates, packaging README + PyInstaller sketch |

Season calendar work (weekly dry runs, post-game alias logging) still happens on the field using these tools.
