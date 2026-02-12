from __future__ import annotations

import threading
import queue
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
import subprocess

from .models import AuthConfig, AuthMode, ArchiveOptions
from .archiver import run_archive
from .git_ops import CancelledError


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("TFS/Azure DevOps Git Archiver (bundle/zip)")
        self.geometry("980x680")
        self.minsize(900, 620)

        self._log_q: "queue.Queue[str]" = queue.Queue()
        self._worker: threading.Thread | None = None
        self._cancel_flag = threading.Event()
        self._current_proc: subprocess.Popen | None = None

        self._build_ui()
        self.after(100, self._drain_log_queue)

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=10)
        root.pack(fill="both", expand=True)

        root.columnconfigure(0, weight=1)
        root.rowconfigure(2, weight=1)

        # ---- Connection / Output ----
        frm_top = ttk.LabelFrame(root, text="Connection / Output", padding=10)
        frm_top.grid(row=0, column=0, sticky="ew")
        frm_top.columnconfigure(1, weight=1)

        ttk.Label(frm_top, text="Collection URL:").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=2)
        self.var_collection = tk.StringVar(value="https://tfs.example.local/tfs/DefaultCollection")
        ttk.Entry(frm_top, textvariable=self.var_collection).grid(row=0, column=1, sticky="ew", pady=2)

        ttk.Label(frm_top, text="Project:").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=2)
        self.var_project = tk.StringVar(value="SampleProject")
        ttk.Entry(frm_top, textvariable=self.var_project).grid(row=1, column=1, sticky="ew", pady=2)

        ttk.Label(frm_top, text="Out root:").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=2)
        self.var_out_root = tk.StringVar(value=str(Path.cwd() / "out_archive"))
        ent_out = ttk.Entry(frm_top, textvariable=self.var_out_root)
        ent_out.grid(row=2, column=1, sticky="ew", pady=2)
        ttk.Button(frm_top, text="Browse...", command=self._browse_out_root).grid(row=2, column=2, sticky="ew", padx=(8, 0), pady=2)

        ttk.Label(frm_top, text="API version:").grid(row=3, column=0, sticky="w", padx=(0, 8), pady=2)
        self.var_api_version = tk.StringVar(value="6.0")
        ttk.Entry(frm_top, textvariable=self.var_api_version, width=10).grid(row=3, column=1, sticky="w", pady=2)

        # ---- Auth ----
        frm_auth = ttk.LabelFrame(root, text="Auth", padding=10)
        frm_auth.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        frm_auth.columnconfigure(1, weight=1)
        frm_auth.columnconfigure(3, weight=1)

        self.var_auth_mode = tk.StringVar(value="pat")
        r1 = ttk.Radiobutton(frm_auth, text="PAT", value="pat", variable=self.var_auth_mode, command=self._sync_auth_fields)
        r2 = ttk.Radiobutton(frm_auth, text="Username / Password (Basic)", value="userpass", variable=self.var_auth_mode, command=self._sync_auth_fields)
        r1.grid(row=0, column=0, sticky="w", pady=2)
        r2.grid(row=0, column=1, sticky="w", pady=2)

        ttk.Label(frm_auth, text="PAT:").grid(row=1, column=0, sticky="w", pady=2)
        self.var_pat = tk.StringVar()
        self.ent_pat = ttk.Entry(frm_auth, textvariable=self.var_pat, show="*")
        self.ent_pat.grid(row=1, column=1, sticky="ew", pady=2, padx=(0, 10))

        ttk.Label(frm_auth, text="Username:").grid(row=2, column=0, sticky="w", pady=2)
        self.var_user = tk.StringVar()
        self.ent_user = ttk.Entry(frm_auth, textvariable=self.var_user)
        self.ent_user.grid(row=2, column=1, sticky="ew", pady=2, padx=(0, 10))

        ttk.Label(frm_auth, text="Password:").grid(row=3, column=0, sticky="w", pady=2)
        self.var_pass = tk.StringVar()
        self.ent_pass = ttk.Entry(frm_auth, textvariable=self.var_pass, show="*")
        self.ent_pass.grid(row=3, column=1, sticky="ew", pady=2, padx=(0, 10))

        # ---- Options ----
        frm_opt = ttk.LabelFrame(root, text="Options", padding=10)
        frm_opt.grid(row=2, column=0, sticky="nsew", pady=(10, 0))
        frm_opt.columnconfigure(0, weight=1)
        frm_opt.rowconfigure(1, weight=1)

        row0 = ttk.Frame(frm_opt)
        row0.grid(row=0, column=0, sticky="ew")
        for i in range(8):
            row0.columnconfigure(i, weight=0)
        row0.columnconfigure(7, weight=1)

        self.var_zip = tk.BooleanVar(value=True)
        self.var_del_bundle = tk.BooleanVar(value=True)
        self.var_keep_mirrors = tk.BooleanVar(value=False)
        self.var_skip_existing = tk.BooleanVar(value=True)

        ttk.Checkbutton(row0, text="ZIP bundles", variable=self.var_zip).grid(row=0, column=0, sticky="w", padx=(0, 10))
        ttk.Checkbutton(row0, text="Delete .bundle after ZIP", variable=self.var_del_bundle).grid(row=0, column=1, sticky="w", padx=(0, 10))
        ttk.Checkbutton(row0, text="Keep mirrors/", variable=self.var_keep_mirrors).grid(row=0, column=2, sticky="w", padx=(0, 10))
        ttk.Checkbutton(row0, text="Skip existing", variable=self.var_skip_existing).grid(row=0, column=3, sticky="w", padx=(0, 10))

        ttk.Label(row0, text="Only:").grid(row=0, column=4, sticky="e")
        self.var_only = tk.StringVar(value="")
        ttk.Entry(row0, textvariable=self.var_only, width=20).grid(row=0, column=5, sticky="w", padx=(6, 10))

        ttk.Label(row0, text="Max repos:").grid(row=0, column=6, sticky="e")
        self.var_max = tk.StringVar(value="0")
        ttk.Entry(row0, textvariable=self.var_max, width=8).grid(row=0, column=7, sticky="w", padx=(6, 0))

        row1 = ttk.Frame(frm_opt)
        row1.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        row1.columnconfigure(0, weight=1)
        row1.rowconfigure(0, weight=1)

        self.txt_log = tk.Text(row1, wrap="word")
        self.txt_log.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(row1, command=self.txt_log.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.txt_log.configure(yscrollcommand=scroll.set)

        # ---- Buttons ----
        frm_btn = ttk.Frame(root)
        frm_btn.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        frm_btn.columnconfigure(2, weight=1)

        self.btn_start = ttk.Button(frm_btn, text="Start", command=self._start)
        self.btn_cancel = ttk.Button(frm_btn, text="Cancel", command=self._cancel, state="disabled")

        self.btn_start.grid(row=0, column=0, sticky="w")
        self.btn_cancel.grid(row=0, column=1, sticky="w", padx=(10, 0))

        self._sync_auth_fields()

    def _browse_out_root(self) -> None:
        p = filedialog.askdirectory(title="Select output folder")
        if p:
            self.var_out_root.set(p)

    def _sync_auth_fields(self) -> None:
        mode = self.var_auth_mode.get()
        if mode == "pat":
            self.ent_pat.configure(state="normal")
            self.ent_user.configure(state="disabled")
            self.ent_pass.configure(state="disabled")
        else:
            self.ent_pat.configure(state="disabled")
            self.ent_user.configure(state="normal")
            self.ent_pass.configure(state="normal")

    def _log(self, line: str) -> None:
        self._log_q.put(line)

    def _drain_log_queue(self) -> None:
        try:
            while True:
                line = self._log_q.get_nowait()
                self.txt_log.insert("end", f"{line}\n")
                self.txt_log.see("end")
        except queue.Empty:
            pass
        self.after(100, self._drain_log_queue)

    def _set_current_proc(self, p: subprocess.Popen | None) -> None:
        self._current_proc = p

    def _start(self) -> None:
        if self._worker and self._worker.is_alive():
            messagebox.showinfo("Running", "Task is already running.")
            return

        try:
            auth = self._build_auth()
            opts = self._build_opts()
        except Exception as e:
            messagebox.showerror("Invalid settings", str(e))
            return

        self._cancel_flag.clear()
        self.btn_start.configure(state="disabled")
        self.btn_cancel.configure(state="normal")
        self.txt_log.delete("1.0", "end")

        def worker() -> None:
            try:
                res = run_archive(
                    auth=auth,
                    opts=opts,
                    on_progress=self._log,
                    is_cancelled=self._cancel_flag.is_set,
                    current_proc_setter=self._set_current_proc,
                )
                self._log(f"FINISHED: OK={res.ok}, FAIL={res.fail}")
                self._log(f"LOG: {res.log_path}")
                self._log(f"CSV: {res.csv_path}")
                self._log(f"README: {res.readme_path}")
                self.after(0, lambda: messagebox.showinfo("Done", f"OK={res.ok}, FAIL={res.fail}\n\n{res.outcome if hasattr(res,'outcome') else ''}"))
            except CancelledError:
                self._log("CANCELLED")
            except Exception as e:
                self._log(f"ERROR: {e}")
                self.after(0, lambda: messagebox.showerror("Error", str(e)))
            finally:
                self.after(0, self._on_finish)

        self._worker = threading.Thread(target=worker, daemon=True)
        self._worker.start()

    def _cancel(self) -> None:
        if not (self._worker and self._worker.is_alive()):
            return
        self._cancel_flag.set()
        # best-effort terminate current git process (if any)
        p = self._current_proc
        if p:
            try:
                p.terminate()
            except Exception:
                pass
        self._log("Cancel requested...")

    def _on_finish(self) -> None:
        self.btn_start.configure(state="normal")
        self.btn_cancel.configure(state="disabled")

    def _build_auth(self) -> AuthConfig:
        mode = self.var_auth_mode.get()
        if mode == "pat":
            pat = (self.var_pat.get() or "").strip()
            if not pat:
                raise ValueError("PAT is required.")
            return AuthConfig(mode=AuthMode.PAT, pat=pat)
        else:
            user = (self.var_user.get() or "").strip()
            pwd = self.var_pass.get() or ""
            if not user or not pwd:
                raise ValueError("Username and Password are required.")
            return AuthConfig(mode=AuthMode.USERPASS, username=user, password=pwd)

    def _build_opts(self) -> ArchiveOptions:
        out_root = Path(self.var_out_root.get()).expanduser()
        max_repos = int(self.var_max.get() or "0")

        return ArchiveOptions(
            collection_url=(self.var_collection.get() or "").strip(),
            project=(self.var_project.get() or "").strip(),
            out_root=out_root,
            api_version=(self.var_api_version.get() or "6.0").strip(),

            keep_mirrors=bool(self.var_keep_mirrors.get()),
            only_substring=(self.var_only.get() or "").strip(),
            sleep_sec=0.0,

            zip_bundles=bool(self.var_zip.get()),
            delete_bundle_after_zip=bool(self.var_del_bundle.get()),
            skip_existing=bool(self.var_skip_existing.get()),
            max_repos=max_repos,
        )


def main() -> int:
    app = App()
    app.mainloop()
    return 0
