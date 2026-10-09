"""Parts library browser: search, filter by type, drag parts onto the canvas."""

from __future__ import annotations

from PySide6.QtCore import QMimeData, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLineEdit,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cable_tool.inserts import layout_for
from cable_tool.library import PART_TYPES, contacts_included

from .canvas_view import PART_MIME
from .document import Document

TYPE_TITLES = {"connector": "Connectors", "contact": "Contacts", "backshell": "Backshells", "heatshrink": "Heatshrink & boots",
               "label": "Labels", "marker": "Wire markers", "wire": "Wire", "cable": "Cable", "splice": "Splices",
               "shield_term": "Shield terminations", "shield": "Shield / braid", "other": "Other", "": "Untyped"}


class _PartTree(QTreeWidget):
    def mimeData(self, items):
        md = QMimeData()
        pns = [i.data(0, Qt.UserRole) for i in items if i.data(0, Qt.UserRole)]
        if pns:
            md.setData(PART_MIME, pns[0].encode("utf-8"))
            md.setText(pns[0])
        return md

    def mimeTypes(self):
        return [PART_MIME]


class LibraryPanel(QWidget):
    def __init__(self, doc: Document, new_part, import_library):
        super().__init__()
        self.doc = doc
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search P/N or description")
        self.search.textChanged.connect(self.refresh)
        self.type = QComboBox()
        self.type.addItems(["All types"] + PART_TYPES)
        self.type.currentTextChanged.connect(self.refresh)
        self.tree = _PartTree()
        self.tree.setHeaderLabels(["Part", "Description"])
        self.tree.setDragEnabled(True)
        self.tree.setDragDropMode(QTreeWidget.DragOnly)
        self.tree.itemDoubleClicked.connect(self._open)
        add, imp = QToolButton(text="New part…"), QToolButton(text="Import…")
        add.clicked.connect(new_part)
        imp.clicked.connect(import_library)
        top = QHBoxLayout()
        top.addWidget(self.type, 1)
        top.addWidget(add)
        top.addWidget(imp)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addWidget(self.search)
        lay.addLayout(top)
        lay.addWidget(self.tree)
        doc.changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        q = self.search.text().strip().lower()
        want = self.type.currentText()
        open_types = {self.tree.topLevelItem(i).data(0, Qt.UserRole + 1) for i in range(self.tree.topLevelItemCount())
                      if self.tree.topLevelItem(i).isExpanded()}
        self.tree.clear()
        groups: dict[str, list] = {}
        for p in self.doc.design.library.parts.values():
            if want != "All types" and p.type != want:
                continue
            if q and q not in p.pn.lower() and q not in p.description.lower():
                continue
            groups.setdefault(p.type, []).append(p)
        for t in [*PART_TYPES, ""]:
            if t not in groups:
                continue
            top = QTreeWidgetItem([f"{TYPE_TITLES.get(t, t)} ({len(groups[t])})"])
            top.setData(0, Qt.UserRole + 1, t)
            top.setFlags(Qt.ItemIsEnabled)
            for p in sorted(groups[t], key=lambda p: p.pn):
                it = QTreeWidgetItem([p.pn, p.description])
                it.setData(0, Qt.UserRole, p.pn)
                it.setToolTip(0, _summary(p, self.doc.design.library))
                it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled)
                top.addChild(it)
            self.tree.addTopLevelItem(top)
            top.setExpanded(bool(q) or not open_types or t in open_types)
        self.tree.resizeColumnToContents(0)

    def _open(self, item):
        pn = item.data(0, Qt.UserRole)
        if pn:
            self.doc.select("part", pn)


def _summary(p, library=None) -> str:
    bits = [f"{p.pn} ({p.type or 'untyped'})", p.description]
    if p.awg_range:
        bits.append(f"AWG {p.awg_range[0]:g}-{p.awg_range[1]:g}")
    if p.dia_min is not None or p.dia_max is not None:
        bits.append(f"Dia {p.dia_min if p.dia_min is not None else '?'}-{p.dia_max if p.dia_max is not None else '?'} in")
    if p.od:
        bits.append(f"OD {p.od} in")
    if p.contacts:
        bits.append(f"{int(p.contacts)} contacts")
    if p.contact_pn:
        if p.type == "connector":
            supplied = "supplied with connector" if contacts_included(p.pn, p) else "order separately"
            contact = library.get(p.contact_pn) if library else None
            awg = f", AWG {contact.awg_range[0]:g}-{contact.awg_range[1]:g}" if contact and contact.awg_range else ""
            bits.append(f"contact {p.contact_pn}{awg} ({supplied})")
        else:
            bits.append(f"contact {p.contact_pn}")
    found = layout_for(p.pn) if p.type == "connector" else None
    if found:
        info, cavs = found
        bits.append(f"insert {info.insert_name}, {info.contact_type} contacts {cavs[0].contact}-{cavs[-1].contact}, "
                    f"face view available")
    return "\n".join(b for b in bits if b)
