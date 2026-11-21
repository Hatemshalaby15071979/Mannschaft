# V6 Report

Date: 2026-11-21 · Branch: `master` (v5 repo) / `main` (root repo, local only)
Executor: autonomous agent · Scope: `V6-ARCHITECTURE-PLAN.md` + `V6-EXECUTION-PROMPT.md`

---

## 1. Verdict

V6 shipped additively. The original eight screens, `/api/render`, the renderer,
adapters, contract, corpus and every rendered audio file are unchanged. Three new
screens (Video, Karten, Wörterbuch) and four read-only API routes sit on top.

| Phase | Commit | What landed |
|---|---|---|
| V6-0 Guard | `df06f80` | `tools/hash_legacy.py`, 2,657-file snapshot, baseline 188 tests |
| 0A Design shell | `e1603d9` | `v6-shell.css`, `v6.css`, sidebar index, masthead, KPI tiles, level tabs, expandable rows, theme/motion/focus controls, alias bridge |
| 1 Media | `e1603d9` | `src/v5/media/`, `content/lesson_media.json`, `GET /api/media/{id}`, `#/clip/{id}`, SW YouTube exclusion |
| 2 Cards | `e1603d9` | `src/v5/cards/`, `content/cards/*.json`, `GET /api/cards/{id}`, `#/cards/{id}`, `card_graded` events |
| 3 Dictionary | `e1603d9` | `src/v5/dictionary/`, `content/dictionary/seed.json` (542 entries), `GET /api/dict?q=`, `#/dict`, word taps |
| 4 Journey | `e1603d9` | `GET /api/lesson/{id}/context`, clip/cards buttons on the lesson screen, `clip_opened` event |
| 5 Verify / package | `baa1d50` | CI, packaging, serve scripts, README, this report, STATUS |
| Root repo | `27e9d6c` | `git init -b main` at the project root; plans, archives, v5 gitlink; no remote |

---

## 2. Quality

| Gate | Result |
|---|---|
| `make check` | **223 passed in 20.19 s**, `ruff` clean (`--no-cache`; see note) |
| Tests before → after | 188 → **223** (+35 in `tests/test_v6.py`) |
| `make validate --all` | **12 lessons, 0 errors, 0 warnings** |
| Browser walkthrough | 11 routes; **0 console errors, 0 failed requests** (excluding navigation `ERR_ABORTED`) |
| Playback restore | autosave fired, position after reload **8,200 ms** |
| Clip embed | `youtube-nocookie.com/embed/…?start=29&end=89&rel=0`, no autoplay, no YouTube URL in Cache Storage |
| Cards | 10 per lesson (120 total); grading POSTs `/api/progress` |
| Dictionary | 542 local entries; 4 outbound links with `rel="noopener"` |
| Structured logging | one line per request: `ts=… method=GET route=/api/health status=200 ms=0.9` |
| Contract validation | on-disk media manifest, 12 decks, dictionary seed and overrides load through their strict models |
| Design leak grep | `grep -riIE 'n8n|WFM|Hatemshalaby|Operations___|github.com/Hatemshalaby' src/v5/client content --exclude-dir=audio` → **no matches** |
| Legacy hash gate | See below |

### Accessibility

- Skip link is the **first Tab stop** on load (fixed: the router no longer moves
  focus on first paint, which had pushed the sequential start point past it).
- Focus outline: `3px solid`, computed `outline-style: solid`, visible on first Tab.
- `aria-current="page"` maintained on the tabbar; screen gets focus on navigation.
- Reduced motion: with `prefers-reduced-motion: reduce`, computed transition and
  animation durations are `0.00001s` (effectively zero); the in-app toggle works too.
- Mobile header: at 360 px the index and controls sit on two rows; measured bar
  bottom 98.3 px vs content top 100.8 px → no overlap. Light and dark both checked.
- Contrast (WCAG 2.1, body text ≥ 4.5:1):

| Pair | Dark | Light |
|---|---|---|
| on-surface / surface | 13.55 | 16.45 |
| on-surface-variant / surface | 7.68 | 7.10 |
| primary link / background | 9.11 | 5.00 |
| error | 6.27 | 4.55 |
| positive | 8.26 | 4.56 |
| warning | 9.43 | **4.70** (was 3.03; light token darkened to `#8a6800`) |

### Legacy hash gate — honest note

The Phase-0 snapshot lived in `/tmp/v6_legacy_before.sha256` and was removed when
`/tmp` was cleared between sessions. The gate was therefore re-proven two ways:

1. **mtime audit:** the newest file under every frozen path is dated
   `2026-11-18 11:56` (audio), `2026-11-17 12:58` (corpus), `2026-11-17 12:13`
   (`voices.toml`); `find v3 v4 webapp -newermt 2026-11-19` → **no results**.
   V6 work began 2026-11-21, so no frozen asset was written.
