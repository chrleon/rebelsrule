"""
Rebels Rule — a Rebelle-style ruler for Krita.

Toggle with Tools > Scripts > Rebels Rule (default Ctrl+Alt+R). While on:
  - Tap (press + release without moving) on the canvas to drop an anchor.
  - Press and drag to paint: the stroke is locked to the infinite line that
    runs through the anchor and the point where the stroke started.
  - Strokes with a modifier held (Ctrl, Shift, Alt, Space-pan...) and any
    non-left pen/mouse button pass straight through to Krita untouched.
  - With no anchor set, a drag paints normally.
  - Esc clears the anchor.

How it works: an application-level event filter intercepts tablet/mouse
events headed for Krita's canvas widget, swallows the originals and
re-sends synthetic copies whose positions are projected onto the ruler
line. Pressure, tilt, rotation and timestamps are kept, so brush dynamics
behave normally.

The anchor is stored in image coordinates, so it stays pinned to the
artwork when you pan, zoom or rotate the canvas.
"""

from krita import Krita, Extension

from PyQt5.QtCore import Qt, QEvent, QObject, QPointF, QLineF, QTimer
from PyQt5.QtGui import QTabletEvent, QMouseEvent, QPainter, QPen, QColor, QIcon
from PyQt5.QtWidgets import QApplication, QWidget

import math


ACTION_ID = "rebelsrule_toggle"

# Exact QMetaObject class names of Krita's canvas viewport widget.
_CANVAS_CLASS_NAMES = ("KisOpenGLCanvas2", "KisQPainterCanvas")

TAP_PX = 4.0          # movement below this between press/release = a tap
SAME_POINT_PX = 6.0   # stroke starting this close to the anchor takes its
                      # direction from the first drag movement instead

_TABLET_TYPES = (QEvent.TabletPress, QEvent.TabletMove, QEvent.TabletRelease)
_MOUSE_TYPES = (QEvent.MouseButtonPress, QEvent.MouseMove,
                QEvent.MouseButtonRelease, QEvent.MouseButtonDblClick)

IDLE, PENDING, STROKE, PASSTHRU = range(4)


def _is_canvas(obj):
    return (isinstance(obj, QWidget)
            and obj.metaObject().className() in _CANVAS_CLASS_NAMES)


def _dist(a, b):
    return math.hypot(a.x() - b.x(), a.y() - b.y())


# ---------------------------------------------------------------------------
# Event snapshots (Qt reuses/deletes event objects, so copy what we need)
# ---------------------------------------------------------------------------

class _Snap:
    def __init__(self, ev, tablet):
        self.tablet = tablet
        self.type = ev.type()
        self.timestamp = ev.timestamp()
        self.modifiers = ev.modifiers()
        self.button = ev.button()
        self.buttons = ev.buttons()
        if tablet:
            self.pos = QPointF(ev.posF())
            self.global_pos = QPointF(ev.globalPosF())
            self.device = int(ev.deviceType())
            self.pointer = int(ev.pointerType())
            self.pressure = ev.pressure()
            self.x_tilt = ev.xTilt()
            self.y_tilt = ev.yTilt()
            self.tangential = ev.tangentialPressure()
            self.rotation = ev.rotation()
            self.z = ev.z()
            self.unique_id = ev.uniqueId()
        else:
            self.pos = QPointF(ev.localPos())
            self.window_pos = QPointF(ev.windowPos())
            self.global_pos = QPointF(ev.screenPos())

    def build(self, pos, ev_type=None):
        """New event identical to this one but located at widget pos `pos`."""
        t = self.type if ev_type is None else ev_type
        delta = pos - self.pos
        if self.tablet:
            e = QTabletEvent(t, pos, self.global_pos + delta,
                             self.device, self.pointer, self.pressure,
                             self.x_tilt, self.y_tilt, self.tangential,
                             self.rotation, self.z, self.modifiers,
                             self.unique_id, self.button, self.buttons)
        else:
            e = QMouseEvent(t, pos, self.window_pos + delta,
                            self.global_pos + delta,
                            self.button, self.buttons, self.modifiers)
        e.setTimestamp(self.timestamp)
        return e


# ---------------------------------------------------------------------------
# Overlay: draws the anchor and a preview of the ruler line
# ---------------------------------------------------------------------------

