"""Editing helpers shared by the desktop app (and usable from scripts)."""

from __future__ import annotations

import re

from .model import SHIELD_BACKSHELL, SHIELD_FLOAT, CableDesign, WireGroup

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
        for g in design.groups:
            if g.parent == old:
                g.parent = new
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


def next_group_id(design: CableDesign, prefix: str) -> str:
    used = {g.group_id for g in design.groups}
    n = 1
    while f"{prefix}{n}" in used:
        n += 1
    return f"{prefix}{n}"


def add_shield(design: CableDesign, wire_ids, kind: str = "SHIELDED", term_from: str = SHIELD_BACKSHELL,
               term_to: str = SHIELD_FLOAT) -> str:
    """Put a shield over the given wires and return its group id.

    Wires already in a pair or cable go in with their whole pair or cable, and the outermost group that lies wholly
    inside the selection becomes a child of the new shield (so a shield over two cables keeps the cables as they
    are). The new shield nests inside any group that already encloses everything selected."""
    selected = set(wire_ids)
    # a pair or cable can't be split: take in the whole of one that is only partly selected (a plain shield can be:
    # the new shield then goes inside it)
    for w in design.wires:
        g = design.group(w.group) if w.wire_id in selected and w.group else None
        if g and (g.twisted or g.jacketed):
            selected |= {m.wire_id for m in design.group_members(g.group_id)}
    if not selected:
        raise ValueError("no wires selected")

    def inside(gid: str) -> bool:
        return all(m.wire_id in selected for m in design.group_members(gid))

    tops: dict[str, None] = {}
    loose = []
    for w in design.wires:
        if w.wire_id not in selected:
            continue
        top = ""
        for gid in design.group_chain(w.group):
            if inside(gid):
                top = gid
            else:
                break
        if top:
            tops[top] = None
        else:
            loose.append(w)
    parents = {design.group(t).parent for t in tops} | {w.group for w in loose}
    gid = next_group_id(design, "S")
    shield = WireGroup(gid, kind, term_from=term_from, term_to=term_to,
                       parent=parents.pop() if len(parents) == 1 else "")
    design.groups.append(shield)
    for t in tops:
        design.group(t).parent = gid
    for w in loose:
        w.group = gid
    return gid


def remove_group(design: CableDesign, gid: str) -> None:
    """Delete group ``gid``: its wires and nested groups move up to its parent."""
    g = design.group(gid)
    if g is None:
        return
    for w in design.wires:
        if w.group == gid:
            w.group = g.parent
    for k in design.groups:
        if k.parent == gid:
            k.parent = g.parent
    design.groups = [k for k in design.groups if k.group_id != gid]


def set_shield_term(design: CableDesign, gid: str, ref: str, value: str) -> None:
    """Set the shield termination of ``gid`` at connector ``ref`` (the From end, or the far end(s))."""
    g = design.group(gid)
    if g is None:
        return
    a, _b = design.group_ends(gid)
    if ref == a:
        g.term_from = value
    else:
        g.term_to = value
    if re.fullmatch(r"(?i)shell|backshell", value or ""):
        c = design.connector(ref)
        if c:
            c.show_shell = True
