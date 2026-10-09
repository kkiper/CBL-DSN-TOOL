"""Harness canvas: a node editor in the style of Splice CAD.

* Connectors are pin tables with a port per pin; splices are nodes.
* Drag from a pin (or splice) to another pin (or splice) to add a wire, using the "New wire" defaults.
* Drag parts from the library: a connector or splice part onto empty canvas adds one; a backshell, boot,
  label or contact onto a connector assigns it; a wire or cable part onto a wire assigns it.
* Select wires and right-click to group them (twisted pair, shielded...), to put a shield over them, or to put an
  overall shield over the whole bundle. Shields are drawn as dashed capsules across their wires next to each
  connector, overall shields a column further out; wires that aren't neighbours get one capsule per run,
  joined down the column (one shield).
* Right-click a connector to show its SHELL connection; right-click a shield to terminate it at each end
  (SHELL, a pin, or floating) or remove it. Delete removes the selection.
* Items with DRC errors are outlined red, warnings amber.
"""

from __future__ import annotations

import re

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QGraphicsItem,
    QGraphicsObject,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QMenu,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from cable_tool.drawing import _Row, _shield_columns, assign_sides
from cable_tool.drc import ERROR, WARNING
from cable_tool.edit import add_shield, remove_group, set_shield_term
from cable_tool.inserts import layout_for
from cable_tool.model import (
    SHIELD_BACKSHELL,
    SHIELD_FLOAT,
    CableDesign,
    ConnectorEnd,
    Splice,
    Wire,
    WireGroup,
    natural_key,
    parse_shield_term,
)

from .document import Document
from .tables import GROUP_KINDS, next_id

PART_MIME = "application/x-cable-part"
ROW_H, HEAD_H, CONN_W, PORT_R = 18.0, 40.0, 190.0, 4.5
WIRE_COLORS = {
    "WHT": "#c8c8c8", "WHITE": "#c8c8c8", "BLK": "#202020", "BLACK": "#202020", "RED": "#d62728", "BLU": "#1f5fd6",
    "BLUE": "#1f5fd6", "GRN": "#2ca02c", "GREEN": "#2ca02c", "YEL": "#e6b800", "YELLOW": "#e6b800", "ORN": "#ff7f0e",
    "ORANGE": "#ff7f0e", "BRN": "#8c564b", "BROWN": "#8c564b", "VIO": "#9467bd", "VIOLET": "#9467bd",
    "GRY": "#7f7f7f", "GRAY": "#7f7f7f", "PNK": "#e377c2", "PINK": "#e377c2",
}
SEVERITY_PEN = {ERROR: QColor("#d9534f"), WARNING: QColor("#e0a800")}
SHELL = "SHELL"                 # the connector shell / backshell connection (shield terminations only)
SHIELD_COLOR = QColor("#6a4c93")
FONT = QFont("Sans Serif", 9)
BOLD = QFont("Sans Serif", 10, QFont.Bold)


def wire_color(w: Wire) -> QColor:
    return QColor(WIRE_COLORS.get(w.color.strip().upper(), "#5a6470"))


def connector_pins(design: CableDesign, c: ConnectorEnd) -> list[str]:
    """Pins shown on the canvas, in the connector's row order (set by moving pins) where one is set."""
    pins = _default_pins(design, c)
    if c.pin_order:
        order = {p: i for i, p in enumerate(c.pin_order)}
        default = {p: i for i, p in enumerate(pins)}
        pins = sorted(pins, key=lambda p: (0, order[p]) if p in order else (1, default[p]))
    return pins


def _default_pins(design: CableDesign, c: ConnectorEnd) -> list[str]:
    """The connector's contact positions (from the insert layout or library) plus any used pins."""
    used = design.pins_used(c.ref)
    found = layout_for(c.connector_pn)
    if found:   # known insert arrangement: its contact labels, in catalogue order, then any stray pins
        known = [cav.contact for cav in found[1]]
        return known + [p for p in used if p not in known]
    part = design.library.get(c.connector_pn)
    n = int(part.contacts) if part and part.contacts else 0
    pins = list(used)
    if n and n <= 128 and all(re.fullmatch(r"\d+", p) for p in used):
        pins = [str(i) for i in range(1, n + 1)] + [p for p in used if not p.isdigit() or int(p) > n]
    elif not n:
        nums = [int(p) for p in used if p.isdigit()]
        letters = [p for p in used if re.fullmatch(r"[A-Z]", p)]
        if letters and not nums:
            last = max(letters)
            spare = [chr(ord(last) + k) for k in range(1, 4) if ord(last) + k <= ord("Z")]
        else:
            start = max(nums, default=0)
            spare = [str(start + k) for k in range(1, 4)]
        pins = used + [s for s in spare if s not in used]
    return sorted(dict.fromkeys(pins), key=natural_key)


