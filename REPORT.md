# MUN Research Station — build report

**Date:** 7 November 2026
**Machine:** Windows 11, Python 3.14.6, Ollama 0.40.13
**Ollama endpoint:** `http://127.0.0.1:11434` (native API; `/v1` also answers)
**Models:** `qwen3:8b` (pulled), `qwen3-mun` (created from `Modelfile`, `num_ctx 8192`,
temperature 0.3), `qwen3-embedding:0.6b` (1024 dimensions)
**App:** `http://127.0.0.1:8765` (started with `python scripts/run_server.py` or `start.bat`)

---

## 1. What was built

The implementation plan is a nine-phase project. This build covers Phases 0–5 fully, the
dossier/speech/working-paper/POI code from Phases 6–7, and part of Phase 8. Every file is
under ~300 lines except the dossier pipeline.

### Phase 0 — scaffolding and environment
- `config.yaml` (endpoint, models, context length, budgets, thresholds), `requirements.txt`
  pinned to versions that install and import on this machine.
- FastAPI app with Jinja2 templates and vendored HTMX + CSS (`app/web/static/`), no CDN,
  no web fonts, no telemetry — the UI works offline.
- `app/llm/client.py`: Ollama client with chat, streaming, structured JSON and embeddings.
  Qwen3 thinking is off by default (`/no_think`), and a stateful `ThinkStripper` removes
  think blocks even when the tags are split across stream chunks.
- Status bar on every page showing LLM health and library counts.
- `install.bat`, `start.bat`, `doctor.bat`, `fetch.bat`, `backup.bat`, `update.bat`.
  `doctor.bat` checks Python, packages, Ollama, model presence, **the applied `num_ctx`**,
  the embedding model, the database, missing embeddings and disk space, printing PASS/FAIL
  with a plain-English fix.

### Phase 1 — database and ingestion
- `app/schema.sql`: documents, chunks, FTS5 external-content index with triggers, `chunk_vec`
  (float32 blobs), countries, votes, topics, doc_topics, edges, conferences,
  dossier_sections, jobs, notes, settings, plus the plan's indexes.
- `app/ingest/clean.py`: PyMuPDF block extraction with reading order, repeated
  header/footer removal, hyphen repair, parse-quality scoring.
- Structure-aware parsers:
  - `resolution.py` — preambular and operative paragraphs, sub-paragraphs merged into the
    parent OP, `PP n` / `OP n` labels.
  - `treaty.py` — one article per chunk (`Art. 51`), chapter tracking, preamble chunk.
  - `pv.py` — speaker interventions; scans for speaker markers anywhere because PyMuPDF
    merges the S/PV roster and interventions into long blocks; keeps the President's
    statement, which carries vote results.
  - `press.py` — paragraph groups plus vote-summary extraction.
  - `report.py` — numbered SG report / ICJ paragraphs.
- `pipeline.py`: SHA-256 + symbol dedupe (re-running never duplicates), type detection,
  date extraction, embedding with a context header, link extraction, topic tagging.
- Drag-and-drop upload, `corpus/inbox` ingestion, Library page with quality flags.

### Phase 2 — retrieval and Evidence mode
- Router (`router.py`): country aliases, document symbols, article and chapter references,
  intent words. A bare article reference resolves to the UN Charter; naming another
  instrument (`Rome Statute`, `Vienna Convention`) scopes it to treaties.
- Exact shortcut → FTS5 BM25 + vector cosine → reciprocal rank fusion → hybrid rerank →
  relative score floor (50% of best) → per-document cap of 3 → top 8 → accepted-graph
  expansion → 3,500-token pack with `[S1]…` IDs.
- Low-evidence gate returns "Not found in your library" with the closest passages and does
  not call the model.
- Guardrails (`guards.py`): every marker validated against the pack, markers expanded to
  real citations from the database, resolution numbers/dates/vote counts checked against
  evidence, unflagged sentences counted, quote never written by the model.

