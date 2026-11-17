# STATUS — v5

> Single source of truth for progress. Read `../AGENTS.md` first.
> Update this file **after every step**, then commit.

---

## NEXT ACTION

**Start M3 — segment renderer + cache.**
Files: `src/v5/render/cache.py`, `src/v5/render/segment.py`, `tests/test_cache.py`.
DoD: cache key covers every synthesis input; second render of the same segment is a hit;
renderer refuses to run if any voice in `config/voices.toml` lacks a `profile_id`.
Test against a mocked HTTP transport — the real endpoint needs M4.

Then M5 (assembler) — `src/v5/render/assemble.py`, `tests/test_assemble.py`.

**M4 is the human gate:** create the six German voices in VoiceStudio → Design, fill in
`profile_id` + `seed` in `config/voices.toml`. Nothing audio-real can be verified until then.

---

## Milestones

| # | Milestone | State | Evidence |
|---|---|---|---|
| M0 | Foundations | DONE | see log |
| M1 | Contract + validator | DONE | see log |
| M2 | VoiceStudio adapter | DONE | see log |
| M3 | Segment renderer + cache | TODO | — |
| M4 | Six German voices | **BLOCKED (human)** | needs VoiceStudio Design session |
| M5 | Assembler | TODO | — |
| M6 | Corpus stages A–C | TODO | — |
| M7 | Server | TODO | — |
| M8 | Client | TODO | — |
| M9 | Pilot 12 lessons | TODO | 1 of 12 exists (A2-01, abbreviated) |
| M10 | Scale to 72 | TODO | — |
| M11 | Release | TODO | — |

---

## Log

| Date | M | Summary |
|---|---|---|
| 2026-11-17 | — | Plan written (`V5-ENGINEERING-PLAN.md`), `AGENTS.md` written, decisions locked: design voices + 72 lessons |