class ConnectorItem(QGraphicsObject):
    moved = Signal(str, QPointF)

    def __init__(self, design: CableDesign, c: ConnectorEnd, side: int):
        super().__init__()
        self.ref, self.side = c.ref, side       # side +1: ports on the right, -1: ports on the left
        self.c = c
        self.pins = connector_pins(design, c)
        self.signals = {}
        for w in design.wires:
            for r, p in ((w.from_ref, w.from_pin), (w.to_ref, w.to_pin)):
                if r == c.ref:
                    self.signals.setdefault(p, w.signal)
        for g, p in design.shield_pins(c.ref):
            self.signals.setdefault(p, f"{g.group_id} SHIELD")
        self.used = set(design.pins_used(c.ref))
        self.shell = design.shell_shown(c.ref)
        self.shell_used = bool(design.shell_terminations(c.ref))
        self.severity: str | None = None
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable |
                      QGraphicsItem.ItemSendsGeometryChanges)
        self.setAcceptDrops(True)
        self.setZValue(2)
        self.drop_hint = False

    def rows(self) -> list[str]:
        """Port rows top to bottom: the pins, then SHELL when shown."""
        return self.pins + ([SHELL] if self.shell else [])

    def boundingRect(self):
        return QRectF(-PORT_R - 2, -2, CONN_W + 2 * PORT_R + 4, HEAD_H + ROW_H * max(len(self.rows()), 1) + 4)

    def port_pos(self, pin: str) -> QPointF:
        rows = self.rows()
        i = rows.index(pin) if pin in rows else 0
        x = CONN_W if self.side == 1 else 0.0
        return self.mapToScene(QPointF(x, HEAD_H + (i + 0.5) * ROW_H))

    def pin_at(self, scene_pos: QPointF, tolerance: float = 9.0) -> str | None:
        p = self.mapFromScene(scene_pos)
        x = CONN_W if self.side == 1 else 0.0
        for i, pin in enumerate(self.rows()):
            y = HEAD_H + (i + 0.5) * ROW_H
            if abs(p.x() - x) <= tolerance and abs(p.y() - y) <= ROW_H / 2:
                return pin
        return None

    def paint(self, p: QPainter, option, widget=None):
        h = HEAD_H + ROW_H * max(len(self.rows()), 1)
        border = QColor("#2b6cb0") if self.isSelected() else SEVERITY_PEN.get(self.severity, QColor("#3a3f44"))
        p.setPen(QPen(border, 2.2 if self.isSelected() or self.severity else 1.2))
        p.setBrush(QColor("#eaf2fb") if self.drop_hint else QColor("#ffffff"))
        p.drawRoundedRect(QRectF(0, 0, CONN_W, h), 5, 5)
        p.fillRect(QRectF(1, 1, CONN_W - 2, HEAD_H - 1), QColor("#e9edf2"))
        p.setPen(QColor("#1d232a"))
        p.setFont(BOLD)
        p.drawText(QRectF(8, 2, CONN_W - 16, 18), Qt.AlignLeft | Qt.AlignVCenter, self.c.ref)
        p.setFont(FONT)
        p.setPen(QColor("#4a5560"))
        p.drawText(QRectF(60, 2, CONN_W - 68, 18), Qt.AlignRight | Qt.AlignVCenter, self.c.connector_pn or "(no P/N)")
        p.drawText(QRectF(8, 19, CONN_W - 16, 18), Qt.AlignLeft | Qt.AlignVCenter,
                   QFontMetricsF(FONT).elidedText(self.c.description or "", Qt.ElideRight, CONN_W - 16))
        for i, pin in enumerate(self.pins):
            y = HEAD_H + i * ROW_H
            p.setPen(QPen(QColor("#d5dbe1"), 1))
            p.drawLine(QPointF(0, y), QPointF(CONN_W, y))
            used = pin in self.used
            p.setPen(QColor("#1d232a") if used else QColor("#9aa3ab"))
            pin_rect = QRectF(4, y, 34, ROW_H) if self.side == -1 else QRectF(CONN_W - 38, y, 34, ROW_H)
            sig_rect = QRectF(42, y, CONN_W - 84, ROW_H) if self.side == -1 else QRectF(8, y, CONN_W - 50, ROW_H)
            p.setFont(BOLD if used else FONT)
            p.drawText(pin_rect, Qt.AlignCenter, pin)
            p.setFont(FONT)
            p.drawText(sig_rect, Qt.AlignVCenter | (Qt.AlignLeft if self.side == -1 else Qt.AlignLeft),
                       QFontMetricsF(FONT).elidedText(self.signals.get(pin, ""), Qt.ElideRight, sig_rect.width()))
            x = CONN_W if self.side == 1 else 0
            p.setPen(QPen(QColor("#3a3f44"), 1.2))
            p.setBrush(QColor("#2b6cb0") if used else QColor("#ffffff"))
            p.drawEllipse(QPointF(x, y + ROW_H / 2), PORT_R, PORT_R)
        if self.shell:
            y = HEAD_H + len(self.pins) * ROW_H
            p.fillRect(QRectF(1, y, CONN_W - 2, ROW_H - 1), QColor("#efe9f6"))
            p.setPen(QPen(QColor("#d5dbe1"), 1))
            p.drawLine(QPointF(0, y), QPointF(CONN_W, y))
            p.setPen(SHIELD_COLOR)
            p.setFont(BOLD if self.shell_used else FONT)
            text_rect = QRectF(8, y, CONN_W - 50, ROW_H) if self.side == 1 else QRectF(42, y, CONN_W - 50, ROW_H)
            p.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, "SHELL")
            x = CONN_W if self.side == 1 else 0
            gx = x - self.side * 22
            for k, half in enumerate((6, 4, 2)):        # ground symbol
                p.drawLine(QPointF(gx + self.side * k * 3, y + ROW_H / 2 - half),
                           QPointF(gx + self.side * k * 3, y + ROW_H / 2 + half))
            p.setPen(QPen(SHIELD_COLOR, 1.2))
            p.setBrush(SHIELD_COLOR if self.shell_used else QColor("#ffffff"))
            p.drawRect(QRectF(x - PORT_R, y + ROW_H / 2 - PORT_R, 2 * PORT_R, 2 * PORT_R))

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged and self.scene():
            self.scene().item_moved(self)
        return super().itemChange(change, value)

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        self.moved.emit(self.ref, self.pos())


