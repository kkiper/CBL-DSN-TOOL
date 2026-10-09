"""Dialogs: title block & design settings, export, and new library part."""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from cable_tool.bom import bom_dataframe, build_bom
from cable_tool.canvas import sheet_to_svg, sheets_to_pdf
from cable_tool.drawing import build_drawing
from cable_tool.drc import run_drc
from cable_tool.dxf import sheet_to_dxf
from cable_tool.library import PART_TYPES, Part, parse_bool
from cable_tool.model import TitleBlock
from cable_tool.project import save_design

from .document import Document
from .tables import RecordTable

TITLE_LABELS = {
    "title": "Title", "drawing_number": "Drawing number", "revision": "Revision (if no history)",
    "company": "Design activity (company)", "cage_code": "CAGE code", "contract_number": "Contract number",
    "drawn_by": "Drawn by", "date": "Drawn date", "checked_by": "Checked by", "checked_date": "Checked date",
    "engineer": "Engineer", "engineer_date": "Engineer date", "approved_by": "Approved by",
    "approved_date": "Approved date", "scale": "Scale", "weight": "Weight", "next_assy": "Next assy",
    "used_on": "Used on", "statement": "Proprietary / distribution statement",
}


class DesignDialog(QDialog):
    """Title block, application block, units/tolerance/length, revision history and general notes."""

    def __init__(self, doc: Document, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.setWindowTitle("Title block and design settings")
        self.resize(820, 620)
        tabs = QTabWidget()

        tb = doc.design.title_block
        page = QWidget()
        grid = QGridLayout(page)
        self.edits: dict[str, QLineEdit] = {}
        for i, f in enumerate(fields(TitleBlock)):
            edit = QLineEdit(str(getattr(tb, f.name) or ""))
            self.edits[f.name] = edit
            r, c = (i % 10), (i // 10) * 2
            grid.addWidget(QLabel(TITLE_LABELS.get(f.name, f.name)), r, c)
            grid.addWidget(edit, r, c + 1)
        tabs.addTab(page, "Title block")

        page = QWidget()
        form = QFormLayout(page)
        self.units = QComboBox()
        self.units.addItems(["IN", "MM"])
        self.units.setCurrentText(doc.design.units if doc.design.units in ("IN", "MM") else "IN")
        self.tol = QLineEdit(doc.design.tolerance)
        self.length = QDoubleSpinBox()
        self.length.setRange(0, 1e6)
        self.length.setDecimals(2)
        self.length.setSpecialValueText("(not set)")
        self.length.setValue(doc.design.overall_length or 0)
        form.addRow("Units", self.units)
        form.addRow("Length tolerance (±)", self.tol)
        form.addRow("Overall length (two-connector cable)", self.length)
        form.addRow(QLabel("For a harness with a breakout, enter each connector's length to the breakout in the "
                           "Connectors table instead."))
        tabs.addTab(page, "Lengths and units")

        rev = RecordTable(doc, "revisions")
        tabs.addTab(rev, "Revision history (Y14.35)")

        self.notes = QPlainTextEdit("\n".join(doc.design.notes))
        notes_page = QWidget()
        nl = QVBoxLayout(notes_page)
        nl.addWidget(QLabel("One general note per line. {UNITS}, {UNITS_NAME} and {TOL} are filled in. Flag notes for "
                            "boots, labels, markers, splices and shields are added automatically."))
        nl.addWidget(self.notes)
        tabs.addTab(notes_page, "General notes")

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(tabs)
        lay.addWidget(buttons)

    def accept(self):
        values = {k: e.text().strip() for k, e in self.edits.items()}
        units, tol, length = self.units.currentText(), self.tol.text().strip() or "0.5", self.length.value() or None
        notes = [n for n in self.notes.toPlainText().splitlines() if n.strip()]

        def apply(d):
            for k, v in values.items():
                setattr(d.title_block, k, v)
            d.units, d.tolerance, d.overall_length, d.notes = units, tol, length, notes
        self.doc.edit("Title block and settings", apply)
        super().accept()


class ExportDialog(QDialog):
    FORMATS = [("pdf", "Drawing (PDF, all sheets)", True), ("dxf", "CAD sheets (DXF R12, one per sheet)", True),
               ("svg", "SVG sheets", False), ("bom", "Bill of materials (CSV)", True),
               ("drc", "Design rule check report (CSV)", True), ("xlsx", "Project workbook (XLSX)", False)]

    def __init__(self, doc: Document, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.setWindowTitle("Export drawing package")
        stem = (doc.design.title_block.drawing_number or (doc.path.stem if doc.path else "cable")).replace("/", "_")
        folder = str(doc.path.parent if doc.path else Path.home())
        self.folder = QLineEdit(folder)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        self.stem = QLineEdit(stem)
        row = QHBoxLayout()
        row.addWidget(self.folder, 1)
        row.addWidget(browse)
        box = QGroupBox("Formats")
        bl = QVBoxLayout(box)
        self.checks = {}
        for key, label, on in self.FORMATS:
            cb = QCheckBox(label)
            cb.setChecked(on)
            self.checks[key] = cb
            bl.addWidget(cb)
        form = QFormLayout()
        form.addRow("Folder", row)
        form.addRow("File name", self.stem)
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        export = buttons.addButton("Export", QDialogButtonBox.AcceptRole)
        export.setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(box)
        lay.addWidget(buttons)
        self.written: list[Path] = []

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Export folder", self.folder.text())
        if d:
            self.folder.setText(d)

    def accept(self):
        try:
            self.written = export_package(self.doc, Path(self.folder.text()), self.stem.text().strip() or "cable",
                                          {k for k, cb in self.checks.items() if cb.isChecked()})
        except OSError as exc:
            QMessageBox.critical(self, "Export failed", str(exc))
            return
        super().accept()


def export_package(doc: Document, folder: Path, stem: str, formats: set[str]) -> list[Path]:
    d = doc.design
    folder.mkdir(parents=True, exist_ok=True)
    sheets, _ = build_drawing(d, d.sheet_size)
    out: list[Path] = []
    if "pdf" in formats:
        p = folder / f"{stem}.pdf"
        p.write_bytes(sheets_to_pdf(sheets, title=f"{d.title_block.drawing_number} {d.title_block.title}".strip()))
        out.append(p)
    for fmt, render in (("dxf", sheet_to_dxf), ("svg", sheet_to_svg)):
        if fmt in formats:
            for i, sheet in enumerate(sheets, start=1):
                p = folder / f"{stem}_sheet{i}.{fmt}"
                p.write_text(render(sheet), encoding="utf-8")
                out.append(p)
    if "bom" in formats:
        p = folder / f"{stem}_bom.csv"
        bom_dataframe(build_bom(d), d.units).to_csv(p, index=False)
        out.append(p)
    if "drc" in formats:
        p = folder / f"{stem}_drc.csv"
        run_drc(d, sheets).to_dataframe().to_csv(p, index=False)
        out.append(p)
    if "xlsx" in formats:
        p = folder / f"{stem}_project.xlsx"
        p.write_bytes(save_design(d))
        out.append(p)
    return out


# Parameters each part type uses (shown in the new-part dialog)
TYPE_FIELDS = {
    "wire": ["awg", "od", "color"],
    "cable": ["awg", "od", "conductors"],
    "connector": ["contact_pn", "contacts", "contacts_included", "awg_min", "awg_max", "dia_min", "dia_max"],
    "contact": ["awg_min", "awg_max", "dia_min", "dia_max"],
    "backshell": ["dia_min", "dia_max"],
    "heatshrink": ["dia_min", "dia_max"],
    "label": ["dia_min", "dia_max"],
    "marker": ["dia_min", "dia_max"],
    "splice": ["awg_min", "awg_max", "cma_min", "cma_max"],
    "shield_term": ["dia_min", "dia_max", "awg_min", "awg_max"],
    "shield": ["wall"],
    "other": [],
}
FIELD_HELP = {
    "awg": "AWG", "od": "OD (in)", "color": "Color", "conductors": "Conductors", "contact_pn": "Default contact P/N",
    "contacts": "Contact count", "contacts_included": "Contacts included (YES / NO / blank = P/N rule)", "awg_min": "AWG min (largest wire)", "awg_max": "AWG max (smallest wire)",
    "dia_min": "Dia min (in)", "dia_max": "Dia max (in)", "cma_min": "CMA min", "cma_max": "CMA max",
    "wall": "Wall (in)",
}
DIA_MEANING = {
    "connector": "Dia = wire sealing range", "contact": "Dia = wire sealing range",
    "backshell": "Dia = cable clamp range", "heatshrink": "Dia min = recovered ID, max = expanded ID",
    "label": "Dia min = recovered ID, max = expanded ID", "marker": "Dia min = recovered ID, max = expanded ID",
    "shield_term": "Dia = range over the shield",
}


class NewPartDialog(QDialog):
    """Create a library part (the Splice-style 'custom connector / cable' wizard)."""

    def __init__(self, doc: Document, part_type: str = "connector", parent=None):
        super().__init__(parent)
        self.doc = doc
        self.setWindowTitle("New library part")
        self.pn = QLineEdit()
        self.desc = QLineEdit()
        self.cage = QLineEdit()
        self.type = QComboBox()
        self.type.addItems(PART_TYPES)
        self.type.setCurrentText(part_type)
        self.params = QFormLayout()
        self.meaning = QLabel()
        self.meaning.setStyleSheet("color: palette(mid);")
        self.inputs: dict[str, QLineEdit] = {}
        form = QFormLayout()
        form.addRow("P/N", self.pn)
        form.addRow("Type", self.type)
        form.addRow("Description", self.desc)
        form.addRow("CAGE code", self.cage)
        box = QGroupBox("Parameters")
        bl = QVBoxLayout(box)
        bl.addLayout(self.params)
        bl.addWidget(self.meaning)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(box)
        lay.addWidget(buttons)
        self.type.currentTextChanged.connect(self._fields)
        self._fields(part_type)

    def _fields(self, t: str):
        while self.params.rowCount():
            self.params.removeRow(0)
        self.inputs.clear()
        for f in TYPE_FIELDS.get(t, []):
            e = QLineEdit()
            self.inputs[f] = e
            self.params.addRow(FIELD_HELP[f], e)
        self.meaning.setText(DIA_MEANING.get(t, ""))

    def part(self) -> Part:
        p = Part(pn=self.pn.text().strip(), type=self.type.currentText(), description=self.desc.text().strip(),
                 cage=self.cage.text().strip())
        for f, e in self.inputs.items():
            text = e.text().strip()
            if not text:
                continue
            if f in ("color", "contact_pn"):
                setattr(p, f, text)
            elif f == "contacts_included":
                p.contacts_included = parse_bool(text)
            else:
                try:
                    setattr(p, f, float(text))
                except ValueError:
                    pass
        return p

    def accept(self):
        if not self.pn.text().strip():
            QMessageBox.warning(self, "New part", "Enter a part number.")
            return
        part = self.part()
        self.doc.edit(f"Add part {part.pn}", lambda d: d.library.add(part))
        super().accept()


__all__ = ["DesignDialog", "ExportDialog", "NewPartDialog", "export_package"]
