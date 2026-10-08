"""The open project: design data, undo/redo, file I/O, and change notification.

Every edit goes through :meth:`Document.edit`, which snapshots the design before and after so it can be undone.
Panels and the canvas listen to :attr:`Document.changed` and redraw from :attr:`Document.design`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QUndoCommand, QUndoStack

from cable_tool import jsonio
from cable_tool.model import CableDesign
from cable_tool.project import apply_table, load_design, save_design, sync_connectors

PROJECT_EXT = ".cbl"


class _Snapshot(QUndoCommand):
    def __init__(self, doc: "Document", text: str, before: str, after: str):
        super().__init__(text)
        self.doc, self.before, self.after = doc, before, after
        self._first = True

    def redo(self):
        if self._first:          # the edit has already been applied
            self._first = False
            return
        self.doc._restore(self.after)

    def undo(self):
        self.doc._restore(self.before)


class Document(QObject):
    changed = Signal()                       # design content changed (redraw everything)
    selection_requested = Signal(str, str)   # kind ("wire", "connector", "group", "splice", "part"), key
    file_changed = Signal()                  # path or dirty flag changed

    def __init__(self, design: CableDesign | None = None):
        super().__init__()
        self.design = design or CableDesign()
        self.path: Path | None = None
        self.undo_stack = QUndoStack(self)
        self.undo_stack.cleanChanged.connect(lambda _clean: self.file_changed.emit())

    # --- editing ---------------------------------------------------------------------------------
    def edit(self, text: str, fn: Callable[[CableDesign], object]):
        """Apply ``fn`` to the design as one undoable step. Returns ``fn``'s result."""
        before = jsonio.dumps(self.design)
        result = fn(self.design)
        sync_connectors(self.design)
        after = jsonio.dumps(self.design)
        if after != before:
            self.undo_stack.push(_Snapshot(self, text, before, after))
            self.changed.emit()
        return result

    def _restore(self, text: str) -> None:
        self.design = jsonio.loads(text)
        self.changed.emit()

    @property
    def dirty(self) -> bool:
        return not self.undo_stack.isClean()

    def select(self, kind: str, key: str) -> None:
        self.selection_requested.emit(kind, key)

    # --- files -----------------------------------------------------------------------------------
    def new(self) -> None:
        self.design = CableDesign()
        self.path = None
        self.undo_stack.clear()
        self.changed.emit()
        self.file_changed.emit()

    def open(self, path: str | Path) -> list[str]:
        """Open a .cbl project, or a wiring list / project workbook (.xlsx, .csv). Returns load warnings."""
        path = Path(path)
        warnings: list[str] = []
        if path.suffix.lower() == PROJECT_EXT:
            design = jsonio.loads(path.read_text(encoding="utf-8"))
            self.path = path
        else:
            design, warnings = load_design(path.name, path.read_bytes())
            self.path = None           # imported: "Save" asks where to put the .cbl
        self.design = design
        self.undo_stack.clear()
        self.changed.emit()
        self.file_changed.emit()
        return warnings

    def import_table(self, kind: str, path: str | Path) -> None:
        """Merge a connectors / groups / splices / parts-library file into the design (undoable)."""
        path = Path(path)
        data = path.read_bytes()
        self.edit(f"Import {kind}", lambda d: apply_table(d, kind, path.name, data))

    def save(self, path: str | Path | None = None) -> Path:
        path = Path(path) if path else self.path
        if path is None:
            raise ValueError("No file name")
        if path.suffix.lower() == ".xlsx":
            path.write_bytes(save_design(self.design))
        else:
            if path.suffix.lower() != PROJECT_EXT:
                path = path.with_suffix(PROJECT_EXT)
            path.write_text(jsonio.dumps(self.design), encoding="utf-8")
            self.path = path
            self.undo_stack.setClean()
        self.file_changed.emit()
        return path

    @property
    def title(self) -> str:
        name = self.path.name if self.path else (self.design.title_block.drawing_number or "Untitled")
        return f"{name}{' *' if self.dirty else ''}"
