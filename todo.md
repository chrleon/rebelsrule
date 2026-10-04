# TODO

## Bugs

- [ ] **Rebels Rule: sometimes doesn't activate after switching back to Krita.**
  Steps: turn the ruler on, set an anchor, switch to another app, then come
  back to Krita. Sometimes the ruler no longer locks strokes (intermittent).
  Suspects: Krita/Qt dropping the app-wide event filter or the pen's
  proximity state on focus loss; the stroke state machine left in `PENDING`
  or `STROKE` if a release event was lost while Krita was in the background
  (see `filter_event` in `rebelsrule/rebelsrule/core.py`).

## Release

- [ ] Make the GitHub repo (`chrleon/kritaplugins`) public when development is done.