class RulerOverlay(QWidget):

    def __init__(self, canvas_widget, ext):
        super().__init__(canvas_widget)
        self.ext = ext
        self.hover = None
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setGeometry(canvas_widget.rect())
        canvas_widget.installEventFilter(self)
        self.show()
        self.raise_()

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Resize:
            self.setGeometry(obj.rect())
        return False

    def paintEvent(self, event):
        anchor = self.ext.anchor_widget_pos()
        if anchor is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        guide = self.ext.active_line() or (
            (anchor, self.hover) if self.hover is not None
            and _dist(anchor, self.hover) > SAME_POINT_PX else None)
        if guide is not None:
            origin, through = guide
            line = QLineF(origin, through)
            line.setLength(20000)
            back = QLineF(origin, through)
            back.setLength(-20000)
            full = QLineF(back.p2(), line.p2())
            for color, width, style in ((QColor(255, 255, 255, 160), 1, Qt.SolidLine),
                                        (QColor(0, 0, 0, 200), 1, Qt.DashLine)):
                pen = QPen(color, width, style)
                pen.setCosmetic(True)
                p.setPen(pen)
                p.drawLine(full)

        # Anchor: white-haloed black crosshair ring.
        r = 6.0
        for color, width in ((QColor(255, 255, 255), 3), (QColor(0, 0, 0), 1.5)):
            pen = QPen(color, width)
            pen.setCosmetic(True)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(anchor, r, r)
            p.drawLine(QPointF(anchor.x() - r - 4, anchor.y()), QPointF(anchor.x() - r + 2, anchor.y()))
            p.drawLine(QPointF(anchor.x() + r - 2, anchor.y()), QPointF(anchor.x() + r + 4, anchor.y()))
            p.drawLine(QPointF(anchor.x(), anchor.y() - r - 4), QPointF(anchor.x(), anchor.y() - r + 2))
            p.drawLine(QPointF(anchor.x(), anchor.y() + r - 2), QPointF(anchor.x(), anchor.y() + r + 4))
        p.end()


# ---------------------------------------------------------------------------
# Extension + input interception
# ---------------------------------------------------------------------------

class _Filter(QObject):
    def __init__(self, ext):
        super().__init__()
        self.ext = ext

    def eventFilter(self, obj, event):
        try:
            return self.ext.filter_event(obj, event)
        except Exception as e:  # never let a bug eat the user's input
            print(f"[rebelsrule] {e!r}")
            self.ext.phase = IDLE
            return False