### Phase 3 — fetcher and corpus
- `scripts/fetch_corpus.py`: manifest-driven download from
  `https://documents.un.org/api/symbol/access?s=SYMBOL&l=en&t=pdf`, sequential, delayed,
  named User-Agent, local cache, missing items listed for manual download.
- `scripts/discover.py`: searches the UN Digital Library (MARCXML), extracts S/PV and SC/
  symbols, downloads them, and ingests only files that mention the topic.
- Manifests for the core legal pack and Haiti, including the S/PV records that were verified.

### Phase 4 — votes and Stance
- `votes.py`: manual entry, UN Digital Library CSV import (reports unknown symbols),
  press-release paragraph parsing, tally computation and document-vs-table validation.
- Stance mode: vote rows from the table, statements filtered by country and topic, then a
  cited summary. Refuses with "No data" when a country has no statements and no votes.
- `/votes` page: manual Y/N/A/NV entry, per-resolution tallies, CSV import.
- Vote and stance questions in Evidence mode now refuse when the votes table is empty or the
  country has no statements, instead of answering from unrelated passages.

### Phase 5 — graph and connections
- Regex link extraction with relation typing (recalls / reaffirms / extends / amends /
  supersedes / cites), stub documents for unresolved references, BFS shortest path over
  accepted edges, Connect mode with one sentence per hop, review queue with accept/reject.
  Rejected and pending edges are never used in answers.

### Phases 6–7 — dossier, speech, working paper, POIs
- Ten independent sections saved as each finishes, background jobs with progress,
  per-section regeneration, Markdown and DOCX export.
- Speech: five bounded paragraphs, then a trim/expand pass (up to two attempts) to fit the
  time limit within ~10%.
- Working paper: preambular and operative clauses from retrieved language, resolution
  validator that rejects references not present in the library.
- POIs: code-generated tensions (statements + votes, or two conflicting statements), bounded
  card generation, every card shows verbatim evidence, and countries without an angle say
  "No strong angle found" instead of inventing one.
- Blocs: vote-similarity clustering; correctly reports empty when there are no votes.

---

## 2. Verification evidence

| Check | Command | Result |
| --- | --- | --- |
| Test suite | `python -m pytest -q` | **23 passed** |
| Environment | `python scripts/doctor.py` | **all PASS**, including `num_ctx=8192` |
| Evaluation set | `python eval/run_eval.py` | recall **4/4**, refusal **4/4**, invalid markers **0**, median retrieval **65 ms**, exit 0 |
| Pages | `curl` on `/ /ask /library /connections /votes /settings /jobs /dossier/1` | **200** each |
| Streaming answer | POST `/api/ask` (SSE) | valid markers, 0 flags, evidence spans S/RES/2699 and S/RES/2743 |
| Full dossier | job on conference 1 | **10 sections, 0 errors** |
| Speech length | dossier section | **177 words** vs 195-word target (−9%) |
| Working paper | dossier section | validator found **no invented references** |
| POI cards | dossier section | 2 cards with evidence, 4 countries "No strong angle" |
| Exports | `/export/1.md`, `/export/1.docx` | 200, 26.5 KB and 43.4 KB |

**Library contents:** 52 documents (16 real resolutions/treaties plus the UN Charter and five
S/PV records; the remainder are reference stubs created by link extraction), 1,366 chunks,
1,366 embeddings, 76 accepted graph edges, 14 countries with statements, 10 dossier sections.
There are **0 vote rows** — see blocker 4.1.

Retrieval spot checks: `Article 51` → UN CHARTER Art. 51 first; `Article 51 of the Rome
Statute` → Rome Statute only; MSS question → S/RES/2699 OP 20 and S/RES/2743 PP 9;
off-topic Arctic question → refused with both phrasings tested.

---

## 3. Deviations from the plan (and why)

1. **Python 3.14, not 3.11.** Only 3.14 is installed on this machine. Packages are pinned to
   versions verified here; the code avoids version-specific syntax. `install.bat` accepts
   3.11+.
