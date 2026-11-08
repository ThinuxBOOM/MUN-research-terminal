"""Guardrail tests: markers, number validation, refusal, resolution references."""
from app.llm import guards

KNOWN = {"S/RES/2699 (2023)", "S/RES/2751 (2024)"}


def test_resolution_ref_year_must_match():
    assert guards.validate_resolution_refs("S/RES/2699 (2023)", KNOWN) == []
    wrong = guards.validate_resolution_refs("S/RES/2699 (2024)", KNOWN)
    assert wrong and "S/RES/2699 (2024)" in wrong[0]


def test_missing_resolution_number_fails():
    missing = guards.validate_resolution_refs("S/RES/9999 (2021)", KNOWN)
    assert missing and "9999" in missing[0]


def test_bare_resolution_number_only_when_unique():
    assert guards.validate_resolution_refs("resolution 2699", KNOWN) == []
    ambiguous = KNOWN | {"S/RES/2699 (2024)"}
    assert guards.validate_resolution_refs("resolution 2699", ambiguous)
    assert guards.validate_resolution_refs("resolution 2699 (2024)", ambiguous) == []
from app.llm.client import ThinkStripper, strip_think


PACK = [
    {"id": "S1", "symbol": "S/RES/2699 (2023)", "label": "OP 1", "date": "2023-10-02",
     "text": "Authorizes the Multinational Security Support mission for 12 months."},
    {"id": "S2", "symbol": "S/RES/2645 (2022)", "label": "OP 4", "date": "2022-07-15",
     "text": "Extends the mandate of BINUH until 15 July 2023."},
]


def test_marker_validation_accepts_known_ids():
    report = guards.check_answer("q", "The Council authorised it [S1].", PACK)
    assert report["clean"] and not report["bad_markers"]


def test_unknown_marker_is_flagged():
    report = guards.check_answer("q", "The Council authorised it [S9].", PACK)
    assert report["bad_markers"] == ["S9"]
    assert any(flag["level"] == "error" for flag in report["flags"])


def test_invented_resolution_number_is_flagged():
    report = guards.check_answer("q", "This follows resolution 9999 (2021) [S1].", PACK)
    assert any("9999" in flag["message"] for flag in report["flags"])


def test_number_present_in_pack_is_allowed():
    report = guards.check_answer("q", "Mission authorised in 2023 [S1].", PACK)
    assert not any("2023" in flag.get("message", "") for flag in report["flags"])


def test_expand_uses_database_citations():
    text = guards.expand("The mission was authorised [S1].", PACK)
    assert "S/RES/2699 (2023) · OP 1 · 2023-10-02" in text


def test_working_paper_reference_validator():
    known = {"S/RES/2699 (2023)", "S/RES/2645 (2022)"}
    assert guards.validate_resolution_refs("Recalling S/RES/2699 (2023)", known) == []
    assert "resolution 1111" in " ".join(guards.validate_resolution_refs("resolution 1111", known))


def test_think_blocks_are_stripped_in_stream():
    stripper = ThinkStripper()
    out = "".join(stripper.feed(piece) for piece in
                  ["<thi", "nk>hidden ", "reasoning</thi", "nk>Visible answer."])
    out += stripper.flush()
    assert "hidden" not in out
    assert out.strip() == "Visible answer."
    open_tag = "<" + "think" + ">"
    close_tag = "<" + "/" + "think" + ">"
    assert strip_think(f"a{open_tag}b{close_tag}c") == "ac"
