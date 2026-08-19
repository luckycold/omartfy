# Contributing to Omartfy

Thanks for improving Omartfy. Keep changes focused, compatible with the current Omarchy Quattro plugin API, and safe for users who connect to untrusted ntfy publishers.

## Development setup

1. Fork and clone the repository.
2. Link the checkout into your user plugin directory:

   ```bash
   ln -s "$PWD" ~/.config/omarchy/plugins/dailen.omartfy
   omarchy plugin enable dailen.omartfy --section right
   ```

3. Use a local ntfy server or `test/mock_ntfy.py`; do not commit real topics, URLs, credentials, notification content, or state files.
4. Changes under the installed plugin path normally hot-reload. Use `omarchy restart shell` when a service-process change does not reload cleanly.

## Required checks

Run these from the repository root before opening a pull request:

```bash
python3 -W error::ResourceWarning -m unittest discover -s test -p 'test_*.py'
node --test test/model.test.js
omarchy plugin validate "$PWD"
```

For UI changes, open the real panel and exercise the changed mouse and keyboard paths. Include a screenshot when appearance changes.

## Design constraints

- Keep the bar indicator compact and the panel keyboard-friendly.
- Preserve separate server authentication, connection, and unread state.
- Treat notification payloads and action targets as untrusted input.
- Never put credentials in URLs, logs, process arguments, screenshots, fixtures, or error messages.
- Keep publisher-supplied HTTP actions opt-in per server and user-activated.
- Avoid runtime package dependencies when Python and the QML modules shipped with Omarchy are sufficient.
- Preserve local notification state across shell restarts and plugin upgrades.

## Pull requests

Describe the observable behavior, risk, and verification performed. Add tests for new bridge or model contracts. Do not add compatibility aliases or leave obsolete paths behind when changing an internal API.

Security vulnerabilities should not be filed as public issues. Follow [SECURITY.md](SECURITY.md).