2. **fresh 2,657-file snapshot:** `/tmp/v6_legacy_after.sha256`, matching the
   count recorded in V6-0. `git status` for tracked frozen modules shows only the
   sanctioned `server/app.py`.

No legacy file was modified or deleted. The two sanctioned mutation points are
`server/app.py` (routes) and `client/js/main.js` (routes + first-paint focus fix).

---

## 3. Artifacts

| Zip | Size | SHA-256 | Clean install |
|---|---|---|---|
| `v5/dist/v5-core.zip` | 586,198 B (0.56 MiB) | `2a1c7e57c0aa2ab39bfbb6dbc29dd5ba7421a77c6cecb8d181984be0fe73687c` | **OK** |
| `v5/dist/v5-full.zip` | 223,317,363 B (212.97 MiB) | `f2b9b2f59014c7740719cb18b44a56a6a8ea5158ba748d9058b041c608186c40` | **served OK** (see below) |

`make dist-check` unzipped core into a fresh `/tmp` directory and ran
`python3 -m v5 --help`, `python3 -m v5 validate --all` (12 lessons, 0 errors) and
`python3 -m pytest -q` (223 passed), then probed `/api/health`:
`{"app":"ok","voicestudio":{"up":false,…},"lessons":{"total":12,"rendered":0},"corpus":{"clips":790}}`.
`rendered: 0` is correct: core deliberately excludes audio.

The **full** zip was unzipped into a fresh directory and actually served on an
ephemeral loopback port: health `app=ok`, `lessons.rendered=12`, `/api/audio/A1-01`
returned 2,756,924 bytes, `Range: bytes=0-99` returned **206** with
`Content-Range: bytes 0-99/2756924` and exactly 100 matching bytes, and
`/api/media`, `/api/cards`, `/api/dict`, `/api/lesson/{id}/context` all returned 200.

**Rollback:** keep the previous `v5-full.zip`; stop the server
(`make stop-bg`), replace the install directory with the older zip's contents,
start it again. No database migration is involved — `user/*.sqlite` is separate.

---

## 4. Repository

- Root repo initialised at the project root, branch `main`, **local only**.
- No remote added, nothing pushed — **awaiting owner approval** for a GitHub remote.
- Ignored: `__pycache__/`, `*.pyc`, caches, `*.sqlite*`, `dist/`, `.env*`,
  `content/audio/` (generated), corpus sqlite/cache, editor/OS files.
- Tracked: lessons, derived JSON (cards, dictionary, media manifest), config,
  `src/`, client assets, tests, Makefile, pyproject, `AGENTS.md`, STATUS, plans,
  report, CI workflow, tools.
- Commits follow `m<N>: <what>`; the v5 repo carries V6-0 → V6-2, the root repo
  carries the monorepo import.

---

## 5. Service

```bash
make serve-bg     # idempotent; 127.0.0.1:8766; log /tmp/opencode/german-v6-server.log
make stop-bg      # stops by PID file
curl -s http://127.0.0.1:8766/api/health
```

Observed health with VoiceStudio down:

```json
{"app":"ok","voicestudio":{"up":false,"voices":null,
 "error":"[Errno 111] Connection refused"},"voices_ok":true,
 "missing_voices":[],"lessons":{"total":12,"rendered":12},"corpus":{"clips":790}}
```

The probe has a short timeout and never blocks the app. Rendering stays optional;
all new screens read generated JSON, not VoiceStudio.

---

## 6. Honest gaps

- **Core zip has no audio.** Lessons show transcript, cards and video, but no MP3
  until rendered or until the full zip is used. This is by design.
- **YouTube needs a network.** The iframe is privacy-enhanced and never cached by
  the service worker; offline it shows the "Watch on YouTube" fallback, not a video.
- **Media matching is heuristic.** All 12 lessons got a primary clip with no level
  gap, but the selector scores corpus metadata; it does not verify that the clip's
  content matches the authored scene. Overrides are the correction path.
- **Dictionary is a glossary index, not a dictionary.** 542 entries from the
  lessons' own glossaries plus outbound links; no scraped definitions.
- **Voices are not human-auditioned.** M4's objective distinctness passed 6/6; the
  plan's listening criteria remain advisory.
- **Schema location differs from §5 by necessity.** §5 asks new schemas to live in
  `src/v5/contract/`, but §3.1 freezes that directory and the hash gate enforces it.
  The strict models therefore live beside their generators
  (`media/manifest.py`, `cards/schema.py`, `dictionary/schema.py`) and
  `test_on_disk_json_validates_against_its_schema` validates every checked-in file.
- **M10/M11 remain deferred** by the 2026-11-18 pilot decision. V6 did not resume
  scale-out or release work.
- **Lint uses `--no-cache` locally** because this project sits on a mount where
  ruff's atomic cache rename fails with `EINVAL`. CI uses the normal cache.

Nothing in this report is claimed from an old output file; every result above came
from a command run in this session.