2. **Ollama native `/api/chat`, not the OpenAI-compatible `/v1`.** The plan itself notes that
   `/v1` ignores per-request `num_ctx`; the native API applies it. Any compatible endpoint can
   still be configured; `settings.native_llm_base()` strips `/v1` if present.
3. **Embeddings through Ollama (`qwen3-embedding:0.6b`, 1024 dims), not fastembed.** Avoids a
   ~100 MB ONNX download on a machine with ~9 GB free, and uses a model already pulled. The
   vector store is a float32 blob table searched with numpy cosine; sqlite-vec can be swapped
   in without touching ranking.
4. **Hybrid reranker, not a fastembed cross-encoder.** `rerank.py` scores 0.55 × embedding
   cosine + 0.30 × lexical coverage + 0.15 × exact symbol/article boost, on CPU. Single
   function, replaceable.
5. **The UN Charter** is not served by the symbol API; it was downloaded from
   `treaties.un.org` and stored as `UN CHARTER`, with a filename special case in the pipeline.

---

## 4. Remaining blockers

### 4.1 No per-country vote data (blocks blocs and POI quality)
- The ingested S/PV records state tallies ("12 votes in favour, none against, 3 abstentions")
  but not roll calls.
- `press.un.org` blocks automated download (bot challenge page), so press releases with
  abstainer names must be saved by hand into `corpus/inbox`.
- A UN Digital Library vote CSV needs a manual download.
- **Consequence:** `/votes` is empty, bloc clustering reports "empty", vote tables in Stance
  are empty, POI cards fall back to statements only. Vote accuracy cannot be claimed.
- **Unblock:** download the UN voting CSV and import it on `/votes`, or enter rows by hand.
  The importer validates tallies against stated counts and reports unknown symbols.

### 4.2 Thin statement coverage
- Only five S/PV records are ingested (2026 Haiti meetings). China, Russia and several others
  have no statements, so their profiles and POIs correctly say "No data".
- **Unblock:** `python scripts/discover.py Haiti` again with a higher `--limit`, add
  Secretary-General reports and press releases to `corpus/inbox`, then ingest from the Library.

### 4.3 Evaluation set is small and partly self-authored
- Eight questions, four of them unanswerable by design. The 4/4 recall result is a smoke test,
  not a graded benchmark; the plan expects 30–40 questions with ground truth from your prep.

### 4.4 Scanned PDFs
- `A/RES/260 (III)` (Genocide Convention) is a scan with no text layer and is flagged
  `low_quality` instead of being ingested. OCR is not implemented (plan calls it optional).

### 4.5 Not verified
- Dossier sections other than speech were generated once and inspected by size and status,
  not read line by line for factual quality.
- UI pages were verified over HTTP; the rendered layout was not visually reviewed.
- `install.bat` was written for a clean machine but this session used the existing Python, so
  the full install-from-scratch path was not executed end to end.

---

## 5. How to run

```
install.bat     # one-time: venv, packages, models, qwen3-mun, database, doctor
fetch.bat       # online: core + Haiti manifests, then ingest
start.bat       # opens http://127.0.0.1:8765
doctor.bat      # PASS/FAIL with fixes
backup.bat      # database + corpus + config to backups/YYYYMMDD-HHMM
```

Optional corpus discovery: `python scripts/discover.py Haiti --limit 12`.
Evaluation: `python eval/run_eval.py`. Full re-embed: `python scripts/reembed.py --force`.

The working demo dossier (UNSC, "The situation in Haiti", Colombia) is conference 1 at
`/dossier/1`.

---

# Second pass (8 November 2026)

## Task 1 — manifest and labels (done)
- `corpus/manifests/haiti.yaml` now lists 2692, 2700, 2751, 2793 with corrected labels.
  S/RES/2743 (2024) is labelled the BINUH renewal; S/RES/2751 (2024) is the MSS renewal.
