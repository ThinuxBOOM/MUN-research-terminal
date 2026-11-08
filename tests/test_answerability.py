"""Answerability gates: evidence must mention the question's specific subject."""
from app.db import init_db
from app.modes import service


def _conn(tmp_path):
    conn = init_db(tmp_path / "answerability.db")
    doc_id = conn.execute(
        "INSERT INTO documents(symbol, doc_type, year, status) "
        "VALUES ('S/PV.1', 'pv_record', 2025, 'ok')").lastrowid
    texts = [
        "The Council discussed Haiti and space cooperation.",
        "The representatives remain connected on Haiti.",
        "Haiti asked for support.",
    ]
    for ordinal, text in enumerate(texts):
        conn.execute("INSERT INTO chunks(doc_id, ordinal, text) VALUES (?, ?, ?)",
                     (doc_id, ordinal, text))
    conn.execute("INSERT INTO votes(doc_id, iso3, vote, source) VALUES (?, 'CHN', 'A', 'manual')",
                 (doc_id,))
    conn.commit()
    return conn


def test_rare_subject_term_missing_from_pack_is_flagged(tmp_path):
    conn = _conn(tmp_path)
    missing = service._missing_subject_terms(
        conn, "What about Haiti's space programme?", "Haiti programme")
    assert missing == ["space"]
    conn.close()


def test_term_absent_from_library_is_not_treated_as_a_subject(tmp_path):
    conn = _conn(tmp_path)
    # "authorises" occurs nowhere: an inflection variant, not a missing subject.
    assert service._missing_subject_terms(conn, "Which resolution authorises this?",
                                         "resolution") == []
    conn.close()


def test_relation_words_are_not_subjects(tmp_path):
    conn = _conn(tmp_path)
    missing = service._missing_subject_terms(
        conn, "How is the force connected to the MSS resolution?", "gang suppression force mss")
    assert missing == []
    conn.close()


def test_vote_question_with_a_year_no_roll_call_refuses(tmp_path):
    conn = _conn(tmp_path)
    assert service._vote_year_gap(conn, "How did the Council vote on Haiti in 2018?") == 2018
    assert service._vote_year_gap(conn, "How did China vote on resolution 2793?") is None
    assert service._vote_year_gap(conn, "How did China vote in 2025?") is None
    # A year in a non-vote question is not a vote-year gap.
    assert service._vote_year_gap(conn, "What did the Council decide about Haiti in 2018?") is None
    conn.close()
