#!/usr/bin/env python3
"""Verify GitHub Release artifacts by downloading tar.gz and matching SHA256 files.

Usage:
  export GITHUB_TOKEN=...
  python3 scripts/verify_release.py --owner xajnx --repo ChatIRC --tag v0.1.0

The script fetches the release by tag, finds assets ending in .tar.gz, and for each looks for a corresponding .sha256 file. It downloads both and verifies the checksum.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import sys
try:
    # prefer requests if available
    import requests
except Exception:
    requests = None
import urllib.request


def http_get(url: str, headers: dict | None = None) -> bytes:
    if requests:
        resp = requests.get(url, headers=headers)
        resp.raise_for_status()
        return resp.content
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req) as fh:
        return fh.read()


def compute_sha256(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--owner", required=True)
    p.add_argument("--repo", required=True)
    p.add_argument("--tag", required=True)
    p.add_argument("--token", default=os.environ.get("GITHUB_TOKEN"))
    args = p.parse_args()

    headers = {"Accept": "application/vnd.github+json"}
    if args.token:
        headers["Authorization"] = f"token {args.token}"

    api_url = f"https://api.github.com/repos/{args.owner}/{args.repo}/releases/tags/{args.tag}"
    try:
        body = http_get(api_url, headers=headers)
        data = json.loads(body)
    except Exception as e:
        print("Error fetching release:", e)
        sys.exit(2)

    assets = data.get("assets", [])
    assets_by_name = {a["name"]: a for a in assets}
    tar_assets = [n for n in assets_by_name.keys() if n.endswith('.tar.gz')]
    if not tar_assets:
        print("No tar.gz artifacts found on release.")
        sys.exit(1)

    ok = True
    for tar_name in tar_assets:
        sha_name = tar_name.replace('.tar.gz', '.sha256')
        tar_info = assets_by_name.get(tar_name)
        sha_info = assets_by_name.get(sha_name)
        print(f"Verifying {tar_name} ...")
        if not tar_info:
            print(f"  Missing artifact: {tar_name}")
            ok = False
            continue
        if not sha_info:
            print(f"  Missing checksum file: {sha_name}")
            ok = False
            continue
        try:
            tar_data = http_get(tar_info["browser_download_url"], headers=headers)
            sha_data = http_get(sha_info["browser_download_url"], headers=headers)
        except Exception as e:
            print("  Error downloading:", e)
            ok = False
            continue
        actual = compute_sha256(tar_data)
        try:
            claimed = sha_data.decode('utf-8').strip().split()[0]
        except Exception:
            claimed = sha_data.decode('utf-8').strip()
        if actual.lower() == claimed.lower():
            print("  OK: checksum matches")
        else:
            print(f"  MISMATCH: actual {actual} != claimed {claimed}")
            ok = False

    if not ok:
        print("One or more artifacts failed verification.")
        sys.exit(3)
    print("All artifacts verified successfully.")


if __name__ == '__main__':
    main()