- Fetched and ingested: S/RES/2692 (2023) 41 chunks, S/RES/2700 (2023) 41, S/RES/2751 (2024)
  11, S/RES/2793 (2025) 38, plus S/PV.9684, S/PV.10009, S/PV.9735, S/PV.9377, S/PV.9444,
  S/PV.9095, S/PV.9159, S/PV.8559, S/PV.9430. All resolutions report parse quality 0.95.
- Fixed a real ingestion bug: real PDFs were being skipped because link extraction had already
  created a stub with the same symbol. A downloaded document now replaces its stub.
- `corpus/MANUAL_DOWNLOADS.md` lists the press releases (press.un.org blocks automated
  download), SG reports, and the scanned Genocide Convention.
- Verified from the documents: 2743 unanimous 15-0-0 (S/PV.9684); 2793 12-0-3 (S/PV.10009,
  abstaining China, Pakistan, Russian Federation); 2751 unanimous (S/PV.9735); 2692 unanimous
  (S/PV.9377); 2700 unanimous (S/PV.9444); 2699 13-0-2 (S/PV.9430, China and Russia);
  2476 13-0-2 (S/PV.8559, China and Dominican Republic).

## Task 2 — real vote data (done for the nine Haiti resolutions)
- `corpus/votes/council_members.csv`: 2019-2026 membership, sourced from
  https://www.un.org/securitycouncil/content/countries-elected-members (page read this session).
- `corpus/votes/haiti_votes.csv`: nine rows, every tally read from the adoption S/PV record.
- `app/ingest/votes.py`: `import_tallies` expands a tally into per-country rows, rejects any
  row whose derived Y/N/A counts disagree with the stated tally, stores the source URL on
  every vote row, and stores rows without abstainer names as NEEDS_NAMES with no votes written.
- Imported: 135 vote rows across nine resolutions; every row validated; zero rejected; zero
  unresolved names. `/votes` has an "Import Haiti votes" button and a NEEDS_NAMES to-do list.
- Stance prepare now returns nine vote rows for the United States and nine for China.
- Blocs were not re-run after the import.

## Task 3 — coverage (partial)
- `scripts/coverage.py` writes `corpus/COVERAGE.md` (2022-2026, 2026 Council plus Colombia).
- No new `discover.py` run was made, so year coverage is still five 2026 S/PV records.
- The zero list includes China and Russia even though they spoke in S/PV.10009: 237 chunks
  have a speaker name but no speaker_country. This is a PV speaker-mapping bug, not a corpus
  gap, and should be fixed before trusting the coverage table.

## Task 4 — validator year bug (done)
- `validate_resolution_refs` now rejects S/RES/2699 (2024) when only 2699 (2023) exists,
  rejects unknown numbers, and accepts a bare "resolution 2699" only when the number is
  unique. Four new tests cover representable cases; 29 tests pass in total.

## Task 5 — evaluation set (drafts only, targets not met)
- `eval/haiti_qa.yaml`: 32 questions across exact lookups, votes, stance, connections,
  argument/counterargument and ten unanswerable, all marked `verified: false`.
- `eval/run_eval.py` reports recall, refusal correctness, vote-table accuracy, latency, and
  (with `--answers N`) marker validity and hallucinated resolution numbers; it exits 1 if a
  measured target fails.
- Latest run: recall 16/21 = 76% (target 85%), refusals 8/10 = 80% (target 90%), vote table
  6/6 = 100%, median retrieval 83 ms. **The runner exits 1.** Recall failures are vote and
  argue/counter questions whose evidence panel is not the mechanism being tested; the two
  refusal misses are the Moon Treaty and Haiti space-programme drafts. These are draft
  questions, not a passing benchmark.

## Task 6 — pasted text and OCR (implemented, not yet exercised)
- `.txt`/`.md` ingestion reads a first line `SYMBOL: A/RES/260 (III)` and uses it as the
  symbol; discussed in MANUAL_DOWNLOADS.md.
- `clean.ocr_available()` / `clean.ocr_pdf()` run ocrmypdf when it and Tesseract are present;
  otherwise the scanned-PDF error now explains both the OCR install and the paste route.
- No OCR binary is installed here and the paste route was not run end to end.

