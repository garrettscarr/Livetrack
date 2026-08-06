# Dress rehearsal checklist (CP1 / Week 3–4)

Run a scripted 1st half on booth + tablet before Game 1.

## Setup

- [ ] Mac: `run_live_shared.command` starts Streamlit
- [ ] Tablet opens laptop IP:8501 and unlocks with PIN
- [ ] Opponent set to Farmersville (or Week 1 opp)
- [ ] Half = 1, Sheet = Log

## Script (~25 snaps)

For each snap: phrase or tap → confirm → commit. Mix:

1. Start drive
2. 5–8 snaps with formation + play + yards/result
3. One intentional wrong confirm → fix on card
4. One Undo
5. Lineup: verbal sub or on-field change
6. Ball touch on a catch
7. End drive + Film pending → Fill Film phrase
8. Start another short drive (3–4 snaps)
9. **End 1st Half → Generate Halftime Report**
10. Confirm Half flips to 2 and HT tabs render

## Pass criteria

- [ ] No crashes / blank pages
- [ ] Live log row count matches committed snaps
- [ ] HT report JSON + MD written under `data/halftime_reports/`
- [ ] Tablet and laptop stay in sync (same log after refresh)
- [ ] Post-game: `refresh_all.py` still succeeds

## Freeze

After a clean rehearsal: no risky refactors until after Game 1 unless fixing a P0 booth bug.
