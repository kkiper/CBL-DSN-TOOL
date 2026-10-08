"""Main window: harness canvas and drawing preview in the centre, library and properties at the sides,
tables and the live design rule check at the bottom."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QTabWidget,
)

from cable_tool import __version__ as engine_version
from cable_tool.model import CableDesign, TitleBlock
from cable_tool.project import apply_table, load_design

from . import __version__
from .canvas_view import CanvasView
from .dialogs import DesignDialog, ExportDialog, NewPartDialog
from .document import PROJECT_EXT, Document
from .library_panel import LibraryPanel
from .panels import Analyzer, DrcPanel, PreviewPanel, PropertiesPanel
from .tables import RecordTable

APP_NAME = "Cable Designer"
OPEN_FILTER = "Cable projects (*.cbl);;Wiring lists and workbooks (*.xlsx *.xls *.csv *.tsv);;All files (*)"
TABLE_FILTER = "Tables (*.xlsx *.xls *.csv *.tsv)"
TABLE_TABS = [("wires", "Wires"), ("connectors", "Connectors"), ("groups", "Groups and shields"),
              ("splices", "Splices"), ("parts", "Parts library")]


def resource_dir() -> Path:
    """Folder holding bundled samples (works from source and from a PyInstaller build)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    return base / "samples"


SAMPLES = {
    "Two-connector cable with shielded pair and splice (W101)": dict(
        wires="cable_wirelist.csv", parts="parts_library.csv", connectors="cable_connectors.csv",
        groups="cable_groups.csv", splices="cable_splices.csv", length=48.0, dwg="W101-001",
        title="CABLE ASSY, FCC TO PDU"),
    "Y-harness with breakout (W200)": dict(
        wires="y_harness_wirelist.csv", parts="parts_library.csv", connectors="y_harness_connectors.csv",
        length=None, dwg="W200-001", title="HARNESS, SENSORS A AND B"),
}


def sample_design(name: str) -> CableDesign:
    spec, root = SAMPLES[name], resource_dir()
    design, _ = load_design(spec["wires"], (root / spec["wires"]).read_bytes())
    for kind in ("parts", "connectors", "groups", "splices"):
        if spec.get(kind):
            apply_table(design, kind, spec[kind], (root / spec[kind]).read_bytes())
    design.overall_length = spec["length"]
    design.title_block = TitleBlock(drawing_number=spec["dwg"], title=spec["title"])
    return design


