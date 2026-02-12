from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict, List

from .models import RepoInfo


def http_get_json(url: str, auth_basic_b64: str, timeout: int = 60) -> Dict[str, Any]:
    req = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Accept": "application/json",
            "Authorization": f"Basic {auth_basic_b64}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read().decode("utf-8", errors="replace")
            return json.loads(data)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if hasattr(e, "read") else ""
        raise RuntimeError(f"HTTP {e.code} for {url}\n{body}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"URL error for {url}: {e}") from e


def list_repos(collection_url: str, project: str, auth_b64: str, api_version: str) -> List[RepoInfo]:
    base = collection_url.rstrip("/")
    url = f"{base}/{project}/_apis/git/repositories?api-version={api_version}"
    data = http_get_json(url, auth_b64)

    items = data.get("value", [])
    repos: List[RepoInfo] = []
    for x in items:
        name = x.get("name") or ""
        rid = x.get("id") or ""
        remote_url = x.get("remoteUrl") or x.get("url") or ""
        if not name or not remote_url:
            continue
        repos.append(RepoInfo(name=name, remote_url=remote_url, id=rid))
    return repos
