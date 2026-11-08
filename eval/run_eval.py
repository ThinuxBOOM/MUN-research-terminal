"""Evaluation runner: recall, refusals, vote accuracy, markers, latency (task 5).

Retrieval and refusal decisions are measured for every question without calling the model.
Citation-marker validity and hallucinated resolution numbers need generated answers, so they
are measured on the first N answerable questions when --answers N is passed; otherwise they
are reported as not measured rather than as a pass.
"""
from __future__ import annotations

import argparse
import re
import statistics
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import connect  # noqa: E402
from app.modes import service  # noqa: E402

TARGET_RECALL = 0.85
TARGET_REFUSAL = 0.90
TARGET_VOTES = 1.0


def _conference(conn) -> dict | None:
    row = conn.execute("SELECT * FROM conferences ORDER BY id LIMIT 1").fetchone()
    if not row:
        return None
    conf = dict(row)
    conf["countries_list"] = conf.get("countries") or "[]"
    return conf


def _vote_checks(conn, item: dict) -> tuple[int, list[str]]:
    checked, bad = 0, []
    for expected in item.get("expect_vote") or []:
        checked += 1
        row = conn.execute(
            "SELECT v.vote FROM votes v JOIN documents d ON d.id = v.doc_id "
            "WHERE d.symbol = ? AND v.iso3 = ?",
            (expected["symbol"], expected["iso3"])).fetchone()
        if not row or row["vote"] != expected["vote"]:
            bad.append(f"{expected['symbol']} {expected['iso3']}: expected "
                       f"{expected['vote']}, table has {row['vote'] if row else 'none'}")
    return checked, bad


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--answers", type=int, default=0,
                        help="generate answers for the first N answerable questions")
    args = parser.parse_args()

    data = yaml.safe_load(Path(__file__).with_name("haiti_qa.yaml").read_text(encoding="utf-8"))
    questions = data.get("questions", [])
    conn = connect()
    conf = _conference(conn)
    library_symbols = {row["symbol"] for row in conn.execute(
        "SELECT symbol FROM documents WHERE symbol IS NOT NULL")}

    recall_hits = recall_total = 0
    refusal_ok = refusal_total = 0
    votes_checked = 0
    vote_errors: list[str] = []
    latencies: list[int] = []
    generated = invalid_markers = hallucinated = 0
    generated_targets = args.answers

    print(f"{'id':<5}{'recall':<8}{'refused':<9}{'vote':<6}question")
    for item in questions:
        mode = item.get("mode", "evidence")
        payload = {"question": item["question"], "conference": conf,
                   "country": item.get("country")}
        started = time.perf_counter()
        prep = service.prepare(conn, mode, payload)
        latencies.append(prep.get("meta", {}).get("retrieval_ms") or 0)
        symbols = {evidence["symbol"] for evidence in prep.get("evidence", [])}
        expected = item.get("expect_symbols") or []
        hit = None
        if expected:
            recall_total += 1
            hit = all(sym in symbols for sym in expected)
            recall_hits += 1 if hit else 0
        refused = bool(prep.get("refusal"))
        if item.get("should_refuse"):
            refusal_total += 1
            refusal_ok += 1 if refused else 0
        checked, bad = _vote_checks(conn, item)
        votes_checked += checked
        vote_errors.extend(bad)
        vote_state = "ok" if checked and not bad else ("FAIL" if bad else "")
        if generated_targets > 0 and not refused:
            generated_targets -= 1
            result = service.run(conn, mode, payload)
            generated += 1
            if not result.get("valid", True):
                invalid_markers += 1
            for number in re.findall(r"S/RES/(\d{1,4})", result.get("answer", "")):
                if not any(f"/{number}" in symbol for symbol in library_symbols):
                    hallucinated += 1
        print(f"{item['id']:<5}{str(hit):<8}{str(refused):<9}{vote_state:<6}{item['question'][:58]}")
    conn.close()

    recall = recall_hits / recall_total if recall_total else 1.0
    refusal = refusal_ok / refusal_total if refusal_total else 1.0
    vote_acc = 1 - (len(vote_errors) / votes_checked) if votes_checked else 1.0
    print("\nSummary")
    print(f"  source recall in top evidence: {recall_hits}/{recall_total} = {recall:.0%}"
          f" (target {TARGET_RECALL:.0%})")
    print(f"  refusal correct on unanswerables: {refusal_ok}/{refusal_total} = {refusal:.0%}"
          f" (target {TARGET_REFUSAL:.0%})")
    print(f"  vote table accuracy: {votes_checked - len(vote_errors)}/{votes_checked}"
          f" = {vote_acc:.0%} (target {TARGET_VOTES:.0%})")
    print(f"  median retrieval latency: {statistics.median(latencies) if latencies else 0:.0f} ms")
    if generated:
        print(f"  answers generated: {generated}; invalid citation markers: {invalid_markers}"
              f" (target 0); hallucinated resolution numbers: {hallucinated} (target 0)")
    else:
        print("  citation markers / hallucinated numbers: not measured (pass --answers N)")
    for error in vote_errors:
        print("  vote error: " + error)

    failed = []
    if recall < TARGET_RECALL:
        failed.append("recall")
    if refusal < TARGET_REFUSAL:
        failed.append("refusal")
    if vote_acc < TARGET_VOTES:
        failed.append("votes")
    if generated and invalid_markers:
        failed.append("markers")
    if generated and hallucinated:
        failed.append("hallucinated numbers")
    if failed:
        print("  FAILED targets: " + ", ".join(failed))
        return 1
    print("  all measured targets passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
