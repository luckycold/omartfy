# Omartfy

A multi-server [ntfy](https://ntfy.sh/) client for the Omarchy bar. Omartfy combines notifications from ntfy.sh and self-hosted servers into one keyboard-friendly panel while keeping each server's authentication, connection state, and unread count separate.

![Omartfy notification panel](preview.png)

## Features

- One symbolic bar icon with unread, urgent, and connection indicators
- Merged chronological `All` inbox plus per-server tabs
- Multiple topics and credentials per server profile
- Bearer token, Basic, and unauthenticated connections
- Local read, dismiss, and clear state without publishing changes to ntfy
- ntfy view, copy, and opt-in HTTP actions
- Lazy icon and image-attachment previews with strict size, format, redirect, and origin checks
- Keyboard navigation, inline search, overflow tabs, and a dedicated server editor
- Durable cursor replay and event deduplication across shell restarts

## Requirements

- Omarchy with the Quattro shell plugin system
- Python 3
- `setpriv` from util-linux
- `wl-copy` from wl-clipboard
- `omarchy-launch-browser`

No pip, npm, third-party ntfy SDK, SSE, or WebSocket package is required.

## Install

```bash
omarchy plugin add https://github.com/DailenG/omartfy --enable
```

The widget defaults to the right bar section. Open the panel and select **Settings** to add an ntfy server and one or more comma-separated topics. No default subscription is created because ntfy topics act as public addresses unless protected by server-side access controls.

### Server settings

- **Label:** unique local name shown on tabs and notifications
- **Base URL:** `https://ntfy.sh` or a self-hosted HTTP(S) URL; reverse-proxy path prefixes are supported
- **Topics:** one or more ntfy topic names
- **Authentication:** none, Bearer token, or Basic username/password
- **Allow publisher-supplied HTTP actions:** disabled by default; enable only for trusted publishers
- **Allow credentials over insecure HTTP:** shown only when credentials would cross non-loopback plain HTTP

A blank secret while editing an existing profile preserves the stored secret.

## Keyboard controls

| Key | Action |
| --- | --- |
| `j` / `k`, Up / Down | Select notification |
| `h` / `l`, Left / Right | Switch server tab |
| Enter / Space | Expand selected notification |
| `1`–`3` | Run the corresponding visible ntfy action |
| `o` | Open the notification click URL |
| `a` | Open the attachment URL |
| `x` | Dismiss locally |
| `r` | Reconnect and reload |
| `s` | Open server settings |
| `/` | Search |
| Escape | Close search, nested UI, or panel |
| Tab / Shift-Tab | Switch adjacent Omarchy panels |

## Data and security

Omarchy plugins run unsandboxed with the current user's permissions. Omartfy:

- Reads configuration from `${XDG_CONFIG_HOME:-~/.config}/omarchy/ntfy.json`
- Stores cursor, notification, dismissal, and media state under `${XDG_STATE_HOME:-~/.local/state}/omarchy/ntfy/`
- Writes configuration and state atomically with mode `0600`; the state directory uses mode `0700`
- Stores configured tokens and passwords locally in the mode-`0600` JSON configuration file; it does not use a keyring
- Sends credentials only in HTTP authorization headers, never URLs or process arguments
- Never disables TLS certificate verification
- Keeps HTTP actions disabled per server until explicitly enabled
- Runs publisher-provided HTTP actions only after user activation, without redirects or retries
- Launches validated HTTP(S) view URLs through `omarchy-launch-browser` and copies values through `wl-copy`

Review topic access controls and publisher trust before enabling a server or HTTP actions.

## Remove

```bash
omarchy plugin remove omartfy.ntfy
```

Removal leaves configuration and local notification history in place so reinstalling does not lose state. To remove that data too, after removing the plugin run:

```bash
rm -rf ~/.config/omarchy/ntfy.json ~/.local/state/omarchy/ntfy
```

## Development

Validate and test from the repository root:

```bash
python3 -m unittest discover -s test -p 'test_*.py'
node --test test/model.test.js
omarchy plugin validate "$PWD"
```

`test/mock_ntfy.py` provides a local ntfy-compatible HTTP fixture for stream, action, authentication, and media checks.

## License

Omartfy is licensed under the [MIT License](LICENSE).

The ntfy mask in `assets/ntfy-mask.svg` is copied from ntfy commit `4c2b69e0591b51d7ed7b2e71954f0f7be936b47f` and remains licensed under Apache-2.0. Its attribution and license text are preserved in the asset and `third_party/ntfy-APACHE-2.0.txt`.
