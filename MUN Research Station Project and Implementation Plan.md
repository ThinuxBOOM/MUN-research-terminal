# MUN Research Station: Project and Implementation Plan

Written by the orchestrator (Claude) for the builder agent. Version 1.0.

## 0. Rules for the builder agent

1. Build one phase at a time, in order. Do not start a phase until the previous phase’s acceptance tests pass.
2. Do not add features that are not in this plan. If something is ambiguous, ask the user instead of guessing.
3. Keep files small (about 300 lines or fewer). Prefer many small modules.
4. Pin every dependency in requirements.txt, after confirming it installs on Windows 11 with Python 3.11.
5. Every phase ends with working code, automated tests, a README update, and a demo the user can start by double-clicking a .bat file.
6. The user is a beginner. Every script prints plain-English progress and plain-English errors with a suggested fix. Never leave a raw traceback as the only message.
7. The app must work fully offline after setup. No CDN links, no web fonts, no telemetry. Vendor all JS and CSS into app/static.
8. The LLM is small (Qwen3 8B). Code orchestrates; the model only performs the bounded jobs described here. Never build open-ended agent loops or let the model choose tools.
9. The model must never be the source of a citation, quote, vote, date or resolution number. Section 8 guardrails are mandatory.

## 1. Product summary

A local, offline research tool for Model UN delegates, aimed at the General Assembly and Security Council.

- **Library:** a SQLite database of UN documents (charters, treaties, resolutions, meeting records, press releases, reports, ICJ opinions), split into citable chunks and linked by a graph of connections.
- **Prep mode:** the user fills in a form (committee, agenda, own country, participating countries). The app builds a dossier: background, legal framework, resolution history with votes, country profiles, blocs, counterarguments, a drafted opening speech, a drafted working paper (Security Council) and point-of-information (POI) cards with follow-ups per country.
- **Live mode (Ask):** the user types targeted questions (for example: What is the US stance on Haiti?) and gets evidence first, then a short cited answer.
- **First test case:** UN Security Council, agenda “The situation in Haiti”, user represents Colombia.
- **Ranking of priorities:** prep mode is accuracy > ease of setup > speed. Live mode is speed ≈ accuracy.

## 2. Constraints

| Item | Value |
| --- | --- |
| OS | Windows 11 |
| CPU / RAM | Intel Core 5 210H, 16 GB |
| GPU | RTX 5050 laptop, 8 GB VRAM |
| LLM | Qwen3 8B, Q4\_K\_M, via Ollama |
| Usable context | 8192 tokens (do not exceed; larger spills out of VRAM and gets slow) |
| Embeddings and reranker | CPU only, so they never compete for VRAM |
| Network | Internet only during fetch and prep; the app itself never needs it |

Budget per live-mode LLM call: system prompt ≤ 500 tokens, evidence pack ≤ 3500 tokens, question ≤ 200, answer ≤ 700, leaving a safety margin.

## 3. Stack

| Layer | Choice |
| --- | --- |
| Backend | Python 3.11, FastAPI, Uvicorn |
| UI | Jinja2 templates + HTMX + a vendored CSS file (no Node.js needed). Streaming via Server-Sent Events |
| Storage | One SQLite file (data/mun.db) with FTS5 and the sqlite-vec extension |
| Graph | Plain SQL tables (nodes are documents and chunks, edges are typed). 1 to 2 hop traversal with recursive SQL |
| PDF text | PyMuPDF first. OCR fallback (Tesseract via OCRmyPDF, or Docling) only for scanned files, as an optional later step |
| Embeddings | fastembed (ONNX, CPU, no PyTorch). Default BAAI/bge-small-en-v1.5; configurable. Store the model name and dimension in settings; provide a re-embed script |
| Reranker | fastembed cross-encoder on CPU, top 30 to top 8 |
| LLM client | openai Python package pointed at http://localhost:11434/v1 (Ollama’s OpenAI-compatible endpoint). The base URL, model name and key are settings, so any compatible server works |
| Export | Markdown, DOCX (python-docx), and a print-friendly CSS for PDF from the browser |
| Tests | pytest |
| Config | config.yaml plus a Settings page in the UI |

### Ollama detail that matters