class RebelsRuleExtension(Extension):

    def __init__(self, parent):
        super().__init__(parent)
        self.enabled = False
        self.action = None
        self.filter = _Filter(self)
        self.overlays = {}        # id(canvas widget) -> RulerOverlay

        self.anchor_img = None    # QPointF in image coordinates
        self.phase = IDLE
        self.source_tablet = False
        self.widget = None        # canvas widget receiving the current stroke
        self.press = None         # _Snap of the buffered press
        self.origin = None        # QPointF widget coords (line origin)
        self.direction = None     # unit vector (dx, dy)
        self.sending = False

        # Keep the anchor marker glued to the art while panning/zooming/rotating.
        self._last_anchor_pos = None
        self.timer = QTimer()
        self.timer.setInterval(50)
        self.timer.timeout.connect(self._follow_canvas)

    def _follow_canvas(self):
        pos = self.anchor_widget_pos()
        key = None if pos is None else (round(pos.x(), 1), round(pos.y(), 1))
        if key != self._last_anchor_pos:
            self._last_anchor_pos = key
            self._update_overlays()

    def setup(self):
        pass

    def createActions(self, window):
        self.action = window.createAction(ACTION_ID, "Rebels Rule", "tools/scripts")
        self.action.setCheckable(True)
        self.action.toggled.connect(self.set_enabled)

    # ---- enable / disable ----

    def set_enabled(self, on):
        if on == self.enabled:
            return
        self.enabled = on
        app = QApplication.instance()
        if on:
            app.installEventFilter(self.filter)
            self.timer.start()
            self._message("Ruler on: tap to set anchor, drag to draw along it"
                          if self.anchor_img is None else "Ruler on")
        else:
            app.removeEventFilter(self.filter)
            self.timer.stop()
            self.phase = IDLE
            self._message("Ruler off")
        self._update_overlays()

    def _message(self, text):
        win = Krita.instance().activeWindow()
        view = win.activeView() if win else None
        if view is not None:
            try:
                view.showFloatingMessage(text, QIcon(), 1500, 1)
            except Exception:
                pass

    # ---- coordinates (widget <-> image, rotation/mirror aware) ----

    def _view(self):
        win = Krita.instance().activeWindow()
        return win.activeView() if win else None

    def _widget_to_image(self, pt):
        view = self._view()
        if view is None:
            return QPointF(pt)
        to_canvas, ok = view.flakeToCanvasTransform().inverted()
        return view.flakeToImageTransform().map(to_canvas.map(pt))

    def _image_to_widget(self, pt):
        view = self._view()
        if view is None:
            return QPointF(pt)
        to_flake, ok = view.flakeToImageTransform().inverted()
        return view.flakeToCanvasTransform().map(to_flake.map(pt))

    def anchor_widget_pos(self):
        if self.anchor_img is None:
            return None
        return self._image_to_widget(self.anchor_img)

    def active_line(self):
        if self.phase != STROKE or self.origin is None:
            return None
        o, (dx, dy) = self.origin, self.direction
        return (o, QPointF(o.x() + dx, o.y() + dy))

    def _project(self, pt):
        o, (dx, dy) = self.origin, self.direction
        t = (pt.x() - o.x()) * dx + (pt.y() - o.y()) * dy
        return QPointF(o.x() + t * dx, o.y() + t * dy)

    # ---- overlay management ----

    def _overlay_for(self, widget):
        ov = self.overlays.get(id(widget))
        if ov is None:
            ov = RulerOverlay(widget, self)
            self.overlays[id(widget)] = ov
            widget.destroyed.connect(lambda *_, k=id(widget): self.overlays.pop(k, None))
        return ov

    def _update_overlays(self, hover_widget=None, hover=None):
        for ov in list(self.overlays.values()):
            try:
                ov.setVisible(self.enabled)
                if hover_widget is not None and ov.parent() is hover_widget:
                    ov.hover = hover
                ov.update()
            except RuntimeError:  # underlying C++ widget already gone
                pass

    # ---- the interception state machine ----

    def _send(self, widget, event):
        self.sending = True
        try:
            QApplication.sendEvent(widget, event)
        finally:
            self.sending = False

    def filter_event(self, obj, ev):
        if self.sending or not self.enabled:
            return False
        t = ev.type()

        if t == QEvent.KeyPress and ev.key() == Qt.Key_Escape \
                and self.anchor_img is not None and self.phase == IDLE:
            self.anchor_img = None
            self._update_overlays()
            return False

        tablet = t in _TABLET_TYPES
        if not tablet and t not in _MOUSE_TYPES:
            return False
        if not _is_canvas(obj):
            return False

        # While a tablet gesture is in flight, swallow Qt's mouse fallbacks.
        if not tablet and self.phase != IDLE and self.source_tablet:
            ev.accept()
            return True
        if self.phase != IDLE and obj is not self.widget:
            return False

        pos = QPointF(ev.posF() if tablet else ev.localPos())
        is_press = t in (QEvent.TabletPress, QEvent.MouseButtonPress)
        is_release = t in (QEvent.TabletRelease, QEvent.MouseButtonRelease)

        if t == QEvent.MouseButtonDblClick:
            # Our tap already handled it; don't let Krita see a stray click.
            if self.phase == IDLE and not tablet:
                ev.accept()
                return True
            return False

        if self.phase == IDLE:
            if is_press:
                if ev.button() != Qt.LeftButton or ev.modifiers() != Qt.NoModifier:
                    return False
                self._overlay_for(obj)
                self.phase = PENDING
                self.source_tablet = tablet
                self.widget = obj
                self.press = _Snap(ev, tablet)
                ev.accept()
                return True
            # Hover: refresh the preview line.
            if self.anchor_img is not None:
                self._overlay_for(obj)
                self._update_overlays(obj, pos)
            return False

        if tablet != self.source_tablet:
            return False

        if self.phase == PASSTHRU:
            if is_release:
                self.phase = IDLE
            return False

        if self.phase == PENDING:
            if is_release:
                if _dist(pos, self.press.pos) < TAP_PX:
                    # Tap: (re)place the anchor; Krita never sees this click.
                    self.anchor_img = self._widget_to_image(self.press.pos)
                    self.phase = IDLE
                    self._update_overlays(obj, pos)
                    ev.accept()
                    return True
                # Fast flick that never produced a move: replay it unconstrained.
                self._send(obj, self.press.build(self.press.pos))
                self.phase = IDLE
                return False
            if is_press or _dist(pos, self.press.pos) < TAP_PX:
                ev.accept()
                return True

            # Movement past the tap threshold: this is a stroke.
            anchor = self.anchor_widget_pos()
            if anchor is None:
                self._send(obj, self.press.build(self.press.pos))
                self.phase = PASSTHRU
                return False
            through = self.press.pos if _dist(self.press.pos, anchor) > SAME_POINT_PX else pos
            dx, dy = through.x() - anchor.x(), through.y() - anchor.y()
            n = math.hypot(dx, dy) or 1.0
            self.origin = anchor
            self.direction = (dx / n, dy / n)
            self.phase = STROKE
            self._send(obj, self.press.build(self._project(self.press.pos)))
            # fall through to send this move

        if self.phase == STROKE:
            snap = _Snap(ev, tablet)
            self._send(obj, snap.build(self._project(pos)))
            if is_release:
                self.phase = IDLE
                self._update_overlays(obj, pos)
            elif t in (QEvent.TabletMove, QEvent.MouseMove):
                self._overlay_for(obj).update()
            ev.accept()
            return True

        return False
