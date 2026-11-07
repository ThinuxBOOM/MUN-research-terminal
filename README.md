# MUN Research Station

A local, offline research tool for Model UN delegates (General Assembly and Security Council).
It keeps a searchable library of real UN documents and answers questions **from those documents
only**, showing the evidence before the answer.

Everything runs on this laptop. After setup the app needs no internet.

---

## Quick start (beginner)

1. Install **Python 3.11 or newer** from python.org — tick *Add python.exe to PATH*.
2. Install **Ollama** from ollama.com.
3. Double-click **`install.bat`**. It creates a virtual environment, installs the Python
   packages, pulls `qwen3:8b`, creates the `qwen3-mun` model with `num_ctx 8192`, downloads the
   embedding model, creates the database and runs the doctor.
4. Double-click **`fetch.bat`** while online. It downloads the core legal pack and the Haiti pack
   into `corpus/raw`, then indexes them. Anything it cannot fetch is listed; download those by
   hand into `corpus/inbox` and use **Library → Ingest corpus/inbox**.
5. Double-click **`start.bat`**. The browser opens at `http://127.0.0.1:8765`.

| Script | What it does |
| --- | --- |
| `install.bat` | One-time setup (env, packages, models, database, doctor) |
| `start.bat` | Starts Ollama if needed, starts the app, opens the browser |
| `doctor.bat` | PASS/FAIL checks with a plain-English fix for each failure |
| `fetch.bat` | Downloads + indexes the corpus manifests |
| `python scripts/discover.py Haiti` | Searches the UN Digital Library, fetches matching S/PV records, and keeps only files that mention the topic |
| `backup.bat` | Copies the database, config and raw corpus to `backups/YYYYMMDD-HHMM` |
| `update.bat` | Upgrades packages without touching data |

---

## Using it

1. **New conference** — name, committee, agenda, your country, participating countries
   (one-click UNSC-15 preset), speech length. A coverage check warns when the library is thin.
2. **Dossier** — ten sections, each saved as soon as it finishes: background, legal framework,
   resolution history with votes, country profiles, blocs, your position, counterarguments,
   speech, working paper, POIs. Each section has its own **Regenerate** button. Export Markdown
   or DOCX.
3. **Ask** — six modes: Evidence, Stance, Connect, Argue, Counter, Check clause. The evidence
   panel appears first and is streamed from the database; the answer streams beside it. Every
   citation marker is checked; unverified numbers are flagged.

Keyboard: `/` focuses the Ask box.

---

## How the accuracy guardrails work

- Retrieval is entirely code: route → exact symbol/article lookup → FTS5 BM25 + embedding search
  → reciprocal rank fusion → rerank → accepted-graph expansion → token-budgeted pack.
- The model sees only the numbered passages (`[S1] …`) and must end sentences with markers.
- After generation, every marker is checked against the pack; sentences with unknown markers or
  unsupported numbers/dates are flagged in the UI.
- Votes are rendered from the `votes` table, never written by the model.
- If the best rerank score is below the threshold, the app answers "Not found in your library"
  and shows the closest passages without calling the model.
- Qwen3 thinking is off by default (`/no_think`); think blocks are stripped even when split across
  stream chunks.

---

## Project layout

```
app/
  main.py settings.py db.py schema.sql textutil.py vectorindex.py jobs.py
  llm/        client.py guards.py prompts.py prompts/*.txt
  ingest/     pipeline.py clean.py chunker.py countries.py votes.py links.py topics.py
              parsers/ resolution.py treaty.py pv.py press.py report.py
  retrieve/   service.py search.py fusion.py rerank.py pack.py graph.py router.py
  modes/      service.py  (evidence, stance, connect, argue, counter, check)
  dossier/    pipeline.py export.py form.py
  web/        routes.py templates/ static/ (vendored htmx + css)
corpus/       manifests/ raw/ inbox/
eval/         haiti_qa.yaml run_eval.py
tests/        pytest suite
data/         mun.db, exports/, logs/
```

## Configuration

`config.yaml` holds the endpoint, models, context length, budgets and thresholds. The
**Settings** page writes runtime overrides to the database (endpoint, models, theme, threshold,
thinking mode). The default endpoint is `http://localhost:11434` (Ollama native API, which is the
only one that applies `num_ctx` per request).

## Verified status

See [REPORT.md](REPORT.md) for measured results (23 tests passing, evaluation set at 4/4 source
recall and 4/4 correct refusals, a full ten-section dossier) and the list of remaining
blockers, chiefly the missing per-country vote data.

## Notes and limits

- Embeddings use `qwen3-embedding:0.6b` through Ollama (1024 dimensions), stored as float32 in
  `chunk_vec` and searched with numpy cosine. Set `retrieval` thresholds in Settings if you switch
  models; the vector store is rebuilt with `python scripts/reembed.py --force`.
- The reranker is a CPU hybrid of embedding cosine and lexical coverage, not a cross-encoder
  (fastembed/ONNX was not installed on this machine). It is a single function in
  `app/retrieve/rerank.py` and can be swapped without touching anything else.
- Scanned PDFs are flagged as `low_quality` and are not OCR'd.
- Votes: import a UN Digital Library CSV from the Library page, or use the press-release parser.
  Vote rows are never generated by the model. The library currently has statements from five
  S/PV records but **no vote rows**, so Stance shows statements and says so.
- `press.un.org` blocks automated downloads, so press releases must be saved by hand into
  `corpus/inbox`. S/PV records do download through the symbol API.
- The UN fetcher can break when UN URLs change; `corpus/inbox` is a first-class fallback.
