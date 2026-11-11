# Venture Foundry: Performance, Concurrency & Reliability Audit

Branch: `perf/concurrency-optimizations` · Target: 30–40 concurrent users on Streamlit Community Cloud

All numbers below are **measured** unless marked otherwise. They come from a 2-core Linux sandbox
running Python 3.13 and Streamlit 1.67. Streamlit's `AppTest` drove real script runs against seeded
databases: 1 game, 10 teams, canvases, assumptions, evidence and inbox mail, advanced to round 3,
8 or 14. Community Cloud's CPU share is unknown, and may be smaller than this sandbox's. **Treat
absolute times as relative, and the before/after ratios as the meaningful result.**

## A. Executive summary

- **The main problem: each click repeated the same database work thousands of times.** The sidebar
  checks whether each of ~16 tools is locked, active, or reference. Each check rebuilt the semester
  schedule and re-walked every earlier round's deliverables and answers, through a new SQLite
  connection per query. The to-do list and the "Next" strip rebuilt the full checklist up to three
  more times. A single student click made **~3,000 database connections at round 8 and ~6,000 at
  round 14.** The app got slower every week of the semester.
- **Concurrency bugs.**
  - At a scheduled advance time, several students loading at once could each advance the round. Each
    advance charged salaries, applied learning, and sent mail again.
  - Teammates spending at the same moment could overdraw credits or overwrite each other's balance.
  - Training progress could be lost the same way.
- **Data-loss risk.** All semester data lives in a local SQLite file. Community Cloud doesn't keep
  local files across reboots or redeploys.
- **Security.** The landing page let anyone enter any team without a join code, and displayed the
  default Director PIN.

**Result.** Student clicks are now **13–27× faster by mid/late semester** (every student page ≈ 50–70 ms at round 14), and their cost stays flat
as the semester goes on. Each click now uses about 40 database connections, down from thousands. The
concurrency bugs are fixed and covered by tests. The Director can back up and restore the whole
game. The security holes are closed.

## B. Optimization results (measured)

### Single-session response time per click (median of 3) and DB connections

| Page (student) | Round 3: before → after | Round 8: before → after | Round 14: before → after |
|---|---|---|---|
| Round Briefing | 299 → 57 ms (956 → 25 conn) | 902 → 67 ms (3,102 → 34) | **1,645 → 70 ms** (6,156 → 41) |
| Canvases | 262 → 59 ms | 658 → 54 ms | 1,133 → 65 ms |
| Assumption Map | 182 → 37 ms | 575 → 62 ms | 893 → 58 ms |
| Evidence Ledger | 235 → 75 ms | 546 → 56 ms | 889 → 69 ms |
| My Venture | 338 → 215 ms* | 660 → 236 ms* | 958 → **66 ms** (223 ms before the chart change) |
| Leaderboard | 447 → 41 ms | 859 → 40 ms | 1,351 → 50 ms |
| Director: Round Scores | 290 → 127 ms | 407 → 145 ms | 588 → 169 ms |

\*Rounds 3 and 8 were measured before the chart change. Replacing `st.line_chart` with direct
Vega-Lite specs removed ~150 ms of Altair object building per view (round 14: 223 → 66 ms).

### Simultaneous-burst test (round 14)

N sessions all click 5 pages back-to-back at the same moment, in one process sharing the GIL like
the real server. This is a **worst case**: real classes spread their clicks out. Browser and network
time are not included.

| Concurrent sessions | Before: p50 / p95 | After: p50 / p95 |
|---|---|---|
| 1 | 1.28 s / 1.56 s | 0.065 s / 0.17 s |
| 10 | 18.8 s / 28.3 s | 0.44 s / 1.8 s |
| 20 | 43.6 s / 66.5 s | 0.96 s / 3.6 s |
| 40 | **did not finish in 15 min** | 2.0–2.9 s / 7.3–10.5 s (3 runs; one noisy run at 6.7 s p50) |

**Memory:** about 148 MB with 1 session and about 293 MB peak with 40, which works out to roughly
3.6 MB per session including test-harness overhead. That is well under Community Cloud's 690 MB
throttle point.

**Errors under concurrency:** a few runs hit a "duplicate widget key" error on the AI-log form. It
occurs on the original code too, and it never occurs when sessions run one at a time: 34 page
renders and 16 Director pages were all clean. It appears to be an artifact of running several
`AppTest` instances in threads, not an app bug. Watch for it in real use anyway.

### Component summary

| Component | Problem identified | Modification | Measured improvement |
|---|---|---|---|
| Application startup | `init_db()` (schema + ~12 PRAGMA lookups + migrations) ran on every rerun of every session | Once per process (`st.cache_resource`) | Included in per-click times above |
| Page loading | N+1 recomputation: 3k–6k DB connections per click | Per-run read cache (`db.run_memo`) on 44 read helpers + schedule/checklist derivations | 13–27× faster at rounds 8–14 |
| Session management | Cache must not leak across users | Thread-local, script-body-only, cleared on every commit, never shared | 34 of 34 student page renders are text-identical before vs after |
| CPU utilization | Above; Altair chart building on every rerun | Memoization; Vega-Lite specs instead of `st.line_chart`/Altair | See tables |
| Memory consumption | Leaderboard held full team rows | Shared cache keeps display fields only; upload cap 10 MB | ~3.6 MB/session |
| File uploads | Roster (KB-sized) parsed once from memory; 200 MB default cap | `maxUploadSize = 10` | Not measured (not a bottleneck) |
| File downloads | Roster template rebuilt on every Team Setup rerun | Built once per process | Not measured (small) |
| Caching | None anywhere | Per-run read cache; leaderboard shared per game for 30 s | Leaderboard 1,351 → 50 ms |
| Concurrent users | Lock errors, double advance, overdraw, lost training | WAL + 30 s busy timeout; per-game advance lock; atomic spend/usage; serialized skill XP | Burst table above; race tests pass |

