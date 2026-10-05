# Evidence from the submitted run

Files FACTORY.md cites that no seat produced. All are from the run of 4 Oct 2026 and are copied
here unchanged; paths inside them are the operator's machine.

| File | What it is |
|---|---|
| `checks.sha256` | SHA-256 of the 11 shipped check files, taken at 10:25, before the dispatch |
| `window-kicker.log` | the usage-window kicker: armed at 10:48, armed again at 13:24 when the operator replaced it, fired at 14:31 and restarted the six seats |
| `seat-watchdog.log` | the seat watchdog: started before the dispatch, no restart needed |
| `isolated-stage-4/` | the event harness's report, counts and logs for `--stage 4 --mode isolated` on revision `cd6e904`, the band's last commit |
| `factory-numbers.txt` | output of `tools/factory_numbers.py` for the run. Its verdict table counts verdict messages in the room; FACTORY.md counts the committed verdict files, so the two differ |
| `visual-brief/` | the written visual direction the dispatch pointed to, and its two images |

The seats' Claude Code transcripts and the Codex session logs, from which the token counts were
read, are not in this repository.
