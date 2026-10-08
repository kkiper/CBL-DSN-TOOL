"""ASME Y14 drawing format: sheet sizing, letter heights, title/revision blocks, parts list, flag notes."""

import io

from cable_tool.asme import LETTER_HEIGHT, MIN_VIEW_SCALE, THIN, check_format, font_for, larger_sizes
from cable_tool.canvas import sheet_to_svg
from cable_tool.drawing import build_drawing
from cable_tool.drc import run_drc
from cable_tool.dxf import sheet_to_dxf
from cable_tool.library import Part
from cable_tool.model import Revision
from cable_tool.project import load_design, save_design

from test_cable_tool import two_connector_design  # noqa: E402


def test_letter_height_constants():
    assert font_for("general") * 0.718 / 72 >= LETTER_HEIGHT["general"]
    assert font_for("title") * 0.718 / 72 >= 0.24
    assert MIN_VIEW_SCALE > 1.7
    assert larger_sizes("ANSI C (22 x 17 in)") == ["ANSI C (22 x 17 in)", "ANSI D (34 x 22 in)", "ANSI E (44 x 34 in)"]


def test_forced_small_sheet_is_flagged():
    design = two_connector_design()
    sheets, warnings = build_drawing(design, "ANSI B (17 x 11 in)", auto_size=False)
    assert any("too small" in w for w in warnings)
    issues = check_format(sheets, design)
    assert any("below the ASME Y14.2 minimum letter height" in i.message for i in issues)


def test_title_block_and_revision_checks():
    design = two_connector_design()
    sheets, _ = build_drawing(design)
    msgs = {i.message for i in check_format(sheets, design)}
    assert "No drawing number in the title block." in msgs and "No DRAWN name in the title block." in msgs
    tb = design.title_block
    tb.drawing_number, tb.drawn_by, tb.date, tb.company, tb.cage_code = "W101-001", "K. KIPER", "2026-10-08", "ACME", "1ABC2"
    tb.revision = "A"
    design.revisions = [Revision("-", "INITIAL RELEASE", "2026-01-05", "JS"), Revision("B", "ADD SP1", "2026-10-08", "JS", "C3")]
    sheets, _ = build_drawing(design)
    issues = check_format(sheets, design)
    assert any("doesn't match the latest revision 'B'" in i.message for i in issues)
    svg = sheet_to_svg(sheets[0])
    assert "ADD SP1" in svg and ">C3<" in svg and ">1ABC2<" in svg
    assert "W101-001  REV B" in svg and 'transform="rotate(-180' in svg      # reverse-oriented number block


def test_parts_list_find_numbers_flags_and_cage():
    design = two_connector_design()
    design.library.get("M81824/1-1").cage = "81349"
    sheets, _ = build_drawing(design)
    meta = sheets[0].meta
    assert set(meta["balloons"]) <= set(meta["find_numbers"])
    assert meta["flag_notes"]["splice"] and meta["flag_notes"]["label"]
    svg = sheet_to_svg(sheets[0])
    assert ">81349<" in svg and "INSTALL SPLICE (FIND NO. 16) AT LOCATION SHOWN" in svg
    assert not any(f.severity == "ERROR" for f in run_drc(design, sheets).findings if f.rule == "Drawing format")


def test_pen_weights_do_not_scale():
    design = two_connector_design()
    sheets, _ = build_drawing(design)
    svg = sheet_to_svg(sheets[1])          # wiring diagram is drawn inside a scaled group
    widths = {float(w) for w in __import__("re").findall(r'stroke-width="([\d.]+)"', svg)}
    scaled_thin = round(THIN / sheets[1].root.items[-2].scale, 2)
    assert any(abs(w - scaled_thin) < 0.02 for w in widths)


def test_revisions_and_title_fields_round_trip():
    design = two_connector_design()
    design.title_block.cage_code, design.title_block.contract_number = "1ABC2", "N00019-26-C-0001"
    design.revisions = [Revision("A", "INITIAL RELEASE", "2026-10-08", "KK")]
    reloaded, _ = load_design("p.xlsx", save_design(design))
    assert reloaded.title_block.cage_code == "1ABC2"
    assert reloaded.title_block.contract_number == "N00019-26-C-0001"
    assert [(r.rev, r.description, r.approved) for r in reloaded.revisions] == [("A", "INITIAL RELEASE", "KK")]


def test_dxf_text_rotation_and_heights():
    import pytest

    ezdxf = pytest.importorskip("ezdxf")
    from ezdxf import recover

    design = two_connector_design()
    design.title_block.drawing_number = "W101"
    sheets, _ = build_drawing(design)
    doc, auditor = recover.read(io.BytesIO(sheet_to_dxf(sheets[0]).encode()))
    assert not auditor.has_errors
    texts = list(doc.modelspace().query("TEXT"))
    assert any(abs(t.dxf.rotation - 180) < 1e-6 for t in texts)
    assert min(t.dxf.height for t in texts) >= 0.10 - 1e-3          # block headings are the smallest
    assert ezdxf.__version__ and Part
