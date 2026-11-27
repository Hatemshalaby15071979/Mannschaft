# AGENTS.md — Agent Charter & Ledger for Mannschaft

> **Read order (mandatory, every landing):** `AGENTS.md` → `CONSTITUTION.md` →
> `GOVERNANCE.md` → `README.md` → `STATUS.md`. Then **sign in** to the ledger below, do
> the work, **sign out**. No entry, no trust: an unlogged session's work is treated as
> unverified until someone checks it.

## 1. Who agents are here

An "agent" is any entity that reads or writes this repository — an AI model, an
automation script, or a human acting as operator. There is exactly **one supreme
authority**: the repository owner (**Hatem Shalaby**). An agent acts only on the
owner's instruction and records every landing.

## 2. The mandatory sign-in / sign-out rule

Every agent, on **every landing** (a landing = one session that ends with the agent
stopping, whether the task is finished or not), must:

1. **SIGN IN** before any write action — who, why, what will be touched, sensitive or
   network actions planned, and the **date and time from the system clock**.
2. **SIGN OUT** when the landing's work is complete or stopped — what changed, why,
   the files touched, evidence of verification, and **the current status when leaving**,
   written so the next agent can continue without re-discovery.

Fail closed: if a task cannot be completed, still sign out and state exactly what is
incomplete. Never claim verification that did not happen.

### Entry format

```
## [YYYY-MM-DD HH:MM TZ] — <agent name / model>
Task: <what was assigned>
Touched: <files created / modified / deleted / moved>
Why: <the reasoning, not just the diff>
Verification: <what was actually checked and the observed result>
Left undone: <what is incomplete, needs review, or is deferred — or "nothing">
Sensitive: <any remote writes, secrets, or destructive actions, or "none">
```

## 3. Environment facts

- **Repo:** Mannschaft — a single-user, localhost, listening-first German learning app for A1–C2. Twelve hand-authored pilot lessons, six VoiceStudio voices, rendered audio, and a local dictionary seed. Release `v6.0.1`.
- **Owner account:** https://github.com/Hatemshalaby15071979
- **Default branch:** main
- **Where it runs:** fully local. The server binds to `127.0.0.1` (port 8766) and makes no outbound calls in the learning path. No account, no sync, no telemetry. VoiceStudio is optional and only needed to synthesise new audio. CI runs on GitHub Actions, Python 3.11–3.14.
- **Verification commands:** `make check` (ruff + the pytest suite), `make validate` (`python -m v5 validate --all`), `make dist-check` (unzip into an empty directory and re-run the checks), `scripts/check_root_docs.py` (the root-document gate; add `--self-test` to prove it fails closed).
- **Two tests are environment-dependent.** `tests/test_assemble.py::test_mp3_duration_agrees_with_timeline` and `::test_line_clips_are_written_per_segment` compare a probed MP3 duration against the timeline within 50–60 ms. On a machine whose ffmpeg/TTS build differs from the author's they drift slightly past that tolerance (observed here: 63 ms and 65 ms). They are not a signal about your change unless you touched assembly.

## 4. Rules this agent must follow

- Read and obey **CONSTITUTION.md** (philosophy + clean-code policy). On conflict, it
  wins over this file.
- Follow **GOVERNANCE.md** for the repo map, documentation policy, and archiving rules.
- `STATUS.md` is the progress ledger: update it **after every step**, then commit — that
  is the repository's own standing instruction, and this charter does not replace it.
- Keep `README.md` the single source of truth; landing pages and dashboards mirror it.
- Keep local and remote in harmony: after a sanctioned change, commit and push so the
  GitHub copy matches the working copy.
- Sign in and sign out every landing, with the real clock time.
- `content/audio/` is derived and git-ignored. Never commit rendered audio or corpus
  intermediates; never claim the app has been listened to end to end without saying
  which lessons were actually played.

## 5. Ledger (sign-in / sign-out)

## [2026-11-27 05:00 EET] — sami (OpenMausBot), owner-authorised governance landing

STATUS: SIGN-IN (work in progress)

Task: Bring this repository onto the portfolio governance standard, as the owner approved in chat on 2026-11-27 ("bring the remaining eleven onto the same governance standard"). Add the missing root documents, move the dated milestone report into `docs/archive/`, land the shared root-document gate and wire it into CI.

Touched: Will add `AGENTS.md`, `CHANGELOG.md`, `CONSTITUTION.md`, `GOVERNANCE.md`, `SECURITY.md`, `scripts/check_root_docs.py`; move `V6-REPORT.md` to `docs/archive/` and repoint its five references in `STATUS.md`; extend the `src/v5/__init__.py` docstring; add one job to `.github/workflows/ci.yml`. Nothing is deleted, and `STATUS.md` stays at the root.

Why: The repository had a README and a progress ledger but no CONSTITUTION.md, no GOVERNANCE.md, no agent charter, and no security policy. `STATUS.md` also recorded an open owner decision — no licence has been chosen — so this landing must not invent one.

Verification: Planned — `scripts/check_root_docs.py` and `--self-test` locally, then ruff, pytest and `python -m v5 validate --all`, then the GitHub Actions run on the landing commit.

Left undone: Nothing at sign-in.

Sensitive: `git push origin main` (owner's instruction in chat, 2026-11-27). No force push, no history rewrite, no secrets.
