from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Callable

from .utils import append_log


class CancelledError(RuntimeError):
    pass


def run_git(
    args: List[str],
    cwd: Optional[Path],
    log_path: Path,
    *,
    extra_env: Optional[Dict[str, str]] = None,
    is_cancelled: Optional[Callable[[], bool]] = None,
    current_proc_setter: Optional[Callable[[subprocess.Popen | None], None]] = None,
    on_output: Optional[Callable[[str], None]] = None,
) -> int:
    """
    Git runner with REAL-TIME progress streaming (works with git clone --progress):
    - Uses binary pipes + read1() to avoid buffering issues
    - Handles both '\\n' and '\\r' progress updates
    - stderr merged into stdout
    """

    def mask_args(cmd: List[str]) -> str:
        masked: List[str] = []
        for a in cmd:
            if "http.extraHeader=Authorization:" in a or "Authorization: Basic" in a:
                masked.append("http.extraHeader=Authorization: Basic ***REDACTED***")
            else:
                masked.append(a)
        return " ".join(masked)

    if is_cancelled and is_cancelled():
        raise CancelledError("Cancelled before git start")

    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    if extra_env:
        env.update(extra_env)

    cmd_str = mask_args(args)
    append_log(log_path, f"RUN: {cmd_str}")
    if on_output:
        on_output(f"RUN: {cmd_str}")

    # IMPORTANT: text=False (binary), so we can use read1()
    p = subprocess.Popen(
        args,
        cwd=str(cwd) if cwd else None,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=False,
        bufsize=0,
    )

    if current_proc_setter:
        current_proc_setter(p)

    try:
        assert p.stdout is not None

        with log_path.open("ab") as lf:  # binary log write
            buf = b""

            def emit_piece(piece_bytes: bytes) -> None:
                if not on_output:
                    return
                try:
                    s = piece_bytes.decode("utf-8", errors="replace")
                except Exception:
                    s = str(piece_bytes)
                s = s.strip("\n")
                # do not spam empty pieces
                if s.strip():
                    on_output(s)

            while True:
                if is_cancelled and is_cancelled():
                    try:
                        p.terminate()
                    except Exception:
                        pass
                    raise CancelledError("Cancelled during git process")

                # read1 returns as soon as ANY data is available (key for progress)
                chunk = p.stdout.read1(4096)  # type: ignore[attr-defined]
                if not chunk:
                    break

                # Write raw bytes to terminal + log file
                try:
                    sys.stdout.buffer.write(chunk)
                    sys.stdout.buffer.flush()
                except Exception:
                    # fallback if buffer isn't available
                    sys.stdout.write(chunk.decode("utf-8", errors="replace"))
                    sys.stdout.flush()

                lf.write(chunk)
                lf.flush()

                # Stream to GUI: split by '\r' or '\n'
                buf += chunk
                while True:
                    npos = buf.find(b"\n")
                    rpos = buf.find(b"\r")

                    if npos == -1 and rpos == -1:
                        # keep buffer under control
                        if len(buf) > 8192:
                            emit_piece(buf[-2048:])
                            buf = b""
                        break

                    if npos == -1:
                        cut = rpos
                        sep = b"\r"
                    elif rpos == -1:
                        cut = npos
                        sep = b"\n"
                    else:
                        cut = min(npos, rpos)
                        sep = buf[cut : cut + 1]

                    piece = buf[:cut]
                    buf = buf[cut + 1 :]

                    # For '\r' progress updates: emit immediately
                    emit_piece(piece)

            # flush remaining
            if buf:
                emit_piece(buf)

        return p.wait()

    finally:
        if current_proc_setter:
            current_proc_setter(None)