class MainWindow(QMainWindow):
    def __init__(self, doc: Document | None = None):
        super().__init__()
        self.doc = doc or Document()
        self.settings = QSettings("CableDesigner", "CableDesigner")
        self.analyzer = Analyzer(self.doc)

        self.canvas = CanvasView(self.doc)
        self.preview = PreviewPanel(self.doc, self.analyzer)
        self.centre = QTabWidget()
        self.centre.addTab(self.canvas, "Harness")
        self.centre.addTab(self.preview, "Drawing")
        self.setCentralWidget(self.centre)

        self.library = LibraryPanel(self.doc, self.new_part, lambda: self.import_table("parts"))
        self.props = PropertiesPanel(self.doc)
        self.tables = {key: RecordTable(self.doc, key) for key, _ in TABLE_TABS}
        self.drc = DrcPanel(self.doc, self.analyzer)
        self.bottom = QTabWidget()
        for key, title in TABLE_TABS:
            self.bottom.addTab(self.tables[key], title)
        self.bottom.addTab(self.drc, "Design rule check")
        self.docks = {}
        for name, widget, area in (("Library", self.library, Qt.LeftDockWidgetArea),
                                   ("Properties", self.props, Qt.RightDockWidgetArea),
                                   ("Tables and checks", self.bottom, Qt.BottomDockWidgetArea)):
            dock = QDockWidget(name, self)
            dock.setObjectName(name)
            dock.setWidget(widget)
            self.addDockWidget(area, dock)
            self.docks[name] = dock

        self.status_drc = QLabel()
        self.statusBar().addPermanentWidget(self.status_drc)
        self.analyzer.listeners.append(self._analysis_done)
        self.analyzer.listeners.append(self.canvas.set_analysis)
        self.doc.file_changed.connect(self._update_title)
        self.doc.selection_requested.connect(self._select_in_tables)

        self._build_menus()
        self._update_title()
        self.resize(1500, 950)
        state = self.settings.value("window_state")
        if state is not None:
            self.restoreState(state)
        self.autosave = QTimer(self)
        self.autosave.setInterval(120_000)
        self.autosave.timeout.connect(self._autosave)
        self.autosave.start()
        self.analyzer.run()

    # --- menus -------------------------------------------------------------------------------------
    def _act(self, menu, text, fn, shortcut=None, tip=""):
        a = QAction(text, self)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        if tip:
            a.setStatusTip(tip)
        a.triggered.connect(fn)
        menu.addAction(a)
        return a

    def _build_menus(self):
        mb = self.menuBar()
        f = mb.addMenu("&File")
        self._act(f, "&New", self.new_file, QKeySequence.New)
        self._act(f, "&Open…", self.open_file, QKeySequence.Open, "Open a .cbl project, or a wiring list / workbook")
        self.recent_menu = f.addMenu("Open &recent")
        samples = f.addMenu("Open &sample")
        for name in SAMPLES:
            self._act(samples, name, lambda _=False, n=name: self.open_sample(n))
        f.addSeparator()
        imp = f.addMenu("&Import into this project")
        for kind, label in (("connectors", "Connector table…"), ("groups", "Groups and shields…"),
                            ("splices", "Splice table…"), ("parts", "Parts library…")):
            self._act(imp, label, lambda _=False, k=kind: self.import_table(k))
        f.addSeparator()
        self._act(f, "&Save", self.save_file, QKeySequence.Save)
        self._act(f, "Save &as…", self.save_as, QKeySequence.SaveAs)
        self._act(f, "&Export drawing package…", self.export, "Ctrl+E", "PDF, DXF, SVG, BOM, DRC report")
        f.addSeparator()
        self._act(f, "&Quit", self.close, QKeySequence.Quit)
        self._fill_recent()

        e = mb.addMenu("&Edit")
        undo = self.doc.undo_stack.createUndoAction(self, "&Undo")
        undo.setShortcut(QKeySequence.Undo)
        redo = self.doc.undo_stack.createRedoAction(self, "&Redo")
        redo.setShortcut(QKeySequence.Redo)
        e.addAction(undo)
        e.addAction(redo)
        e.addSeparator()
        self._act(e, "Add &connector", lambda: self.canvas.add_connector(None))
        self._act(e, "Add s&plice", lambda: self.canvas.add_splice(None))
        self._act(e, "New library &part…", self.new_part)
        self._act(e, "&Delete selected", self.canvas.delete_selected)

        d = mb.addMenu("&Design")
        self._act(d, "&Title block, revisions and notes…", self.design_settings, "Ctrl+T")
        self._act(d, "&Auto layout canvas", self.canvas.auto_layout)
        self._act(d, "&Run design rule check", self._run_now, "F5")

        v = mb.addMenu("&View")
        for name, dock in self.docks.items():
            v.addAction(dock.toggleViewAction())
        self._act(v, "&Harness", lambda: self.centre.setCurrentIndex(0), "Ctrl+1")
        self._act(v, "&Drawing", lambda: self.centre.setCurrentIndex(1), "Ctrl+2")

        h = mb.addMenu("&Help")
        self._act(h, "&About", self.about)

    # --- file handling -------------------------------------------------------------------------------
    def _confirm_discard(self) -> bool:
        if not self.doc.dirty:
            return True
        r = QMessageBox.question(self, APP_NAME, "Save changes to the current project?",
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if r == QMessageBox.Save:
            return self.save_file()
        return r == QMessageBox.Discard

    def new_file(self):
        if self._confirm_discard():
            self.doc.new()

    def open_file(self, path: str | None = None):
        if not self._confirm_discard():
            return
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Open", self._last_dir(), OPEN_FILTER)
            if not path:
                return
        try:
            warnings = self.doc.open(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Open", f"Couldn't open {path}:\n{exc}")
            return
        self._remember(path)
        if warnings:
            QMessageBox.information(self, "Open", "\n".join(warnings))
        self.canvas._fitted = False
        self.canvas.refresh()

    def open_sample(self, name: str):
        if not self._confirm_discard():
            return
        self.doc.new()
        self.doc.design = sample_design(name)
        self.doc.changed.emit()
        self.canvas._fitted = False
        self.canvas.auto_layout()
        self.doc.undo_stack.clear()
        self._update_title()

    def import_table(self, kind: str):
        path, _ = QFileDialog.getOpenFileName(self, f"Import {kind}", self._last_dir(), TABLE_FILTER)
        if path:
            try:
                self.doc.import_table(kind, path)
            except Exception as exc:  # noqa: BLE001
                QMessageBox.critical(self, "Import", f"Couldn't import {path}:\n{exc}")

    def save_file(self) -> bool:
        if self.doc.path is None:
            return self.save_as()
        self.doc.save()
        self.statusBar().showMessage(f"Saved {self.doc.path}", 4000)
        return True

    def save_as(self) -> bool:
        stem = self.doc.design.title_block.drawing_number or "cable"
        path, _ = QFileDialog.getSaveFileName(self, "Save project", str(Path(self._last_dir()) / f"{stem}{PROJECT_EXT}"),
                                              "Cable project (*.cbl);;Project workbook (*.xlsx)")
        if not path:
            return False
        saved = self.doc.save(path)
        self._remember(str(saved))
        self.statusBar().showMessage(f"Saved {saved}", 4000)
        return True

    def export(self):
        dlg = ExportDialog(self.doc, self)
        if dlg.exec():
            self.statusBar().showMessage(f"Exported {len(dlg.written)} file(s) to {dlg.folder.text()}", 6000)

    def design_settings(self):
        DesignDialog(self.doc, self).exec()

    def new_part(self):
        NewPartDialog(self.doc, parent=self).exec()

    def _autosave(self):
        if self.doc.dirty:
            folder = Path(self.settings.fileName()).parent
            try:
                folder.mkdir(parents=True, exist_ok=True)
                from cable_tool import jsonio

                (folder / "autosave.cbl").write_text(jsonio.dumps(self.doc.design), encoding="utf-8")
            except OSError:
                pass

    def _last_dir(self) -> str:
        return str(self.settings.value("last_dir", str(Path.home())))

    def _remember(self, path: str):
        self.settings.setValue("last_dir", str(Path(path).parent))
        recent = [p for p in (self.settings.value("recent", []) or []) if p != path]
        self.settings.setValue("recent", ([path] + recent)[:8])
        self._fill_recent()

    def _fill_recent(self):
        self.recent_menu.clear()
        for p in self.settings.value("recent", []) or []:
            self._act(self.recent_menu, p, lambda _=False, path=p: self.open_file(path))
        self.recent_menu.setEnabled(bool(self.recent_menu.actions()))

    # --- status ------------------------------------------------------------------------------------
    def _update_title(self):
        self.setWindowTitle(f"{self.doc.title} — {APP_NAME}")

    def _analysis_done(self, analyzer):
        c = analyzer.report.counts()
        size = analyzer.sheets[0].meta.get("sheet_size", "") if analyzer.sheets else ""
        self.status_drc.setText(f"DRC: {c['ERROR']} errors, {c['WARNING']} warnings   |   {len(analyzer.sheets)} sheets, {size}")
        self._update_title()

    def _run_now(self):
        self.analyzer.run()
        self.bottom.setCurrentWidget(self.drc)

    def _select_in_tables(self, kind: str, key: str):
        table = {"wire": "wires", "connector": "connectors", "group": "groups", "splice": "splices",
                 "part": "parts"}.get(kind)
        if table:
            t = self.tables[table]
            t.view.blockSignals(True)
            t.select_key(key)
            t.view.blockSignals(False)
            if self.sender() is not None and kind in ("part", "group"):
                self.bottom.setCurrentWidget(t)

    def about(self):
        QMessageBox.about(self, f"About {APP_NAME}",
                          f"<b>{APP_NAME}</b> {__version__}<br>Drawing engine {engine_version}<br><br>"
                          "Cable and harness design with ASME Y14-format drawings (PDF, DXF, SVG), "
                          "parts library and design rule check.")

    def closeEvent(self, e):
        if self._confirm_discard():
            self.settings.setValue("window_state", self.saveState())
            e.accept()
        else:
            e.ignore()


def smoke_test(out_dir: str) -> int:
    """Headless check used by CI on the packaged app: open a sample, check it, export everything."""
    from .dialogs import export_package
    from cable_tool.drc import run_drc
    from cable_tool.drawing import build_drawing

    doc = Document(sample_design(next(iter(SAMPLES))))
    sheets, _ = build_drawing(doc.design, doc.design.sheet_size)
    report = run_drc(doc.design, sheets)
    written = export_package(doc, Path(out_dir), "smoke", {"pdf", "dxf", "svg", "bom", "drc", "xlsx"})
    print(f"{len(sheets)} sheets, {report.counts()}, {len(written)} files written to {out_dir}")
    return 0 if written and report.counts()["ERROR"] == 0 else 1


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    if "--smoke-test" in argv:
        i = argv.index("--smoke-test")
        out = argv[i + 1] if len(argv) > i + 1 else "smoke-test-output"
        app = QApplication.instance() or QApplication(argv)
        return smoke_test(out)
    app = QApplication.instance() or QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("CableDesigner")
    icon = resource_dir().parent / "packaging" / "icon.png"
    if icon.exists():
        from PySide6.QtGui import QIcon

        app.setWindowIcon(QIcon(str(icon)))
    win = MainWindow()
    files = [a for a in argv[1:] if not a.startswith("-")]
    if files:
        win.open_file(files[0])
    win.show()
    return app.exec()
