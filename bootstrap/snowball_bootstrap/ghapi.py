"""Minimal GitHub REST calls the pull job needs: find and download the latest state artifact."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        return None


def _api_base() -> str:
    return os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")


def _request(url: str, token: str, accept: str = "application/vnd.github+json") -> urllib.request.Request:
    return urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": accept,
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "snowball-bootstrap",
    })


def latest_artifact(repo: str, name: str, token: str, branch: str = "main") -> dict | None:
    """Newest non-expired artifact with this exact name made by a run on `branch`, or None (E17)."""
    query = urllib.parse.urlencode({"name": name, "per_page": 50})
    with urllib.request.urlopen(_request(f"{_api_base()}/repos/{repo}/actions/artifacts?{query}", token),
                                timeout=60) as resp:
        data = json.load(resp)
    candidates = [a for a in data.get("artifacts", []) if a.get("name") == name and not a.get("expired")
                  and (a.get("workflow_run") or {}).get("head_branch") == branch]
    candidates.sort(key=lambda a: a.get("created_at", ""), reverse=True)
    return candidates[0] if candidates else None


def download_zip(repo: str, artifact_id: int, token: str) -> bytes:
    """Download an artifact; the token is sent to GitHub only, never to the storage redirect."""
    opener = urllib.request.build_opener(_NoRedirect())
    url = f"{_api_base()}/repos/{repo}/actions/artifacts/{int(artifact_id)}/zip"
    try:
        with opener.open(_request(url, token), timeout=60) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code not in (301, 302, 303, 307, 308):
            raise
        location = exc.headers.get("Location")
        if not location or not location.startswith("https://"):
            raise
    with urllib.request.urlopen(urllib.request.Request(location, headers={"User-Agent": "snowball-bootstrap"}),
                                timeout=120) as resp:
        return resp.read()
