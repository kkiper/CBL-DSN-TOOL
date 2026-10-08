"""Spreadsheet views of the design: wires, connectors, groups, splices, parts library and revisions.

One generic model (:class:`RecordModel`) shows a list of dataclass records; every edit goes through
``Document.edit`` so it can be undone and every other view refreshes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QStyledItemDelegate,
    QTableView,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from cable_tool.edit import rename
from cable_tool.library import PART_TYPES, Part
from cable_tool.model import CableDesign, ConnectorEnd, Revision, Splice, Wire, WireGroup

from .document import Document

GROUP_KINDS = ["TWISTED PAIR", "TWISTED TRIPLE", "SHIELDED", "SHIELDED TWISTED PAIR", "SHIELDED TWISTED TRIPLE",
               "JACKETED CABLE"]


@dataclass
class Col:
    field: str
    header: str
    kind: str = "text"          # text | float | choice
    choices: list[str] = field(default_factory=list)
    tip: str = ""


@dataclass
class TableSpec:
    name: str
    kind: str                                   # selection kind: wire, connector, group, splice, part, revision
    key_field: str
    columns: list[Col]
    rows: Callable[[CableDesign], list]
    new: Callable[[CableDesign], object]
    add: Callable[[CableDesign, object], None]
    remove: Callable[[CableDesign, list[int]], None]
    help: str = ""


def next_id(existing: list[str], prefix: str) -> str:
    nums = [int(m.group(1)) for e in existing if (m := re.fullmatch(re.escape(prefix) + r"(\d+)", e or ""))]
    return f"{prefix}{max(nums, default=0) + 1}"


def _remove_from(attr: str):
    def fn(d: CableDesign, idx: list[int]):
        lst = getattr(d, attr)
        for i in sorted(idx, reverse=True):
            if 0 <= i < len(lst):
                del lst[i]
    return fn


def _remove_parts(d: CableDesign, idx: list[int]):
    keys = list(d.library.parts)
    for i in sorted(idx, reverse=True):
        if 0 <= i < len(keys):
            d.library.parts.pop(keys[i], None)


def _add_part(d: CableDesign, p: Part):
    d.library.add(p)


SPECS: dict[str, TableSpec] = {
    "wires": TableSpec(
        "Wires", "wire", "wire_id",
        [Col("wire_id", "Wire ID"), Col("from_ref", "From"), Col("from_pin", "From Pin"), Col("to_ref", "To"),
         Col("to_pin", "To Pin"), Col("signal", "Signal"), Col("gauge", "Gauge"), Col("color", "Color"),
         Col("wire_pn", "Wire P/N"), Col("length", "Length", "float", tip="Overrides the length from the cable"),
         Col("label_pn", "Wire Label P/N"), Col("heatshrink_pn", "Wire Heatshrink P/N"), Col("group", "Group"),
         Col("notes", "Notes")],
        lambda d: d.wires,
        lambda d: Wire(next_id([w.wire_id for w in d.wires], "W"), "", "", "", ""),
        lambda d, o: d.wires.append(o), _remove_from("wires"),
        "One row per wire. Use a splice ref (SP1...) as From or To to splice. Wires in the same Group are twisted, "
        "shielded or one cable."),
    "connectors": TableSpec(
        "Connectors", "connector", "ref",
        [Col("ref", "Ref"), Col("description", "Description"), Col("connector_pn", "Connector P/N"),
         Col("contact_pn", "Contact P/N"), Col("backshell_pn", "Backshell P/N"), Col("heatshrink_pn", "Heatshrink P/N"),
         Col("label_pn", "Label P/N"), Col("label_text", "Label Text"),
         Col("length", "Length", "float", tip="Connector face to breakout")],
        lambda d: d.connectors,
        lambda d: ConnectorEnd(next_id([c.ref for c in d.connectors], "P")),
        lambda d, o: d.connectors.append(o), _remove_from("connectors")),
    "groups": TableSpec(
        "Groups & shields", "group", "group_id",
        [Col("group_id", "Group"), Col("kind", "Type", "choice", GROUP_KINDS), Col("cable_pn", "Cable P/N"),
         Col("shield_pn", "Shield P/N"), Col("shield_term_pn", "Shield Term P/N"),
         Col("term_from", "Shield Term From", tip="BACKSHELL, FLOAT, or a pin (11 or P2-11)"),
         Col("term_to", "Shield Term To", tip="BACKSHELL, FLOAT, or a pin"), Col("notes", "Notes")],
        lambda d: d.groups,
        lambda d: WireGroup(next_id([g.group_id for g in d.groups], "G")),
        lambda d, o: d.groups.append(o), _remove_from("groups")),
    "splices": TableSpec(
        "Splices", "splice", "ref",
        [Col("ref", "Ref"), Col("splice_pn", "Splice P/N"), Col("near", "Near", tip="Connector whose leg it's on"),
         Col("distance", "Distance", "float", tip="From that connector's face"), Col("notes", "Notes")],
        lambda d: d.splices,
        lambda d: Splice(next_id([s.ref for s in d.splices], "SP")),
        lambda d, o: d.splices.append(o), _remove_from("splices")),
    "parts": TableSpec(
        "Parts library", "part", "pn",
        [Col("pn", "P/N"), Col("type", "Type", "choice", PART_TYPES), Col("description", "Description"),
         Col("cage", "CAGE"), Col("awg", "AWG", "float"), Col("od", "OD (in)", "float"),
         Col("awg_min", "AWG Min", "float"), Col("awg_max", "AWG Max", "float"),
         Col("dia_min", "Dia Min (in)", "float", tip="Sealing / clamp range or recovered ID"),
         Col("dia_max", "Dia Max (in)", "float", tip="Sealing / clamp range or expanded ID"),
         Col("cma_min", "CMA Min", "float"), Col("cma_max", "CMA Max", "float"), Col("contact_pn", "Contact P/N"),
         Col("contacts", "Contacts", "float"), Col("conductors", "Conductors", "float"), Col("wall", "Wall (in)", "float"),
         Col("color", "Color"), Col("notes", "Notes")],
        lambda d: list(d.library.parts.values()),
        lambda d: Part(next_id(list(d.library.parts), "NEW-PART-")),
        _add_part, _remove_parts),
    "revisions": TableSpec(
        "Revisions", "revision", "rev",
        [Col("zone", "Zone"), Col("rev", "Rev"), Col("description", "Description"), Col("date", "Date"),
         Col("approved", "Approved")],
        lambda d: d.revisions,
        lambda d: Revision(rev=_next_rev(d)),
        lambda d, o: d.revisions.append(o), _remove_from("revisions")),
}


def _next_rev(d: CableDesign) -> str:
    if not d.revisions:
        return "-"
    last = d.revisions[-1].rev
    if last in ("-", ""):
        return "A"
    if re.fullmatch(r"[A-HJ-NP-RT-WYZ]", last):      # Y14.35 skips I, O, Q, S, X
        letters = [c for c in "ABCDEFGHJKLMNPRTUVWY"]
        i = letters.index(last) if last in letters else -1
        return letters[i + 1] if 0 <= i < len(letters) - 1 else "AA"
    return last + "1"


class RecordModel(QAbstractTableModel):
    def __init__(self, doc: Document, spec: TableSpec):
        super().__init__()
        self.doc, self.spec = doc, spec
        doc.changed.connect(self.refresh)

    def refresh(self):
        self.beginResetModel()
        self.endResetModel()

    def rows(self) -> list:
        return self.spec.rows(self.doc.design)

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows())

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.spec.columns)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal:
            col = self.spec.columns[section]
            if role == Qt.DisplayRole:
                return col.header
            if role == Qt.ToolTipRole and col.tip:
                return col.tip
        elif role == Qt.DisplayRole:
            return section + 1
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        rec = self.rows()[index.row()]
        col = self.spec.columns[index.column()]
        value = getattr(rec, col.field)
        if role in (Qt.DisplayRole, Qt.EditRole):
            if value is None:
                return ""
            if isinstance(value, float):
                return f"{value:g}"
            return str(value)
        if role == Qt.TextAlignmentRole and col.kind == "float":
            return int(Qt.AlignRight | Qt.AlignVCenter)
        return None

    def flags(self, index):
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable

    def setData(self, index, value, role=Qt.EditRole):
        if role != Qt.EditRole or not index.isValid():
            return False
        col = self.spec.columns[index.column()]
        text = str(value).strip()
        if col.kind == "float":
            if text == "":
                new = None
            else:
                try:
                    new = float(text)
                except ValueError:
                    return False
        else:
            new = text
        row = index.row()

        def apply(d: CableDesign):
            rec = self.spec.rows(d)[row]
            if self.spec.kind == "part" and col.field == "pn":
                if not new or new == rec.pn:
                    return
                d.library.parts = {(new if k == rec.pn else k): v for k, v in d.library.parts.items()}
            if col.field == self.spec.key_field and self.spec.kind != "revision":
                rename(d, self.spec.kind, str(getattr(rec, col.field)), str(new))
            setattr(rec, col.field, new)
        self.doc.edit(f"Edit {col.header}", apply)
        return True

    def key_of(self, row: int) -> str:
        return str(getattr(self.rows()[row], self.spec.key_field))

    def row_of(self, key: str) -> int:
        for i, rec in enumerate(self.rows()):
            if str(getattr(rec, self.spec.key_field)) == key:
                return i
        return -1


class _ChoiceDelegate(QStyledItemDelegate):
    def __init__(self, choices, parent=None):
        super().__init__(parent)
        self.choices = choices

    def createEditor(self, parent, option, index):
        box = QComboBox(parent)
        box.setEditable(True)
        box.addItems(self.choices)
        return box

    def setEditorData(self, editor, index):
        editor.setCurrentText(index.data(Qt.EditRole) or "")

    def setModelData(self, editor, model, index):
        model.setData(index, editor.currentText(), Qt.EditRole)


class RecordTable(QWidget):
    """A table with Add / Delete buttons and a help line."""

    def __init__(self, doc: Document, key: str, parent=None):
        super().__init__(parent)
        self.doc, self.spec = doc, SPECS[key]
        self.model = RecordModel(doc, self.spec)
        self.view = QTableView()
        self.view.setModel(self.model)
        self.view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.view.setAlternatingRowColors(True)
        self.view.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.view.horizontalHeader().setStretchLastSection(True)
        self.view.verticalHeader().setDefaultSectionSize(22)
        for i, col in enumerate(self.spec.columns):
            if col.kind == "choice":
                self.view.setItemDelegateForColumn(i, _ChoiceDelegate(col.choices, self.view))
        add, delete = QToolButton(text="+ Add"), QToolButton(text="− Delete")
        add.clicked.connect(self.add_row)
        delete.clicked.connect(self.delete_rows)
        bar = QHBoxLayout()
        bar.addWidget(add)
        bar.addWidget(delete)
        if self.spec.help:
            tip = QLabel(self.spec.help)
            tip.setStyleSheet("color: palette(mid);")
            tip.setWordWrap(True)
            bar.addWidget(tip, 1)
        else:
            bar.addStretch(1)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addLayout(bar)
        lay.addWidget(self.view)
        act = QAction(self.view)
        act.setShortcut(QKeySequence.Delete)
        act.setShortcutContext(Qt.WidgetWithChildrenShortcut)
        act.triggered.connect(self.delete_rows)
        self.view.addAction(act)
        self.view.selectionModel().currentRowChanged.connect(
            lambda cur, _prev: cur.isValid() and doc.select(self.spec.kind, self.model.key_of(cur.row())))

    def add_row(self):
        self.doc.edit(f"Add {self.spec.kind}", lambda d: self.spec.add(d, self.spec.new(d)))
        last = self.model.rowCount() - 1
        self.view.selectRow(last)
        self.view.edit(self.model.index(last, 0))

    def delete_rows(self):
        rows = sorted({i.row() for i in self.view.selectionModel().selectedRows()})
        if rows:
            self.doc.edit(f"Delete {len(rows)} {self.spec.kind}(s)", lambda d: self.spec.remove(d, rows))

    def select_key(self, key: str) -> bool:
        row = self.model.row_of(key)
        if row >= 0:
            self.view.selectRow(row)
            self.view.scrollTo(self.model.index(row, 0))
            return True
        return False
