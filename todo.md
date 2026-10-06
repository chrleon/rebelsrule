# TODO

## Bugs

- [x] **Rebels Rule: sometimes doesn't activate after switching back to Krita.**
  Steps: turn the ruler on, set an anchor, switch to another app, then come
  back to Krita. Sometimes the ruler no longer locks strokes (intermittent).
  Cause: a lost release left the gesture state machine stuck mid-gesture,
  so later pen events failed the same-device check and passed through.
  Fixed by resetting on focus loss, on a new press and on a buttonless hover
  (`_reset_gesture` in `core.py`). Reproduced and verified offline; still
  to confirm in real use - the Log Viewer shows `reset stuck gesture (...)`
  whenever it kicks in.

## Release

- [x] Make the GitHub repo public when development is done.
- [x] Rename the repo to `chrleon/rebelsrule`; `chrleon/kritaplugins` now only forwards the old site address.
