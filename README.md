# FitDash

A Noctalia v5 bar widget for Fitbit data through the Google Health API. The bar shows today's steps; clicking it opens a themed, scrollable summary with distance, active energy, active zone minutes, sleep, resting heart rate, HRV, and blood oxygen. Availability depends on your device, recorded data, and granted permissions.

FitDash uses **Luau**, not legacy Noctalia v4/Quickshell QML. It requires Noctalia plugin API 24 or later. Tested locally with Noctalia v5.1.0.

## Install

Requirements: Python 3.11+, `uv`, Noctalia, a browser, and an unlocked desktop **Secret Service** keyring. No root privileges or OS package changes are required.

```sh
./scripts/install.sh
```

This installs locked Python dependencies into `~/.local/share/fitdash-widget/venv`, links this checkout into the local Noctalia plugin directory, and enables `democe/fitdash`. Keep the checkout in place: both the development plugin and Python package refer to it. `XDG_DATA_HOME` changes the installation destination; if you use a nondefault destination, set **Backend executable** in FitDash settings accordingly.

Add **FitDash / steps** through Noctalia's bar settings. Its fully qualified type is `democe/fitdash:steps`. The installer does not replace your bar layout. Middle-click the bar widget to open widget settings; the panel's gear opens shared plugin settings.

## Connect Google Health

1. Create a Google Cloud project, enable Google Health API, configure OAuth consent, and add your account as a test user.
2. Create a **Desktop app** OAuth client. Store its downloaded JSON outside the repository, preferably at `~/.config/fitdash-widget/client.json`, with directory mode `0700` and file mode `0600`. Alternatively choose its path in plugin settings.
3. Click **Connect Google Health** and finish authorization in your normal browser. The callback listens only on `127.0.0.1`, on an ephemeral port, for up to five minutes.

The base scopes are `googlehealth.activity_and_fitness.readonly` and `googlehealth.settings.readonly`. Sleep and vitals add `googlehealth.sleep.readonly` and `googlehealth.health_metrics_and_measurements.readonly`. All use the `https://www.googleapis.com/auth/` prefix. Disable unwanted groups before connecting to omit those optional scopes. Reconnect after enabling additional groups. Previously granted permissions remain granted until changed/revoked in Google; hiding a group is not revocation.

OAuth uses Google's Python libraries, Authorization Code + PKCE, and a random validated state. Access/refresh tokens stay in Secret Service under service `fitdash-widget:democe/fitdash`, account `google-health`. There is no plaintext-token fallback. Google projects in **Testing** issue refresh tokens that expire after seven days; use **Reconnect** when needed. See [Google setup and token lifecycle](https://developers.google.com/health/setup).

The legacy Fitbit Web API is not used. Existing legacy Fitbit tokens cannot be imported.

## Behavior and settings

Use the **Copy summary** button beside the panel’s close button to copy the date, steps, daily goal, and enabled table rows as a Markdown table. Display units, observation dates, and data statuses are preserved.

- **Steps and activity:** refresh every five minutes by default; configurable from 60–3600 seconds.
- **Sleep and vitals:** refresh every thirty minutes, or during an explicit manual refresh. Values show their observation dates. Sleep is the latest main sleep, falling back to the latest session, and displays minutes asleep rather than time in bed.
- **Refresh:** requests fresh data, subject to a 30-second cooldown and server backoff. Reading the cloud API does not force your wearable to sync.
- **Units and date:** use the account's units and time zone; optional metric/imperial and IANA time-zone overrides are available. The goal is a local, configurable daily step goal, initially 10,000.
- **Sources:** all reconciled sources by default; wearable-only and Google-source options are available. Values are not summed across overlapping devices.
- **Offline:** show cached values with stale markers. Yesterday's steps never become today's counter. A missing measurement is shown as an em dash, not zero.
- **Partial failures:** retain valid values when another endpoint fails. Honor quota backoff, retry transient failures on subsequent polls, and attempt at most one token refresh/retry for an unauthorized API response.
- **Clear cache:** removes health snapshots/history while retaining the Google connection. Automatic polling can fetch data again.
- **Disconnect:** removes local credentials and health data, then attempts Google revocation. If revocation fails, the panel reports that local disconnection succeeded and Google account access still needs removing.
- **Demo:** shows synthetic values without requesting health data. Useful for layout work.

