"""Native project file (.cbl): the whole design as JSON, including canvas positions and revision history."""

from __future__ import annotations

import json
from dataclasses import asdict, fields

from .library import Part, PartsLibrary
from .model import CableDesign, ConnectorEnd, Revision, Splice, TitleBlock, Wire, WireGroup

FORMAT = "cable-designer-project"
VERSION = 1


def _build(cls, data: dict):
    names = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in (data or {}).items() if k in names})


def design_to_dict(design: CableDesign) -> dict:
    return {
        "format": FORMAT,
        "version": VERSION,
        "title_block": asdict(design.title_block),
        "connectors": [asdict(c) for c in design.connectors],
        "wires": [asdict(w) for w in design.wires],
        "groups": [asdict(g) for g in design.groups],
        "splices": [asdict(s) for s in design.splices],
        "revisions": [asdict(r) for r in design.revisions],
        "notes": list(design.notes),
        "part_descriptions": dict(design.part_descriptions),
        "library": {"source": design.library.source, "parts": [asdict(p) for p in design.library.parts.values()]},
        "layout": {k: list(v) for k, v in design.layout.items()},
        "sheet_size": design.sheet_size,
        "units": design.units,
        "tolerance": design.tolerance,
        "overall_length": design.overall_length,
        "datum": design.datum,
    }


def design_from_dict(data: dict) -> CableDesign:
    if data.get("format") != FORMAT:
        raise ValueError("Not a cable designer project file")
    lib = PartsLibrary(source=data.get("library", {}).get("source", ""))
    for p in data.get("library", {}).get("parts", []):
        lib.add(_build(Part, p))
    d = CableDesign(
        title_block=_build(TitleBlock, data.get("title_block", {})),
        connectors=[_build(ConnectorEnd, c) for c in data.get("connectors", [])],
        wires=[_build(Wire, w) for w in data.get("wires", [])],
        groups=[_build(WireGroup, g) for g in data.get("groups", [])],
        splices=[_build(Splice, s) for s in data.get("splices", [])],
        revisions=[_build(Revision, r) for r in data.get("revisions", [])],
        notes=list(data.get("notes", [])),
        part_descriptions=dict(data.get("part_descriptions", {})),
        library=lib,
        layout={k: tuple(v) for k, v in data.get("layout", {}).items()},
        units=data.get("units", "IN"),
        tolerance=data.get("tolerance", "0.5"),
        overall_length=data.get("overall_length"),
        datum=data.get("datum", ""),
    )
    if data.get("sheet_size"):
        d.sheet_size = data["sheet_size"]
    return d


def dumps(design: CableDesign) -> str:
    return json.dumps(design_to_dict(design), indent=1)


def loads(text: str) -> CableDesign:
    return design_from_dict(json.loads(text))
