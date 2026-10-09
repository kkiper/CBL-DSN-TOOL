"""Insert layouts, connector face views and contacts supplied with D38999 connectors."""

import sys
from pathlib import Path

import pytest

from cable_tool.bom import build_bom
from cable_tool.canvas import sheet_to_svg
from cable_tool.drawing import build_drawing
from cable_tool.drc import ERROR, run_drc
from cable_tool.inserts import face_view, insert_info, layouts
from cable_tool.library import contacts_included, load_library
from cable_tool.model import CableDesign, ConnectorEnd, Wire

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import gen_libraries as gen  # noqa: E402


def test_insert_info_from_part_number():
    info = insert_info("D38999/26WD18SN")
    assert (info.arrangement, info.shell_size, info.contact_type, info.key, info.insert_name) == \
        ("D18", 15, "socket", "N", "15-18")
    assert insert_info("D38999/20FC04PN-LC").arrangement == "C4"
    assert insert_info("D38999/24ZJ61PA").contact_type == "pin"
    assert insert_info("MS3126F14-19S") is None


def test_layouts_agree_with_library_and_mil_std_1560():
    lays = layouts()
    assert len(lays) >= 30
    for (shell, arr), (count, size) in gen.INSERTS.items():
        code = f"{shell}{int(arr)}"
        if code in lays:
            assert len(lays[code]) == count and {c.size for c in lays[code]} == {size}, code
    d19 = {c.contact for c in lays["D19"]}
    assert d19 == set("ABCDEFGHJKLMNPRSTUV")
    for cavs in lays.values():
        assert len({c.contact for c in cavs}) == len(cavs)
        assert all(abs(c.x) < 1 and abs(c.y) < 1 for c in cavs)
    a = next(c for c in lays["D19"] if c.contact == "A")
    assert a.y > 0.5        # contact A at the top of the pin-insert face


def test_face_view_marks_wired_contacts_and_mirrors_sockets():
    pin = face_view("J1", "D38999/20WD19PN", {"A"}, 7)
    skt = face_view("P1", "D38999/26WD19SN", {"A"}, 7)
    from cable_tool.canvas import Circle
    fills = [c for c in pin.items if isinstance(c, Circle) and c.fill == "#000000"]
    assert len(fills) == 1
    sk = [c for c in skt.items if isinstance(c, Circle) and c.fill == "#000000"][0]
    assert sk.cx == pytest.approx(-fills[0].cx) and sk.cy == pytest.approx(fills[0].cy)
    assert face_view("P1", "MS3126F14-19S", set(), 7) is None
    assert face_view("P1", "D38999/26WD35SN", set(), 7) is None   # numbering not documented per cavity


def _design(pins=("A", "B")):
    path = ROOT / "libraries" / "d38999_series_iii.csv"
    lib = load_library(path.name, path.read_bytes())
    return CableDesign(
        connectors=[ConnectorEnd("P1", "D38999/26FD19SN"), ConnectorEnd("J1", "D38999/20FD19PN-LC")],
        wires=[Wire(f"W{i}", "P1", p, "J1", p, gauge="20") for i, p in enumerate(pins, 1)],
        library=lib, overall_length=24)


def test_contacts_supplied_unless_less_contacts():
    assert contacts_included("D38999/26FD19SN", None) and not contacts_included("D38999/26FD19SN-LC", None)
    assert not contacts_included("MS3126F14-19S", None)
    design = _design()
    bom = {b.pn: b for b in build_bom(design)}
    assert "M39029/56-351" not in bom                               # supplied with P1
    assert bom["M39029/58-363"].qty == 2                            # J1 is the -LC version
    lib = design.library.get("D38999/26FD19SN")
    assert lib.contacts_included is True and lib.contact_pn == "M39029/56-351"
    sheets = build_drawing(design)[0]
    notes, assembly = sheet_to_svg(sheets[0]), sheet_to_svg(sheets[1])
    assert "ARE SUPPLIED WITH CONNECTORS" in notes
    assert "P1 PINOUT, FRONT FACE" in assembly and "J1 PINOUT, FRONT FACE" in assembly
    assert "INSERT 15-19, KEY N" in assembly


