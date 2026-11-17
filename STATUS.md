# STATUS — v5

> Single source of truth for progress. Read `../AGENTS.md` first.
> Update this file **after every step**, then commit.

---

## NEXT ACTION

**M2 — VoiceStudio longform adapter + golden test.**
Files: `src/v5/adapters/longform.py`, `src/v5/adapters/srt.py`,
`tests/test_adapter.py`, `tests/golden/`.
DoD: `parse_script_to_spans()` on emitted text reproduces the segment list exactly
(voice, text, pause, quantised speed) — imported from the **real** module, not a copy.
Plus a regex guard: emitted text contains no `[DE]`, `[EN]`, `====`.

**M4 is the human gate:** create the six German voices in VoiceStudio → Design, fill in
`profile_id` + `seed` in `config/voices.toml`. Nothing audio-real can be verified until then.

---

## Milestones

| # | Milestone | State | Evidence |
|---|---|---|---|
| M0 | Foundations | DONE | `make check` → 6 passed; commit `7bb568f` |
| M1 | Contract + validator | DONE | `make validate` → A2-01: 0 errors 0 warnings; `make check` → 21 passed |
| M2 | VoiceStudio adapter | TODO | — |
| M3 | Segment renderer + cache | TODO | — |
| M4 | Six German voices | **BLOCKED (human)** | needs VoiceStudio Design session |
| M5 | Assembler | TODO | — |
| M6 | Corpus stages A–C | TODO | — |
| M7 | Server | TODO | — |
| M8 | Client | TODO | — |
| M9 | Pilot 12 lessons | TODO | 1 of 12 exists (A2-01, 28 segments — abbreviated; expand to ~70 in M9) |
| M10 | Scale to 72 | TODO | — |
| M11 | Release | TODO | — |

---

## Log

| Date | M | Summary |
|---|---|---|
| 2026-11-17 | — | Plan written (`V5-ENGINEERING-PLAN.md`), `AGENTS.md` written, decisions locked: design voices + 72 lessons |
| 2026-11-17 | M0 | Scaffold, `make check` green, 6 voices + 6 levels in TOML config |
| 2026-11-17 | M1 | Contract models (pydantic, `extra=forbid`), semantic validator, CLI, A2-01 pilot lesson |
| — | — | **Correction recorded:** contract uses `speaker` (cast role), not `voice`. The plan §6.1 example still says `voice` on scene/note — fix the doc when convenient; the code is authoritative. |
| — | — | **Gotcha:** `register` shadows `ABCMeta.register` and `schema` shadows `BaseModel.schema` → pydantic warns. Fixed with `register_`/`schema_` + `alias=`. Any new field named `json`, `schema`, `register`, `copy`, `dict` will hit the same thing. |