class SpliceItem(QGraphicsObject):
    moved = Signal(str, QPointF)
    R = 9.0

    def __init__(self, sp: Splice):
        super().__init__()
        self.ref, self.sp = sp.ref, sp
        self.severity: str | None = None
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable |
                      QGraphicsItem.ItemSendsGeometryChanges)
        self.setZValue(3)

    def boundingRect(self):
        return QRectF(-60, -30, 120, 60)

    def shape(self):
        path = QPainterPath()
        path.addEllipse(QPointF(0, 0), self.R + 3, self.R + 3)
        return path

    def port_pos(self, _pin: str = "") -> QPointF:
        return self.scenePos()

    def paint(self, p: QPainter, option, widget=None):
        border = QColor("#2b6cb0") if self.isSelected() else SEVERITY_PEN.get(self.severity, QColor("#1d232a"))
        p.setPen(QPen(border, 2))
        p.setBrush(QColor("#1d232a"))
        p.drawEllipse(QPointF(0, 0), self.R * 0.7, self.R * 0.7)
        p.setFont(BOLD)
        p.setPen(QColor("#1d232a"))
        p.drawText(QRectF(-60, -30, 120, 18), Qt.AlignCenter, self.ref)
        p.setFont(FONT)
        p.setPen(QColor("#4a5560"))
        p.drawText(QRectF(-60, 12, 120, 16), Qt.AlignCenter, self.sp.splice_pn or "")

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged and self.scene():
            self.scene().item_moved(self)
        return super().itemChange(change, value)

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        self.moved.emit(self.ref, self.pos())


class WireItem(QGraphicsPathItem):
    def __init__(self, w: Wire, group: WireGroup | None):
        super().__init__()
        self.wire, self.group = w, group
        self.wire_id = w.wire_id
        self.severity: str | None = None
        self.setFlags(QGraphicsItem.ItemIsSelectable)
        self.setAcceptDrops(True)
        self.setZValue(1)
        tip = f"{w.wire_id}  {w.gauge + ' AWG ' if w.gauge else ''}{w.color}  {w.wire_pn}\n{w.signal}"
        if group:
            tip += f"\nGroup {group.group_id}: {group.kind.title()}"
        self.setToolTip(tip.strip())
        self.label = None

    def route(self, a: QPointF, b: QPointF, da: int, db: int):
        path = QPainterPath(a)
        k = max(60.0, abs(b.x() - a.x()) * 0.45)
        path.cubicTo(QPointF(a.x() + da * k, a.y()), QPointF(b.x() + db * k, b.y()), b)
        self.setPath(path)
        self.restyle()

    def restyle(self):
        col = wire_color(self.wire)
        width = 3.2 if self.isSelected() else 2.0
        if self.severity:
            col = SEVERITY_PEN[self.severity]
        pen = QPen(col, width)
        if self.group and self.group.twisted:       # shields are drawn as ovals (ShieldItem)
            pen.setStyle(Qt.DashDotLine)
        pen.setCapStyle(Qt.RoundCap)
        self.setPen(pen)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemSelectedHasChanged:
            self.restyle()
        return super().itemChange(change, value)

    def shape(self):
        from PySide6.QtGui import QPainterPathStroker

        s = QPainterPathStroker()
        s.setWidth(10)
        return s.createStroke(self.path())


