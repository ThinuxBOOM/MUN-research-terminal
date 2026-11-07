-- MUN Research Station database schema (SQLite + FTS5).
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS documents (
  id INTEGER PRIMARY KEY,
  symbol TEXT UNIQUE,
  title TEXT,
  doc_type TEXT,   -- charter|treaty|resolution|pv_record|press_release|sg_report|icj|rules|position|other
  organ TEXT,      -- GA|SC|ICJ|SG|OTHER
  date TEXT,
  year INTEGER,
  source_path TEXT,
  source_url TEXT,
  sha256 TEXT,
  parse_quality REAL,
  status TEXT,     -- ok|low_quality|stub|error
  ingested_at TEXT
);

CREATE TABLE IF NOT EXISTS chunks (
  id INTEGER PRIMARY KEY,
  doc_id INTEGER REFERENCES documents(id) ON DELETE CASCADE,
  ordinal INTEGER,
  kind TEXT,       -- article|preambular|operative|intervention|paragraph|section
  label TEXT,
  speaker_name TEXT,
  speaker_country TEXT,
  meeting_no TEXT,
  date TEXT,
  text TEXT,
  token_count INTEGER
);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
  text, label, content=chunks, content_rowid=id, tokenize='unicode61'
);

CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
  INSERT INTO chunks_fts(rowid, text, label) VALUES (new.id, new.text, new.label);
END;
CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
  INSERT INTO chunks_fts(chunks_fts, rowid, text, label) VALUES ('delete', old.id, old.text, old.label);
END;
CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
  INSERT INTO chunks_fts(chunks_fts, rowid, text, label) VALUES ('delete', old.id, old.text, old.label);
  INSERT INTO chunks_fts(rowid, text, label) VALUES (new.id, new.text, new.label);
END;

-- Vector store. Embeddings are stored as float32 BLOBs; app/vectorindex.py uses
-- sqlite-vec when the extension is available and numpy cosine otherwise.
CREATE TABLE IF NOT EXISTS chunk_vec (
  chunk_id INTEGER PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
  dim INTEGER NOT NULL,
  vec BLOB NOT NULL
);

CREATE TABLE IF NOT EXISTS countries (
  iso3 TEXT PRIMARY KEY,
  name TEXT,
  aliases TEXT   -- JSON list
);

CREATE TABLE IF NOT EXISTS votes (
  id INTEGER PRIMARY KEY,
  doc_id INTEGER REFERENCES documents(id) ON DELETE CASCADE,
  iso3 TEXT,
  vote TEXT,     -- Y|N|A|NV
  source TEXT    -- undl_csv|press_release|manual
);

CREATE TABLE IF NOT EXISTS topics (
  id INTEGER PRIMARY KEY,
  name TEXT UNIQUE,
  keywords TEXT  -- JSON list
);

CREATE TABLE IF NOT EXISTS doc_topics (
  doc_id INTEGER, topic_id INTEGER, origin TEXT,
  PRIMARY KEY (doc_id, topic_id)
);

CREATE TABLE IF NOT EXISTS edges (
  id INTEGER PRIMARY KEY,
  src_type TEXT, src_id INTEGER, dst_type TEXT, dst_id INTEGER,
  rel TEXT,     -- cites|recalls|reaffirms|amends|extends|supersedes|supports|contradicts|related
  origin TEXT,  -- regex|llm|manual
  confidence REAL,
  status TEXT DEFAULT 'pending',   -- pending|accepted|rejected
  evidence_chunk_id INTEGER
);

CREATE TABLE IF NOT EXISTS conferences (
  id INTEGER PRIMARY KEY,
  name TEXT, committee TEXT, agenda TEXT, my_country TEXT,
  countries TEXT,   -- JSON list of ISO3
  topic_id INTEGER,
  speech_seconds INTEGER,
  want_working_paper INTEGER DEFAULT 1,
  created_at TEXT
);

CREATE TABLE IF NOT EXISTS dossier_sections (
  id INTEGER PRIMARY KEY,
  conference_id INTEGER REFERENCES conferences(id) ON DELETE CASCADE,
  section TEXT, country TEXT, content_md TEXT, evidence_json TEXT,
  status TEXT, generated_at TEXT
);

CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY,
  kind TEXT, status TEXT, progress REAL, message TEXT, payload TEXT, created_at TEXT
);

CREATE TABLE IF NOT EXISTS notes (
  id INTEGER PRIMARY KEY,
  conference_id INTEGER, chunk_id INTEGER, text TEXT, created_at TEXT
);

CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY, value TEXT
);

CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id);
CREATE INDEX IF NOT EXISTS idx_chunks_country ON chunks(speaker_country);
CREATE INDEX IF NOT EXISTS idx_chunks_ordinal ON chunks(doc_id, ordinal);
CREATE INDEX IF NOT EXISTS idx_votes_doc ON votes(doc_id);
CREATE INDEX IF NOT EXISTS idx_votes_iso ON votes(iso3);
CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(src_id);
CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst_id);
CREATE INDEX IF NOT EXISTS idx_docs_symbol ON documents(symbol);
CREATE INDEX IF NOT EXISTS idx_docs_year ON documents(year);
CREATE INDEX IF NOT EXISTS idx_dossier_conf ON dossier_sections(conference_id);
