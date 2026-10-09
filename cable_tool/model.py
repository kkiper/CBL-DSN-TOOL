"""Data model for a cable assembly: connector ends, wires, groups (twisted / shielded), splices."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .library import PartsLibrary


@dataclass
class ConnectorEnd:
    """One end of the cable: a connector plus the hardware that goes with it."""

    ref: str                      # reference designator, e.g. P1, J2
    connector_pn: str = ""
    backshell_pn: str = ""
    heatshrink_pn: str = ""       # boot / transition shrink over the backshell
    label_pn: str = ""            # identification label/marker sleeve on the cable near this end
    label_text: str = ""          # legend printed on the label; defaults to the ref designator
    length: float | None = None   # distance from the connector face to the breakout (or the far end)
    description: str = ""         # e.g. "TO FLIGHT COMPUTER"
    contact_pn: str = ""          # contact used in this connector (else the library's default)
    show_shell: bool = False      # show the connector's SHELL connection (shield-to-shell/backshell) on the canvas
    pin_order: list = field(default_factory=list)   # display order of the pin rows (canvas and wiring diagram)

    @property
    def legend(self) -> str:
        return self.label_text or self.ref


@dataclass
class Wire:
    wire_id: str
    from_ref: str
    from_pin: str
    to_ref: str
    to_pin: str
    signal: str = ""
    gauge: str = ""
    color: str = ""
    wire_pn: str = ""
    length: float | None = None
    label_pn: str = ""            # wire marker, one at each end
    heatshrink_pn: str = ""       # e.g. ID / insulation sleeve, one at each end
    notes: str = ""
    group: str = ""               # twisted / shielded group or cable this wire belongs to


SHIELD_BACKSHELL = "BACKSHELL"
SHIELD_FLOAT = "FLOAT"


@dataclass
class WireGroup:
    """Wires that are twisted together, shielded together, or are conductors of one jacketed cable."""

    group_id: str
    kind: str = "TWISTED PAIR"    # TWISTED PAIR / TWISTED TRIPLE / SHIELDED / SHIELDED TWISTED PAIR / CABLE
    cable_pn: str = ""            # pre-made cable (e.g. M27500 shielded pair); members are its conductors
    shield_pn: str = ""           # overall braid / shield sleeving for a built-up group
    shield_term_pn: str = ""      # shield termination part (solder sleeve, band, ...) per terminated end
    term_from: str = ""           # shield at the group's From end: BACKSHELL, FLOAT, or a pin (12 / P1-12)
    term_to: str = ""             # shield at the group's To end (and at every other far end of an overall shield)
    notes: str = ""
    parent: str = ""              # enclosing group, e.g. the overall shield this pair or cable runs inside

    @property
    def twisted(self) -> bool:
        k = self.kind.upper().replace(" ", "")
        return "TWIST" in k or k in ("TP", "TSP", "STP", "TT", "TQ")

    @property
    def shielded(self) -> bool:
        k = self.kind.upper().replace(" ", "")
        return "SHIELD" in k or "SCREEN" in k or k in ("TSP", "STP", "SP", "S")

    @property
    def jacketed(self) -> bool:
        return bool(self.cable_pn) or "CABLE" in self.kind.upper() or "JACKET" in self.kind.upper()


@dataclass
class Splice:
    ref: str                      # SP1, SP2, ...
    splice_pn: str = ""
    near: str = ""                # connector whose leg the splice is on
    distance: float | None = None  # from that connector's face
    notes: str = ""


@dataclass
class TitleBlock:
    """ASME Y14.1 title block, application block and approvals."""

    title: str = "CABLE ASSEMBLY"
    drawing_number: str = ""
    revision: str = "-"
    company: str = ""              # name (and address) of the design activity
    cage_code: str = ""            # CAGE code of the design activity
    drawn_by: str = ""
    date: str = ""                 # date drawn
    checked_by: str = ""
    checked_date: str = ""
    engineer: str = ""
    engineer_date: str = ""
    approved_by: str = ""
    approved_date: str = ""
    contract_number: str = ""
    scale: str = "NONE"
    weight: str = ""
    next_assy: str = ""            # application block
    used_on: str = ""
    statement: str = ""            # proprietary / distribution statement


@dataclass
class Revision:
    """One row of the ASME Y14.35 revision block."""

    rev: str
    description: str = ""
    date: str = ""
    approved: str = ""
    zone: str = ""


UNIT_NAMES = {"IN": "INCHES", "MM": "MILLIMETERS", "CM": "CENTIMETERS", "FT": "FEET", "M": "METERS"}
UNIT_PER_INCH = {"IN": 1.0, "MM": 25.4, "CM": 2.54, "FT": 1 / 12, "M": 0.0254}

DEFAULT_NOTES = [
    "INTERPRET DRAWING PER ASME Y14.100.",
    "DIMENSIONS ARE IN {UNITS_NAME}. LENGTH TOLERANCE ±{TOL} {UNITS}.",
    "WIRE PER WIRE LIST. TERMINATE CONTACTS PER CONNECTOR MANUFACTURER'S INSTRUCTIONS.",
    "100% CONTINUITY AND ISOLATION TEST PER WIRE LIST.",
]

SPLICE_REF = re.compile(r"^(SP|SPL|SPLICE)[-_ ]?\d+[A-Z]?$", re.I)


@dataclass
class CableDesign:
    title_block: TitleBlock = field(default_factory=TitleBlock)
    connectors: list[ConnectorEnd] = field(default_factory=list)
    wires: list[Wire] = field(default_factory=list)
    groups: list[WireGroup] = field(default_factory=list)
    splices: list[Splice] = field(default_factory=list)
    notes: list[str] = field(default_factory=lambda: list(DEFAULT_NOTES))
    part_descriptions: dict[str, str] = field(default_factory=dict)
    library: PartsLibrary = field(default_factory=PartsLibrary)
    revisions: list[Revision] = field(default_factory=list)
    layout: dict[str, tuple[float, float]] = field(default_factory=dict)   # canvas positions by ref (desktop app)
    sheet_size: str = "ANSI B (17 x 11 in)"                                # smallest drawing sheet size
    units: str = "IN"
    tolerance: str = "0.5"
    overall_length: float | None = None   # used for two-connector cables when ends have no lengths
    datum: str = ""                       # connector whose face is DATUM A (IPC-D-620); blank = the first connector

    # Lookups ---------------------------------------------------------------
    def connector(self, ref: str) -> ConnectorEnd | None:
        return next((c for c in self.connectors if c.ref == ref), None)

    def splice(self, ref: str) -> Splice | None:
        return next((s for s in self.splices if s.ref == ref), None)

    def group(self, gid: str) -> WireGroup | None:
        return next((g for g in self.groups if g.group_id == gid), None)

    def is_splice(self, ref: str) -> bool:
        return self.splice(ref) is not None or (self.connector(ref) is None and bool(SPLICE_REF.match(ref or "")))

    def group_chain(self, gid: str) -> list[str]:
        """``gid`` and the groups enclosing it, innermost first (stops at a missing group or a cycle)."""
        chain: list[str] = []
        while gid and gid not in chain:
            chain.append(gid)
            g = self.group(gid)
            gid = g.parent if g else ""
        return chain

    def group_members(self, gid: str) -> list[Wire]:
        """Every wire inside group ``gid``, including the wires of groups nested in it."""
        return [w for w in self.wires if w.group and gid in self.group_chain(w.group)]

    def direct_members(self, gid: str) -> list[Wire]:
        """Wires assigned to ``gid`` itself (not through a nested group)."""
        return [w for w in self.wires if w.group == gid]

    def group_children(self, gid: str) -> list[WireGroup]:
        return [g for g in self.groups if g.parent == gid and g.group_id != gid]

    def group_level(self, gid: str) -> int:
        """Nesting depth below ``gid``: 0 for a group with no nested groups, 1 for a shield over pairs, ..."""
        kids = [k for k in self.group_children(gid) if self.group_members(k.group_id)]
        return 1 + max(self.group_level(k.group_id) for k in kids) if kids and len(self.group_chain(gid)) < 20 else 0

    def description(self, pn: str) -> str:
        return (self.part_descriptions.get(pn) or self.library.description(pn) or "").strip()

    def contacts_included(self, ref: str) -> bool:
        """Is connector ``ref`` supplied with its contacts (so they aren't ordered separately)?"""
        from .library import contacts_included

        c = self.connector(ref)
        return bool(c) and contacts_included(c.connector_pn, self.library.get(c.connector_pn))

    def contact_pn(self, ref: str) -> str:
        c = self.connector(ref)
        if not c:
            return ""
        if c.contact_pn:
            return c.contact_pn
        part = self.library.get(c.connector_pn)
        return part.contact_pn if part else ""

    def datum_ref(self) -> str:
        """Connector whose face is the dimensioning datum (IPC-D-620): ``datum`` if set, else the first connector."""
        if self.datum and self.connector(self.datum):
            return self.datum
        return self.connectors[0].ref if self.connectors else ""

    # Lengths ---------------------------------------------------------------
    def leg_length(self, ref: str) -> float | None:
        c = self.connector(ref)
        return c.length if c else None

    def end_to_end_length(self) -> float | None:
        """Overall length of a two-connector cable."""
        if len(self.connectors) != 2:
            return None
        if self.overall_length:
            return self.overall_length
        a, b = (c.length for c in self.connectors)
        return a + b if a is not None and b is not None else None

    def _position(self, ref: str) -> tuple[str, float] | None:
        """(connector whose leg it's on, distance from that connector's face)."""
        if self.connector(ref):
            return (ref, 0.0)
        sp = self.splice(ref)
        if sp and sp.near and sp.distance is not None and self.connector(sp.near):
            return (sp.near, sp.distance)
        return None

    def path_length(self, ref_a: str, ref_b: str) -> float | None:
        pa, pb = self._position(ref_a), self._position(ref_b)
        if pa is None or pb is None:
            return None
        (a, da), (b, db) = pa, pb
        if a == b:
            return abs(da - db) if ref_a != ref_b else None
        if len(self.connectors) == 2 and self.end_to_end_length() is not None:
            return self.end_to_end_length() - da - db
        la, lb = self.leg_length(a), self.leg_length(b)
        return (la - da) + (lb - db) if la is not None and lb is not None else None

    def wire_length(self, wire: Wire) -> float | None:
        """Wire cut length: explicit value, otherwise the cable path between its two ends."""
        if wire.length is not None:
            return wire.length
        return self.path_length(wire.from_ref, wire.to_ref)

    def group_length(self, gid: str) -> float | None:
        lengths = [self.wire_length(w) for w in self.group_members(gid)]
        if not lengths or any(v is None for v in lengths):
            return None
        return max(lengths)

    # Groups ------------------------------------------------------------------
    def group_ends(self, gid: str) -> tuple[str, str]:
        """(From connector, To connector) of a group, taken from its first member."""
        members = self.group_members(gid)
        return (members[0].from_ref, members[0].to_ref) if members else ("", "")

    def group_refs(self, gid: str) -> list[str]:
        """Connectors and splices a group's wires end at, its From end first."""
        members = self.group_members(gid)
        if not members:
            return []
        refs = [members[0].from_ref, members[0].to_ref]
        for w in members[1:]:
            refs += [w.from_ref, w.to_ref]
        return list(dict.fromkeys(r for r in refs if r))

    def shield_term_at(self, g: WireGroup, ref: str) -> str:
        """Shield termination at ``ref``: term_from at the group's From end, term_to at every other end."""
        a, b = self.group_ends(g.group_id)
        if ref == a:
            return g.term_from
        if ref == b or ref in self.group_refs(g.group_id):
            return g.term_to
        return ""

    def shell_terminations(self, ref: str) -> list[WireGroup]:
        """Shielded groups whose shield is terminated to connector ``ref``'s shell or backshell."""
        out = []
        for g in self.groups:
            if g.shielded and self.group_members(g.group_id):
                kind, _ = parse_shield_term(self.shield_term_at(g, ref), ref)
                if kind == SHIELD_BACKSHELL:
                    out.append(g)
        return out

    def shell_shown(self, ref: str) -> bool:
        """Show the SHELL connection of ``ref``: switched on, or a shield is terminated to it."""
        c = self.connector(ref)
        return bool(c) and (c.show_shell or bool(self.shell_terminations(ref)))

    def shell_name(self, ref: str) -> str:
        """What a SHELL termination lands on: the backshell if the connector has one, else the connector shell."""
        c = self.connector(ref)
        return "BACKSHELL" if c and c.backshell_pn else "CONNECTOR SHELL"

    def shield_pins(self, ref: str) -> list[tuple[WireGroup, str]]:
        """Shield terminations that land on a pin of connector ``ref``: [(group, pin)]."""
        out = []
        for g in self.groups:
            kind, pin = parse_shield_term(self.shield_term_at(g, ref), ref)
            if kind == "PIN" and pin and self.group_members(g.group_id):
                out.append((g, pin))
        return out

    def pins_used(self, ref: str) -> list[str]:
        pins = []
        for w in self.wires:
            for r, p in ((w.from_ref, w.from_pin), (w.to_ref, w.to_pin)):
                if r == ref and p and p not in pins:
                    pins.append(p)
        for _, p in self.shield_pins(ref):
            if p not in pins:
                pins.append(p)
        return sorted(pins, key=natural_key)

    def contact_positions(self, ref: str) -> list[str]:
        """Every contact position of connector ``ref``: from its insert layout, else 1..N from the library's contact
        count when the pins are numbered. Empty when unknown."""
        from .inserts import layout_for

        c = self.connector(ref)
        if not c:
            return []
        found = layout_for(c.connector_pn)
        if found:
            return [cav.contact for cav in found[1]]
        part = self.library.get(c.connector_pn)
        used = self.pins_used(ref)
        if part and part.contacts and all(p.isdigit() for p in used):
            return [str(i) for i in range(1, int(part.contacts) + 1)]
        return []

    def pin_sort_key(self, ref: str):
        """Sort key for ``ref``'s pins: the connector's own row order first, then natural order."""
        c = self.connector(ref)
        order = {p: i for i, p in enumerate(c.pin_order)} if c else {}
        return lambda pin: (0, order[pin], []) if pin in order else (1, 0, natural_key(pin))

    def pin_group(self, ref: str, pin: str) -> str:
        """Innermost group of whatever is on ``ref``-``pin`` (a wire, or a shield drain), or ''."""
        for w in self.wires:
            if w.group and ((w.from_ref, w.from_pin) == (ref, pin) or (w.to_ref, w.to_pin) == (ref, pin)):
                return w.group
        for g, p in self.shield_pins(ref):
            if p == pin:
                return g.group_id
        return ""

    def arranged_pins(self, ref: str, pins: list[str]) -> list[str]:
        """``pins`` reordered so the pins of each group (shield, pair, cable) are neighbours, nested groups inside
        their shield; otherwise the given order is kept."""
        pos = {p: i for i, p in enumerate(pins)}
        first: dict[str, int] = {}
        chains = {}
        for p in pins:
            chain = list(reversed(self.group_chain(self.pin_group(ref, p))))     # outermost first
            chains[p] = chain
            for gid in chain:
                first.setdefault(gid, pos[p])
        return sorted(pins, key=lambda p: [first[g] for g in chains[p]] + [pos[p]])

    def unused_pins(self, ref: str) -> list[str]:
        """Contact positions of ``ref`` with nothing connected (NC)."""
        used = set(self.pins_used(ref))
        return [p for p in self.contact_positions(ref) if p not in used]

    def wire_gauge(self, w: Wire) -> float | None:
        from .library import parse_awg

        awg = parse_awg(w.gauge)
        if awg is None:
            part = self.library.get(w.wire_pn)
            awg = part.awg if part else None
        return awg

    def rendered_notes(self) -> list[str]:
        name = UNIT_NAMES.get(self.units.upper(), self.units)
        return [n.replace("{UNITS_NAME}", name).replace("{UNITS}", self.units).replace("{TOL}", self.tolerance)
                for n in self.notes if n.strip()]

    def to_inches(self, value: float) -> float:
        return value / UNIT_PER_INCH.get(self.units.upper(), 1.0)

    def from_inches(self, value: float) -> float:
        return value * UNIT_PER_INCH.get(self.units.upper(), 1.0)


def parse_shield_term(value: str, ref: str) -> tuple[str, str]:
    """Return (kind, pin): kind is BACKSHELL, FLOAT, PIN, or '' (not specified)."""
    v = (value or "").strip()
    u = v.upper().replace(" ", "")
    if not u:
        return ("", "")
    if u in ("BACKSHELL", "BS", "360", "360DEG", "CHASSIS", "CASE", "GROUND", "GND", "SHELL"):
        return (SHIELD_BACKSHELL, "")
    if u in ("FLOAT", "FLOATING", "OPEN", "NONE", "NC", "INSULATE", "DEADEND"):
        return (SHIELD_FLOAT, "")
    m = re.match(r"^(?:(.+?)[-:.])?(?:PIN)?\s*([A-Za-z]?\d+[A-Za-z]?|[A-Za-z])$", v.replace(" ", ""), re.I)
    if m and (m.group(1) is None or m.group(1).upper() == ref.upper()):
        return ("PIN", m.group(2))
    return ("PIN", v)


def natural_key(s: str):
    """Sort key so that pin 2 comes before pin 10 and A before B."""
    return [(0, int(t), "") if t.isdigit() else (1, 0, t.upper()) for t in re.findall(r"\d+|\D+", str(s))]


def fmt_length(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.2f}".rstrip("0").rstrip(".") if value != int(value) else f"{int(value)}"


def fmt_dia(value_in: float | None, design: CableDesign | None = None) -> str:
    """Diameter in the design's units (inches by default) with sensible precision."""
    if value_in is None:
        return ""
    if design and design.units.upper() != "IN":
        return f"{design.from_inches(value_in):.1f} {design.units}"
    return f"{value_in:.3f} IN"