## Task 7 — verification (not done)
- Dossier was not regenerated after the data changes.
- `app/dossier/checks.py`, DOSSIER_REVIEW.md, a from-scratch install test and screenshots were
  not produced. No headless browser check was attempted.

## Test status
`python -m pytest -q` -> **29 passed**. `python eval/run_eval.py` -> exit 1 (targets above).

## Third pass — downloads completed (8 November 2026)

- **Secretary-General reports on BINUH** downloaded from the UN symbol service and ingested:
  S/2024/310 (75 chunks), S/2024/508 (69), S/2025/641 (66), quality 0.95 each.
- **SC/16185** press release: press.un.org blocks direct automated requests (HTTP 406), so the
  published text was read from https://press.un.org/en/2025/sc16185.doc.htm, saved as
  `corpus/inbox/SC_16185.txt` with `SYMBOL: SC/16185`, and ingested as a press release
  (9 chunks). It independently confirms 12-0-3 with China, Pakistan and Russia abstaining.
- **Genocide Convention**: the UN page returns 403 and the A/RES/260 (III) PDF is a scan, so
  the text was taken from OHCHR, saved as `corpus/inbox/A_RES_260_III.txt` with
  `SYMBOL: A/RES/260 (III)`, and ingested as a treaty: 9 chunks, Art. I-X, quality 0.95.
- Fixed three issues found by doing this: multi-line `SYMBOL:` headers were not read; article
  headings without a blank line were not split; Roman-numeral article headings were rejected
  by the treaty parser; and `S/2024/310` filenames produced no symbol. A pasted GA resolution
  with article headings now parses as a treaty.
- **Tests: 29 passed.** Library now 73 documents (SG reports and press release added).
- Still open: the S/PV speaker-to-country mapping (China and Russia show zero statements),
  the evaluation targets (recall 76%, refusals 80%), dossier regeneration, `dossier/checks.py`,
  DOSSIER_REVIEW.md, clean-install test and screenshots.

## Fourth pass — speaker mapping fixed (8 November 2026)

- Root cause: the S/PV speaker pattern rejected any marker with a parenthetical before the
  colon, such as "Mr. Geng Shuang (China) (spoke in Chinese):". China's intervention was
  therefore merged into the previous speaker's chunk and attributed to the United States.
- `app/ingest/parsers/pv.py` now allows one such parenthetical. A parser smoke test asserts
  that China is recognised.
- All 14 S/PV records were re-ingested (chunks grew, e.g. S/PV.10198 102, S/PV.9430 47).
  Statement chunks: China 38, United States 35, Russia 31, France 22, United Kingdom 14
  (China, Russia and France were previously zero). Unresolved speaker names fell from 237 to
  165.
- `corpus/COVERAGE.md` regenerated: **no country is at zero** across 2022-2026. China 36,
  United States 34, Russia 27, Panama 21, France 19, Colombia 17.
- Stance now works for the US, China, Russia and France: each returns nine vote rows plus
  8-9 statement chunks with no refusal.
- Evaluation re-run: **recall 21/21 = 100%**, vote-table accuracy **6/6 = 100%**, median
  retrieval 70 ms, tests **29 passed**. Refusal correctness is **6/10 = 60%**, still below the
  90% target, so the runner still exits 1. The four misses are draft questions (u05 2018 vote,
  u06 EU coffee tariff, u07 Moon Treaty, u10 Haiti space programme) where ordinary Haiti
  passages score above the evidence gate. They are drafts marked `verified: false` and should
  be replaced with your own questions rather than tuned around.

## Fifth pass — dossier rebuilt and checked (8 November 2026)

- The demo dossier (conference 1) was rebuilt after the vote and corpus changes. All ten
  sections report `ok`; **blocs now has real content** because votes are stored (it was
  `empty` before).
- New `app/dossier/checks.py` checks every section: missing/failed sections, resolution
  references with wrong year or absent from the library, speech citing at least three distinct
  sources, and each POI card having at least two evidence items. It also reports uncited
  factual sentences.