Ollama’s /v1 endpoint ignores a per-request num\_ctx. So install.bat must create a custom model from a Modelfile (FROM qwen3:8b, PARAMETER num\_ctx 8192, PARAMETER temperature 0.3) named qwen3-mun, and the app uses that model name. The doctor script must verify the context length is actually applied.

### Qwen3 thinking mode

Thinking is off by default: append /no\_think to the user message for all tasks. Always strip any think blocks from the output before display. Allow thinking only for the two drafting tasks (working paper clause design and speech outline), controlled by a config flag. Use temperature 0.2 for evidence tasks and 0.5 for drafting.

## 4. Repository layout

```
mun-station/
  install.bat  start.bat  doctor.bat  fetch.bat  backup.bat  update.bat
  config.yaml  requirements.txt  README.md
  app/
    main.py  settings.py  db.py  schema.sql
    llm/        client.py  prompts/ (one .txt per task)  guards.py
    ingest/     pipeline.py  parsers/ (resolution, treaty, pv, press, report, icj)
                chunker.py  countries.py  votes.py  links.py  topics.py
    retrieve/   search.py  fusion.py  rerank.py  pack.py  graph.py  router.py
    modes/      evidence.py  stance.py  connect.py  argument.py  counter.py  draftcheck.py
    dossier/    form.py  pipeline.py  sections/ (background, legal, history, profiles,
                blocs, counter, speech, working_paper, poi)  export.py
    web/        routes_*.py  templates/  static/ (vendored htmx, css)
    jobs.py
  corpus/
    manifests/  core.yaml  haiti.yaml   (lists of document symbols and URLs)
    inbox/      (user drops files here)
    raw/        (downloaded originals, never deleted)
  eval/  haiti_qa.yaml  run_eval.py
  tests/
  data/  mun.db  logs/
```

## 5. Database schema (schema.sql)

```sql
CREATE TABLE documents (
  id INTEGER PRIMARY KEY, symbol TEXT UNIQUE, title TEXT,
  doc_type TEXT,   -- charter|treaty|resolution|pv_record|press_release|sg_report|icj|rules|position|other
  organ TEXT,      -- GA|SC|ICJ|SG|OTHER
  date TEXT, year INTEGER, source_path TEXT, source_url TEXT,
  sha256 TEXT, parse_quality REAL, status TEXT, ingested_at TEXT
);
CREATE TABLE chunks (
  id INTEGER PRIMARY KEY, doc_id INTEGER REFERENCES documents(id),
  ordinal INTEGER, kind TEXT,  -- article|preambular|operative|intervention|paragraph|section
  label TEXT,                  -- e.g. Art. 51, OP 4, PP 2, Speaker: Mr. X
  speaker_name TEXT, speaker_country TEXT,   -- ISO3, for interventions
  meeting_no TEXT, date TEXT, text TEXT, token_count INTEGER
);
CREATE VIRTUAL TABLE chunks_fts USING fts5(text, label, content=chunks, content_rowid=id);
CREATE VIRTUAL TABLE chunk_vec USING vec0(chunk_id INTEGER PRIMARY KEY, embedding FLOAT[384]);
CREATE TABLE countries (iso3 TEXT PRIMARY KEY, name TEXT, aliases TEXT);  -- aliases as JSON list
CREATE TABLE votes (
  id INTEGER PRIMARY KEY, doc_id INTEGER REFERENCES documents(id),
  iso3 TEXT, vote TEXT,        -- Y|N|A|NV
  source TEXT                  -- undl_csv|press_release|manual
);
CREATE TABLE topics (id INTEGER PRIMARY KEY, name TEXT UNIQUE, keywords TEXT);
CREATE TABLE doc_topics (doc_id INTEGER, topic_id INTEGER, origin TEXT, PRIMARY KEY (doc_id, topic_id));
CREATE TABLE edges (
  id INTEGER PRIMARY KEY, src_type TEXT, src_id INTEGER, dst_type TEXT, dst_id INTEGER,
  rel TEXT,      -- cites|recalls|reaffirms|amends|extends|supersedes|supports|contradicts|related
  origin TEXT,   -- regex|llm|manual
  confidence REAL, status TEXT DEFAULT 'pending',  -- pending|accepted|rejected
  evidence_chunk_id INTEGER
);
CREATE TABLE conferences (
  id INTEGER PRIMARY KEY, name TEXT, committee TEXT, agenda TEXT, my_country TEXT,
  countries TEXT,  -- JSON list of ISO3
  topic_id INTEGER, speech_seconds INTEGER, created_at TEXT
);
CREATE TABLE dossier_sections (
  id INTEGER PRIMARY KEY, conference_id INTEGER, section TEXT, country TEXT,
  content_md TEXT, evidence_json TEXT, status TEXT, generated_at TEXT
);
CREATE TABLE jobs (id INTEGER PRIMARY KEY, kind TEXT, status TEXT, progress REAL, message TEXT, payload TEXT, created_at TEXT);
CREATE TABLE notes (id INTEGER PRIMARY KEY, conference_id INTEGER, chunk_id INTEGER, text TEXT, created_at TEXT);
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);
```

