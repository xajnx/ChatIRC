#!/usr/bin/env python3
"""Helper to create a GitHub release and optionally upload to Gumroad.

Usage:
  python3 scripts/release_helper.py --tag v0.1.0 --artifact path/to/art.tar.gz [--gumroad]

Requires GITHUB_TOKEN in env with repo write access. If --gumroad is passed, also requires
GUMROAD_TOKEN and GUMROAD_PRODUCT_ID env vars and will call scripts/gumroad_upload.py to upload.
"""
import os
import sys
import argparse
import requests


def create_release(owner, repo, tag, name, body, draft=False, prerelease=False, token=None):
    url = f'https://api.github.com/repos/{owner}/{repo}/releases'
    headers = {'Authorization': f'token {token}'} if token else {}
    payload = {'tag_name': tag, 'name': name, 'body': body, 'draft': draft, 'prerelease': prerelease}
    r = requests.post(url, json=payload, headers=headers)
    r.raise_for_status()
    return r.json()


def upload_asset(upload_url, path, token=None):
    # upload_url is the template like https://uploads.github.com/repos/.../releases/:id/assets{?name,label}
    name = os.path.basename(path)
    upload_url = upload_url.split('{', 1)[0] + f'?name={name}'
    headers = {'Authorization': f'token {token}'} if token else {}
    with open(path, 'rb') as fh:
        headers.update({'Content-Type': 'application/gzip'})
        r = requests.post(upload_url, headers=headers, data=fh)
    r.raise_for_status()
    return r.json()


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--tag', required=True)
    p.add_argument('--artifact', required=True, help='Path to artifact to attach')
    p.add_argument('--owner', default=os.environ.get('GITHUB_REPOSITORY_OWNER', ''))
    p.add_argument('--repo', default=os.environ.get('GITHUB_REPOSITORY', '').split('/', 1)[-1] if os.environ.get('GITHUB_REPOSITORY') else '')
    p.add_argument('--name', default=None)
    p.add_argument('--body', default='')
    p.add_argument('--gumroad', action='store_true')
    args = p.parse_args()
    token = os.environ.get('GITHUB_TOKEN')
    if not token:
        print('GITHUB_TOKEN env required', file=sys.stderr)
        sys.exit(2)
    owner = args.owner or os.environ.get('GITHUB_REPOSITORY', '').split('/', 1)[0]
    repo = args.repo or os.environ.get('GITHUB_REPOSITORY', '').split('/', 1)[-1]
    if not owner or not repo:
        print('owner and repo must be provided or GITHUB_REPOSITORY set', file=sys.stderr)
        sys.exit(2)
    name = args.name or args.tag
    rel = create_release(owner, repo, args.tag, name, args.body, token=token)
    print('Created release:', rel.get('html_url'))
    upload_url = rel.get('upload_url')
    art = args.artifact
    if os.path.exists(art):
        print('Uploading artifact', art)
        uploaded = upload_asset(upload_url, art, token=token)
        print('Uploaded asset:', uploaded.get('browser_download_url'))
    else:
        print('Artifact not found, skipping upload:', art)

    if args.gumroad:
        gum_token = os.environ.get('GUMROAD_TOKEN')
        gum_prod = os.environ.get('GUMROAD_PRODUCT_ID')
        if not gum_token or not gum_prod:
            print('Gumroad token/product not set in env; skipping gumroad upload', file=sys.stderr)
            sys.exit(1)
        # call the gumroad uploader
        import subprocess
        cmd = [sys.executable, 'scripts/gumroad_upload.py', '--file', art]
        print('Calling gumroad upload...')
        subprocess.check_call(cmd, env=os.environ)


if __name__ == '__main__':
    main()
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
