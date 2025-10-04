#!/usr/bin/env python3
"""Helper to verify built artifacts locally and optionally upload to Gumroad.

Usage:
  python3 scripts/release_helper.py --artifacts dist/* --verify
  python3 scripts/release_helper.py --artifacts dist/* --upload-gumroad --gumroad-token <token> --product-id <id>

Note: Uploading to Gumroad requires a seller's access token and product setup. This script performs a simple POST for file upload; you should verify Gumroad's current API for large-file handling.
"""
from __future__ import annotations
import argparse
import hashlib
import os
import sys
import glob
import requests


def compute_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        while True:
            chunk = fh.read(8192)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--artifacts', nargs='+', required=True)
    p.add_argument('--verify', action='store_true')
    p.add_argument('--upload-gumroad', action='store_true')
    p.add_argument('--gumroad-token')
    p.add_argument('--product-id')
    args = p.parse_args()

    artifacts = []
    for pat in args.artifacts:
        artifacts.extend(sorted(glob.glob(pat)))
    if not artifacts:
        print('No artifacts found')
        sys.exit(1)

    for a in artifacts:
        if a.endswith('.tar.gz'):
            print('Artifact:', a)
            if args.verify:
                sha = compute_sha256(a)
                print('  SHA256:', sha)

    if args.upload_gumroad:
        if not args.gumroad_token or not args.product_id:
            print('Gumroad upload requires --gumroad-token and --product-id')
            sys.exit(2)
        for a in artifacts:
            if a.endswith('.tar.gz'):
                print('Uploading', a)
                with open(a, 'rb') as fh:
                    r = requests.post('https://api.gumroad.com/v2/products/{}'.format(args.product_id),
                                      headers={'Authorization': 'Bearer ' + args.gumroad_token},
                                      files={'file': fh})
                    print('  status:', r.status_code, r.text)


if __name__ == '__main__':
    main()
