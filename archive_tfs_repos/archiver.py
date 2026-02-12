from __future__ import annotations

import csv
import shutil
import textwrap
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Tuple, List

from .models import RepoInfo, ArchiveOptions, RunPaths, AuthConfig
from .utils import (
    append_log,
    ensure_dir,
    file_size_bytes,
    now_str,
    safe_filename,
    ts_compact,
    write_text,
    b64_basic,
    b64_basic_pat,
)
from .tfs_api import list_repos
from .git_ops import run_git, CancelledError


def make_readme(out_root: Path) -> str:
    return textwrap.dedent(f"""\
    # TFS/Azure DevOps Git Bundles Archive

    Created: {now_str()}
    Folder:  {out_root}

    ## Contents
    - bundles/   : *.bundle OR *.zip (if zip enabled)
    - logs/      : run logs
    - reports/   : CSV report

    ## Notes
    - Bundle includes all refs (--all): branches/tags should be present.
    - If your server uses LFS, LFS objects are not embedded into bundle automatically.
    """)


def make_restore_ru(repo_name: str, branch_hint: str = "master") -> str:
    return f"""\
АРХИВ РЕПОЗИТОРИЯ: {repo_name}

В архиве находятся:
  - {repo_name}.bundle
  - README_RESTORE_RU.txt
  - README_RESTORE_EN.txt

============================================================
КАК ВОССТАНОВИТЬ РЕПОЗИТОРИЙ ИЗ BUNDLE
============================================================

Вариант A (проще всего):

  git clone {repo_name}.bundle {repo_name}
  cd {repo_name}
  git checkout {branch_hint}

Вариант B (вручную):

  mkdir {repo_name}
  cd {repo_name}
  git init
  git remote add origin ../{repo_name}.bundle
  git fetch origin --all
  git checkout {branch_hint}

Примечания:
- Bundle создаётся так: git bundle create {repo_name}.bundle --all
- Проверка:           git bundle verify {repo_name}.bundle

Дата: {now_str()}
"""


def make_restore_en(repo_name: str, branch_hint: str = "master") -> str:
    return f"""\
REPOSITORY ARCHIVE: {repo_name}

Inside:
  - {repo_name}.bundle
  - README_RESTORE_RU.txt
  - README_RESTORE_EN.txt

============================================================
HOW TO RESTORE FROM BUNDLE
============================================================

Option A (simple):

  git clone {repo_name}.bundle {repo_name}
  cd {repo_name}
  git checkout {branch_hint}

Option B (manual):

  mkdir {repo_name}
  cd {repo_name}
  git init
  git remote add origin ../{repo_name}.bundle
  git fetch origin --all
  git checkout {branch_hint}

Notes:
- Bundle was created with: git bundle create {repo_name}.bundle --all
- Integrity check used:   git bundle verify {repo_name}.bundle

Date: {now_str()}
"""


def pack_bundle_to_zip(repo_name_safe: str, bundle_path: Path, log_path: Path) -> Path:
    zip_name = f"{repo_name_safe}_{ts_compact()}.zip"
    zip_path = bundle_path.parent / zip_name

    append_log(log_path, f"[{repo_name_safe}] Creating ZIP: {zip_path}")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(bundle_path, arcname=bundle_path.name)
        zf.writestr("README_RESTORE_RU.txt", make_restore_ru(repo_name_safe))
        zf.writestr("README_RESTORE_EN.txt", make_restore_en(repo_name_safe))

    return zip_path


def build_run_paths(opts: ArchiveOptions, run_id: str) -> RunPaths:
    out_root = opts.out_root.expanduser().resolve()

    bundles_dir = out_root / "bundles"
    mirrors_dir = out_root / "mirrors"
    logs_dir = out_root / "logs"
    reports_dir = out_root / "reports"

    ensure_dir(bundles_dir)
    ensure_dir(mirrors_dir)
    ensure_dir(logs_dir)
    ensure_dir(reports_dir)

    log_path = logs_dir / f"archive_{safe_filename(opts.project)}_{run_id}.log"
    csv_path = reports_dir / f"report_{safe_filename(opts.project)}_{run_id}.csv"
    readme_path = out_root / "README_RESTORE.md"

    return RunPaths(
        out_root=out_root,
        bundles_dir=bundles_dir,
        mirrors_dir=mirrors_dir,
        logs_dir=logs_dir,
        reports_dir=reports_dir,
        log_path=log_path,
        csv_path=csv_path,
        readme_path=readme_path,
    )


