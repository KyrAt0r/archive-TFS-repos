from __future__ import annotations

import base64
import datetime as dt
from pathlib import Path


def now_str() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def ts_compact() -> str:
    return dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def safe_filename(name: str) -> str:
    repl = []
    for ch in name:
        if ch.isalnum() or ch in ("-", "_", "."):
            repl.append(ch)
        else:
            repl.append("_")
    return "".join(repl).strip("_") or "repo"


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def write_text(p: Path, s: str) -> None:
    p.write_text(s, encoding="utf-8")


def append_log(log_path: Path, line: str) -> None:
    msg = f"[{now_str()}] {line}"
    print(msg)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(msg + "\n")


def b64_basic(user: str, password: str) -> str:
    raw = f"{user}:{password}".encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def b64_basic_pat(pat: str) -> str:
    # Azure DevOps/TFS PAT: ":PAT"
    raw = f":{pat}".encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def file_size_bytes(p: Path | None) -> int:
    try:
        return p.stat().st_size if p and p.exists() else 0
    except Exception:
        return 0