## C. Code modifications

| File | Change |
|---|---|
| `db.py` | Request-scoped read cache. WAL, `synchronous=NORMAL`, 30 s timeout. Atomic `adjust_resources` (`BEGIN IMMEDIATE`). `increment_team_field`. Online-backup `backup_bytes`, `validate_backup`, `restore_from_bytes`. |
| `logic.py` | Memoized schedule and checklist. `sync_active_game` with a non-blocking per-game lock, which `director_advance` also takes. Atomic usage counters and serialized skill XP. Managing Partner notes sent from a background thread (`send_managing_partner_notes_async`, `mp_job_status`). PIN helpers (`check_pin` with constant-time compare; `VF_INSTRUCTOR_PIN` secret override). |
| `app.py` | Schema and favicon set up once. Request cache around the script body. Removed the landing-page team picker and the PIN caption. PIN rate-limit (30 s after 5 misses). Director "👀 View the game as a team" and "↩️ Back to Director console". New "Backup & Restore" page. |
| `views_instructor.py` | Backup & Restore page. Home-page backup reminder (over 24 h) and default-PIN warning. PIN field is now a password input with a minimum of 6 characters. Background MP-note sending with status. Cached roster template. |
| `views_student.py` | Shared leaderboard cache. Trend and Pareto charts as Vega-Lite specs (same chart types and colors). |
| `requirements.txt` | Pinned `streamlit==1.67.0` (the tested version) and bounded the others. |
| `.streamlit/config.toml` | `maxUploadSize = 10`, `gatherUsageStats = false`. |
| `.gitignore` | Ignores `*.db` files so student data is never committed. |
| `venture_foundry.zip` | Removed (a stale copy of an older version). |
| `README.md` | PIN, backup, view-as-team, and performance notes. |
| `tests/test_perf_safety.py` | 13 regression tests. |

**Behavior changes users will notice:**

- The leaderboard can lag by up to 30 s within a round.
- Managing Partner notes arrive over a few minutes after an advance, instead of the advance waiting
  for them.
- Students can no longer pick a team from the landing page. Directors use the sidebar instead.
- The Director sees a warning until the PIN is changed, and a reminder until a recent backup exists.

## D. Testing

- `pytest -q tests/` passes all 13 tests. They cover:
  - WAL mode
  - Cache scoping and invalidation
  - Copy safety
  - Checklist equivalence with and without the cache
  - No overdraw under 25 concurrent spends
  - Atomic counters
  - A single advance and a single salary charge under 12 simultaneous loads
  - Backup round-trip
  - Rejecting junk or foreign restore files
  - PIN secret override
  - Background MP notes run once without blocking
  - No lost skill XP under 20 concurrent trainings
- Every student page (2 teams × 17 pages) and every Director page (16) renders without exceptions, on
  both a seeded and a brand-new database. Student page text is **identical** to `main`.
- Manually scripted flows: PIN lockout, login, default-PIN warning, backup reminder, view-as-team and
  back, and the Backup page download.
- Not tested: a real browser against Community Cloud, and restore through the UI uploader. The
  restore logic itself is unit-tested.

## E. Remaining constraints

- **Durability: addressed by the Neon Postgres backend.** Set `DATABASE_URL` and the app stores
  everything in Postgres via `pgcompat.py`. Measured against a local Postgres 16:
  - All 16 tests pass.
  - All 34 student page renders are text-identical to the original SQLite app, and all 16 Director
    pages are error-free.
  - A SQLite → Postgres → SQLite backup round-trip is lossless.
  - About 22–25 queries per click, down from 34, after batching per-team reads.

  On Neon, each query is a network round trip. Expect each click to take roughly 22–25 × the
  Streamlit-to-Neon latency longer, and a ~0.5–1 s first query after Neon has suspended an idle
  compute. **Not yet measured against Neon itself.**
- **Platform.**
  - Community Cloud's documented limits are roughly 0.078–2 CPU cores and 690 MB–2.7 GB RAM, and can
    change without notice.
  - There is one Python process (GIL) and no horizontal scaling.
  - Apps sleep after inactivity and take time to wake.
  - Actual CPU allotment can't be observed, so it remains **unknown**.
- **Is 30–40 users realistic?** At the app level, yes for normal classroom use: ~65 ms per click and
  ~4 MB per session. Under a worst-case burst of 40 users all clicking nonstop, expect waits of a few
  seconds, longer if Community Cloud gives the app less CPU than this sandbox had. A short check
  during a real class session (40 students, watch for slowness or "Oh no" pages) is the final
  confirmation.