class ShieldItem(QGraphicsPathItem):
    """A shield drawn as on a wiring diagram (IPC/WHMA-A-620 figures): a dashed capsule across its wires next to
    each connector it reaches. Inner shields sit nearest the connector and each enclosing (overall) shield a column
    further out, so capsules never overlap. A shield over wires that aren't neighbours has one capsule per run,
    joined down its column. The drain leaves the bottom of the capsule and runs along its column, then straight
    into its termination: the SHELL port or a pin. A floating end gets a short insulated stub."""

    W = 12.0            # capsule width
    COL0, COL_STEP = 34.0, 22.0

    def __init__(self, group: WireGroup, level: int):
        super().__init__()
        self.group, self.level = group, level
        self.gid = group.group_id
        self.setFlags(QGraphicsItem.ItemIsSelectable)
        self.setZValue(1.5)
        self.labels: list = []
        self.setToolTip(f"{self.gid}: {group.kind.title()}  (right-click to terminate or remove)")

    def layout(self, scene: "HarnessScene"):
        d = scene.doc.design
        members = {w.wire_id for w in d.group_members(self.gid)}
        path = QPainterPath()
        for lab in self.labels:
            scene.removeItem(lab)
        self.labels = []
        grow = 2.0 * self.level
        for ref in d.group_refs(self.gid):
            conn = scene.connectors.get(ref)
            if conn is None:
                continue
            pts: dict[str, QPointF] = {}
            for w in d.wires:
                if w.wire_id in members:
                    for r, pin in ((w.from_ref, w.from_pin), (w.to_ref, w.to_pin)):
                        if r == ref and pin in conn.pins:
                            pts.setdefault(pin, conn.port_pos(pin))
            if not pts:
                continue
            out = conn.side
            col = scene.shield_cols.get(ref, {}).get(self.gid, self.level)
            x = conn.port_pos(conn.pins[0]).x() + out * (self.COL0 + self.COL_STEP * col)
            spans = []
            for run in self._runs(conn, pts, d, members):
                ys = [pts[p].y() for p in run]
                top, bot = min(ys) - 8 - grow, max(ys) + 8 + grow
                path.addRoundedRect(QRectF(x - self.W / 2, top, self.W, bot - top), self.W / 2, self.W / 2)
                spans.append((top, bot))
            for (_t1, b1), (t2, _b2) in zip(spans, spans[1:]):     # one shield: join its capsules
                path.moveTo(x, b1)
                path.lineTo(x, t2)
            top, bot = spans[0][0], spans[-1][1]
            kind, pin = parse_shield_term(d.shield_term_at(self.group, ref), ref)
            target = None
            if kind == SHIELD_BACKSHELL and conn.shell:
                target = conn.port_pos(SHELL)
            elif kind == "PIN" and pin in conn.pins:
                target = conn.port_pos(pin)
            if target is not None:
                start = bot if target.y() >= (top + bot) / 2 else top
                path.moveTo(x, start)
                path.lineTo(x, target.y())
                path.lineTo(target.x() + out * PORT_R, target.y())
            elif kind == SHIELD_FLOAT:
                path.moveTo(x, bot)
                path.lineTo(x, bot + 7)
                path.moveTo(x - 5, bot + 7)
                path.lineTo(x + 5, bot + 7)
            text = self.gid + ("" if kind else " ?")
            lab = scene.addSimpleText(text, FONT)
            lab.setBrush(SHIELD_COLOR)
            lab.setZValue(1.6)
            lab.setPos(x - lab.boundingRect().width() / 2, top - 16)
            self.labels.append(lab)
        self.setPath(path)
        self.restyle()

    @staticmethod
    def _runs(conn: "ConnectorItem", pts: dict, d: CableDesign, members: set[str]) -> list[list[str]]:
        """Member pins in the connector's row order, split where a row carrying another wire lies between."""
        order = [p for p in conn.pins if p in pts] + [p for p in pts if p not in conn.pins]
        idx = {p: i for i, p in enumerate(conn.pins)}
        others = {p for w in d.wires if w.wire_id not in members
                  for r, p in ((w.from_ref, w.from_pin), (w.to_ref, w.to_pin)) if r == conn.ref}
        runs: list[list[str]] = []
        prev = None
        for p in order:
            between = conn.pins[idx[prev] + 1:idx[p]] if prev in idx and p in idx else []
            if prev is None or any(b in others for b in between):
                runs.append([])
            runs[-1].append(p)
            prev = p
        return runs

    def paint(self, painter, option, widget=None):
        from PySide6.QtWidgets import QStyle

        option.state &= ~QStyle.State_Selected        # selection shows as a heavier pen, not a bounding box
        super().paint(painter, option, widget)

    def restyle(self):
        pen = QPen(QColor("#2b6cb0") if self.isSelected() else SHIELD_COLOR, 2.2 if self.isSelected() else 1.4)
        pen.setStyle(Qt.DashLine)
        self.setPen(pen)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemSelectedHasChanged:
            self.restyle()
        return super().itemChange(change, value)

    def shape(self):
        from PySide6.QtGui import QPainterPathStroker

        s = QPainterPathStroker()
        s.setWidth(8)
        return s.createStroke(self.path())