def auth_to_basic_b64(auth: AuthConfig) -> str:
    auth.validate()
    if auth.mode.value == "pat":
        return b64_basic_pat(auth.pat or "")
    return b64_basic(auth.username or "", auth.password or "")


def archive_one_repo(
    repo: RepoInfo,
    paths: RunPaths,
    log_path: Path,
    auth_basic_b64: str,
    *,
    keep_mirrors: bool,
    zip_enabled: bool,
    delete_bundle_after_zip: bool,
    skip_existing: bool,
    is_cancelled: Optional[Callable[[], bool]] = None,
    current_proc_setter=None,
    on_progress: Optional[Callable[[str], None]] = None,
) -> Tuple[bool, str, Optional[Path]]:
    repo_safe = safe_filename(repo.name)
    mirror_path = paths.mirrors_dir / f"{repo_safe}.git"
    bundle_path = paths.bundles_dir / f"{repo_safe}.bundle"

    if zip_enabled and skip_existing:
        existing = sorted(paths.bundles_dir.glob(f"{repo_safe}_*.zip"))
        if existing:
            append_log(log_path, f"[{repo.name}] SKIP: ZIP already exists: {existing[-1].name}")
            return True, "SKIPPED (zip exists)", existing[-1]

    if (not zip_enabled) and skip_existing and bundle_path.exists():
        append_log(log_path, f"[{repo.name}] SKIP: bundle already exists: {bundle_path.name}")
        return True, "SKIPPED (bundle exists)", bundle_path

    extra_header = f"Authorization: Basic {auth_basic_b64}"

    if mirror_path.exists():
        append_log(log_path, f"[{repo.name}] Mirror already exists, removing: {mirror_path}")
        shutil.rmtree(mirror_path, ignore_errors=True)

    rc = run_git(
        [
            "git",
            "-c",
            f"http.extraHeader={extra_header}",
            "-c",
            "core.askPass=",
            "clone",
            "--mirror",
            "--progress",
            repo.remote_url,
            str(mirror_path),
        ],
        cwd=None,
        log_path=log_path,
        is_cancelled=is_cancelled,
        current_proc_setter=current_proc_setter,
        on_output=on_progress,
    )
    if rc != 0:
        return False, f"git clone --mirror failed (rc={rc})", None

    if bundle_path.exists():
        bundle_path.unlink(missing_ok=True)

    rc = run_git(
        ["git", "bundle", "create", str(bundle_path), "--all"],
        cwd=mirror_path,
        log_path=log_path,
        is_cancelled=is_cancelled,
        current_proc_setter=current_proc_setter,
        on_output=on_progress,
    )
    if rc != 0:
        return False, f"git bundle create failed (rc={rc})", None

    rc = run_git(
        ["git", "bundle", "verify", str(bundle_path)],
        cwd=mirror_path,
        log_path=log_path,
        is_cancelled=is_cancelled,
        current_proc_setter=current_proc_setter,
        on_output=on_progress,
    )
    if rc != 0:
        return False, f"git bundle verify failed (rc={rc})", bundle_path

    artifact_path: Path = bundle_path

    if zip_enabled:
        zip_path = pack_bundle_to_zip(repo_safe, bundle_path, log_path)
        artifact_path = zip_path
        append_log(log_path, f"[{repo.name}] ZIP created: {zip_path}")

        if delete_bundle_after_zip:
            bundle_path.unlink(missing_ok=True)
            append_log(log_path, f"[{repo.name}] Deleted bundle after ZIP: {bundle_path.name}")

    if not keep_mirrors:
        append_log(log_path, f"[{repo.name}] Removing mirror: {mirror_path}")
        shutil.rmtree(mirror_path, ignore_errors=True)

    return True, "OK", artifact_path


