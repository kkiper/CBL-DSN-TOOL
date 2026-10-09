"""Desktop app tests (headless Qt via pytest-qt)."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from cable_desktop.canvas_view import PART_MIME, ConnectorItem, connector_pins  # noqa: E402
from cable_desktop.dialogs import NewPartDialog, export_package  # noqa: E402
from cable_desktop.document import Document  # noqa: E402
from cable_desktop.mainwindow import SAMPLES, MainWindow, sample_design  # noqa: E402
from cable_tool.model import ConnectorEnd  # noqa: E402

W101 = next(iter(SAMPLES))


@pytest.fixture
def win(qtbot, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings

    from PySide6.QtWidgets import QMessageBox

    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    # Never block on a modal box in tests
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Discard))
    for name in ("information", "warning", "critical"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *a, **k: QMessageBox.Ok))
    w = MainWindow()
    qtbot.addWidget(w)
    w.resize(1400, 900)
    w.show()
    w.open_sample(W101)
    w.analyzer.run()
    yield w
    w.doc.undo_stack.setClean()


def test_sample_loads_everywhere(win):
    assert set(win.canvas.scene.connectors) == {"P1", "P2"} and set(win.canvas.scene.splices) == {"SP1"}
    assert len(win.canvas.scene.wires) == 13
    assert win.tables["wires"].model.rowCount() == 13
    assert win.preview.tabs.count() == len(win.analyzer.sheets) >= 3
    assert win.analyzer.report.counts()["ERROR"] == 0
    assert "DRC: 0 errors" in win.status_drc.text()


def test_edit_cell_and_undo(win):
    model = win.tables["wires"].model
    idx = model.index(0, 5)                       # W1 signal
    assert model.setData(idx, "+28V MAIN")
    assert win.doc.design.wires[0].signal == "+28V MAIN" and win.doc.dirty
    win.doc.undo_stack.undo()
    assert win.doc.design.wires[0].signal == "+28V PWR"
    win.doc.undo_stack.redo()
    assert win.doc.design.wires[0].signal == "+28V MAIN"


def test_rename_connector_updates_references(win):
    model = win.tables["connectors"].model
    assert model.setData(model.index(model.row_of("P2"), 0), "J7")
    d = win.doc.design
    assert d.connector("J7") and not d.connector("P2")
    assert all("P2" not in (w.from_ref, w.to_ref) for w in d.wires)
    assert d.splice("SP1").near == "J7" and d.group("TSP1").term_to == "J7-L"


def test_drag_pin_to_pin_creates_wire(win, qtbot):
    canvas = win.canvas
    canvas.wire_pn.setCurrentText("M22759/16-22-9")
    scene, view = canvas.scene, canvas.view
    p1, p2 = scene.connectors["P1"], scene.connectors["P2"]
    a, b = p1.port_pos("N"), p2.port_pos("N")
    vp = view.viewport()
    pa, pb = view.mapFromScene(a), view.mapFromScene(b)
    QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, pa)
    QTest.mouseMove(vp, QPoint((pa.x() + pb.x()) // 2, pa.y()))
    QTest.mouseMove(vp, pb)
    QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, pb)
    new = win.doc.design.wires[-1]
    assert (new.wire_id, new.from_ref, new.from_pin, new.to_ref, new.to_pin) == ("W14", "P1", "N", "P2", "N")
    assert new.wire_pn == "M22759/16-22-9" and new.gauge == "22" and new.color == "WHT"   # from the library
    assert len(win.canvas.scene.wires) == 14
    win.analyzer.run()
    assert win.tables["wires"].model.rowCount() == 14


def test_library_drops(win):
    canvas = win.canvas
    p1 = canvas.scene.connectors["P1"]
    canvas.drop_part("M85049/52-1-14W", p1.port_pos("1"), [p1])            # backshell onto a connector
    assert win.doc.design.connector("P1").backshell_pn == "M85049/52-1-14W"
    canvas.drop_part("MS3126F10-6P", QPointF(900, 600), [])                 # connector onto empty canvas
    new = win.doc.design.connectors[-1]
    assert new.ref == "P3" and new.connector_pn == "MS3126F10-6P" and win.doc.design.layout["P3"] == (900, 600)
    assert len(connector_pins(win.doc.design, new)) == 6                  # from the library's contact count
    wire = next(w for w in canvas.scene.wires if w.wire_id == "W7")
    canvas.drop_part("M22759/16-20-0", QPointF(0, 0), [wire])               # wire part onto a wire
    w7 = next(w for w in win.doc.design.wires if w.wire_id == "W7")
    assert (w7.wire_pn, w7.gauge, w7.color) == ("M22759/16-20-0", "20", "BLK")


def test_drop_mime_from_library_tree(win):
    md = win.library.tree.mimeData([win.library.tree.topLevelItem(0).child(0)])
    assert md.hasFormat(PART_MIME) and bytes(md.data(PART_MIME)).decode()
    assert isinstance(md, QMimeData)


def test_group_and_delete(win):
    canvas = win.canvas
    canvas.group_wires(["W7", "W8"], "SHIELDED TWISTED PAIR")
    g = win.doc.design.group("TSP2")
    assert g and g.term_from == "BACKSHELL" and {w.wire_id for w in win.doc.design.group_members("TSP2")} == {"W7", "W8"}
    for it in canvas.scene.wires:
        it.setSelected(it.wire_id == "W11")
    canvas.delete_selected()
    assert not any(w.wire_id == "W11" for w in win.doc.design.wires)
    win.doc.undo_stack.undo()
    assert any(w.wire_id == "W11" for w in win.doc.design.wires)


def test_drc_highlights_on_canvas(win):
    d = win.doc.design
    d.library.get("M39029/56-351").awg_min, d.library.get("M39029/56-351").awg_max = 22, 28   # 20 AWG no longer fits
    win.doc.changed.emit()
    win.analyzer.run()
    assert win.analyzer.report.counts()["ERROR"] > 0
    assert win.canvas.scene.connectors["P1"].severity == "ERROR"


def test_move_is_saved_and_undoable(win):
    item = win.canvas.scene.connectors["P2"]
    item.setPos(QPointF(1000, 50))
    item.moved.emit("P2", item.pos())
    assert win.doc.design.layout["P2"] == (1000, 50)
    win.doc.undo_stack.undo()
    assert win.doc.design.layout["P2"] != (1000, 50)


def test_save_open_and_export(win, tmp_path):
    path = win.doc.save(tmp_path / "w101")
    assert path.suffix == ".cbl" and not win.doc.dirty
    doc = Document()
    doc.open(path)
    assert len(doc.design.wires) == 13 and doc.design.layout and doc.design.library.get("M81824/1-1")
    written = export_package(doc, tmp_path / "out", "W101", {"pdf", "dxf", "bom", "drc", "xlsx", "svg"})
    names = {p.name for p in written}
    assert {"W101.pdf", "W101_bom.csv", "W101_drc.csv", "W101_project.xlsx", "W101_sheet1.dxf", "W101_sheet1.svg"} <= names
    assert (tmp_path / "out" / "W101.pdf").read_bytes().startswith(b"%PDF")


def test_new_part_dialog(win):
    dlg = NewPartDialog(win.doc, "backshell", win)
    dlg.pn.setText("BS-123")
    dlg.inputs["dia_min"].setText("0.1")
    dlg.inputs["dia_max"].setText("0.3")
    dlg.accept()
    p = win.doc.design.library.get("BS-123")
    assert p.type == "backshell" and p.dia_range == (0.1, 0.3)


def test_open_wiring_list_csv(win, tmp_path):
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "samples" / "y_harness_wirelist.csv"
    win.doc.undo_stack.setClean()
    win.open_file(str(src))
    assert {c.ref for c in win.doc.design.connectors} == {"P1", "P2", "P3"}
    assert isinstance(win.canvas.scene.connectors["P1"], ConnectorItem)
    assert sample_design(W101).overall_length == 48 and ConnectorEnd


def test_import_sample_library(win):
    from cable_desktop.mainwindow import SAMPLE_LIBRARIES

    for name in SAMPLE_LIBRARIES:
        win.import_sample_library(name)
    lib = win.doc.design.library
    assert lib.get("D38999/26WD35SN").contacts == 37 and lib.get("M22759/32-22-9").awg == 22
    win.doc.undo_stack.undo()
    assert win.doc.design.library.get("M22759/32-22-9") is None


def test_contact_info_and_contacts_included_column(win):
    from cable_desktop.panels import contact_info
    from cable_desktop.tables import SPECS

    d = win.doc.design
    text = contact_info(d, "connector", d.connector("P1"))
    assert "M39029/56-351" in text and "Supplied with the connector" in text and "Insert 15-18" in text
    col = next(c for c in SPECS["parts"].columns if c.field == "contacts_included")
    assert col.kind == "bool"


def test_calculators_tab(win, tmp_path):
    calc_panel = win.calculators
    assert win.centre.indexOf(calc_panel) == 2 and win.centre.tabText(2) == "Calculators"
    ws = calc_panel.wire_size
    ws.awg.setCurrentText("22")
    assert ws.out["cma"].text() == "754 cmil" and ws.out["nearest"].text().startswith("22 AWG (19/34)")
    ws.set_mode("Strands")
    ws.strand_size.setValue(32)
    ws.strand_count.setValue(19)
    assert ws.out["nearest"].text().startswith("20 AWG")
    ws._row_clicked(0, 0)                                  # reference table row -> AWG 26
    assert ws.mode_key() == "AWG" and ws.awg.currentText() == "26" and ws.out["cma"].text() == "304 cmil"

    b = calc_panel.bundle
    b.clear_rows()
    b.add_row("wire", "M22759/16", None, 2, 20)
    b.add_row("wire", "M22759/16", None, 6, 22)
    assert b.rows[0].source.text() == "table" and b.rows[0].od.value() == pytest.approx(0.062)
    cable = b.add_row("cable", "M27500-22TG2T14")
    assert cable.source.text() == "library" and cable.od.value() == pytest.approx(0.135)
    typed = b.add_row("cable", "M27500-20SB3T23")
    typed.od.setValue(0.180)
    assert typed.source.text() == "typed"
    assert b.out_dia.text().startswith("0.328 in")
    b.packing.setValue(1.3)
    assert b.out_dia.text().startswith("0.355 in")
    # fit check against library parts, and its on/off switch
    combo = b.fit_parts["backshell"]
    combo.setCurrentIndex(combo.findData("M85049/38S15W"))
    assert b.fit_status["backshell"].text().startswith("OK")
    b.fit_enable.setChecked(False)
    assert b.fit_box.isHidden()
    b.fit_enable.setChecked(True)
    # load from a connector, and its on/off switch
    b.connector.setCurrentText("P1")
    b.packing.setValue(1.2)
    b.load_connector()
    assert sum(r.qty.value() for r in b.rows) == 10 and b.out_dia.text().startswith("0.257 in")
    b.load_enable.setChecked(False)
    assert b.load_btn.isHidden() and b.connector.isHidden()
    out = tmp_path / "bundle.csv"
    b.export_csv(str(out))
    text = out.read_text()
    assert "Bundle diameter (in),0.257" in text and "M27500-22TG2T14" in text
