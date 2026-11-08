"""Vote storage, tallying, validation and CSV import (plan 6.4)."""
from app.db import init_db
from app.ingest import votes as votes_mod


def _conn(tmp_path):
    conn = init_db(tmp_path / "votes.db")
    doc_id = conn.execute(
        "INSERT INTO documents(symbol, doc_type, status) VALUES ('S/RES/2699 (2023)', 'resolution', 'ok')"
    ).lastrowid
    conn.commit()
    return conn, doc_id


def test_manual_votes_tally_and_document_validation(tmp_path):
    conn, doc_id = _conn(tmp_path)
    assert votes_mod.add_vote(conn, doc_id, "USA", "Y", "manual")
    assert votes_mod.add_vote(conn, doc_id, "CHN", "A", "manual")
    assert votes_mod.add_vote(conn, doc_id, "RUS", "yes", "manual")  # alias normalised
    conn.commit()

    tally = votes_mod.tally(conn, doc_id)
    assert (tally["in_favour"], tally["abstentions"], tally["against"], tally["total"]) == (2, 1, 0, 3)

    mismatch = votes_mod.validate(conn, doc_id, {"in_favour": 15, "abstentions": 0})
    assert not mismatch["ok"] and mismatch["mismatches"]
    assert votes_mod.validate(conn, doc_id, {"in_favour": 2, "abstentions": 1})["ok"]
    conn.close()


def test_add_vote_replaces_existing_row(tmp_path):
    conn, doc_id = _conn(tmp_path)
    votes_mod.add_vote(conn, doc_id, "FRA", "Y", "manual")
    votes_mod.add_vote(conn, doc_id, "FRA", "A", "manual")
    conn.commit()
    rows = conn.execute("SELECT vote FROM votes WHERE doc_id = ? AND iso3 = 'FRA'", (doc_id,)).fetchall()
    assert [row["vote"] for row in rows] == ["A"]
    conn.close()


def _roster(tmp_path, iso3=("USA", "CHN", "RUS", "FRA", "GBR")):
    path = tmp_path / "members.csv"
    path.write_text("year,iso3,source_url\n" +
                    "".join(f"2023,{code},https://www.un.org/securitycouncil\n" for code in iso3),
                    encoding="utf-8")
    return path


def _tally_doc(tmp_path):
    conn, doc_id = _conn(tmp_path)
    conn.execute("UPDATE documents SET date = '2023-10-02', year = 2023 WHERE id = ?",
                 (doc_id,))
    conn.commit()
    return conn, doc_id


def test_tally_import_expands_to_per_country_rows(tmp_path):
    conn, doc_id = _tally_doc(tmp_path)
    path = tmp_path / "haiti.csv"
    path.write_text(
        "symbol,date,tally_yes,tally_no,tally_abstain,abstainers,no_voters,non_voters,source_url\n"
        "S/RES/2699 (2023),2023-10-02,3,0,2,China;Russian Federation,,,https://example.org/pv\n",
        encoding="utf-8")
    summary = votes_mod.import_tallies(conn, path, _roster(tmp_path))
    assert summary["imported"] == ["S/RES/2699 (2023)"]
    assert summary["rejected"] == []
    tally = votes_mod.tally(conn, doc_id)
    assert (tally["in_favour"], tally["against"], tally["abstentions"]) == (3, 0, 2)
    sources = {row["source"] for row in votes_mod.members_for(conn, doc_id)}
    assert sources == {"https://example.org/pv"}
    state = conn.execute("SELECT status FROM vote_tallies WHERE doc_id = ?", (doc_id,)).fetchone()
    assert state["status"] == "OK"
    conn.close()


def test_tally_import_rejects_mismatched_counts(tmp_path):
    conn, doc_id = _tally_doc(tmp_path)
    path = tmp_path / "bad.csv"
    path.write_text(
        "symbol,date,tally_yes,tally_no,tally_abstain,abstainers,no_voters,non_voters,source_url\n"
        "S/RES/2699 (2023),2023-10-02,4,0,2,China;Russian Federation,,,https://example.org/pv\n",
        encoding="utf-8")
    summary = votes_mod.import_tallies(conn, path, _roster(tmp_path))
    assert summary["imported"] == []
    assert summary["rejected"] and "Rejected" in summary["rejected"][0]["message"]
    assert votes_mod.tally(conn, doc_id)["total"] == 0
    conn.close()


def test_tally_without_abstainer_names_needs_names(tmp_path):
    conn, doc_id = _tally_doc(tmp_path)
    path = tmp_path / "pending.csv"
    path.write_text(
        "symbol,date,tally_yes,tally_no,tally_abstain,abstainers,no_voters,non_voters,source_url\n"
        "S/RES/2699 (2023),2023-10-02,3,0,2,,,,https://example.org/pv\n",
        encoding="utf-8")
    summary = votes_mod.import_tallies(conn, path, _roster(tmp_path))
    assert summary["needs_names"] == ["S/RES/2699 (2023)"]
    assert votes_mod.tally(conn, doc_id)["total"] == 0
    assert [row["symbol"] for row in votes_mod.needs_names(conn)] == ["S/RES/2699 (2023)"]
    conn.close()


def test_csv_import_reports_unknown_symbols(tmp_path):
    conn, _ = _conn(tmp_path)
    path = tmp_path / "votes.csv"
    path.write_text("symbol,iso3,vote\nS/RES/2699 (2023),FRA,Y\nS/RES/9999 (1999),FRA,Y\n",
                    encoding="utf-8")
    summary = votes_mod.import_csv(conn, path)
    assert summary["added"] == 1
    assert summary["unknown_symbols"] == ["S/RES/9999 (1999)"]
    conn.close()
