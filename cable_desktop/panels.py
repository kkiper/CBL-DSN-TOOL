"""Dockable panels: live design rule check, drawing preview, and a property inspector."""

from __future__ import annotations

import re

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSlider,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cable_tool.asme import SHEET_SIZES
from cable_tool.canvas import sheet_to_svg
from cable_tool.drawing import build_drawing
from cable_tool.drc import ERROR, INFO, WARNING, DrcReport, run_drc
from cable_tool.edit import rename
from cable_tool.inserts import layout_for
from cable_tool.library import contacts_included, parse_bool

from .document import Document
from .tables import SPECS

SEVERITY_COLOR = {ERROR: QColor("#d9534f"), WARNING: QColor("#e0a800"), INFO: QColor("#6c757d")}


class Analyzer:
    """Rebuilds the drawing and DRC shortly after the design changes (debounced) and notifies listeners."""

    def __init__(self, doc: Document, delay_ms: int = 300):
        self.doc = doc
        self.sheets = []
        self.layout_notes: list[str] = []
        self.report = DrcReport()
        self.listeners = []
        self.timer = QTimer()
        self.timer.setSingleShot(True)
        self.timer.setInterval(delay_ms)
        self.timer.timeout.connect(self.run)
        doc.changed.connect(self.timer.start)

    def run(self):
        d = self.doc.design
        try:
            self.sheets, self.layout_notes = build_drawing(d, d.sheet_size if d.sheet_size in SHEET_SIZES else
                                                           next(iter(SHEET_SIZES)))
            self.report = run_drc(d, self.sheets)
        except Exception as exc:  # noqa: BLE001 - never let a drawing bug take down the editor
            self.sheets = []
            self.report = DrcReport()
            self.report.add(ERROR, "Internal", "", f"Drawing generation failed: {exc}")
        for fn in self.listeners:
            fn(self)


def _item_kind(design, item: str) -> tuple[str, str] | None:
    """Map a DRC finding's item text to (selection kind, key)."""
    if not item:
        return None
    ref = re.split(r"[-@]", item)[0]
    if design.connector(ref):
        return ("connector", ref)
    if any(w.wire_id == item for w in design.wires):
        return ("wire", item)
    if design.splice(ref):
        return ("splice", ref)
    if design.group(ref):
        return ("group", ref)
    if design.library.get(item):
        return ("part", item)
    return None


class DrcPanel(QWidget):
    def __init__(self, doc: Document, analyzer: Analyzer):
        super().__init__()
        self.doc = doc
        self.summary = QLabel()
        self.show_info = QCheckBox("Show info")
        self.show_info.toggled.connect(lambda _: self.update_from(analyzer))
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Severity", "Rule", "Item", "Message"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.header().setSectionResizeMode(3, QHeaderView.Stretch)
        self.tree.itemDoubleClicked.connect(self._jump)
        top = QHBoxLayout()
        top.addWidget(self.summary, 1)
        top.addWidget(self.show_info)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addLayout(top)
        lay.addWidget(self.tree)
        analyzer.listeners.append(self.update_from)

    def update_from(self, analyzer: Analyzer):
        report = analyzer.report
        c = report.counts()
        bundles = ", ".join(f"{r} Ø{b.diameter:.3f} in" for r, b in report.bundles.items() if b.diameter)
        self.summary.setText(f"<b>{c[ERROR]}</b> errors · <b>{c[WARNING]}</b> warnings · {c[INFO]} info"
                             + (f" &nbsp;&nbsp; Bundle: {bundles}" if bundles else ""))
        self.tree.clear()
        for f in report.sorted():
            if f.severity == INFO and not self.show_info.isChecked():
                continue
            it = QTreeWidgetItem([f.severity, f.rule, f.item, f.message])
            it.setForeground(0, SEVERITY_COLOR[f.severity])
            it.setToolTip(3, f.message)
            it.setData(0, Qt.UserRole, f.item)
            self.tree.addTopLevelItem(it)
        for i in range(3):
            self.tree.resizeColumnToContents(i)

    def _jump(self, item: QTreeWidgetItem):
        target = _item_kind(self.doc.design, item.data(0, Qt.UserRole) or "")
        if target:
            self.doc.select(*target)


