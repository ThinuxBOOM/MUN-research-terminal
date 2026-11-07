"""Parser tests: structure-aware chunking and country/vote extraction."""
from app.ingest import countries
from app.ingest.parsers import pv, resolution, treaty
from app.ingest.votes import normalize_vote, parse_paragraph


def test_resolution_splits_preambular_and_operative():
    paragraphs = [
        "United Nations", "S/RES/2699 (2023)", "Security Council",
        "Resolution 2699 (2023)", "Adopted by the Security Council at its 9428th meeting, on 2 October 2023",
        "The Security Council,",
        "Recalling its previous resolutions on Haiti, in particular resolution 2645 (2022),",
        "Reaffirming its strong commitment to the sovereignty of Haiti,",
        "1. Authorizes the deployment of a Multinational Security Support mission;",
        "2. Decides that the mission shall report every 90 days;",
        "(a) requests the Secretary-General to monitor the mandate;",
        "3. Urges all Member States to contribute personnel;",
    ]
    chunks = resolution.parse(paragraphs, {"date": "2023-10-02"})
    labels = [chunk["label"] for chunk in chunks]
    assert labels == ["PP 1", "PP 2", "OP 1", "OP 2", "OP 3"], labels
    assert "Multinational Security Support" in chunks[2]["text"]
    assert "requests the Secretary-General" in chunks[3]["text"]  # sub-paragraph merged


def test_treaty_splits_articles():
    paragraphs = [
        "Preamble text of the Charter.", "Article 1",
        "The Purposes of the United Nations are set out here.",
        "Article 2", "The Organization is based on the principle of sovereignty.",
        "Article 51", "Nothing in the present Charter shall impair the inherent right of self-defence.",
    ]
    chunks = treaty.parse(paragraphs, {"date": "1945-06-26"})
    labels = [chunk["label"] for chunk in chunks]
    assert labels == ["Preamble", "Art. 1", "Art. 2", "Art. 51"]
    assert "self-defence" in chunks[3]["text"]


def test_pv_speaker_country_and_meeting():
    paragraphs = [
        "United Nations", "S/PV.9428", "Security Council", "2 October 2023",
        "The President: The meeting is called to order.",
        "Mr. RODRIGUEZ (Colombia): Colombia supports the mission.",
        "We will continue to support the people of Haiti.",
        "Ms. THOMAS-GREENFIELD (United States of America): The United States supports it.",
    ]
    chunks = pv.parse(paragraphs, {"date": "2023-10-02", "meeting_no": "9428"})
    assert len(chunks) == 3
    assert chunks[1]["speaker_country"] == "COL"
    assert chunks[2]["speaker_country"] == "USA"
    assert chunks[1]["meeting_no"] == "9428"
    assert "We will continue" in chunks[1]["text"]


def test_country_aliases():
    assert countries.lookup("United States") == "USA"
    assert countries.lookup("United States of America") == "USA"
    assert countries.lookup("Russian Federation") == "RUS"
    assert countries.lookup("Türkiye") == "TUR"
    assert countries.lookup("Atlantis") is None


def test_vote_normalisation_and_paragraph():
    assert normalize_vote("abstaining") == "A"
    assert normalize_vote("yes") == "Y"
    rows = parse_paragraph("France (yes), Russia (abstaining), China (no)")
    assert {row["name"]: row["vote"] for row in rows} == {"France": "Y", "Russia": "A", "China": "N"}