Make the vector dimension follow the configured embedding model. Add indexes on chunks(doc\_id), chunks(speaker\_country), votes(doc\_id), votes(iso3), edges(src\_id), edges(dst\_id).

## 6. Ingestion pipeline

Flow: file in (inbox or fetcher) → hash and dedupe → detect type → extract text → clean → parse into chunks → normalize countries → extract links → assign topics → embed → index. Everything is resumable and idempotent; re-running never duplicates.

### 6.1 Cleaning

Remove running headers and footers, page numbers, and UN document-symbol stamps repeated per page. Fix hyphenated line breaks. Join two-column text correctly (use PyMuPDF block sort). Compute a parse\_quality score; list low-quality documents in the UI for the user to review rather than silently ingesting garbage.

### 6.2 Structure-aware chunking (one parser per type)

| Type | Chunk unit | Label |
| --- | --- | --- |
| Charter and treaties | One article (split long ones by paragraph) | Art. 51 |
| Resolutions | One preambular or operative paragraph, with sub-paragraphs kept together | PP 3, OP 5 |
| S/PV meeting records | One speaker intervention (split at about 400 tokens); keeps meeting number, date, speaker name, country | Speaker + meeting |
| Press releases (SC/xxxx) | One paragraph group; the vote summary is parsed separately | para |
| SG reports, ICJ opinions | One numbered paragraph or short section | para N |

Target 150 to 400 tokens per chunk, hard maximum 500. Each chunk is embedded with a context header, for example: \[S/RES/2699 (2023) | OP 4 | Security Council | 2023-10-02\]. The header is not shown to the user; the clean text is.

### 6.3 Countries

A countries table with ISO3 codes and aliases (United States, United States of America, US, USA; Russian Federation, Russia; UK and full name; Türkiye and Turkey; and so on). Speaker lines in S/PV records carry the country in parentheses, so map them with this table. Unknown names go to a review list.

### 6.4 Votes

Three sources, in this order of priority: (1) a CSV import of UN Digital Library voting data; (2) a parser for the vote paragraph of press releases and S/PV records (adopted by N votes in favour, with abstentions by …); (3) a manual entry form. Every vote row stores its source. Validate that the totals match the stated tally and flag mismatches.

### 6.5 Links (graph)

- **Regex pass (high confidence):** find resolution references (for example resolution 1325 (2000), S/RES/2699 (2023), A/RES/…) and article references (Article 51, Chapter VII). Resolve to documents in the library; unresolved references are kept as stub nodes so they can be fetched later.
- **Typed relations from trigger words:** recalling and reaffirming → recalls/reaffirms; decides to extend or extends → extends; amends or replaces → amends/supersedes; acting under Chapter VII → cites.
- **LLM pass (low confidence, optional job):** for pairs of chunks that are close in vector space and in the same topic, ask Qwen to label the relation as supports, contradicts or unrelated. All results go in as pending.
- **Review queue:** nothing from the LLM pass is used in answers until the user accepts it. Regex edges are accepted automatically, but are reviewable.

### 6.6 Topics

A topic is a name plus keywords (for example Haiti: Haiti, BINUH, Port-au-Prince, gangs, Multinational Security Support). Documents are tagged by keyword match with a minimum hit count, and the user can add or remove tags manually.

### 6.7 Fetcher and corpus packs