class SvgPage(QWidget):
    """Renders one SVG sheet at a zoom factor (white paper, drop shadow)."""

    def __init__(self):
        super().__init__()
        self.renderer = QSvgRenderer()
        self.zoom = 0.5

    def set_svg(self, svg: str):
        self.renderer.load(QByteArray(svg.encode("utf-8")))
        self._resize()

    def set_zoom(self, z: float):
        self.zoom = z
        self._resize()

    def _resize(self):
        size = self.renderer.defaultSize()
        self.setFixedSize(QSize(int(size.width() * self.zoom) + 20, int(size.height() * self.zoom) + 20))
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width() - 20, self.height() - 20
        p.fillRect(14, 14, w, h, QColor(0, 0, 0, 40))
        p.fillRect(10, 10, w, h, Qt.white)
        self.renderer.render(p, QRectF(10, 10, w, h))


class PreviewPanel(QWidget):
    def __init__(self, doc: Document, analyzer: Analyzer):
        super().__init__()
        self.doc = doc
        self.tabs = QTabWidget()
        self.pages: list[SvgPage] = []
        self.zoom = QSlider(Qt.Horizontal)
        self.zoom.setRange(10, 200)
        self.zoom.setValue(45)
        self.zoom.valueChanged.connect(lambda v: [p.set_zoom(v / 100) for p in self.pages])
        self.size_box = QComboBox()
        self.size_box.addItems(list(SHEET_SIZES))
        self.size_box.currentTextChanged.connect(self._size_changed)
        self.note = QLabel()
        self.note.setStyleSheet("color: palette(mid);")
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Smallest sheet:"))
        bar.addWidget(self.size_box)
        bar.addWidget(self.note, 1)
        bar.addWidget(QLabel("Zoom"))
        bar.addWidget(self.zoom)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addLayout(bar)
        lay.addWidget(self.tabs)
        analyzer.listeners.append(self.update_from)

    def _size_changed(self, name: str):
        if name and name != self.doc.design.sheet_size:
            self.doc.edit("Sheet size", lambda d: setattr(d, "sheet_size", name))

    def update_from(self, analyzer: Analyzer):
        self.size_box.blockSignals(True)
        self.size_box.setCurrentText(self.doc.design.sheet_size)
        self.size_box.blockSignals(False)
        used = analyzer.sheets[0].meta.get("sheet_size", "") if analyzer.sheets else ""
        self.note.setText(f"Drawn on {used}" if used and used != self.doc.design.sheet_size else "")
        current = self.tabs.currentIndex()
        while len(self.pages) < len(analyzer.sheets):
            page = SvgPage()
            page.set_zoom(self.zoom.value() / 100)
            scroll = QScrollArea()
            scroll.setWidget(page)
            scroll.setAlignment(Qt.AlignCenter)
            scroll.setStyleSheet("QScrollArea { background: #8a8f96; }")
            self.pages.append(page)
            self.tabs.addTab(scroll, "")
        while len(self.pages) > len(analyzer.sheets):
            self.tabs.removeTab(len(self.pages) - 1)
            self.pages.pop()
        for i, (sheet, page) in enumerate(zip(analyzer.sheets, self.pages)):
            page.set_svg(sheet_to_svg(sheet))
            self.tabs.setTabText(i, f"Sheet {i + 1}: {sheet.name}")
        if 0 <= current < len(self.pages):
            self.tabs.setCurrentIndex(current)


