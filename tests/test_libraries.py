"""The sample D38999 / M22759 libraries load and drive the design rule check."""

from pathlib import Path

import pytest

from cable_tool.drc import ERROR, run_drc
from cable_tool.library import load_library
from cable_tool.model import CableDesign, ConnectorEnd, Wire

LIB = Path(__file__).resolve().parents[1] / "libraries"


@pytest.fixture(scope="module")
def library():
    d38999 = load_library("d38999_series_iii.csv", (LIB / "d38999_series_iii.csv").read_bytes())
    m22759 = load_library("m22759_wire.csv", (LIB / "m22759_wire.csv").read_bytes())
    return d38999.merged(m22759)


def test_libraries_load(library):
    plug = library.get("D38999/26FD35SN")
    assert plug.type == "connector" and plug.contacts == 37 and plug.contact_pn == "M39029/56-348"
    assert library.get("D38999/20WD18PN").contact_pn == "M39029/58-363"
    assert library.get("M39029/56-348").awg_range == (22, 28)
    assert library.get("M39029/58-364").awg_range == (16, 20)
    wire = library.get("M22759/16-20-2")
    assert wire.type == "wire" and wire.awg == 20 and wire.color == "RED" and wire.od > 0
    assert library.get("M22759/32-22-9").awg == 22
    assert sum(p.type == "connector" for p in library.parts.values()) == 936
    assert sum(p.type == "wire" for p in library.parts.values()) == 170


def test_regenerated_files_match_generator():
    import importlib.util

    spec = importlib.util.spec_from_file_location("gen", Path(__file__).resolve().parents[1] / "tools" / "gen_libraries.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    import csv

    for name, rows in (("d38999_series_iii.csv", gen.d38999_rows()), ("m22759_wire.csv", gen.m22759_rows())):
        with (LIB / name).open(encoding="utf-8") as f:
            assert len(list(csv.reader(f))) == len(rows) + 1, f"{name} is stale: run python tools/gen_libraries.py"


def _design(library, connector_pn: str, wire_pn: str, pin: str = "1") -> CableDesign:
    mate = connector_pn.replace("SN", "PN").replace("/26", "/20")
    return CableDesign(
        connectors=[ConnectorEnd("P1", connector_pn), ConnectorEnd("J1", mate)],
        wires=[Wire("W1", "P1", pin, "J1", pin, wire_pn=wire_pn)],
        library=library, overall_length=24,
    )


def test_drc_with_sample_libraries(library):
    # 20 AWG power wire in a 37-way (size 22D) connector: contacts only take 22-28 AWG
    bad = run_drc(_design(library, "D38999/26FD35SN", "M22759/16-20-2"))
    errs = [f for f in bad.findings if f.severity == ERROR and f.rule == "Contact wire size"]
    assert {f.item for f in errs} == {"P1-1", "J1-1"}
    assert "M39029/56-348 accepts 22 to 28 AWG" in errs[0].message
    # Same wire in an 18-way (size 20) connector is fine
    good = run_drc(_design(library, "D38999/26FD18SN", "M22759/16-20-2", pin="A"))
    assert not [f for f in good.findings if f.severity == ERROR]