class HarnessScene(QGraphicsScene):
    def __init__(self, doc: Document, view_state: "CanvasView"):
        super().__init__(view_state)
        self.doc = doc
        self.owner = view_state
        self.connectors: dict[str, ConnectorItem] = {}
        self.splices: dict[str, SpliceItem] = {}
        self.wires: list[WireItem] = []
        self.shields: dict[str, ShieldItem] = {}
        self.shield_cols: dict[str, dict[str, int]] = {}
        self.dragging = None        # (item, pin, start QPointF)
        self.rubber = None
        self._building = False
        self.setBackgroundBrush(QColor("#f4f6f8"))

    # --- build -----------------------------------------------------------------------------------
    def rebuild(self, severities: dict[tuple[str, str], str] | None = None):
        self._building = True
        selected = {(type(i).__name__, getattr(i, "ref", getattr(i, "wire_id", getattr(i, "gid", ""))))
                    for i in self.selectedItems()}
        self.clear()
        self.connectors, self.splices, self.wires, self.shields = {}, {}, [], {}
        d = self.doc.design
        positions = auto_positions(d)
        left, right = assign_sides(d)
        side = {c.ref: 1 for c in left} | {c.ref: -1 for c in right}
        for c in d.connectors:
            item = ConnectorItem(d, c, side.get(c.ref, 1))
            item.setPos(QPointF(*d.layout.get(c.ref, positions.get(c.ref, (0, 0)))))
            item.moved.connect(self._commit_move)
            self.addItem(item)
            self.connectors[c.ref] = item
        used_splices = {r for w in d.wires for r in (w.from_ref, w.to_ref) if d.splice(r)}
        for sp in d.splices:
            if sp.ref not in used_splices and sp.ref not in d.layout:
                continue
            item = SpliceItem(sp)
            item.setPos(QPointF(*d.layout.get(sp.ref, positions.get(sp.ref, (0, 0)))))
            item.moved.connect(self._commit_move)
            self.addItem(item)
            self.splices[sp.ref] = item
        for w in d.wires:
            item = WireItem(w, d.group(w.group) if w.group else None)
            self.addItem(item)
            self.wires.append(item)
        for g in d.groups:
            if g.shielded and d.group_members(g.group_id):
                item = ShieldItem(g, d.group_level(g.group_id))
                self.addItem(item)
                self.shields[g.group_id] = item
        self.apply_severities(severities or {})
        self.reroute()
        for it in self.items():
            key = (type(it).__name__, getattr(it, "ref", getattr(it, "wire_id", getattr(it, "gid", ""))))
            if key in selected:
                it.setSelected(True)
        self._building = False

    def _end(self, ref: str, pin: str):
        if ref in self.connectors:
            c = self.connectors[ref]
            return c.port_pos(pin), c.side
        if ref in self.splices:
            return self.splices[ref].port_pos(), 0
        return None, 0

    def reroute(self):
        for item in self.wires:
            w = item.wire
            a, da = self._end(w.from_ref, w.from_pin)
            b, db = self._end(w.to_ref, w.to_pin)
            if a is None or b is None:
                item.setVisible(False)
                continue
            if da == 0:
                da = 1 if b.x() > a.x() else -1
            if db == 0:
                db = 1 if a.x() > b.x() else -1
            item.route(a, b, da, db)
        d = self.doc.design
        self.shield_cols = {}
        for ref, conn in self.connectors.items():
            rows = []
            for pin in conn.pins:
                wire = next((w for w in d.wires if (w.from_ref, w.from_pin) == (ref, pin)
                             or (w.to_ref, w.to_pin) == (ref, pin)), None)
                drain = next((g.group_id for g, p in d.shield_pins(ref) if p == pin), "")
                rows.append(_Row(pin, "", wire, shield_of=drain if wire is None else ""))
            if conn.shell:          # leads to the SHELL port run down their column to the bottom row
                rows += [_Row(SHELL, "", None, shield_of=g.group_id, shell=True) for g in d.shell_terminations(ref)]
            self.shield_cols[ref] = _shield_columns(d, ref, rows)
        for shield in self.shields.values():
            shield.layout(self)

    def item_moved(self, _item):
        if not self._building:
            self.reroute()

    def _commit_move(self, ref: str, pos: QPointF):
        xy = (round(pos.x(), 1), round(pos.y(), 1))
        if self.doc.design.layout.get(ref) != xy:
            self.doc.edit(f"Move {ref}", lambda d: d.layout.__setitem__(ref, xy))

    def apply_severities(self, sev: dict[tuple[str, str], str]):
        for ref, item in self.connectors.items():
            item.severity = sev.get(("connector", ref))
            item.update()
        for ref, item in self.splices.items():
            item.severity = sev.get(("splice", ref))
            item.update()
        for item in self.wires:
            item.severity = sev.get(("wire", item.wire_id))
            item.restyle()

    # --- wiring by drag --------------------------------------------------------------------------
    def _port_under(self, pos: QPointF):
        for it in self.items(pos):
            if isinstance(it, ConnectorItem):
                pin = it.pin_at(pos)
                if pin:
                    return it, pin
            if isinstance(it, SpliceItem):
                return it, ""
        for c in self.connectors.values():          # ports stick out of the box: check them directly
            pin = c.pin_at(pos)
            if pin:
                return c, pin
        return None

    def mousePressEvent(self, e):
        hit = self._port_under(e.scenePos())
        if hit and hit[1] == SHELL:
            hit = None          # the SHELL port takes shield terminations (right-click a shield), not wires
        if hit and e.button() == Qt.LeftButton and (isinstance(hit[0], ConnectorItem) or e.modifiers() & Qt.ShiftModifier):
            item, pin = hit
            start = item.port_pos(pin)
            self.dragging = (item, pin, start)
            self.rubber = self.addPath(QPainterPath(start), QPen(QColor("#2b6cb0"), 2, Qt.DashLine))
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self.dragging:
            _, _, start = self.dragging
            path = QPainterPath(start)
            path.lineTo(e.scenePos())
            self.rubber.setPath(path)
            e.accept()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self.dragging:
            src, src_pin, _ = self.dragging
            self.removeItem(self.rubber)
            self.dragging, self.rubber = None, None
            hit = self._port_under(e.scenePos())
            if hit and hit[1] != SHELL and not (hit[0] is src and hit[1] == src_pin):
                self.owner.add_wire(src.ref, src_pin, hit[0].ref, hit[1])
            e.accept()
            return
        super().mouseReleaseEvent(e)

    # --- drops from the library --------------------------------------------------------------------
    def dragEnterEvent(self, e):
        e.setAccepted(e.mimeData().hasFormat(PART_MIME))

    def dragMoveEvent(self, e):
        e.setAccepted(e.mimeData().hasFormat(PART_MIME))

    def dropEvent(self, e):
        if not e.mimeData().hasFormat(PART_MIME):
            return
        pn = bytes(e.mimeData().data(PART_MIME)).decode("utf-8")
        self.owner.drop_part(pn, e.scenePos(), [it for it in self.items(e.scenePos())])
        e.acceptProposedAction()

    def contextMenuEvent(self, e):
        under = self.items(e.scenePos())
        conn = next((i for i in under if isinstance(i, ConnectorItem)), None)
        shield = next((i for i in under if isinstance(i, ShieldItem)), None)
        if shield is None:
            shield = next((s for s in self.shields.values() if s.shape().contains(e.scenePos())), None)
        wires = [i.wire_id for i in self.selectedItems() if isinstance(i, WireItem)]
        menu = QMenu()
        if conn is not None:
            ref = conn.ref
            act = menu.addAction(f"Show {ref} Shell connection")
            act.setCheckable(True)
            act.setChecked(conn.shell)
            if conn.shell_used:
                act.setEnabled(False)
                act.setToolTip("A shield is terminated to this shell")
            act.toggled.connect(lambda on, r=ref: self.owner.set_show_shell(r, on))
            pin = conn.pin_at(e.scenePos(), tolerance=CONN_W) if conn.pin_at(e.scenePos(), tolerance=CONN_W) != SHELL else None
            if pin:
                menu.addAction(f"Move pin {pin} up", lambda r=ref, p=pin: self.owner.move_pin(r, p, -1))
                menu.addAction(f"Move pin {pin} down", lambda r=ref, p=pin: self.owner.move_pin(r, p, 1))
            menu.addAction(f"Arrange {ref} pins: keep each shield's wires together",
                           lambda r=ref: self.owner.arrange_pins(r))
            menu.addSeparator()
        if shield is not None:
            gid = shield.gid
            d = self.doc.design
            for ref in d.group_refs(gid):
                if ref not in self.connectors:
                    continue
                c_item = self.connectors[ref]
                sub = menu.addMenu(f"Terminate {gid} at {ref}")
                sub.addAction("Shell (shield to " + d.shell_name(ref).lower() + ")",
                              lambda r=ref: self.owner.terminate_shield(gid, r, SHELL))
                sub.addAction("Float (insulate the shield end)", lambda r=ref: self.owner.terminate_shield(gid, r, SHIELD_FLOAT))
                pins = sub.addMenu("Pin")
                for p in c_item.pins[:128]:
                    pins.addAction(p + ("" if p not in c_item.used else "  (in use)"),
                                   lambda r=ref, p=p: self.owner.terminate_shield(gid, r, f"{r}-{p}"))
            menu.addAction(f"Remove shield {gid}", lambda: self.owner.remove_shield(gid))
            menu.addSeparator()
        if wires:
            menu.addAction(f"Add shield over {len(wires)} selected wire(s)", lambda: self.owner.shield_wires(wires))
            sub = menu.addMenu(f"Group {len(wires)} wire(s) as")
            for kind in GROUP_KINDS:
                sub.addAction(kind.title(), lambda k=kind: self.owner.group_wires(wires, k))
            menu.addAction("Remove from group", lambda: self.owner.group_wires(wires, None))
        if self.doc.design.wires:
            menu.addAction("Add overall shield over the entire bundle",
                           lambda: self.owner.shield_wires([w.wire_id for w in self.doc.design.wires]))
        menu.addAction("Add connector here", lambda: self.owner.add_connector(e.scenePos()))
        menu.addAction("Add splice here", lambda: self.owner.add_splice(e.scenePos()))
        if self.selectedItems():
            menu.addSeparator()
            menu.addAction("Delete selected", self.owner.delete_selected)
        menu.exec(e.screenPos())


