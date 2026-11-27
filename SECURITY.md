# Security Policy

Mannschaft is a single-user, localhost-only German learning app. It runs on the
machine it is installed on, binds to `127.0.0.1`, stores its state in a local SQLite
database, and makes no outbound network calls as part of normal use. The rendered
audio and the lesson corpus stay on disk. There is no account, no sync, and no
telemetry.

## Supported versions

| Version | Supported |
| ------- | --------- |
| 6.0.1   | Yes — the current release. |
| 6.0.0   | Superseded by 6.0.1; no separate fixes. |

## Design commitments that are security-relevant

- **Loopback only.** The server binds to `127.0.0.1`. A change that makes it listen on
  `0.0.0.0` is a security change, not a convenience change, and must be treated as one.
- **No credentials in the tree.** VoiceStudio (optional TTS synthesis) and any model
  runtime are configured outside the repository. Nothing in `config/` holds a secret.
- **No network in the learning path.** Playing a lesson, rendering a transcript and
  scoring a drill are all local.
- **Rendered media is not committed.** `content/audio/` is deliberately out of git, so
  a clone carries code and authored content only.

## Reporting a vulnerability

**Reporting contact: to be set by the owner.** There is no monitored security mailbox or
private reporting channel in this repository yet; do not send vulnerability reports to
any address guessed from this file.

Until the owner publishes a contact channel:

1. Do not open a public issue containing exploit details.
2. Do not include real personal data or credentials in any report.
3. The owner will add a private reporting channel (for example GitHub Private
   Vulnerability Reporting) and this section will name it.
