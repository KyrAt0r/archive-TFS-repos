from __future__ import annotations

import argparse
from pathlib import Path

from .models import AuthConfig, AuthMode, ArchiveOptions
from .archiver import run_archive
from .git_ops import CancelledError


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="TFS/Azure DevOps Server Git repositories archiver (bundle/zip)")

    ap.add_argument("--collection-url", required=True, help='e.g. ""')
    ap.add_argument("--project", required=True, help='Team Project name, e.g. ""')
    ap.add_argument("--out-root", required=True, help='Output root, e.g. ""')
    ap.add_argument("--api-version", default="6.0", help="TFS/Azure DevOps Server REST API version")

    ap.add_argument("--auth-mode", required=True, choices=["pat", "userpass"], help="Auth mode")
    ap.add_argument("--pat", default="", help="PAT token (required for auth-mode=pat)")
    ap.add_argument("--username", default="", help="Username (required for auth-mode=userpass)")
    ap.add_argument("--password", default="", help="Password (required for auth-mode=userpass)")

    ap.add_argument("--keep-mirrors", action="store_true", help="Keep mirrors/ folder")
    ap.add_argument("--only", default="", help="Process only repos containing substring (case-insensitive)")
    ap.add_argument("--sleep", type=float, default=0.0, help="Sleep between repos (seconds)")

    ap.add_argument("--zip-bundles", action="store_true", help="Pack each bundle into a ZIP (per repo)")
    ap.add_argument("--delete-bundle-after-zip", action="store_true", help="Delete .bundle after ZIP (default on if zip enabled)")
    ap.add_argument("--no-delete-bundle-after-zip", action="store_true", help="Do not delete .bundle after ZIP")

    ap.add_argument("--skip-existing", action="store_true", help="Skip if artifact exists (default on)")
    ap.add_argument("--no-skip-existing", action="store_true", help="Do not skip existing artifacts")

    ap.add_argument("--max-repos", type=int, default=0, help="Limit number of repos (0 = all)")

    return ap


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)

    auth_mode = AuthMode(args.auth_mode)
    auth = AuthConfig(
        mode=auth_mode,
        pat=args.pat if auth_mode == AuthMode.PAT else None,
        username=args.username if auth_mode == AuthMode.USERPASS else None,
        password=args.password if auth_mode == AuthMode.USERPASS else None,
    )

    delete_bundle_after_zip = True
    if args.no_delete_bundle_after_zip:
        delete_bundle_after_zip = False
    elif args.delete_bundle_after_zip:
        delete_bundle_after_zip = True

    skip_existing = True
    if args.no_skip_existing:
        skip_existing = False
    elif args.skip_existing:
        skip_existing = True

    opts = ArchiveOptions(
        collection_url=args.collection_url,
        project=args.project,
        out_root=Path(args.out_root),
        api_version=args.api_version,

        keep_mirrors=bool(args.keep_mirrors),
        only_substring=args.only,
        sleep_sec=float(args.sleep),

        zip_bundles=bool(args.zip_bundles),
        delete_bundle_after_zip=bool(delete_bundle_after_zip),
        skip_existing=bool(skip_existing),
        max_repos=int(args.max_repos or 0),
    )

    try:
        res = run_archive(auth=auth, opts=opts)
    except CancelledError:
        print("CANCELLED")
        return 130
    except Exception as e:
        print(f"ERROR: {e}")
        return 2

    return 0 if res.fail == 0 else 2