@dataclass
class RunResult:
    ok: int
    fail: int
    log_path: Path
    csv_path: Path
    readme_path: Path


def run_archive(
    auth: AuthConfig,
    opts: ArchiveOptions,
    *,
    on_progress: Optional[Callable[[str], None]] = None,
    is_cancelled: Optional[Callable[[], bool]] = None,
    current_proc_setter=None,
) -> RunResult:
    run_id = ts_compact()
    paths = build_run_paths(opts, run_id)

    write_text(paths.readme_path, make_readme(paths.out_root))

    auth_b64 = auth_to_basic_b64(auth)

    def log(line: str) -> None:
        append_log(paths.log_path, line)
        if on_progress:
            on_progress(line)

    log("START")
    log(f"CollectionUrl: {opts.collection_url}")
    log(f"Project:       {opts.project}")
    log(f"OutRoot:       {paths.out_root}")
    log(f"BundlesDir:    {paths.bundles_dir}")
    log(f"KeepMirrors:   {opts.keep_mirrors}")
    log(f"ZipBundles:    {opts.zip_bundles}")
    log(f"DelBundleZip:  {opts.delete_bundle_after_zip}")
    log(f"SkipExisting:  {opts.skip_existing}")
    log("Fetching repositories...")

    repos = list_repos(opts.collection_url, opts.project, auth_b64, opts.api_version)
    log(f"Found repos: {len(repos)}")

    only = (opts.only_substring or "").strip().lower()
    if only:
        repos = [r for r in repos if only in r.name.lower()]
        log(f"Filtered repos by only='{only}': {len(repos)}")

    if opts.max_repos and opts.max_repos > 0:
        repos = repos[: opts.max_repos]
        log(f"Limited repos by max_repos={opts.max_repos}: {len(repos)}")

    ok_count = 0
    fail_count = 0

    with paths.csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["repo_name", "repo_id", "remote_url", "artifact_path", "artifact_size_bytes", "status", "message"])

        for i, repo in enumerate(repos, start=1):
            if is_cancelled and is_cancelled():
                raise CancelledError("Cancelled before processing next repo")

            log(f"=== [{i}/{len(repos)}] Repo: {repo.name} ===")
            try:
                success, msg, artifact_path = archive_one_repo(
                    repo=repo,
                    paths=paths,
                    log_path=paths.log_path,
                    auth_basic_b64=auth_b64,
                    keep_mirrors=opts.keep_mirrors,
                    zip_enabled=opts.zip_bundles,
                    delete_bundle_after_zip=opts.delete_bundle_after_zip,
                    skip_existing=opts.skip_existing,
                    is_cancelled=is_cancelled,
                    current_proc_setter=current_proc_setter,
                    on_progress=on_progress,
                )
            except CancelledError:
                raise
            except Exception as e:
                success, msg, artifact_path = False, f"EXCEPTION: {e}", None

            if success:
                ok_count += 1
            else:
                fail_count += 1

            w.writerow([
                repo.name,
                repo.id,
                repo.remote_url,
                str(artifact_path) if artifact_path else "",
                file_size_bytes(artifact_path),
                "OK" if success else "FAIL",
                msg,
            ])
            f.flush()

            if opts.sleep_sec > 0:
                time.sleep(opts.sleep_sec)

    log(f"DONE. OK={ok_count} FAIL={fail_count}")
    log(f"CSV report: {paths.csv_path}")
    log(f"README:     {paths.readme_path}")

    if not opts.keep_mirrors:
        try:
            if paths.mirrors_dir.exists() and not any(paths.mirrors_dir.iterdir()):
                paths.mirrors_dir.rmdir()
        except Exception:
            pass

    return RunResult(ok=ok_count, fail=fail_count, log_path=paths.log_path, csv_path=paths.csv_path, readme_path=paths.readme_path)
