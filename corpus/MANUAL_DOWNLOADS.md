# Manual downloads

Updated 8 November 2026. Most of this list is now **done** — the remaining items are at the
bottom.

## Completed automatically

- [x] Secretary-General reports on BINUH, downloaded from the UN symbol service and ingested:
      S/2024/310 (75 chunks), S/2024/508 (69 chunks), S/2025/641 (66 chunks), all quality 0.95.
- [x] Press release `SC/16185` (30 September 2025, 10009th meeting) — press.un.org blocks direct
      automated downloads, so the published text was read from
      https://press.un.org/en/2025/sc16185.doc.htm and saved as `corpus/inbox/SC_16185.txt`
      with a `SYMBOL:` header, then ingested as a press release (9 chunks). It records the
      12–0–3 vote and the abstentions by China, Pakistan and the Russian Federation.
- [x] Genocide Convention text — the UN page returns 403 and the A/RES/260 (III) scan has no
      text layer, so the official text was read from
      https://www.ohchr.org/en/instruments-mechanisms/instruments/convention-prevention-and-punishment-crime-genocide,
      saved as `corpus/inbox/A_RES_260_III.txt` with `SYMBOL: A/RES/260 (III)`, and ingested as
      a treaty: 9 chunks, Art. I–X, quality 0.95.

## Still to do by hand

- [ ] Press releases for S/RES/2751 (2024), 2743 (2024), 2692 (2023) and 2700 (2023). The
      votes and speakers are already in the library from the S/PV records, so these are only
      for the summary wording. Fetch by hand from press.un.org (search the resolution number)
      and save into `corpus/inbox` with `SYMBOL: SC/xxxxx` on the first line.
- [ ] Earlier BINUH reports (2023 series) if you want 2023 statement coverage. The 2024 and
      2025 reports are in.
- [x] Speaker mapping for China, Russia, France, Panama and Colombia — fixed in the S/PV
      parser and all 14 meeting records re-ingested; no country is at zero in COVERAGE.md.
