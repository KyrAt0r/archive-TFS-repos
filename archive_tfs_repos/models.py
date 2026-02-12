from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class RepoInfo:
    name: str
    remote_url: str
    id: str


class AuthMode(str, Enum):
    PAT = "pat"
    USERPASS = "userpass"


@dataclass(frozen=True)
class AuthConfig:
    mode: AuthMode
    pat: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None

    def validate(self) -> None:
        if self.mode == AuthMode.PAT:
            if not self.pat:
                raise ValueError("PAT is required for AuthMode.PAT")
        elif self.mode == AuthMode.USERPASS:
            if not self.username or not self.password:
                raise ValueError("Username and password are required for AuthMode.USERPASS")
        else:
            raise ValueError(f"Unknown auth mode: {self.mode}")


@dataclass(frozen=True)
class ArchiveOptions:
    collection_url: str
    project: str
    out_root: Path
    api_version: str = "6.0"

    keep_mirrors: bool = False
    only_substring: str = ""
    sleep_sec: float = 0.0

    zip_bundles: bool = False
    delete_bundle_after_zip: bool = True
    skip_existing: bool = True
    max_repos: int = 0


@dataclass(frozen=True)
class RunPaths:
    out_root: Path
    bundles_dir: Path
    mirrors_dir: Path
    logs_dir: Path
    reports_dir: Path

    log_path: Path
    csv_path: Path
    readme_path: Path
