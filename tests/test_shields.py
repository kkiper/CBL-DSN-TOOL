"""Shields over selected wires or the whole bundle, nesting, SHELL terminations and pin row order."""

import pytest

from cable_tool.bom import build_bom
from cable_tool.canvas import sheet_to_svg
from cable_tool.drawing import build_drawing, group_rows
from cable_tool.drc import ERROR, _Checker, run_drc
from cable_tool.edit import add_shield, remove_group, rename, set_shield_term
from cable_tool.jsonio import dumps, loads
from cable_tool.project import load_design, save_design
from test_cable_tool import two_connector_design


def test_shield_over_non_adjacent_wires_and_overall_shield_nest():
    d = two_connector_design()
    s1 = add_shield(d, ["W1", "W7"])
    assert d.group(s1).shielded and {w.wire_id for w in d.group_members(s1)} == {"W1", "W7"}
    # selecting one wire of a pair takes the whole pair in; the pair keeps its own group inside the shield
    s3 = add_shield(d, ["W3"])
    assert d.group("TSP1").parent == s3 and {w.wire_id for w in d.group_members(s3)} == {"W3", "W4"}
    remove_group(d, s3)
    assert d.group("TSP1").parent == "" and d.group(s3) is None
    s2 = add_shield(d, [w.wire_id for w in d.wires])
    assert {g.group_id for g in d.group_children(s2)} == {"TSP1", "TP2", s1}
    assert len(d.group_members(s2)) == len(d.wires) and d.direct_members(s2)      # loose wires sit in S2 itself
    assert d.group_chain("TSP1") == ["TSP1", s2] and d.group_level(s2) == 1
    # a shield over part of an overall shield nests inside it
    s4 = add_shield(d, ["W2", "W11"])
    assert d.group(s4).parent == s2
    rename(d, "group", s2, "OS1")
    assert d.group("TSP1").parent == "OS1" and d.group_chain("TSP1") == ["TSP1", "OS1"]


def test_shell_termination_shows_the_shell_and_reads_backshell_or_shell():
    d = two_connector_design()
    gid = add_shield(d, ["W1", "W2"])
    assert not d.connector("P2").show_shell
    set_shield_term(d, gid, "P2", "SHELL")
    assert d.group(gid).term_to == "SHELL" and d.connector("P2").show_shell and d.shell_shown("P2")
    assert gid in {g.group_id for g in d.shell_terminations("P2")}
    assert d.shell_name("P2") == "BACKSHELL"                  # W101 connectors have backshells
    d.connector("P2").backshell_pn = ""
    assert d.shell_name("P2") == "CONNECTOR SHELL"
    headers, rows = group_rows(d, {})
    row = next(r for r in rows if r[0] == gid)
    assert row[headers.index("SHIELD (TO END)")] == "P2: CONNECTOR SHELL"


def test_nested_shield_diameter_bom_and_drc():
    d = two_connector_design()
    s2 = add_shield(d, [w.wire_id for w in d.wires])
    set_shield_term(d, s2, "P1", "SHELL")
    set_shield_term(d, s2, "P2", "SHELL")
    chk = _Checker(d)
    od_s2, _, _ = chk.group_od(d.group(s2))
    od_tsp1, _, _ = chk.group_od(d.group("TSP1"))
    assert od_s2 > od_tsp1
    items = chk.bundle_items("P1")
    assert len(items) == 1 and items[0].od == pytest.approx(od_s2)        # the bundle is the overall shield
    report = run_drc(d)
    assert not [f for f in report.findings if f.rule == "Groups" and f.item == s2]   # splice inside is fine
    # the overall shield's conductors are counted as wire, not dropped
    bom = build_bom(d)
    assert any(b.category == "wire" for b in bom)
    d.group("TSP1").parent = "NOPE"
    assert any(f.rule == "Groups" and "doesn't exist" in f.message for f in run_drc(d).findings)
    d.group("TSP1").parent = "TP2"
    d.group("TP2").parent = "TSP1"
    assert any(f.severity == ERROR and f.rule == "Groups" for f in run_drc(d).findings)


def test_wiring_diagram_ties_non_adjacent_shield_and_uses_pin_order():
    d = two_connector_design()
    s1 = add_shield(d, ["W1", "W7"])
    set_shield_term(d, s1, "P1", "SHELL")
    sheets, _ = build_drawing(d)
    svg = sheet_to_svg(sheets[2])
    assert "JOINED CAPSULES = ONE SHIELD OVER NON-ADJACENT WIRES" in svg and f">{s1}<" in svg
    assert ">SHELL<" in svg and ">BACKSHELL<" in svg         # P1's SHELL row, which the drain runs into
    # put the members next to each other and the tie goes away
    d.connector("P1").pin_order = d.arranged_pins("P1", ["A", "B", "C", "D", "E", "F", "G", "H"])
    d.connector("P2").pin_order = d.arranged_pins("P2", ["A", "B", "C", "D", "E", "F", "G", "H"])
    assert d.connector("P1").pin_order[:2] == ["A", "G"]
    svg = sheet_to_svg(build_drawing(d)[0][2])
    assert "JOINED CAPSULES" not in svg
    assert svg.index(">DISCRETE IN 1<") < svg.index(">28V RTN<")       # P1-G now drawn right under P1-A


def test_round_trip_shell_parent_and_pin_order():
    d = two_connector_design()
    s2 = add_shield(d, [w.wire_id for w in d.wires])
    set_shield_term(d, s2, "P1", "SHELL")
    d.connector("P2").pin_order = ["B", "A"]
    again = loads(dumps(d))
    assert again.connector("P1").show_shell and again.group("TSP1").parent == s2
    assert again.connector("P2").pin_order == ["B", "A"]
    wb, _ = load_design("x.xlsx", save_design(d))
    assert wb.connector("P1").show_shell and not wb.connector("P2").show_shell
    assert wb.group("TSP1").parent == s2 and wb.connector("P2").pin_order == ["B", "A"]


def test_one_shell_row_at_the_bottom_and_columns_do_not_overlap():
    from cable_tool.drawing import _Row, _shell_rows, _shield_columns

    d = two_connector_design()
    d.connector("P1").backshell_pn = ""
    s1 = add_shield(d, ["W1", "W2"])
    s2 = add_shield(d, [w.wire_id for w in d.wires])
    set_shield_term(d, s1, "P1", "SHELL")
    set_shield_term(d, s2, "P1", "SHELL")
    rows = []
    for pin in "ABCDEFGHJKLM":
        wire = next(w for w in d.wires if (w.from_ref, w.from_pin) == ("P1", pin) or (w.to_ref, w.to_pin) == ("P1", pin))
        rows.append(_Row(pin, "", wire))
    out = _shell_rows(d, "P1", rows)
    assert [r for r in out if r.shell] == [out[-1]]                      # one SHELL row, at the bottom
    assert (out[-1].pin, out[-1].signal) == ("SHELL", "CONNECTOR SHELL")
    cols = _shield_columns(d, "P1", out)
    # every lead into the SHELL row has a column of its own; the overall shield sits outside the rest
    assert len({cols[s1], cols["TSP1"], cols[s2]}) == 3
    assert cols[s2] > max(cols[s1], cols["TSP1"], cols["TP2"])
    d.connector("P2").show_shell = False
    assert not any(r.shell for r in _shell_rows(d, "P2", rows))          # no shell shown, no SHELL row
