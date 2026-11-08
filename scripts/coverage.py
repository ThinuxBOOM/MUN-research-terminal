"""Statement coverage per country and year, written to corpus/COVERAGE.md (task 3)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import connect  # noqa: E402
from app.ingest import countries  # noqa: E402

YEARS = [2022, 2023, 2024, 2025, 2026]
COUNCIL_2026 = ["BHR", "CHN", "COL", "COD", "DNK", "FRA", "GRC", "LVA", "LBR", "PAK",
                "PAN", "RUS", "SOM", "GBR", "USA"]


def main() -> int:
    conn = connect()
    rows: list[tuple[str, list[int], int]] = []
    for iso3 in COUNCIL_2026:
        counts = []
        for year in YEARS:
            counts.append(conn.execute(
                "SELECT COUNT(*) AS n FROM chunks c JOIN documents d ON d.id = c.doc_id "
                "WHERE c.speaker_country = ? AND d.year = ?", (iso3, year)).fetchone()["n"])
        rows.append((iso3, counts, sum(counts)))
    conn.close()

    lines = ["# Statement coverage", "",
             "Chunks of verbatim statements per country and year (S/PV meeting records and",
             "press releases already in the library). Council composition is the 2026 list;",
             "Colombia is included as the user's country.", "",
             "| Country | " + " | ".join(str(y) for y in YEARS) + " | total |",
             "| --- | " + " | ".join("---" for _ in YEARS) + " | --- |"]
    zero = []
    for iso3, counts, total in rows:
        lines.append(f"| {countries.name_of(iso3)} | " + " | ".join(str(n) for n in counts) +
                     f" | {total} |")
        if total == 0:
            zero.append(countries.name_of(iso3))
    lines += ["", "## Countries still at zero statements", ""]
    lines += [f"- {name}" for name in zero] or ["- none"]
    lines += ["", "Add S/PV records for these countries (Library page or "
              "`python scripts/discover.py Haiti --limit 40`) to give their stance and POI "
              "sections something to cite.", ""]
    Path("corpus/COVERAGE.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
