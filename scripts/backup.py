"""Copy the database and raw corpus into a dated backup folder (plan 12)."""
from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.settings import CORPUS_RAW, DATA_DIR, DB_PATH  # noqa: E402


def main() -> int:
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    target = ROOT / "backups" / stamp
    target.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        shutil.copy2(DB_PATH, target / "mun.db")
        print(f"Database copied to {target / 'mun.db'}")
    else:
        print("No database yet - nothing to copy.")
    config_path = ROOT / "config.yaml"
    if config_path.exists():
        shutil.copy2(config_path, target / "config.yaml")
    if CORPUS_RAW.exists():
        shutil.copytree(CORPUS_RAW, target / "raw", dirs_exist_ok=True)
        print(f"Raw corpus copied to {target / 'raw'}")
    exports = DATA_DIR / "exports"
    if exports.exists():
        shutil.copytree(exports, target / "exports", dirs_exist_ok=True)
    print(f"\nBackup finished: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
