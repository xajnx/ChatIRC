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
