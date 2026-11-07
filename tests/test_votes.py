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


def test_csv_import_reports_unknown_symbols(tmp_path):
    conn, _ = _conn(tmp_path)
    path = tmp_path / "votes.csv"
    path.write_text("symbol,iso3,vote\nS/RES/2699 (2023),FRA,Y\nS/RES/9999 (1999),FRA,Y\n",
                    encoding="utf-8")
    summary = votes_mod.import_csv(conn, path)
    assert summary["added"] == 1
    assert summary["unknown_symbols"] == ["S/RES/9999 (1999)"]
    conn.close()
