"""Editing helpers shared by the desktop app (and usable from scripts)."""

from __future__ import annotations

from .model import CableDesign

PN_FIELDS = {
    "connectors": ("connector_pn", "contact_pn", "backshell_pn", "heatshrink_pn", "label_pn"),
    "wires": ("wire_pn", "label_pn", "heatshrink_pn"),
    "groups": ("cable_pn", "shield_pn", "shield_term_pn"),
    "splices": ("splice_pn",),
}


def rename(design: CableDesign, kind: str, old: str, new: str) -> None:
    """Rename a connector, splice, group or part and update every reference to it."""
    if not new or old == new:
        return
    if kind in ("connector", "splice"):
        for w in design.wires:
            if w.from_ref == old:
                w.from_ref = new
            if w.to_ref == old:
                w.to_ref = new
        for sp in design.splices:
            if sp.near == old:
                sp.near = new
        for g in design.groups:
            for attr in ("term_from", "term_to"):
                val = getattr(g, attr)
                if val.upper().startswith(old.upper() + "-"):
                    setattr(g, attr, new + val[len(old):])
        if old in design.layout:
            design.layout[new] = design.layout.pop(old)
    elif kind == "group":
        for w in design.wires:
            if w.group == old:
                w.group = new
    elif kind == "part":
        for attr_list, fields in PN_FIELDS.items():
            for rec in getattr(design, attr_list):
                for f in fields:
                    if getattr(rec, f) == old:
                        setattr(rec, f, new)
        for p in design.library.parts.values():
            if p.contact_pn == old:
                p.contact_pn = new
        if old in design.part_descriptions:
            design.part_descriptions[new] = design.part_descriptions.pop(old)
