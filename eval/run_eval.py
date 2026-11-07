"""Evaluation runner: source recall, refusal correctness, citation validity (plan 14)."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import connect  # noqa: E402
from app.modes import service  # noqa: E402


def main() -> int:
    path = Path(__file__).with_name("haiti_qa.yaml")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    questions = data.get("questions", [])
    conn = connect()
    total = len(questions)
    recalled = refused_ok = unanswerable = 0
    invalid_markers = 0
    latencies: list[int] = []
    print(f"{'id':<4}{'recall':<8}{'refused':<9}{'markers':<9}question")
    for item in questions:
        started = time.perf_counter()
        result = service.run(conn, "evidence", {"question": item["question"]})
        latencies.append(result.get("retrieval_ms") or 0)
        symbols = {evidence["symbol"] for evidence in result.get("evidence", [])}
        expected = item.get("expect_symbols") or []
        hit = all(any(exp == sym for sym in symbols) for exp in expected) if expected else None
        if hit:
            recalled += 1
        refused = result.get("refused", False)
        if item.get("should_refuse"):
            unanswerable += 1
            refused_ok += 1 if refused else 0
        if not result.get("valid", True):
            invalid_markers += 1
        print(f"{item['id']:<4}{str(hit):<8}{str(refused):<9}{str(result.get('valid')):<9}"
              f"{item['question'][:60]}")
    conn.close()

    answerable = total - unanswerable
    print("\nSummary")
    print(f"  source recall in top evidence: {recalled}/{answerable or 1}")
    print(f"  refusal correct on unanswerables: {refused_ok}/{unanswerable or 1}")
    print(f"  answers with invalid markers: {invalid_markers}")
    print(f"  median retrieval latency: {sorted(latencies)[len(latencies)//2] if latencies else 0} ms")
    return 0 if recalled == answerable and refused_ok == unanswerable else 1


if __name__ == "__main__":
    raise SystemExit(main())