def auto_positions(design: CableDesign, gap: float = 40.0, spread: float = 640.0) -> dict[str, tuple[float, float]]:
    """Default layout: connectors in two columns (as on the wiring diagram), splices between them."""
    pos: dict[str, tuple[float, float]] = {}
    left, right = assign_sides(design)
    for col, x in ((left, 0.0), (right, spread)):
        y = 0.0
        for c in col:
            pos[c.ref] = (x, y)
            y += HEAD_H + ROW_H * max(len(connector_pins(design, c)), 1) + gap
    for sp in design.splices:
        ys = []
        for w in design.wires:
            for this, other, other_pin in ((w.from_ref, w.to_ref, w.to_pin), (w.to_ref, w.from_ref, w.from_pin)):
                if this == sp.ref and other in pos:
                    c = design.connector(other)
                    pins = connector_pins(design, c)
                    ys.append(pos[other][1] + HEAD_H + (pins.index(other_pin) + 0.5 if other_pin in pins else 0) * ROW_H)
        pos[sp.ref] = ((spread + CONN_W) / 2, sum(ys) / len(ys) if ys else 0.0)
    return pos


class _View(QGraphicsView):
    def __init__(self, scene):
        super().__init__(scene)
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setAcceptDrops(True)

    def wheelEvent(self, e):
        f = 1.15 if e.angleDelta().y() > 0 else 1 / 1.15
        self.scale(f, f)


