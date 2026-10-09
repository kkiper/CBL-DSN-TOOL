"""Calculators tab: wire size conversion (AWG / CMA / mm²) and bundle diameter with fit check."""

from __future__ import annotations

import csv
import io
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from cable_tool import calc
from cable_tool.drc import FIT_OK, fit_status
from cable_tool.library import PACKING_FACTOR, parse_awg

from .document import Document

SLASHES = [f"M22759/{s}" for s in calc.WIRE_SPECS]
ORDERED_AWG = sorted(calc.M22759_CONDUCTORS, reverse=True)          # 26 ... 4/0
WIRE_AWGS = sorted({a for spec in calc.WIRE_SPECS.values() for a in spec["od"]}, reverse=True)


def _in_mm(d: float) -> str:
    return f"{d:.3f} in ({d * calc.MM_PER_IN:.2f} mm)"


# --- Wire size ------------------------------------------------------------------------------------------
class WireSizeCalc(QWidget):
    MODES = [("AWG", "AWG"), ("CMA", "CMA"), ("mm2", "mm²"), ("Strands", "Strands")]

    def __init__(self, parent=None):
        super().__init__(parent)
        convert = QGroupBox("Convert")
        cl = QVBoxLayout(convert)
        modes = QHBoxLayout()
        modes.addWidget(QLabel("Enter by:"))
        self.mode = QButtonGroup(self)
        self.mode_buttons = {}
        for key, text in self.MODES:
            b = QRadioButton(text)
            self.mode.addButton(b)
            self.mode_buttons[key] = b
            modes.addWidget(b)
        modes.addStretch()
        self.mode_buttons["AWG"].setChecked(True)
        cl.addLayout(modes)

        form = QFormLayout()
        self.awg = QComboBox()
        self.awg.setEditable(True)
        self.awg.addItems([calc.awg_label(a) for a in ORDERED_AWG])
        self.awg.setCurrentText("20")
        self.awg.setToolTip("Any AWG, including 1/0 to 4/0")
        self.cma = QDoubleSpinBox()
        self.cma.setRange(1, 1e7)
        self.cma.setDecimals(0)
        self.cma.setValue(1216)
        self.cma.setSuffix(" cmil")
        self.mm2 = QDoubleSpinBox()
        self.mm2.setRange(0.001, 5000)
        self.mm2.setDecimals(3)
        self.mm2.setValue(0.616)
        self.mm2.setSuffix(" mm²")
        strand_row = QHBoxLayout()
        self.strand_size = QDoubleSpinBox()
        self.strand_size.setRange(0.0001, 100)
        self.strand_size.setDecimals(4)
        self.strand_size.setValue(32)
        self.strand_unit = QButtonGroup(self)
        self.unit_buttons = {}
        strand_row.addWidget(self.strand_size)
        for unit in ("AWG", "in", "mm"):
            b = QRadioButton(unit)
            self.strand_unit.addButton(b)
            self.unit_buttons[unit] = b
            strand_row.addWidget(b)
        self.unit_buttons["AWG"].setChecked(True)
        strand_row.addStretch()
        self.strand_count = QSpinBox()
        self.strand_count.setRange(1, 100000)
        self.strand_count.setValue(19)
        form.addRow("AWG", self.awg)
        form.addRow("CMA", self.cma)
        form.addRow("mm²", self.mm2)
        form.addRow("Strand size", strand_row)
        form.addRow("Strand count", self.strand_count)
        cl.addLayout(form)

        result = QGroupBox("Result")
        rl = QFormLayout(result)
        self.out = {k: QLabel() for k in ("cma", "mm2", "awg", "nearest", "at_least", "od")}
        for k, label in (("cma", "Circular mils (CMA)"), ("mm2", "Cross-section"), ("awg", "Equivalent solid AWG"),
                         ("nearest", "Nearest M22759 size"), ("at_least", "Smallest M22759 ≥ this"),
                         ("od", "Typical OD")):
            self.out[k].setTextInteractionFlags(Qt.TextSelectableByMouse)
            rl.addRow(label, self.out[k])
        copy = QPushButton("Copy")
        copy.clicked.connect(self.copy)
        rl.addRow("", copy)

        left = QVBoxLayout()
        left.addWidget(convert)
        left.addWidget(result)
        left.addStretch()

        ref = QGroupBox("M22759 conductor sizes (reference)")
        fl = QVBoxLayout(ref)
        heads = ["AWG", "Strands", "CMA", "mm²"] + [f"OD /{s} (in)" for s in calc.WIRE_SPECS]
        self.table = QTableWidget(len(ORDERED_AWG), len(heads))
        self.table.setHorizontalHeaderLabels(heads)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        for r, awg in enumerate(ORDERED_AWG):
            n, s, cma = calc.M22759_CONDUCTORS[awg]
            ods = [calc.typical_wire_od(slash, awg) for slash in calc.WIRE_SPECS]
            for c, text in enumerate([calc.awg_label(awg), f"{n}/{s}", f"{cma:,}", f"{calc.cma_to_mm2(cma):.3f}"]
                                     + [f"{od:.3f}" if od else "-" for od in ods]):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(r, c, item)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.cellClicked.connect(self._row_clicked)
        fl.addWidget(self.table)
        note = QLabel("Click a row to load it. Stranding per M22759 / ASTM B286; ODs are approximate nominal values. "
                      "Verify against the current slash sheets.")
        note.setWordWrap(True)
        fl.addWidget(note)

        lay = QHBoxLayout(self)
        lw = QWidget()
        lw.setLayout(left)
        lay.addWidget(lw, 1)
        lay.addWidget(ref, 1)

        for w in (self.awg.currentTextChanged, self.cma.valueChanged, self.mm2.valueChanged,
                  self.strand_size.valueChanged, self.strand_count.valueChanged, self.mode.buttonToggled,
                  self.strand_unit.buttonToggled):
            w.connect(self.update_result)
        self.update_result()

    def mode_key(self) -> str:
        return next(k for k, b in self.mode_buttons.items() if b.isChecked())

    def unit_key(self) -> str:
        return next(k for k, b in self.unit_buttons.items() if b.isChecked())

    def set_mode(self, key: str):
        self.mode_buttons[key].setChecked(True)

    def result(self) -> calc.SizeResult | None:
        mode = self.mode_key()
        value = {"AWG": self.awg.currentText(), "CMA": self.cma.value(), "mm2": self.mm2.value(),
                 "Strands": self.strand_size.value()}[mode]
        return calc.size_from(mode, value, self.strand_count.value(), self.unit_key())

    def update_result(self, *_):
        mode = self.mode_key()
        self.awg.setEnabled(mode == "AWG")
        self.cma.setEnabled(mode == "CMA")
        self.mm2.setEnabled(mode == "mm2")
        for w in (self.strand_size, self.strand_count, *self.unit_buttons.values()):
            w.setEnabled(mode == "Strands")
        r = self.result()
        if r is None:
            for lab in self.out.values():
                lab.setText("-")
            return
        n, s, _c = calc.M22759_CONDUCTORS[r.nearest]
        self.out["cma"].setText(f"{r.cma:,.0f} cmil")
        self.out["mm2"].setText(f"{r.mm2:.3f} mm²")
        self.out["awg"].setText(f"{r.awg:.1f}")
        self.out["nearest"].setText(f"{calc.awg_label(r.nearest)} AWG ({n}/{s}), {r.nearest_error:+.1f} % CMA")
        self.out["at_least"].setText(f"{calc.awg_label(r.at_least)} AWG" if r.at_least is not None else "larger than 4/0")
        ods = [f"/{slash} {od:.3f} in" for slash in calc.WIRE_SPECS
               if (od := calc.typical_wire_od(slash, r.nearest))]
        self.out["od"].setText(("  ".join(ods) + f"  (at {calc.awg_label(r.nearest)} AWG)") if ods else "-")
        row = ORDERED_AWG.index(r.nearest)
        self.table.blockSignals(True)
        self.table.selectRow(row)
        self.table.blockSignals(False)

    def _row_clicked(self, row: int, _col: int):
        self.set_mode("AWG")
        self.awg.setCurrentText(calc.awg_label(ORDERED_AWG[row]))

    def text(self) -> str:
        labels = {"cma": "CMA", "mm2": "Cross-section", "awg": "Equivalent solid AWG", "nearest": "Nearest M22759",
                  "at_least": "Smallest M22759 at least", "od": "Typical OD"}
        return "\n".join(f"{labels[k]}\t{lab.text()}" for k, lab in self.out.items())

    def copy(self):
        QGuiApplication.clipboard().setText(self.text())


