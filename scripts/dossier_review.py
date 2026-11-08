"""Write DOSSIER_REVIEW.md: each section's claims next to their evidence (task 7)."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import connect  # noqa: E402

CITE = re.compile(r"\[([^\]]+)\]")
QUOTE = re.compile(r'^>\s*"?(.*?)"?\s*(?:—|--)\s*(.+)$')


def main() -> int:
    conference_id = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    conn = connect()
    conf = conn.execute("SELECT * FROM conferences WHERE id = ?", (conference_id,)).fetchone()
    rows = conn.execute("SELECT * FROM dossier_sections WHERE conference_id = ? ORDER BY id",
                        (conference_id,)).fetchall()
    lines = [f"# Dossier review — {(conf['name'] if conf else 'conference')}", ""]
    if conf:
        lines += [f"**Committee:** {conf['committee']}  ",
                  f"**Agenda:** {conf['agenda']}  ",
                  f"**Country:** {conf['my_country']}", ""]
    lines += ["Each row is a sentence or quote from the dossier with the source it points to.",
              "Check the claim against the quote, then against the document in the library.", ""]
    for row in rows:
        content = row["content_md"] or ""
        lines += [f"## {row['section']} ({row['status']})", ""]
        claims = [line.strip() for line in content.splitlines()
                  if line.strip() and not line.strip().startswith(("#", "|", "-", "*", "_"))]
        evidence = {}
        for item in json.loads(row["evidence_json"] or "[]"):
            if isinstance(item, dict):
                evidence[item.get("chunk_id")] = item
        quoted = False
        for claim in claims:
            match = CITE.search(claim)
            if match or re.search(r"\b(?:S|A)/RES/\d", claim, re.I):
                source = match.group(1) if match else "see quote"
                lines.append(f"- **Claim:** {claim[:400]}")
                lines.append(f"  - Source marker: {source}")
                quoted = True
            elif claim.startswith(">"):
                lines.append(f"- **Evidence quote:** {claim[1:].strip()[:500]}")
            elif len(claim.split()) > 8:
                lines.append(f"- _Uncited sentence for review:_ {claim[:300]}")
        if evidence and not quoted:
            lines.append("- Evidence items stored for this section:")
            for cid, item in list(evidence.items())[:8]:
                lines.append(f"  - {item.get('symbol')} · {item.get('label')} — chunk {cid}")
        lines.append("")
    Path("DOSSIER_REVIEW.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"DOSSIER_REVIEW.md written for conference {conference_id} "
          f"({len(rows)} sections)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