A single Noctalia service feeds every widget instance, so adding a widget to another bar does not multiply API polling. File locks serialize auth, sync, and disconnect. Reconnecting clears prior account data before new readings are cached.

## Local files

| Location | Contents |
|---|---|
| `~/.config/fitdash-widget/client.json` | User-supplied OAuth client configuration |
| `~/.local/share/fitdash-widget/venv/` | Backend environment and locked dependencies |
| `~/.local/share/noctalia/plugins/fitdash` | Development symlink to this checkout |
| `$XDG_STATE_HOME/fitdash-widget/` (default `~/.local/state/fitdash-widget/`) | Atomic snapshot, sanitized auth state, schedule and seven-day daily history |
| Desktop Secret Service keyring | Google OAuth credentials |

State directories are `0700`; files are `0600`. Snapshots contain health information and are **not encrypted**. Tokens, authorization codes, and API payloads are not logged. The backend retains normalized summary values only, and re-fetches yesterday's activity to capture delayed sync/corrections. History is pruned to seven days when syncing; disabling the plugin does not delete files. Clear/disconnect controls remove local health data explicitly.

The state directory is owned by the helper rather than by Noctalia, so command-line authentication and the plugin use the same storage. `--state-dir` can isolate test data, but does not select another Google account: this release supports one connected account per desktop user.

## Development and checks

```sh
uv sync --locked
./scripts/check.sh
LUAU=/path/to/luau uv run python tests/check_luau.py
```

The second command runs Python lint and fixture-based backend tests. The third runs widget, panel and service behavior checks with a real Luau VM and mocked Noctalia APIs. Obtain Luau from the [official project](https://github.com/luau-lang/luau/releases).

```sh
noctalia msg panel-open democe/fitdash:details
noctalia msg plugin democe/fitdash:sync all refresh
noctalia msg plugin democe/fitdash:sync all status
```

The backend CLI supports `status`, `sync`, `auth`, `disconnect`, `clear-cache`, and `demo`. Commands return one JSON response. **Status/sync output contains your health measurements**; avoid pasting it into public logs. Error responses contain fixed status codes, never upstream error messages. A cached status read does not contact Google or unlock the keyring.

```sh
~/.local/share/fitdash-widget/venv/bin/fitdash status
~/.local/share/fitdash-widget/venv/bin/fitdash sync --force
```

Manifest changes require `noctalia msg config-reload`; Luau edits hot-reload. Backend source changes take effect on the next invocation. After modifying dependencies, rerun setup.

Architecture: `service.luau` owns polling and publishes sanitized snapshots; `widget.luau` and `panel.luau` render native `ui.*` controls. `backend/fitdash` owns OAuth, provider normalization, cache, and the CLI boundary. No web server remains running after authorization.

## Remove

Use **Disconnect** first if you want to revoke access and erase local credentials/data. Disable the plugin with:

```sh
noctalia msg plugins disable democe/fitdash
```

Remove the FitDash widget from your bar settings, then remove the FitDash symlink and backend environment if no longer wanted. The client JSON is separate and may be removed independently. Do not restore an old complete Noctalia settings backup over newer unrelated changes; remove only the FitDash entry.

## Validation and scope

Validated on the local session: desktop OAuth callback and keyring storage, live Google Health reads, native bar/panel rendering, and cached restoration after plugin reload. Automated coverage includes state rejection, partial scopes, missing versus zero, DST/date boundaries, duplicate rollups, pagination, cache locking/corruption, history corrections, and API failure/backoff behavior.

The initial release is read-only, single-account, and English-first (all UI labels are translation keys). It has no charts, multi-account selector, public webhooks, or writes to health records. Long translations, keyboard-only navigation, and every display scale still need broader visual testing. Values have been verified as successful API responses; parity with the mobile app at an identical device-sync time has not been independently established.

References: [Noctalia plugin API](https://docs.noctalia.dev/noctalia/plugins/development/), [Google Health data types](https://developers.google.com/health/data-types), [daily rollups](https://developers.google.com/health/reference/rest/v4/users.dataTypes.dataPoints/dailyRollUp), [desktop OAuth](https://developers.google.com/identity/protocols/oauth2/native-app).