- Manifests (corpus/manifests/\*.yaml) list document symbols with optional direct URLs. The fetcher tries the UN document redirect pattern (https://undocs.org/ plus the symbol) and falls back to listing what it could not download so the user can download these manually into corpus/inbox. Verify the URL patterns at build time; UN sites change.
- Be polite: sequential downloads, a delay between requests, a clear User-Agent, and a local cache in corpus/raw.
- Core pack: UN Charter, UDHR, ICCPR, ICESCR, Geneva Conventions and Additional Protocols, Rome Statute, ICJ Statute, Vienna Convention on the Law of Treaties and on Diplomatic Relations, and the Rules of Procedure for the GA and the SC.
- Haiti pack (starting list, to be verified and completed by searching the UN Digital Library for the Haiti topic): the resolutions that established and renewed BINUH, the Haiti sanctions regime resolution, the Multinational Security Support mission authorization and renewals, the Gang Suppression Force authorization, Secretary-General reports on Haiti and BINUH, Security Council meeting records (S/PV) on Haiti, and the corresponding press releases (SC/xxxx). Do not trust this list as complete; the fetcher’s job is to build the real list.

## 7. Retrieval design

All retrieval is code. The model sees only the final pack.

1. **Router (rules first, LLM only as fallback).** Detect: country names (alias table), topic keywords, document symbols and article numbers, and intent words (stance, vote, how do X and Y connect, counterargument). Output a mode plus filters. If the active conference has a topic, bias retrieval to it.
2. **Exact-symbol shortcut.** If the query contains a document symbol or an article number, fetch those chunks directly.
3. **Hybrid search.** FTS5 BM25 top 30 and vector top 30, with filters applied (topic, country, doc type, date range). Merge with Reciprocal Rank Fusion.
4. **Rerank** the merged set with the cross-encoder to the top 8.
5. **Graph expansion.** For the top 3 chunks, add up to 4 chunks from accepted 1-hop neighbours (the resolutions they recall or extend).
6. **Dedupe and pack.** Drop near-duplicates, order by relevance, and give each chunk a short ID (S1, S2, …). Stop at the token budget (3500).
7. **Low-evidence gate.** If the best rerank score is under a tuned threshold, return “Not found in your library” plus the closest 3 passages, and do not call the LLM.

Speed target for live mode: retrieval ≤ 2 seconds; evidence panel visible immediately; the first answer token ≤ 10 seconds.

## 8. LLM guardrails (mandatory)

1. **Evidence first.** The UI shows retrieved passages verbatim from the database before and regardless of the LLM answer.
2. **Citations by ID only.** The model writes claims with markers like \[S3\]. The app expands markers into real citations (document symbol, paragraph label, date) and verbatim quotes pulled from the database. The model is never asked to type a quote.
3. **Citation validation.** After generation, check every marker exists in the pack. Remove or flag sentences with invalid markers or no marker.
4. **Number validation.** Any resolution number, date or vote count in the answer must appear in the pack text or the votes table; otherwise flag the sentence.
5. **Votes are never generated.** Vote tables are rendered by code from the votes table.
6. **Refusal path.** If evidence is missing, say so. Never fill in from the model’s memory.
7. **Bounded tasks.** One job per call. Large outputs (a dossier) are built from many small calls, saved section by section.
8. **JSON tasks** use Ollama’s structured output (response\_format json\_schema), then validate with pydantic; on failure retry once, then fall back to a plain extractive result.
9. **Streaming** for all long answers (SSE), with a cancel button.
10. **Every generated item stores its evidence IDs** so the user can click through to the source.

## 9. Task modes (live mode)

Each mode has a prompt file in app/llm/prompts. Every prompt follows the same skeleton: role, rules, the evidence pack, the task, the output format, and /no\_think. Prompts must stay under 500 tokens.

| Mode | Code does | Qwen does |
| --- | --- | --- |
| Evidence search | Retrieval and pack | 3 to 6 bullet findings, each with \[S#\] |
| Country stance | Votes table from DB; filters statements by country and topic; chronological list | Short stance summary and how it changed over time, with \[S#\] |
| Connect | Graph path between two documents or concepts (shortest path over accepted edges) | One sentence per hop explaining the link, with \[S#\] |
| Argument builder | Retrieves supporting evidence for a claim plus the user’s country position | 3 talking points: claim, evidence \[S#\], so what |
| Counterargument | Retrieves opposing statements and contradicting edges | Likely objections with replies, each with \[S#\] |
| Draft check (lower priority) | Retrieves resolutions related to the pasted clause | Does this clause conflict with or repeat an existing resolution? yes, no or unclear, with \[S#\] |

Example prompt skeleton (Country stance):

> You are an evidence assistant for a Model UN delegate. Use ONLY the numbered passages below. Every sentence you write must end with a passage marker like \[S2\]. If the passages do not answer the question, reply exactly: NOT ENOUGH EVIDENCE. Write at most 5 sentences, plainly and neutrally. Do not mention anything not in the passages. PASSAGES: {pack} QUESTION: What is the stance of {country} on {topic}? /no\_think

## 10. Prep mode: conference form and dossier

### 10.1 Form

Fields: conference name, committee (dropdown: UNSC, UNGA plenary, GA First to Sixth Committees, other), agenda item (text, mapped to a topic), my country (dropdown), participating countries (multi-select, with a one-click UNSC-15 preset), speech length in seconds (default 90), and a checkbox to generate a working paper (on by default for the Security Council, optional otherwise). On submit, show a corpus coverage check: how many documents, votes and statements exist for this topic, and which countries have no data. Warn before generating if coverage is poor.

### 10.2 Dossier pipeline

Runs as a background job. Each section is saved as soon as it finishes, so a failure never loses earlier work, and any section can be regenerated alone. Progress and the current step are always visible.

| # | Section | Built by |
| --- | --- | --- |
| 1 | Agenda background (timeline of events from the documents) | Retrieval, then short LLM summaries per period |
| 2 | Legal framework (charter articles, treaties, key resolutions) | Graph traversal from topic documents, then one-line relevance notes |
| 3 | Resolution history table: symbol, date, summary, vote tally, and each country’s vote | Code (DB), plus one LLM summary line per resolution |
| 4 | Country profiles, one country at a time: votes, key statements (verbatim, dated), stance summary, data gaps | Code plus Country stance mode |
| 5 | Blocs and alliances | Code: vote-similarity matrix on topic resolutions, clustered; Qwen only names and describes each cluster |
| 6 | My country’s position and red lines | Country stance mode on my country, plus an editable box for the user’s official position paper |
| 7 | Likely counterarguments, by country and by theme | Counterargument mode |
| 8 | **Speaker’s list speech** from my country’s perspective | See 10.3 |
| 9 | **Working paper** (Security Council; optional elsewhere) | See 10.4 |
| 10 | **POIs and follow-ups per country** | See 10.5 |

### 10.3 Speech

Build in steps: (a) the code collects my country’s position, three best-supported facts and the key resolution; (b) Qwen drafts one paragraph each for hook, background, position, proposed solution and call to action; (c) code assembles them and checks the word count against the speech length (about 130 words per minute); (d) a trim or expand pass if needed. Every factual claim carries \[S#\] markers, shown as footnotes in the exported version. The user can edit the speech and regenerate single paragraphs.

### 10.4 Working paper

- Format follows Security Council working paper conventions: title, sponsors and signatories, preambular clauses (italicized opening verbs such as Recalling, Reaffirming, Noting), operative clauses (numbered, with verbs such as Calls upon, Decides, Urges).
- Preambular clauses: selected from real language in retrieved resolutions that are linked to the topic, rephrased minimally, each tied to a real resolution that exists in the database. A validator checks every referenced resolution against the documents table and rejects invented ones.
- Operative clauses: drafted one at a time from a fixed outline (security, humanitarian, political process, sanctions or enforcement, financing, monitoring and reporting). After each clause, a bounded check retrieves related existing resolutions and notes possible conflicts for the user.
- Suggested sponsors and signatories come from the bloc analysis. The user can edit everything.
- Exports as DOCX with proper numbering. Provide a separate evidence appendix mapping each clause to its sources.

### 10.5 POIs and follow-ups (the trap questions)

For each participating country, produce POI cards. Method:

1. **Candidate generation (code).** Find tensions: (a) the country voted No or abstained on a resolution while its own statements endorse the same principle; (b) two statements by the same country that conflict; (c) a stated position that conflicts with a resolution the country voted for; (d) a gap between the country’s stated commitments and its voting pattern on this topic. Use embedding similarity between statement chunks and operative clauses combined with the vote table.
2. **Judging (Qwen, bounded).** For each candidate pair, ask a single yes or no question: does statement A conflict with action B? with a one-sentence reason. Keep only yes results with a confidence over a threshold, and mark them “review recommended”.
3. **Card generation.** Each card has: the question (short, neutral in wording and suitable for a 15-second POI), the evidence (verbatim quotes, meeting number, date, vote), the expected answer branches (if they say A, follow up with …; if they say B, follow up with …), and a final pointed follow-up. Qwen writes only the question and the branches; code supplies the evidence.
4. **Accuracy rule.** A card is never generated without at least two linked evidence items. If no strong angle exists, show “No strong angle found for this country” instead of inventing one. Every card shows its evidence so the user can verify before using it in committee.
5. **Optional later step:** import treaty ratification status per country to enable questions like “your country is a party to X, yet …”. Mark this as a stretch goal.

## 11. UI specification

Principles: friendly, uncluttered, big readable text, consistent layout, nothing hidden more than two clicks away, a status bar showing LLM and database health. Light and dark themes. Works at laptop screen size. Keyboard shortcut / focuses the Ask box.

| Page | Contents |
| --- | --- |
| **Home** | List of conferences (cards), a New conference button, library health summary |
| **New conference** | The form in 10.1 with the coverage check |
| **Dossier** | Left sidebar listing sections and countries; main reading pane; a regenerate button per section; copy and export buttons; evidence popovers on every citation; a progress bar while building |
| **Ask** (live mode) | Conference header (committee, agenda, my country) always visible; one large prompt box; mode chips (Evidence, Stance, Connect, Argue, Counter, Check clause); two-pane result: Evidence panel (instant, verbatim, with source and date) and Answer panel (streamed, cited); Pin to notes; recent questions list |
| **Speeches and POIs** | Speech editor with timer and word count; POI deck with one card per country, filterable, printable |
| **Library** | Search and filter documents, view parse quality, add a document by drag and drop, ingestion queue and status |
| **Connections** | Review queue (accept, reject, edit relation), plus a small graph view for a selected document |
| **Corpus packs** | Run fetcher, see missing documents, add a pack |
| **Settings** | Endpoint URL, model name, context length check, embedding model, thinking mode switch, theme |
| **Jobs** | Running and finished background jobs, with logs |

Exports: Markdown and DOCX for the whole dossier or any single section, a print stylesheet for PDF, and a one-page “committee cheat sheet” export (my position, top 5 facts, vote table, best POIs).

## 12. One-click Windows scripts

| Script | What it does |
| --- | --- |
| install.bat | Checks for Python 3.11 (offers to install via winget), creates a virtual environment, installs requirements, checks that Ollama is installed and running, pulls qwen3:8b, creates the qwen3-mun model with the Modelfile, downloads the embedding and reranker models once, creates the database, and runs doctor |
| start.bat | Starts Ollama if needed, starts the app, opens the browser at the local address |
| doctor.bat | Checks Python, packages, Ollama, the model, the context length, GPU use, disk space, the database, and the embedding model, and prints PASS or FAIL with fixes |
| fetch.bat | Runs the fetcher for chosen packs, then ingests corpus/inbox |
| backup.bat | Copies the database and raw corpus to a dated folder |
| update.bat | Updates the app and dependencies without touching data |

## 13. Phases and acceptance criteria

Each phase must meet every acceptance item before the next begins.

### Phase 0: Scaffolding and environment

Build: repo layout, config, install/start/doctor scripts, Modelfile, FastAPI hello page, LLM client with streaming and think-stripping, status bar. Accept: a fresh Windows machine with Python and Ollama installed reaches a working page after install.bat then start.bat; doctor shows PASS; a test prompt streams from qwen3-mun; the context length is confirmed as 8192.

### Phase 1: Database and core ingestion

Build: schema, cleaning, charter/treaty and resolution parsers, chunker, embeddings, FTS and vector indexes, drag-and-drop upload and inbox ingestion, Library page. Accept: the UN Charter and 3 resolutions ingest without errors; articles and paragraphs are separate, correctly labeled chunks; re-ingesting creates no duplicates; a low-quality parse is flagged.

### Phase 2: Retrieval and Evidence mode (first usable live mode)

Build: router, hybrid search, rerank, packing, low-evidence gate, Evidence mode, Ask page, guardrails 1 to 4 and 6, evaluation runner. Accept: Article 51 and similar exact-reference queries return the right chunk first; retrieval takes ≤ 2 seconds on the 8 GB laptop; the evidence panel appears before the answer; answers contain only valid markers; an out-of-library question returns “Not found”.

### Phase 3: Fetcher and Haiti pack

Build: manifests, fetcher, core pack, Haiti pack discovery, S/PV and press release parsers, country alias table, topic tagging. Accept: the core pack and the Haiti pack download or list clearly which items need manual download; at least 90 percent of S/PV interventions get a country; the Haiti topic tags the right documents.

### Phase 4: Votes and Country Stance mode

Build: vote importers (CSV, press release parser, manual form), vote validation, Country stance mode, the votes table component. Accept: for the Haiti resolutions, vote tallies match the official records for every resolution; the question “What is the US stance on Haiti?” shows a vote table and dated verbatim statements, then a cited summary; a country with no statements shows “No data”.

### Phase 5: Graph and connections

Build: regex link extraction, typed edges, stub nodes, graph expansion in retrieval, Connect mode, review queue UI, optional LLM link-suggestion job. Accept: Haiti resolutions link to the resolutions they recall; “How are resolution A and B connected?” returns a path with explanations; rejected edges never appear in answers.

### Phase 6: Conference form and dossier sections 1 to 7

Build: form with coverage check, job system, sections 1 to 7, bloc analysis, Dossier page, section regeneration. Accept: a Haiti dossier for Colombia with the UNSC-15 preset completes in under 30 minutes; sections save independently; the bloc clusters come from votes; every country profile either has evidence or says “No data”.

### Phase 7: Speech, working paper and POIs

Build: sections 8 to 10 as in section 10, validators, DOCX export. Accept: the speech fits the target time within 10 percent and every fact has a source; the working paper’s referenced resolutions all exist in the database; every POI card has two or more evidence items with verbatim quotes; countries with no strong angle say so.

### Phase 8: Polish and delivery

Build: remaining modes (Argue, Counter, Check clause), notes, committee cheat sheet, backup script, theme polish, onboarding screen, README for beginners with screenshots. Accept: a new user can go from download to first dossier by following the README; all pages are consistent; the whole evaluation set passes the thresholds below.

## 14. Evaluation set (Haiti)

File: eval/haiti\_qa.yaml. The user supplies ground truth from their own earlier prep; the builder implements the runner. Target 30 to 40 questions in these categories:

- Exact lookups (which resolution established BINUH, what does OP 4 of resolution X say)
- Votes (how did country X vote on resolution Y)
- Stance questions per country (US, China, Russia, Colombia, France, UK)
- Connections (which earlier resolutions does X recall)
- Argument and counterargument requests from Colombia’s perspective
- Unanswerable questions (topics not in the library, to test refusal)

Each entry stores the question, expected source symbols and labels, expected vote values where relevant, and whether the answer should be refused.

Metrics and thresholds: recall of expected sources in the top 8 ≥ 85 percent; citation marker validity 100 percent; vote accuracy 100 percent (it is code, so no excuse); refusal correct on at least 90 percent of unanswerables; evidence panel latency ≤ 2 seconds; first answer token ≤ 10 seconds; hallucinated resolution numbers 0.

## 15. Known risks

- **Scanned older documents:** OCR is slower and less accurate; treat as a stretch task and flag quality.
- **Sparse data for some countries:** many countries rarely speak. The app must show data gaps rather than fill them.
- **UN website changes:** the fetcher can break. Keep the manual inbox as a first-class path.
- **Small model errors:** mitigated by the guardrails in section 8 and by showing evidence first.
- **Rules of the conference:** the user confirmed laptops are allowed. Keep the app’s data fully local anyway.
- **Time and scope:** if time runs short, the priority order is Phases 0 to 4 (a working live mode with country stance), then 6 and 7 (dossier, speech, working paper, POIs), then 5 and 8.

## 16. Setup checklist for the user (beginner friendly)

1. Install Python 3.11 from python.org (tick Add to PATH).
2. Install Ollama from ollama.com.
3. Download the project and double-click install.bat.
4. Double-click fetch.bat while connected to the internet, then drop any extra PDFs into corpus/inbox.
5. Double-click start.bat. A browser window opens.
6. Before a conference: create the conference in the app, run the dossier, export it, and run backup.bat.

## 17. How to hand this to the builder

Give the builder this whole document once, then give it one phase at a time using the phrase: Build Phase N exactly as specified, then run the acceptance checks and report results. Ask the orchestrator for a tailored builder prompt for each phase, including exact file lists and test commands, when you reach it.
