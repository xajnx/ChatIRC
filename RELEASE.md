Release checklist
=================

- Update `__version__` in `chatirc.py` to the release version.
- Tag the release in git: `git tag -a v0.1.0 -m "Release v0.1.0"`
- Push tags and create a GitHub release pointing to the tag.
- Optionally run `make build` or use the GitHub Actions release workflow to build artifacts.
- Upload binaries to the release page.
- Replace invite placeholder link in `/invite` command and README.