class CanvasView(QWidget):
    """Canvas plus its toolbar (add connector/splice, auto layout, new-wire defaults)."""

    def __init__(self, doc: Document):
        super().__init__()
        self.doc = doc
        self.scene = HarnessScene(doc, self)
        self.view = _View(self.scene)
        self.severities: dict[tuple[str, str], str] = {}
        self.wire_pn = QComboBox()
        self.wire_pn.setEditable(True)
        self.wire_pn.setMinimumWidth(170)
        self.wire_pn.setToolTip("Wire P/N for new wires (gauge and color come from the parts library)")
        self.wire_color = QComboBox()
        self.wire_color.setEditable(True)
        self.wire_color.addItems(["", "WHT", "BLK", "RED", "BLU", "GRN", "YEL", "ORN", "BRN", "VIO", "GRY"])
        self.wire_color.setToolTip("Color for new wires (if the P/N doesn't define one)")
        bar = QHBoxLayout()
        for text, fn in (("+ Connector", lambda: self.add_connector(None)), ("+ Splice", lambda: self.add_splice(None)),
                         ("Auto layout", self.auto_layout), ("Fit", self.fit)):
            b = QToolButton(text=text)
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addSpacing(16)
        bar.addWidget(QLabel("New wire:"))
        bar.addWidget(self.wire_pn)
        bar.addWidget(self.wire_color)
        hint = QLabel("Drag from pin to pin to wire. Drag parts from the library onto the canvas, a connector or a wire.")
        hint.setStyleSheet("color: palette(mid);")
        bar.addWidget(hint, 1)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(bar)
        lay.addWidget(self.view)
        delete = QAction(self)
        delete.setShortcut(Qt.Key_Delete)
        delete.setShortcutContext(Qt.WidgetWithChildrenShortcut)
        delete.triggered.connect(self.delete_selected)
        self.addAction(delete)
        doc.changed.connect(self.refresh)
        doc.selection_requested.connect(self.highlight)
        self.scene.selectionChanged.connect(self._selection_changed)
        self._fitted = False
        self.refresh()

    # --- refresh -----------------------------------------------------------------------------------
    def refresh(self):
        current = self.wire_pn.currentText()
        self.wire_pn.blockSignals(True)
        self.wire_pn.clear()
        wires = [p.pn for p in self.doc.design.library.parts.values() if p.type in ("wire", "")]
        self.wire_pn.addItems([""] + sorted(set(wires) | {w.wire_pn for w in self.doc.design.wires if w.wire_pn}))
        self.wire_pn.setCurrentText(current)
        self.wire_pn.blockSignals(False)
        self.scene.rebuild(self.severities)
        if not self._fitted and self.scene.connectors:
            self._fitted = True
            self.fit()

    def set_analysis(self, analyzer):
        sev: dict[tuple[str, str], str] = {}
        from .panels import _item_kind

        for f in analyzer.report.findings:
            if f.severity not in (ERROR, WARNING) or f.rule in ("Drawing format", "Completeness"):
                continue
            target = _item_kind(self.doc.design, f.item)
            if target and sev.get(target) != ERROR:
                sev[target] = f.severity
        self.severities = sev
        self.scene.apply_severities(sev)

    def fit(self):
        rect = self.scene.itemsBoundingRect().adjusted(-40, -40, 40, 40)
        if rect.isValid():
            self.view.fitInView(rect, Qt.KeepAspectRatio)

    def _selection_changed(self):
        try:
            if self.scene._building:
                return
            items = self.scene.selectedItems()
        except RuntimeError:        # scene is being destroyed with the window
            return
        if len(items) == 1:
            it = items[0]
            if isinstance(it, ConnectorItem):
                self.doc.select("connector", it.ref)
            elif isinstance(it, SpliceItem):
                self.doc.select("splice", it.ref)
            elif isinstance(it, WireItem):
                self.doc.select("wire", it.wire_id)
            elif isinstance(it, ShieldItem):
                self.doc.select("group", it.gid)

    def highlight(self, kind: str, key: str):
        target = None
        if kind == "connector":
            target = self.scene.connectors.get(key)
        elif kind == "splice":
            target = self.scene.splices.get(key)
        elif kind == "wire":
            target = next((w for w in self.scene.wires if w.wire_id == key), None)
        elif kind == "group":
            target = self.scene.shields.get(key)
        if target and not target.isSelected():
            self.scene.blockSignals(True)
            self.scene.clearSelection()
            target.setSelected(True)
            self.scene.blockSignals(False)
            self.view.ensureVisible(target)

    # --- editing actions ----------------------------------------------------------------------------
    def _wire_defaults(self) -> dict:
        pn = self.wire_pn.currentText().strip()
        part = self.doc.design.library.get(pn)
        gauge = f"{part.awg:g}" if part and part.awg is not None else ""
        color = (part.color if part and part.color else "") or self.wire_color.currentText().strip()
        return {"wire_pn": pn, "gauge": gauge, "color": color}

    def add_wire(self, ref_a: str, pin_a: str, ref_b: str, pin_b: str):
        defaults = self._wire_defaults()

        def apply(d: CableDesign):
            wid = next_id([w.wire_id for w in d.wires], "W")
            d.wires.append(Wire(wid, ref_a, pin_a, ref_b, pin_b, **defaults))
            return wid
        wid = self.doc.edit(f"Wire {ref_a}-{pin_a} to {ref_b}-{pin_b}", apply)
        self.doc.select("wire", wid)

    def add_connector(self, pos: QPointF | None, pn: str = ""):
        pos = pos or self.view.mapToScene(self.view.viewport().rect().center())

        def apply(d: CableDesign):
            ref = next_id([c.ref for c in d.connectors], "P")
            d.connectors.append(ConnectorEnd(ref, connector_pn=pn))
            d.layout[ref] = (round(pos.x(), 1), round(pos.y(), 1))
            return ref
        ref = self.doc.edit("Add connector", apply)
        self.doc.select("connector", ref)

    def add_splice(self, pos: QPointF | None, pn: str = ""):
        pos = pos or self.view.mapToScene(self.view.viewport().rect().center())

        def apply(d: CableDesign):
            ref = next_id([s.ref for s in d.splices], "SP")
            d.splices.append(Splice(ref, splice_pn=pn))
            d.layout[ref] = (round(pos.x(), 1), round(pos.y(), 1))
            return ref
        ref = self.doc.edit("Add splice", apply)
        self.doc.select("splice", ref)

    def drop_part(self, pn: str, pos: QPointF, items: list):
        d = self.doc.design
        part = d.library.get(pn)
        t = part.type if part else ""
        conn = next((i for i in items if isinstance(i, ConnectorItem)), None)
        wire = next((i for i in items if isinstance(i, WireItem)), None)
        slot = {"backshell": "backshell_pn", "heatshrink": "heatshrink_pn", "label": "label_pn",
                "contact": "contact_pn", "connector": "connector_pn"}.get(t)
        if conn and slot:
            ref = conn.ref
            self.doc.edit(f"{pn} on {ref}", lambda dd: setattr(dd.connector(ref), slot, pn))
        elif wire and t in ("wire", "marker", "heatshrink", "cable"):
            wid = wire.wire_id

            def apply(dd: CableDesign):
                w = next(x for x in dd.wires if x.wire_id == wid)
                if t == "wire":
                    w.wire_pn = pn
                    if part.awg is not None:
                        w.gauge = f"{part.awg:g}"
                    if part.color:
                        w.color = part.color
                elif t == "marker":
                    w.label_pn = pn
                elif t == "heatshrink":
                    w.heatshrink_pn = pn
                elif t == "cable":
                    gid = w.group or next_id([g.group_id for g in dd.groups], "C")
                    w.group = gid
                    g = dd.group(gid)
                    if g is None:
                        dd.groups.append(WireGroup(gid, "JACKETED CABLE", cable_pn=pn))
                    else:
                        g.cable_pn = pn
            self.doc.edit(f"{pn} on {wid}", apply)
        elif t == "connector" or (not t and not wire):
            self.add_connector(pos, pn)
        elif t == "splice":
            self.add_splice(pos, pn)
        elif t == "wire":
            self.wire_pn.setCurrentText(pn)

    # --- shields, shell and pin order -------------------------------------------------------------------
    def set_show_shell(self, ref: str, on: bool):
        if self.doc.design.connector(ref) and self.doc.design.connector(ref).show_shell != on:
            self.doc.edit(f"{'Show' if on else 'Hide'} {ref} shell", lambda d: setattr(d.connector(ref), "show_shell", on))

    def shield_wires(self, wire_ids: list[str]):
        gid = self.doc.edit("Add shield", lambda d: add_shield(d, wire_ids))
        self.doc.select("group", gid)
        return gid

    def terminate_shield(self, gid: str, ref: str, value: str):
        self.doc.edit(f"Terminate {gid} at {ref}", lambda d: set_shield_term(d, gid, ref, value))

    def remove_shield(self, gid: str):
        self.doc.edit(f"Remove shield {gid}", lambda d: remove_group(d, gid))

    def move_pin(self, ref: str, pin: str, step: int):
        item = self.scene.connectors.get(ref)
        if item is None or pin not in item.pins:
            return
        order = list(item.pins)
        i = order.index(pin)
        j = min(max(i + step, 0), len(order) - 1)
        if i == j:
            return
        order[i], order[j] = order[j], order[i]
        self.doc.edit(f"Move {ref}-{pin}", lambda d: setattr(d.connector(ref), "pin_order", order))

    def arrange_pins(self, ref: str):
        item = self.scene.connectors.get(ref)
        if item is None:
            return
        order = self.doc.design.arranged_pins(ref, list(item.pins))
        if order != item.pins:
            self.doc.edit(f"Arrange {ref} pins", lambda d: setattr(d.connector(ref), "pin_order", order))

    def group_wires(self, wire_ids: list[str], kind: str | None):
        def apply(d: CableDesign):
            if kind is None:
                for w in d.wires:
                    if w.wire_id in wire_ids:
                        w.group = ""
                return
            prefix = "TSP" if "SHIELDED TWISTED" in kind else "TP" if "TWISTED" in kind else "S" if "SHIELD" in kind else "C"
            gid = next_id([g.group_id for g in d.groups], prefix)
            d.groups.append(WireGroup(gid, kind, term_from="BACKSHELL" if "SHIELD" in kind else "",
                                      term_to="FLOAT" if "SHIELD" in kind else ""))
            for w in d.wires:
                if w.wire_id in wire_ids:
                    w.group = gid
        self.doc.edit("Group wires" if kind else "Ungroup wires", apply)

    def delete_selected(self):
        items = self.scene.selectedItems()
        wires = {i.wire_id for i in items if isinstance(i, WireItem)}
        conns = {i.ref for i in items if isinstance(i, ConnectorItem)}
        splices = {i.ref for i in items if isinstance(i, SpliceItem)}
        shields = {i.gid for i in items if isinstance(i, ShieldItem)}
        if not (wires or conns or splices or shields):
            return

        def apply(d: CableDesign):
            for gid in shields:
                remove_group(d, gid)
            d.wires = [w for w in d.wires if w.wire_id not in wires and not ({w.from_ref, w.to_ref} & (conns | splices))]
            d.connectors = [c for c in d.connectors if c.ref not in conns]
            d.splices = [s for s in d.splices if s.ref not in splices]
            for r in conns | splices:
                d.layout.pop(r, None)
        self.doc.edit("Delete", apply)

    def auto_layout(self):
        pos = auto_positions(self.doc.design)
        self.doc.edit("Auto layout", lambda d: d.layout.update(pos))
        self.fit()


__all__ = ["CanvasView", "PART_MIME", "auto_positions", "connector_pins"]
