Releasing ChatIRC (GitHub Releases + Gumroad)

This project builds single-file binaries for Linux, Windows, and macOS using PyInstaller and attaches them to GitHub Releases. Use Gumroad to gate access to the downloadable assets (recommended): upload the release URLs or the binary files to Gumroad and use GitHub Releases as the canonical host for artifacts.

Recommended workflow

1. Create a GitHub Release (tag and publish) on the `release-prep` branch. This triggers the `build_release.yml` workflow which builds binaries for all platforms and attaches them to the Release.

2. After the workflow completes, verify artifacts and checksums on the GitHub Release page. Artifacts will be named `chatirc-ubuntu-latest.tar.gz`, `chatirc-windows-latest.tar.gz`, `chatirc-macos-latest.tar.gz` (matrix labels depend on runner names).

3. On Gumroad, create a new "Product". You can either:
   - Upload the platform-specific tar.gz files directly to Gumroad (recommended if you want Gumroad to host the files), or
   - Use Gumroad's "External URL" option and provide the direct GitHub Release asset URLs (not recommended because asset URLs are tokenized and may expire).

4. Configure Gumroad success/redirect pages and provide buyers with instructions to extract and run the appropriate binary for their OS.

Notes and tips

- For security, prefer uploading the actual binary files to Gumroad rather than pointing to GitHub Release URLs.
- Provide SHA256 checksums on the Gumroad product page so buyers can verify integrity.
- Consider signing macOS and Windows binaries for better UX (not covered here).
- Make sure your GitHub runner names match your expected artifact labels; you can adjust the workflow matrix labels if you want friendlier asset names.

Signing and verification checklist

- If you plan to sell binaries, it's strongly recommended to sign Windows and macOS artifacts to avoid warnings on user systems.
- The CI workflow contains conditional signing steps that run only if you add the appropriate secrets to your repository (`WINDOWS_SIGN_CERT`, `WINDOWS_SIGN_PASSWORD`, `MACOS_SIGN_P12`, `MACOS_SIGN_PASSWORD`, `MACOS_SIGN_IDENTITY`). These steps are optional and skipped otherwise.
- After a release build completes, run the bundled verification script to ensure artifacts and checksums match. Example:

```bash
export GITHUB_TOKEN=...
python3 scripts/verify_release.py --owner xajnx --repo ChatIRC --tag v0.1.0
```

If verification succeeds, upload the binaries and checksums to Gumroad (or provide the GitHub Release links on your Gumroad product page). Keep a copy of your signing credentials in a secure place and rotate them if compromised.

Advanced: signing and notarization

- macOS: for best UX on macOS, consider signing and notarizing the binary with Apple Developer tools. This requires an Apple Developer account, an application-specific password for notarization, and adding secrets to the repository to enable the steps.
- Windows: code-signing certificates can be purchased from major CAs; the workflow supports a base64-encoded .pfx in `WINDOWS_SIGN_CERT` and the password in `WINDOWS_SIGN_PASSWORD`.

If you'd like, I can help add a documented step-by-step for setting up macOS notarization and automatic signing in CI.