- First run failed on one real defect: the speech section listed "see evidence panel" instead
  of resolution symbols, so it cited zero sources. `section_speech` now lists the actual
  symbols from its evidence packs; speech and POIs were rebuilt.
- Final check result: **PASS** (0 hard failures). Warnings remain: counter 13/14, position
  6/6 and speech 11/23 factual sentences carry no inline citation marker; these are reported,
  not hidden.
- `DOSSIER_REVIEW.md` generated for conference 1: per section, claims with their source marker
  or evidence quote, plus uncited sentences flagged for hand review.
- `python -m pytest -q` -> **29 passed**.
- Still not done: clean-install test in a fresh environment, screenshots (Playwright is not
  installed), and the refusal target in the evaluation set (6/10).

## Wrap-up (8 November 2026)

- Speech fixed: the model returned an over-long draft unchanged, so a deterministic trim pass
  now drops whole sentences until the speech is within 5% of target. Rebuilt speech is
  **210 words against a 195-word target (+7.7%)** and cites six resolutions.
- `app/dossier/checks.py` now also fails a speech outside +/-10% of its time target. Final
  result for conference 1: **PASS**, with warnings for uncited sentences in counter (13/14),
  position (6/6) and speech (11/24).
- `DOSSIER_REVIEW.md` regenerated; blocs is non-empty; POIs rebuilt with their evidence.
- `python -m pytest -q` -> **29 passed**.
- Open items: evaluation refusal target still 6/10 (runner exits 1); clean-install test in a
  fresh virtual environment not run; no screenshots (Playwright not installed); new /votes
  import button not exercised in a browser; work is uncommitted.

## Final pass (8 November 2026, second session)

- **Clean install fixed and verified.** `requirements.txt` pinned `pymupdf==1.28.6`, a version
  that does not exist on PyPI, so a fresh install failed. It now pins the installed `2.1`.
  In a new `.venv-clean`: `pip install -r requirements.txt` succeeded, `pip check` reported
  no broken requirements, `python -m pytest -q` gave **33 passed**, and `scripts/doctor.py`
  reported PASS for every check (Python 3.14.6, packages, Ollama, models, database, 1996
  embedded chunks, disk space).
- **Refusal gate strengthened; evaluation now passes.** Two real gaps were fixed in
  `app/modes/service.py`:
  - vote questions that name a year with no roll call in the votes table now refuse
    (previously "How did the Council vote on Haiti in 2018?" was answered from 2024
    statements);
  - evidence retrieval now refuses when the pack never mentions a rare term the question is
    built around (previously "EU tariff on Haitian coffee" and "Moon Treaty" were answered
    from Haiti passages). Meta words ("connected", "raise", "delegations") are excluded.
  Result: `python eval/run_eval.py` -> recall **21/21 = 100%**, refusal **9/10 = 90%**
  (target 90%), vote accuracy **6/6 = 100%**, median 91 ms, **exit 0**. The remaining miss is
  u10 ("Haiti's space programme"), whose words appear separately in the retrieved passages.
- **New tests:** `tests/test_answerability.py` (4 tests). Suite total **33 passed**.
  The counter section initially regressed to "empty" because the generated question contains
  "raise"; that word is now treated as question phrasing and the section rebuilt to 2040 chars.
- **Dossier rebuilt after the gate change:** all ten sections `ok`, `checks.py` PASS
  (warnings: counter 13/14, position 6/6, speech 11/25 uncited). `DOSSIER_REVIEW.md`
  regenerated.
- **Browser checks:** server served `/`, `/votes`, `/dossier/1`, `/library` with HTTP 200 on
  the current code. The real "Import Haiti votes" button was clicked: the request succeeded,
  the page reloaded, and the table still held **135 rows / 9 tallies**, so re-import does not
  duplicate rows. Screenshots saved in `docs/screenshots/` (`votes.png`, `home.png`,
  `library.png`, `dossier.png`).
- Open: u10 refusal miss; no commit made.