# --- Bundle -------------------------------------------------------------------------------------------
class _Row:
    """One bundle row: its widgets and how its OD was found."""

    def __init__(self, kind: str):
        self.kind = kind
        self.pn = QComboBox()
        self.pn.setEditable(True)
        self.awg = QComboBox()
        self.od = QDoubleSpinBox()
        self.od.setRange(0, 10)
        self.od.setDecimals(3)
        self.od.setSingleStep(0.005)
        self.od.setSpecialValueText("enter OD")
        self.source = QLabel()
        self.qty = QSpinBox()
        self.qty.setRange(0, 9999)
        self.qty.setValue(1)
        self.typed = False


class BundleCalc(QWidget):
    COLS = ["Type", "Spec / P/N", "AWG", "OD (in)", "Source", "Qty", "Σ d² (in²)"]
    FIT_TYPES = [("backshell", "Backshell"), ("heatshrink", "Boot"), ("label", "Label")]

    def __init__(self, doc: Document, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.settings = QSettings("CableDesigner", "CableDesigner")
        self.rows: list[_Row] = []
        self._filling = False

        bar = QHBoxLayout()
        self.load_enable = QCheckBox("Load from connector")
        self.connector = QComboBox()
        self.load_btn = QPushButton("Load")
        self.load_btn.clicked.connect(self.load_connector)
        self.fit_enable = QCheckBox("Fit check")
        self.packing = QDoubleSpinBox()
        self.packing.setRange(1.0, 2.0)
        self.packing.setDecimals(2)
        self.packing.setSingleStep(0.05)
        self.packing.setValue(PACKING_FACTOR)
        self.packing.setToolTip("Bundle D = packing factor x sqrt(sum of d²). 1.2 is a common rule of thumb; use a "
                                "higher value for loosely laid bundles.")
        for w in (self.load_enable, self.connector, self.load_btn):
            bar.addWidget(w)
        bar.addSpacing(24)
        bar.addWidget(self.fit_enable)
        bar.addStretch()
        bar.addWidget(QLabel("Packing factor"))
        bar.addWidget(self.packing)

        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.verticalHeader().setVisible(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        buttons = QHBoxLayout()
        for text, fn in (("+ Wire", lambda: self.add_row("wire")), ("+ Cable", lambda: self.add_row("cable")),
                         ("Remove", self.remove_rows)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            buttons.addWidget(b)
        buttons.addStretch()

        result = QGroupBox("Result")
        rl = QFormLayout(result)
        self.out_items, self.out_sum, self.out_dia, self.out_formula = QLabel(), QLabel(), QLabel(), QLabel()
        self.out_dia.setStyleSheet("font-weight: bold;")
        for label, w in (("Items", self.out_items), ("Σ d²", self.out_sum), ("Bundle diameter", self.out_dia),
                         ("Formula", self.out_formula)):
            w.setTextInteractionFlags(Qt.TextSelectableByMouse)
            rl.addRow(label, w)
        copy_row = QHBoxLayout()
        copy_row.addStretch()
        for text, fn in (("Copy", self.copy), ("Export CSV...", self.export_csv)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            copy_row.addWidget(b)
        rl.addRow(copy_row)

        self.fit_box = QGroupBox("Fit check (library parts)")
        fg = QGridLayout(self.fit_box)
        self.fit_parts: dict[str, QComboBox] = {}
        self.fit_status: dict[str, QLabel] = {}
        for r, (ptype, label) in enumerate(self.FIT_TYPES):
            combo = QComboBox()
            combo.currentIndexChanged.connect(self.recalc)
            status = QLabel("-")
            status.setWordWrap(True)
            fg.addWidget(QLabel(label), r, 0)
            fg.addWidget(combo, r, 1)
            fg.addWidget(status, r, 2)
            self.fit_parts[ptype], self.fit_status[ptype] = combo, status
        fg.setColumnStretch(2, 1)

        lower = QHBoxLayout()
        lower.addWidget(result, 1)
        lower.addWidget(self.fit_box, 1)

        lay = QVBoxLayout(self)
        lay.addLayout(bar)
        lay.addWidget(self.table, 1)
        lay.addLayout(buttons)
        lay.addLayout(lower)

        self.load_enable.setChecked(self.settings.value("calc/load_from_connector", True, type=bool))
        self.fit_enable.setChecked(self.settings.value("calc/fit_check", True, type=bool))
        self.load_enable.toggled.connect(self._toggles)
        self.fit_enable.toggled.connect(self._toggles)
        self.packing.valueChanged.connect(self.recalc)
        doc.changed.connect(self.refresh_lists)
        self.refresh_lists()
        self._toggles()
        self.add_row("wire")

    # --- library-driven lists ---------------------------------------------------------------
    def _parts(self, ptype: str) -> list:
        return sorted((p for p in self.doc.design.library.parts.values() if p.type == ptype), key=lambda p: p.pn)

    def refresh_lists(self):
        current = self.connector.currentText()
        self.connector.clear()
        self.connector.addItems([c.ref for c in self.doc.design.connectors])
        if current:
            self.connector.setCurrentText(current)
        for ptype, combo in self.fit_parts.items():
            keep = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("(none)", "")
            for p in self._parts(ptype):
                lo, hi = p.dia_range
                rng = f"  {lo if lo is not None else '?'}–{hi if hi is not None else '?'} in" if (lo or hi) else ""
                combo.addItem(f"{p.pn}{rng}", p.pn)
            combo.setCurrentIndex(max(combo.findData(keep), 0))
            combo.blockSignals(False)
        for row in self.rows:
            self._fill_pn_items(row)
        self.recalc()

    def _toggles(self, *_):
        on = self.load_enable.isChecked()
        self.connector.setVisible(on)
        self.load_btn.setVisible(on)
        self.fit_box.setVisible(self.fit_enable.isChecked())
        self.settings.setValue("calc/load_from_connector", on)
        self.settings.setValue("calc/fit_check", self.fit_enable.isChecked())

    # --- rows -------------------------------------------------------------------------------
    def _fill_pn_items(self, row: _Row):
        text = row.pn.currentText()
        row.pn.blockSignals(True)
        row.pn.clear()
        if row.kind == "wire":
            row.pn.addItems(SLASHES)
        row.pn.addItems([p.pn for p in self._parts(row.kind)])
        row.pn.setCurrentText(text or (SLASHES[0] if row.kind == "wire" else ""))
        row.pn.blockSignals(False)

    def add_row(self, kind: str, pn: str = "", od: float | None = None, qty: int = 1, awg: float | None = None,
                source: str = "") -> _Row:
        row = _Row(kind)
        self._fill_pn_items(row)
        if pn:
            row.pn.setCurrentText(pn)
        row.awg.addItems([calc.awg_label(a) for a in WIRE_AWGS] if kind == "wire" else ["-"])
        row.awg.setEnabled(kind == "wire")
        if kind == "wire":
            row.awg.setCurrentText(calc.awg_label(awg) if awg is not None else "20")
        row.qty.setValue(qty)
        r = self.table.rowCount()
        self.table.insertRow(r)
        kind_item = QTableWidgetItem("M22759 wire" if kind == "wire" else "Cable")
        kind_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        self.table.setItem(r, 0, kind_item)
        for c, w in ((1, row.pn), (2, row.awg), (3, row.od), (4, row.source), (5, row.qty)):
            self.table.setCellWidget(r, c, w)
        sub = QTableWidgetItem("")
        sub.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        self.table.setItem(r, 6, sub)
        self.rows.append(row)
        row.pn.currentTextChanged.connect(lambda _t, rw=row: self._auto_od(rw))
        row.awg.currentTextChanged.connect(lambda _t, rw=row: self._auto_od(rw))
        row.od.valueChanged.connect(lambda _v, rw=row: self._od_typed(rw))
        row.qty.valueChanged.connect(self.recalc)
        if od is not None:
            self._set_od(row, od, source or "typed")
            row.typed = source == "typed"
        else:
            self._auto_od(row)
        self.recalc()
        return row

    def _set_od(self, row: _Row, od: float | None, source: str):
        self._filling = True
        row.od.setValue(od or 0)
        self._filling = False
        row.source.setText(source)

    def _auto_od(self, row: _Row):
        """OD from the library (by P/N), else the M22759 table (by spec and AWG); keeps a typed OD otherwise."""
        pn = row.pn.currentText().strip()
        part = self.doc.design.library.get(pn) if pn else None
        if part and part.od:
            self._set_od(row, part.od, "library")
            row.typed = False
            if row.kind == "wire" and part.awg is not None:
                row.awg.blockSignals(True)
                row.awg.setCurrentText(calc.awg_label(part.awg))
                row.awg.blockSignals(False)
        elif row.kind == "wire" and pn in SLASHES:
            awg = parse_awg(row.awg.currentText())
            od = calc.typical_wire_od(pn.split("/")[1], awg) if awg is not None else None
            self._set_od(row, od, "table" if od else "no data: enter OD")
            row.typed = False
        elif not row.typed:
            self._set_od(row, None, "enter OD")
        self.recalc()

    def _od_typed(self, row: _Row):
        if self._filling:
            return
        row.typed = True
        row.source.setText("typed")
        self.recalc()

    def remove_rows(self):
        for r in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(r)
            del self.rows[r]
        self.recalc()

    def clear_rows(self):
        self.table.setRowCount(0)
        self.rows.clear()

    def load_connector(self):
        ref = self.connector.currentText()
        if not ref:
            return
        self.clear_rows()
        for br in calc.rows_from_connector(self.doc.design, ref):
            part = self.doc.design.library.get(br.pn)
            source = "library" if part and part.od else ("estimated" if br.od else "")
            self.add_row(br.kind, br.pn, br.od, br.qty, br.awg, source)
        self.recalc()

    # --- results ----------------------------------------------------------------------------
    def bundle_rows(self) -> list[calc.BundleRow]:
        return [calc.BundleRow(r.kind, r.pn.currentText().strip(), r.od.value() or None, r.qty.value(),
                               parse_awg(r.awg.currentText()) if r.kind == "wire" else None) for r in self.rows]

    def result(self) -> calc.BundleResult:
        return calc.bundle(self.bundle_rows(), self.packing.value())

    def recalc(self, *_):
        if not hasattr(self, "out_dia"):
            return
        rows = self.bundle_rows()
        for r, br in enumerate(rows):
            item = self.table.item(r, 6)
            if item is not None:
                item.setText(f"{br.od * br.od * br.qty:.5f}" if br.od else "-")
        res = calc.bundle(rows, self.packing.value())
        missing = f", {res.missing} row(s) without an OD left out" if res.missing else ""
        self.out_items.setText(f"{res.items} ({res.wires} wire(s), {res.cables} cable(s)){missing}")
        self.out_sum.setText(f"{res.sum_d2:.5f} in²")
        self.out_dia.setText(_in_mm(res.diameter) if res.diameter else "-")
        self.out_formula.setText(f"D = {self.packing.value():.2f} x sqrt(Σ d²)" if res.items > 1 else
                                 "single item: its own OD")
        for ptype, combo in self.fit_parts.items():
            self.fit_status[ptype].setText(self._fit_text(combo.currentData(), res.diameter))

    def _fit_text(self, pn: str, dia: float | None) -> str:
        if not pn:
            return "-"
        part = self.doc.design.library.get(pn)
        if part is None or dia is None:
            return "-"
        lo, hi = part.dia_range
        status = fit_status(dia, lo, hi)
        if status is None:
            return "no Dia Min/Max in the library"
        if status == FIT_OK:
            return f"OK (bundle {dia:.3f} in)"
        if hi is not None and dia > hi:
            return f"TOO BIG: max {hi:g} in, bundle {dia:.3f} in"
        return f"TOO SMALL to grip: min {lo:g} in, bundle {dia:.3f} in"

    def table_rows(self) -> list[list[str]]:
        out = [["Type", "Spec / P/N", "AWG", "OD (in)", "Source", "Qty"]]
        for r in self.rows:
            out.append([r.kind, r.pn.currentText(), r.awg.currentText(), f"{r.od.value():.3f}", r.source.text(),
                        str(r.qty.value())])
        res = self.result()
        out += [[], ["Packing factor", f"{self.packing.value():.2f}"], ["Sum d² (in²)", f"{res.sum_d2:.5f}"],
                ["Bundle diameter (in)", f"{res.diameter:.3f}" if res.diameter else ""]]
        if self.fit_enable.isChecked():
            for ptype, label in self.FIT_TYPES:
                pn = self.fit_parts[ptype].currentData()
                if pn:
                    out.append([f"{label} fit", pn, self.fit_status[ptype].text()])
        return out

    def copy(self):
        QGuiApplication.clipboard().setText("\n".join("\t".join(r) for r in self.table_rows()))

    def export_csv(self, path: str | None = None):
        if not path:
            path, _ = QFileDialog.getSaveFileName(self, "Export bundle calculation", "bundle.csv", "CSV (*.csv)")
        if not path:
            return
        buf = io.StringIO()
        csv.writer(buf).writerows(self.table_rows())
        Path(path).write_text(buf.getvalue(), encoding="utf-8")


class CalculatorsPanel(QTabWidget):
    def __init__(self, doc: Document, parent=None):
        super().__init__(parent)
        self.wire_size = WireSizeCalc()
        self.bundle = BundleCalc(doc)
        self.addTab(self.wire_size, "Wire size (AWG / CMA / mm²)")
        self.addTab(self.bundle, "Bundle diameter")
