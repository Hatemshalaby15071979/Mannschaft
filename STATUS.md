# STATUS — v5

> Single source of truth for progress. Read `../AGENTS.md` first.
> Update this file **after every step**, then commit.

---

## NEXT ACTION

**M3 — segment renderer + cache.**
Files: `src/v5/render/cache.py`, `src/v5/render/segment.py`, `tests/test_render.py`.
DoD: cache key covers every synthesis input; second render of an identical segment is a
hit; changing one field busts the key; renderer refuses when any voice lacks a
`profile_id`. Mocked HTTP transport only — the real endpoint needs M4.

**Then M5 (assembler):** `src/v5/render/assemble.py` — ffmpeg trim + loudnorm + authored
pauses + `timeline.json`. Testable with synthetic wav files, no VoiceStudio needed.

**M4 is the human gate:** create the six German voices in VoiceStudio → Design, fill in
`profile_id` + `seed` in `config/voices.toml`. Nothing audio-real can be verified until then.

---

## Milestones

| # | Milestone | State | Evidence |
|---|---|---|---|
| M0 | Foundations | DONE | `make check` → 6 passed; commit `7bb568f` |
| M1 | Contract + validator | DONE | `make validate` → A2-01: 0 errors 0 warnings; 21 tests; commit `62eb87e` |
| M2 | VoiceStudio adapter | DONE | golden test: 40 spans parsed by the **real** `longform_parser.py`; 32 tests green |
| M3 | Segment renderer + cache | TODO | — |
| M4 | Six German voices | **BLOCKED (human)** | needs VoiceStudio Design session |
| M5 | Assembler | TODO | — |
| M6 | Corpus stages A–C | TODO | — |
| M7 | Server | TODO | — |
| M8 | Client | TODO | — |
| M9 | Pilot 12 lessons | TODO | 1 of 12 exists (A2-01, 28 segments — expand to ~70 in M9) |
| M10 | Scale to 72 | TODO | — |
| M11 | Release | TODO | — |

---

## Log

| Date | M | Summary |
|---|---|---|
| 2026-11-17 | — | Plan written (`V5-ENGINEERING-PLAN.md`), `AGENTS.md` written, decisions locked: design voices + 72 lessons |
| 2026-11-17 | M0 | Scaffold, `make check` green, 6 voices + 6 levels in TOML config |
| 2026-11-17 | M1 | Contract models (pydantic, `extra=forbid`), semantic validator, CLI, A2-01 pilot lesson |
| 2026-11-17 | M2 | Longform + SRT adapters; golden test against the real parser; docs corrected |
| — | — | **Correction:** contract uses `speaker` (cast role), not `voice`. Plan §6.1 and tests fixed. |
| — | — | **Correction:** `voice_map` keys are bare names (`"kunde"`), not `"[voice:kunde]"`. The router's docstring is wrong; `_map_span_voice` does `voice_map.get(voice_id)`. Would have silently collapsed all voices to default. |
| — | — | **Discovery:** `default_speed` on `parse_script_to_spans` is an exact float, so the level baseline (A2=0.90) does **not** need quantising. Only deviating segments get tags. First implementation wrapped every line in `[emphasis]`; fixed. |
| — | — | **Gotcha:** `register` shadows `ABCMeta.register` and `schema` shadows `BaseModel.schema` → pydantic warns. Fixed with `register_`/`schema_` + `alias=`. Any new field named `json`, `schema`, `register`, `copy`, `dict` hits the same thing. |