class PropertiesPanel(QWidget):
    """Form for the selected connector, wire, group, splice or part."""

    edited = Signal()

    def __init__(self, doc: Document):
        super().__init__()
        self.doc = doc
        self.kind, self.key = "", ""
        self.heading = QLabel("Select a connector, wire, group, splice or part.")
        self.heading.setWordWrap(True)
        self.form = QFormLayout()
        lay = QVBoxLayout(self)
        lay.addWidget(self.heading)
        lay.addLayout(self.form)
        lay.addStretch(1)
        self.fields: dict[str, QLineEdit] = {}
        doc.selection_requested.connect(self.show_item)
        doc.changed.connect(self.reload)

    def _spec(self):
        return next((s for s in SPECS.values() if s.kind == self.kind), None)

    def _record(self):
        spec = self._spec()
        if not spec:
            return None
        return next((r for r in spec.rows(self.doc.design) if str(getattr(r, spec.key_field)) == self.key), None)

    def show_item(self, kind: str, key: str):
        self.kind, self.key = kind, key
        self.reload()

    def reload(self):
        while self.form.rowCount():
            self.form.removeRow(0)
        self.fields.clear()
        spec, rec = self._spec(), self._record()
        if not spec or rec is None:
            self.heading.setText("Select a connector, wire, group, splice or part.")
            return
        self.heading.setText(f"<b>{spec.name[:-1] if spec.name.endswith('s') else spec.name}: {self.key}</b>")
        for col in spec.columns:
            v = getattr(rec, col.field)
            edit = QLineEdit("" if v is None else ("YES" if v else "NO") if isinstance(v, bool)
                             else f"{v:g}" if isinstance(v, float) else str(v))
            if col.tip:
                edit.setToolTip(col.tip)
            edit.editingFinished.connect(lambda c=col, e=edit: self._commit(c, e.text()))
            self.form.addRow(col.header, edit)
            self.fields[col.field] = edit
        info = contact_info(self.doc.design, self.kind, rec)
        if info:
            label = QLabel(info)
            label.setWordWrap(True)
            self.form.addRow("Contacts", label)

    def _commit(self, col, text: str):
        spec, key, kind = self._spec(), self.key, self.kind
        rec = self._record()
        if rec is None:
            return
        old = getattr(rec, col.field)
        if col.kind == "float":
            try:
                value = float(text) if text.strip() else None
            except ValueError:
                return
        elif col.kind == "bool":
            value = parse_bool(text)
        else:
            value = text.strip()
        if value == old or (old is None and value == ""):
            return

        def apply(d):
            r = next((x for x in spec.rows(d) if str(getattr(x, spec.key_field)) == key), None)
            if r is None:
                return
            if kind == "part" and col.field == "pn":
                d.library.parts = {(value if k == key else k): v for k, v in d.library.parts.items()}
            if col.field == spec.key_field:
                rename(d, kind, key, str(value))
            setattr(r, col.field, value)
        if col.field == spec.key_field:
            self.key = str(value)
        self.doc.edit(f"Edit {col.header}", apply)


def contact_info(design, kind: str, rec) -> str:
    """Linked contact data for a connector (connector table row or library part): P/N, wire range, supply, insert."""
    if kind == "connector":
        pn, contact_pn, included = rec.connector_pn, design.contact_pn(rec.ref), design.contacts_included(rec.ref)
    elif kind == "part" and rec.type == "connector":
        pn, contact_pn, included = rec.pn, rec.contact_pn, contacts_included(rec.pn, rec)
    else:
        return ""
    lines = []
    if contact_pn:
        c = design.library.get(contact_pn)
        desc = f" {c.description}" if c and c.description else ""
        awg = f", AWG {c.awg_range[0]:g}-{c.awg_range[1]:g}" if c and c.awg_range else ""
        lines.append(f"{contact_pn}{desc}{awg}")
    lines.append("Supplied with the connector (not a separate parts-list line)." if included
                 else "Ordered separately (parts-list line per contact).")
    found = layout_for(pn)
    if found:
        info, cavs = found
        lines.append(f"Insert {info.insert_name} ({len(cavs)} contacts, {info.contact_type}); pinout on sheet 2.")
    return "\n".join(lines)
