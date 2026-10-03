"""
Permanent shell for Rebels Rule.

Krita only accepts actions (menu entries + shortcuts) at startup, so this
module owns them and never reloads. The actual ruler lives in core.py and
can be swapped out at runtime with "Reload Rebels Rule" (Ctrl+Alt+Shift+R):
the old controller is shut down, every `rebelsrule.*` module except this
one is re-imported from disk, and a fresh controller takes over with the
same on/off state and anchor.

When the plugin is installed with `./build.sh --link` (the package folder
is a symlink into the repo), it also watches its own .py files and
reloads automatically a moment after you save. Copied installs don't
watch.

Changes to this file, __init__.py, the .desktop or .action files still
need a Krita restart.
"""

from krita import Extension

from PyQt5.QtCore import QFileSystemWatcher, QTimer

import importlib
import os
import sys
import traceback

from . import core


TOGGLE_ID = "rebelsrule_toggle"
RELOAD_ID = "rebelsrule_reload"

_PACKAGE = __name__.rpartition(".")[0]
_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
_DEV_MODE = os.path.islink(_PKG_DIR)   # installed via ./build.sh --link


class RebelsRuleExtension(Extension):

    def __init__(self, parent):
        super().__init__(parent)
        self.ctrl = core.RebelsRule()
        self.toggle_action = None
        self.watcher = None
        if _DEV_MODE:
            self._start_watching()

    def setup(self):
        pass

    def createActions(self, window):
        self.toggle_action = window.createAction(TOGGLE_ID, "Rebels Rule", "tools/scripts")
        self.toggle_action.setCheckable(True)
        self.toggle_action.setChecked(self.ctrl.enabled)
        self.toggle_action.toggled.connect(lambda on: self.ctrl.set_enabled(on))

        reload_action = window.createAction(RELOAD_ID, "Reload Rebels Rule", "tools/scripts")
        reload_action.triggered.connect(self.reload)

    # ---- auto-reload on save (dev mode only) ----

    def _start_watching(self):
        self.src_dir = os.path.realpath(_PKG_DIR)
        self.snapshot = self._snapshot()
        self.watcher = QFileSystemWatcher()
        # Editors often save by replacing the file, which drops it from the
        # watcher, so every change re-arms the watch list after a short pause.
        self.debounce = QTimer()
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(300)
        self.debounce.timeout.connect(self._on_settled)
        self.watcher.fileChanged.connect(lambda *_: self.debounce.start())
        self.watcher.directoryChanged.connect(lambda *_: self.debounce.start())
        self._rewatch()

    def _py_files(self):
        try:
            return sorted(os.path.join(self.src_dir, f)
                          for f in os.listdir(self.src_dir) if f.endswith(".py"))
        except OSError:
            return []

    def _snapshot(self):
        snap = {}
        for path in self._py_files():
            try:
                snap[path] = os.stat(path).st_mtime_ns
            except OSError:
                pass
        return snap

    def _rewatch(self):
        watched = self.watcher.files() + self.watcher.directories()
        if watched:
            self.watcher.removePaths(watched)
        self.watcher.addPaths([self.src_dir] + self._py_files())

    def _on_settled(self):
        self._rewatch()
        snap = self._snapshot()
        if snap == self.snapshot:   # e.g. Python writing __pycache__
            return
        self.snapshot = snap
        self.reload(reason="file saved")

    def reload(self, *_, reason=None):
        old = self.ctrl
        was_enabled = old.enabled
        state = old.state()
        old.shutdown()
        try:
            # Reload leaf modules first so core picks up fresh helpers.
            names = sorted((n for n in sys.modules
                            if n.startswith(_PACKAGE + ".") and n != __name__),
                           key=lambda n: n.count("."), reverse=True)
            for name in names:
                importlib.reload(sys.modules[name])
            new = sys.modules[_PACKAGE + ".core"].RebelsRule(state)
        except Exception:
            traceback.print_exc()
            print("[rebelsrule] reload failed, keeping the previous version")
            old.set_enabled(was_enabled, quiet=True)
            old.message("Rebels Rule: reload failed (see Log Viewer)")
            return
        self.ctrl = new
        new.set_enabled(was_enabled, quiet=True)
        new.message("Rebels Rule reloaded" + (f" ({reason})" if reason else ""))
