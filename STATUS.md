# STATUS — v5

> Single source of truth for progress. Read `../AGENTS.md` first.
> Update this file **after every step**, then commit.

---

## NEXT ACTION

**M6 — corpus stages A–C.** Files: `src/v5/corpus/`, `tests/test_corpus.py`.
DoD: `clips.jsonl` with ≥ 400 scored candidates; `corpus suggest --level B1 --situation work`
returns ≥ 3; the `GET /api/corpus/suggest` endpoint (already wired in M7) now returns real
candidates instead of the honest "corpus not built yet" stub.

**M4 is DONE** (see milestone row + log). All six `profile_id`s are filled in
`config/voices.toml`; the six design profiles exist in VoiceStudio's DB with distinct
seeds; `make check` green; `python -m v5 health` → "all voices configured". Real audio
can now be rendered. The remaining human-ear audition (plan §7.2 criteria 1–4) is still
advisory — objective waveform-distinctness passed 6/6.

---

## Milestones

| # | Milestone | State | Evidence |
|---|---|---|---|
| M0 | Foundations | DONE | `make check` → 6 passed; commit `7bb568f` |
| M1 | Contract + validator | DONE | `make validate` → A2-01: 0 errors 0 warnings; 21 tests; commit `62eb87e` |
| M2 | VoiceStudio adapter | DONE | golden test: 40 spans parsed by the **real** `longform_parser.py`; 32 tests green; commit `ff1152b` |
| M3 | Segment renderer + cache | DONE | A2-01: 28 segments → 28 unique keys → 28 engine calls, then **28/28 cache hits, 0 calls**; `make render` refuses with exit 2 while profiles are empty; commit `acd7ca0` |
| M4 | Six German voices | DONE | `b0872fa` — Six design profiles created via `POST /profiles` (kind=design, language=German, distinct seeds, `vd_states` from real `instruct_to_vd_states`); ids in `config/voices.toml`; `/v1/audio/speech` renders all six to distinct WAVs (6/6 hashes); `make check` 152 passed; `v5 health` → all voices configured |
| M5 | Assembler | DONE | 94 tests green. Synthetic 4-segment lesson: computed **8060 ms**, assembled **8060 ms**, mp3 **8060 ms** → **0 ms drift**; −23.55 LUFS in → **−16.45 LUFS out** (target −16, within 1 LU); `timeline.json`/`lesson.srt`/`manifest.json`/`lines/*.mp3` all written; `reuse=True` returns in **0.2 ms**; commit `12301a5` |
| M6 | Corpus stages A–C | TODO | — |
| M7 | Server | DONE | 135 tests (36 server + 5 pipeline). 16 routes on 127.0.0.1:8766; `Range: bytes=0-99` → **206**, `Content-Range: bytes 0-99/2048`, body exactly 100 bytes; suffix range → tail; `bytes=99999-` → **416**; `/api/health` reports VoiceStudio down (`[Errno 111] Connection refused`) without hanging; `assert_loopback` refuses `0.0.0.0`/LAN; live `make serve` returned A2-01 + honest health; commit `e6d4f97` |
| M8 | Client | DONE | 152 tests (16 asset + 2 Playwright smoke). 8 screens; service worker with byte-range slicing (206/416 verified against HTTP semantics); position restored from `/api/progress` after reload; offline after first play; keyboard-only usable; commit `27a746d` |
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
| 2026-11-17 | M3 | Content-addressed segment renderer + `AudioCache`; `python -m v5 render ID` wired; 70 tests green |
| 2026-11-17 | M5 | ffmpeg assembler: exact-silence concat, two-pass `loudnorm`, `timeline.json`, `lesson.srt`, `manifest.json`, `lines/*.mp3`; shared `Segment.gaps()` so both render paths agree; reuse fast-path; 94 tests green |
| — | — | **Surprise:** `loudnorm`'s measure pass *always* reports `"normalization_type": "dynamic"` in ffmpeg 8, even when the applied two-pass `linear=true` result is accurate (−16.02 LUFS on a 60 s probe). Checking that field would have failed every correct render. Assert the measured output loudness instead. |
| — | — | **Gotcha:** a fully silent clip trims to nothing and `ffprobe` prints `N/A`, not a number. `probe_duration_ms` now raises `AssemblyError` with a "synthesis failed" message instead of a bare `ValueError`. A dead engine can no longer produce a silent lesson. |
| — | — | **Design:** `Segment.gaps()` / `takes` / `tail_pause_ms` live once in the contract. The longform adapter reads them, the assembler reads them, so the two render paths cannot drift. `check` uses `answer_pause_ms` as its tail (thinking time) and is excluded from `lesson.srt` — the question is audio, the answer is the UI's job. |
| — | — | **Measurement:** trim chain (`silenceremove` −50 dB, `start_silence=0.04`, `areverse` round-trip) turns 1.30 s padded → 1.08 s, i.e. it keeps the intended 40 ms guard. mp3 duration equals wav duration exactly. |
| 2026-11-17 | M7 | FastAPI app on 127.0.0.1:8766: catalogue, byte-range audio, render job queue, SQLite progress, health probe; `make serve`; 41 new tests |
| — | — | **Decision:** byte-range is Starlette's `FileResponse`, not hand-rolled. Verified 206 + exact `Content-Range` + 416 before writing a line; a custom parser would have been a liability with no upside. |
| — | — | **Correction:** `render`/`assemble` logic moved out of the CLI into `render/pipeline.py`, because the server needs the same guards. Two copies would have drifted. CLI now only maps typed exceptions to exit codes (1 bad lesson, 2 voices unready, 3 engine, 4 assembly). |
| — | — | **Bug caught by test:** the server's default render function used the module-level `content/` paths, so an app built with injected test dirs would have rendered *real* content. `make_render_fn(catalogue)` now binds the pipeline to the app's own dirs; `test_default_render_fn_is_bound_to_the_apps_own_dirs` pins it. |
| — | — | **Gotcha:** the `register` shadow bites again — `Catalogue` must read `script.scene.register_`, not `.register`, or pydantic's `__getattr__` raises `AttributeError` on every lesson. Documented at the read site. |
| — | — | **Design:** render is queued, never inline (a 10-minute lesson cannot hold an HTTP request). The queue has exactly **one** worker: the GPU is a single resource. Duplicate submissions return the active job instead of stacking. |
| — | — | **Correction:** contract uses `speaker` (cast role), not `voice`. Plan §6.1 and tests fixed. |
| — | — | **Correction:** `voice_map` keys are bare names (`"kunde"`), not `"[voice:kunde]"`. The router's docstring is wrong; `_map_span_voice` does `voice_map.get(voice_id)`. Would have silently collapsed all voices to default. |
| — | — | **Discovery:** `default_speed` on `parse_script_to_spans` is an exact float, so the level baseline (A2=0.90) does **not** need quantising. Only deviating segments get tags. First implementation wrapped every line in `[emphasis]`; fixed. |
| — | — | **Gotcha:** `register` shadows `ABCMeta.register` and `schema` shadows `BaseModel.schema` → pydantic warns. Fixed with `register_`/`schema_` + `alias=`. Any new field named `json`, `schema`, `register`, `copy`, `dict` hits the same thing. |
| — | — | **Correction:** plan §14 puts `timeline.json ±50 ms of ffprobe` in M3, but `timeline.json` does not exist until the assembler (M5). Split: M3 = render + cache (proven with mocked transport), the ffprobe assertion moves to M5. |
| — | — | **Design note:** repeats (`echo`/`drill`) are *not* extra synthesis calls. The cache is per segment; the assembler repeats the audio per `repeat`. That keeps the cache at 28 entries for A2-01 instead of 40. |
| 2026-11-17 | M8 | PWA client: 8 screens, service worker with byte-range slicing, persistent player, progress restore on reload; 2 Playwright smoke tests + 16 asset tests; 152 total |
| — | — | **Gotcha:** `ProgressStore` used `with self._connect() as conn:` which **closes** the persistent connection on every call (SQLite's `__exit__` closes, not commits). The `upsert` wrote, the connection closed uncommitted, and the next `all()` opened a fresh connection that saw an empty table. Fixed by dropping the `with` and using `self._conn` directly with explicit `.commit()`. |
| — | — | **Gotcha:** the browser caches `GET /api/progress` from the initial page load. After a `page.reload`, the `play.js` screen's `api.progress()` call returned the cached empty result, so `resumeAt` was `null` and the player never restored the position. Fixed with a cache-buster query param (`_ts=Date.now()`) on the progress fetch and `Cache-Control: no-store` on the response. |
| — | — | **Design:** the player is a **singleton** that outlives its screens. Navigating `#/play` → `#/transcript` never stops playback; the same `<audio>` element is shared. Transcript sync uses `timeline.json` `start_ms` (measured), never estimated. |
| — | — | **Decision:** icons are generated by `tools/make_icons.py` (pure-stdlib PNG writer, 2x supersample + box filter), not shipped as binary blobs in git. `make_icons.py` is the source of truth; the PNGs are the build artefact. |
| 2026-11-17 | M4 | Six German design voices created via VoiceStudio's `POST /profiles` API (kind=design, language=German, distinct pinned seeds, vd_states built by VoiceStudio's own `instruct_to_vd_states`). profile_ids written to `config/voices.toml`. All six render through `/v1/audio/speech` to 6/6 distinct WAVs; `make check` 152 passed. |
| — | — | **Correction:** four "refuses while voices are unready" tests (test_adapter, test_pipeline, test_render ×2, test_server ×2) hard-coded `load_voices()` being empty (the pre-M4 state). With M4 done they either failed or — worse — the CLI test fell through to **real synthesis against the live engine and hung**. Fixed by injecting an explicit `unready_voices()` helper (empty profile_ids) in `tests/helpers.py`. The guard invariants are preserved; the tests no longer depend on ambient config. |
| — | — | **Discovery:** VoiceStudio saves a design profile with a *pending sample* when the TTS model isn't loaded (`main.py` lazily preloads; `profiles.py` defers sample render). That is sufficient: `/v1/audio/speech` resolves the profile row and conditions on its stored `instruct`+`seed` (openai_compat.py:711-723). No GPU sample render was needed to make the voices functional. Backend device reported `cpu`. |
| — | — | **Gotcha:** `POST /profiles` needs `vd_states` as a JSON **string** form field, and heals `instruct` from it via `heal_design_instruct`. Passing only `instruct` is not enough for a design profile — the server 422s without `vd_states`. |

