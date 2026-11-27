# GOVERNANCE.md — Operating Policy & Repo Map for Mannschaft

> Companion to `CONSTITUTION.md` (the *why* — philosophy and clean-code policy, which
> this file enforces operationally) and `AGENTS.md` (the agent charter + ledger).
> Read all three before acting. This file may be updated by any agent **as a logged
> governance change** to keep the map and policy truthful; the CONSTITUTION itself is
> owner-only.

## 1. Repository map

Authoritative directory map for **Mannschaft**. Any file you add, move, rename, or
delete gets reflected here in the same landing.

| Path | Purpose (one line) |
|---|---|
| `src/v5/` | The application tree (internal name `v5`): FastAPI server, engines, CLI (`python -m v5`), client assets and CSS. |
| `content/` | Authored lessons, cards, the dictionary seed, the lesson-media manifest and the corpus working files (`clips.jsonl`). |
| `config/` | Runtime configuration. |
| `tests/` | The test suite (`make check` runs ruff plus pytest). |
| `tools/` | Packaging (`package.py`), icon and logo generation, legacy hashing, detached-server scripts. |
| `assets/` | Brand assets. |
| `brand/` | Engraving art file kept with the brand assets. |
| `docs/` | Standing documentation. |
| `docs/archive/` | One-off and historical reports — the V6 milestone report, dated audits. |
| `.github/` | CI workflow (3.11–3.14). |
| `.hallmark/` | The Hallmark design-system ledger (log, salt, ignore list). |

`content/audio/` holds ~251 MB of rendered audio and is deliberately **not** in git;
it is produced by `make render` and shipped inside the full distribution only.

## 2. Documentation policy (what belongs where)

**Root holds only the requested set** — nothing else:

| File | State | Purpose |
|---|---|---|
| `README.md` | required | The single source of truth: what this is, why it's here, how to use it — in simple English for a professional reader. Carries the Helix Solutions logo. |
| `AGENTS.md` | required | Agent charter + sign-in/out ledger. |
| `CONSTITUTION.md` | required | The owner's engineering philosophy and clean-code policy (unified across every repo). |
| `GOVERNANCE.md` | required | This file: repo map, documentation policy, sync policy, archiving rules. |
| `STATUS.md` | required | The progress ledger and single source of truth for where the work is. It stays at the root because `tools/package.py` ships it inside the core distribution and `src/v5/__init__.py` and `README.md` both point readers at it. |
| `CHANGELOG.md` | standard | Dated user-visible changes. |
| `SECURITY.md` | standard | Threat model, vulnerability reporting, secret handling. |

**`LICENSE` is deliberately absent**, and the table therefore does not name it:
`STATUS.md` records that no licence has been chosen and that `pyproject.toml`
consequently carries no licence field. That is the owner's decision to make, not an
agent's. When the owner chooses one, add the file **and** the `LICENSE` row to the table
above in the same landing — the root-document gate reads this table, so an unrecorded
`LICENSE` would be reported as a stray rather than silently accepted.

**Everything else lives in `docs/`** — reports, audit logs, execution plans, research
notes, ADRs, runbooks, anything dated or one-off. No stray `.md`/`.txt` at the root.
If a document at the root is not in the table above, move it to `docs/` (or
`docs/archive/` if it is historical) and record the move in the `AGENTS.md` ledger.

## 3. Synchronization & harmony policy

The owner's rule: **the repository's actual status must match its README at all times,
locally and remotely.**

1. `README.md` is the canonical account. Landing pages and dashboards mirror it; they
   never fork it.
2. When reality changes, update `README.md` **first**, then mirror it to the pages.
3. Every sanctioned change is committed **and pushed** to the default branch, so the
   GitHub copy, the local working copy, and any local platform that reads the repo
   all show the same truth.
4. A number published anywhere (README, page, badge) must be reproducible from this
   repository. `make check`, `make validate` and `make dist-check` re-derive the figures
   this repository publishes; a stale figure is removed, not left to rot.

## 4. Archiving rule

- Archive (move to `docs/archive/`), never delete: historical reports, superseded plans,
  dated audits, and one-off execution logs.
- Delete outright only regenerable artifacts: caches, build output, coverage files.
- Record every move in the `AGENTS.md` ledger with date and time.

## 5. Engineering philosophy & clean-code policy (operational summary)

The full text is `CONSTITUTION.md`. The operational reminders, enforced here:

- **Fail closed.** Missing input or missing authority is a refusal, never a default.
- **Evidence before claims.** Published numbers carry a command, a date, and an artifact.
- **No duplicates, no temp files, one file one job, every file explains itself.**
- **Secrets never enter the tree.**
- **Simple English** in code, docs, and UI, so a non-technical professional reader
  (recruiter, partner) can follow.
- **One brand mark:** the Helix Solutions logo, everywhere.

## 6. Definition of done

It works; it has a test or a documented manual check; the `AGENTS.md` ledger has an
entry; the docs reflect the new reality; no temporary file was left behind; and every
published number can be re-run to reproduce itself.
