"""Wire size and bundle diameter calculators (engine)."""

import pytest

from cable_tool import calc
from cable_tool.drc import FIT_OK, TOO_BIG, TOO_SMALL, fit_status, run_drc
from test_cable_tool import two_connector_design


def test_awg_cma_mm2_conversions():
    r = calc.size_from("AWG", "20")
    assert r.cma == 1216 and r.mm2 == pytest.approx(0.616, abs=1e-3) and r.nearest == 20 and r.at_least == 20
    assert r.awg == pytest.approx(19.25, abs=0.05)              # 19/32 stranding ~ a 19.2 AWG solid conductor
    assert calc.size_from("mm2", 0.616).nearest == 20
    assert calc.size_from("CMA", 800).nearest == 22 and calc.size_from("CMA", 800).at_least == 20
    one_aught = calc.size_from("AWG", "1/0")
    assert one_aught.cma == 104500 and calc.awg_label(one_aught.nearest) == "1/0"
    assert calc.size_from("CMA", 300000).at_least is None      # bigger than 4/0
    assert calc.size_from("AWG", "x") is None and calc.size_from("CMA", 0) is None
    assert calc.cma_to_awg(calc.circular_mils(17)) == pytest.approx(17)


def test_custom_strands():
    r = calc.size_from("Strands", 32, 19)                       # 19 x 32 AWG
    assert r.cma == pytest.approx(1201, abs=2) and r.nearest == 20
    assert calc.size_from("Strands", 0.008, 19, "in").cma == pytest.approx(1216)
    assert calc.size_from("Strands", 0.2032, 19, "mm").cma == pytest.approx(1216, rel=1e-3)
    assert calc.typical_wire_od("16", 22) == 0.052 and calc.typical_wire_od("32", 8) is None


def test_bundle_diameter_and_packing():
    rows = [calc.BundleRow("wire", "M22759/16", 0.062, 2), calc.BundleRow("wire", "M22759/16", 0.052, 6),
            calc.BundleRow("cable", "M27500-22TG2T14", 0.135, 1), calc.BundleRow("cable", "M27500-20SB3T23", 0.180, 1),
            calc.BundleRow("cable", "NO-OD", None, 3)]
    res = calc.bundle(rows)
    assert res.diameter == pytest.approx(0.328, abs=1e-3) and (res.items, res.wires, res.cables, res.missing) == (10, 8, 2, 1)
    assert calc.bundle(rows, 1.3).diameter == pytest.approx(res.diameter / 1.2 * 1.3)
    assert calc.bundle([calc.BundleRow("cable", "X", 0.2, 1)]).diameter == 0.2
    assert calc.bundle([]).diameter is None


def test_fit_status():
    assert fit_status(0.3, 0.2, 0.4) == FIT_OK
    assert fit_status(0.5, 0.2, 0.4) == TOO_BIG
    assert fit_status(0.1, 0.2, None) == TOO_SMALL
    assert fit_status(0.1, None, None) is None


def test_rows_from_connector_match_the_drc():
    design = two_connector_design()
    rows = calc.rows_from_connector(design, "P1")
    assert sum(r.qty for r in rows) == run_drc(design).bundles["P1"].count
    assert calc.bundle(rows).diameter == pytest.approx(run_drc(design).bundles["P1"].diameter)
    assert any(r.kind == "cable" and r.pn == "M27500-22TG2T14" for r in rows)
