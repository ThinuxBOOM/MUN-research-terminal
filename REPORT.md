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
