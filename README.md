# ChatIRC — IRC-style CLI ChatGPT frontend

ChatIRC is a small curses-based IRC-like client that uses OpenAI chat models as the assistant backend. It aims for a keyboard-first, compact UX inspired by classic IRC clients like BitchX and iirc.

## Highlights

- Per-room chat logs and message history
- Slash commands: `/room`, `/rooms`, `/save`, `/load`, `/nick`, `/topic`, `/help`, `/quit`, `/getkey`, `/invite`
- Tab-completion for commands/rooms and persistent input history
- Unicode-aware wrapping and optional `wcwidth` dependency for accurate layout
- Background API calls so the UI stays responsive

## Quick start

1. Create and activate a virtualenv (recommended):

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

echo "sk-..." > openapi_key
2. Provide your OpenAI API key. Recommended: create a per-user hidden file under `~/.chatirc/openapi_key` (preferred), or put `openapi_key` in the project directory:

Preferred (per-user):

```bash
mkdir -p ~/.chatirc
echo "sk-..." > ~/.chatirc/openapi_key
chmod 600 ~/.chatirc/openapi_key
```

Fallback (project-local):

```bash
echo "sk-..." > openapi_key
chmod 600 openapi_key
```

You can also set `OPENAI_API_KEY` as an environment variable.

3. Run the client:

```bash
python3 chatirc.py
```

## Useful commands

- `/getkey` — opens the OpenAI API keys page in your browser
- `/invite <email>` — opens your mail client with a templated invite (replace the placeholder link with your GitHub release URL)
- `/help` — lists commands

## Packaging

- To build a single-file binary using PyInstaller:

```bash
./build.sh
```

- A `Makefile` target `make build` runs the script. The resulting binary will appear under `dist/`.

## Distribution & monetization notes

- Add a GitHub repository and create releases for the binaries. You can sell/provide releases behind a payment system (Gumroad, Ko-fi) or use a donate model. Ensure your README explains storage of `openapi_key` and does not include private keys.

## Security & privacy

- Do NOT commit your `openapi_key` file into version control. It's ignored via `.gitignore`.
- Consider storing the key under `~/.chatirc/openapi_key` for multi-project installs; the current default matches the working directory file `openapi_key`.

## Contributing

Pull requests welcome. See `TODO.md` for in-progress ideas.

## License

MIT

## Assets and packaging notes

- The `assets/` directory contains `appicon.png` and theme images. When building with PyInstaller the workflow bundles these files with `--add-data` so the runtime can access them. At runtime the helper `get_asset_path(name)` resolves the correct absolute path whether running from source or from a PyInstaller one-file bundle (via `sys._MEIPASS`).

- Windows: the CI attempts to convert `assets/appicon.png` to a `.ico` using ImageMagick if available and passes it to PyInstaller via `--icon`.

- If you want guaranteed OS-native icons ensure `.ico` (for Windows) and `.icns` (for macOS) files are present in `assets/` and update the workflow to use them.

## Testing

- Tests are run with pytest in CI. Locally you can run:

```bash
python3 -m pip install -r requirements.txt
pytest -q
```

## Gumroad deployment and credentials


For security, do NOT store Gumroad credentials in plaintext in the repo. Instead store them as GitHub repository secrets and reference them in your workflow. Required secrets for the current workflow:

  - `GUMROAD_TOKEN` — your Gumroad access token
  - `GUMROAD_PRODUCT_ID` — the product id to upload files to

When developing locally you can export these values in your shell session (not committed) or use a credential helper. Example:

```bash
export GUMROAD_TOKEN="<token>"
export GUMROAD_PRODUCT_ID="<product-id>"
python3 scripts/gumroad_upload.py --file dist/chatirc-<tag>-linux-x86_64.tar.gz
```

The repository also contains `scripts/gumroad_upload.py` which performs a file upload and prints a helpful response; the workflow will call the same endpoint when the secrets are configured.

Optional: Slack notifications

 - You can set a `SLACK_WEBHOOK` GitHub secret to notify a Slack channel when a release is published. The workflow will post a short message containing the release URL. Keep the webhook secret in GitHub secrets and do not commit it to the repo.