def test_drc_flags_pins_not_in_the_insert():
    assert not [f for f in run_drc(_design()).findings if f.rule == "Contact position"]
    bad = [f for f in run_drc(_design(("A", "W", "a"))).findings if f.rule == "Contact position"]
    assert {f.item for f in bad} == {"P1", "J1"} and all(f.severity == ERROR for f in bad)
    assert "a, W" in bad[0].message


def test_drc_warns_when_override_contact_differs_from_supplied():
    design = _design()
    design.connectors[0].contact_pn = "M39029/56-348"
    assert [f for f in run_drc(design).findings if f.rule == "Contacts" and f.item == "P1"]


def test_nc_positions_and_pinouts_under_their_connectors():
    design = _design(("A", "B"))
    nc = design.unused_pins("P1")
    assert len(nc) == 17 and "A" not in nc and "C" in nc
    sheets = build_drawing(design)[0]
    notes, wiring = sheet_to_svg(sheets[0]), sheet_to_svg(sheets[2])
    assert "NC (NO CONNECTION) CONTACT POSITIONS: P1: C, D," in notes
    assert wiring.count(">NC<") == 34                         # every unused position, both connectors
    # each pinout sits under its own connector: left connector's view left of centre, right's right of centre
    from cable_tool.canvas import Group, Text

    av = next(it for it in sheets[1].root.items if isinstance(it, Group) and it.layer == "ASSEMBLY")
    x0, _, x1, _ = av.bounds()
    views = {t.s.split()[0]: v.dx for v in av.items if isinstance(v, Group) and v.layer == "FACE_VIEWS"
             for t in v.items if isinstance(t, Text) and t.s.endswith("FRONT FACE")}
    assert views["P1"] < (x0 + x1) / 2 < views["J1"]


def test_numbered_connector_nc_from_contact_count():
    from cable_tool.library import Part, PartsLibrary

    lib = PartsLibrary({"C6": Part("C6", "connector", contacts=6)})
    design = CableDesign(connectors=[ConnectorEnd("P1", "C6"), ConnectorEnd("P2", "C6")],
                         wires=[Wire("W1", "P1", "1", "P2", "2")], library=lib)
    assert design.unused_pins("P1") == ["2", "3", "4", "5", "6"]
    assert design.unused_pins("P2") == ["1", "3", "4", "5", "6"]


def test_cable_runs_into_the_connector():
    from cable_tool.canvas import Group, Poly
    from cable_tool.drawing import assembly_view

    design = _design()
    av = assembly_view(design, {})
    cable = [p for p in av.items if isinstance(p, Poly) and p.width > 3]
    assert min(min(x for x, _ in p.points) for p in cable) < 56     # starts inside the connector body (0..56)
    assert isinstance(av, Group)


def test_ipc_d_620_dimensions_from_datum():
    from cable_tool.drawing import assign_sides, splice_location
    from cable_tool.model import Splice

    # Two-connector cable: a splice entered near the far end is dimensioned from DATUM A (the first connector)
    design = _design()
    design.overall_length = 48
    design.splices = [Splice("SP1", near="J1", distance=6)]
    assert splice_location(design, design.splices[0]) == (42, "DATUM A (P1 FACE)")
    design.datum = "J1"
    assert splice_location(design, design.splices[0]) == (6, "DATUM A (J1 FACE)")
    assert assign_sides(design)[0][0].ref == "J1"            # the datum connector is drawn first (left)
    # Harness: a splice on a branch is located from the breakout centerline
    harness = CableDesign(connectors=[ConnectorEnd("P1", "X", length=18), ConnectorEnd("P2", "X", length=30),
                                      ConnectorEnd("P3", "X", length=42.5)],
                          splices=[Splice("SP1", near="P3", distance=10), Splice("SP2", near="P1", distance=5)])
    assert splice_location(harness, harness.splices[0]) == (32.5, "BREAKOUT CENTERLINE (TOWARD P3)")
    assert splice_location(harness, harness.splices[1]) == (5, "DATUM A (P1 FACE)")
    svg = sheet_to_svg(build_drawing(design)[0][1])
    assert ">A<" in svg                                        # datum feature symbol
