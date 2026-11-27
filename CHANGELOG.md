# Changelog

All notable changes to Mannschaft are recorded here.
Format follows [Keep a Changelog](https://keepachangelog.com/).

Release history before this file existed is recorded in `STATUS.md` (the milestone log)
and `docs/archive/V6-REPORT.md` (the V6 evidence report); the two release tags on GitHub
are `v6.0.0` and `v6.0.1`, both dated 2026-11-21.

## 2026-11-27

### Added

- `AGENTS.md` — agent charter and the sign-in/sign-out ledger.
- `CONSTITUTION.md` — the owner's engineering philosophy and clean-code policy, the
  same text as in every other repository in the portfolio.
- `GOVERNANCE.md` — repo map, documentation policy, sync policy and archiving rules.
- `SECURITY.md` — threat model and vulnerability reporting.
- `scripts/check_root_docs.py` — the root-document hygiene gate from `GOVERNANCE.md`
  section 2, checked in both directions (the documented root documents are present, and
  no unlisted `.md`/`.txt` sits at the root). Wired into CI, with a self-test that proves
  the gate fails closed.

### Changed

- `V6-REPORT.md` moved to `docs/archive/V6-REPORT.md` — a dated one-off milestone
  report, per `GOVERNANCE.md` section 2 — and `STATUS.md` now points at the new path.
- `src/v5/__init__.py`'s module docstring now also points readers at `AGENTS.md` and
  `GOVERNANCE.md`, not only `README.md` and `STATUS.md`.
