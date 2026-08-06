# Phrase / tag alias backlog (CP3)

Log Live Track STT or Hudl spelling misses here after each game. Promote confirmed pairs into `data/team_config.json` (`play_word_aliases` or `phrase_token_aliases`), then run:

```bash
.venv/bin/python scripts/audit_tags.py
.venv/bin/python refresh_all.py
```

## Confirmed (in config)

| Heard / Hudl | Canonical | Notes |
|--------------|-----------|-------|
| Axel / AXLE / axle | Axle | play_word_aliases |

## Pending from games

| Date | Opponent | Heard / tagged | Should be | Status |
|------|----------|----------------|-----------|--------|
| | | | | |

## Review checklist (post-game)

1. Scan Live Track unmatched phrases (confirm card / inbox).
2. Scan new Hudl play_call strings that look like duplicates of favorites.
3. Add row above; after 2+ confirmations, move into `team_config.json`.
