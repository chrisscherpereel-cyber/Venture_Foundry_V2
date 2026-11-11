# Venture Foundry — Development Handoff

_Last updated: 2026-11-11 · Stage 1 merged into `main` (fast-forward to `5c4a9df`) on 2026-11-11; work branch `dev/stage1-trustworthy-record`. If Streamlit Community Cloud deploys from `main`, the live app picks this up on its next rebuild._

Planning documents (Claude Docs, in the "New Venture Foundry" project):
- *Venture Foundry V2 — Audit and Development Plan* (audit, backlog B1–B20)
- *Venture Foundry V2 — Learning and Simulation Design* (design spec, rubric, acceptance criteria L1–L26, stages)

## Current milestone — Stage 1 "Trustworthy record" (complete, merged to `main`)

The goal: credits, assumption statuses and grades reflect qualified evidence, and a closed round's score can't drift.

| Item | What was built | Where |
|---|---|---|
| L1 / B1 Atomic, retry-safe experiment purchase | The charge, experiment row, build-hours usage and assumption→Testing all happen in **one transaction**. A `request_key` (per form instance) makes a double-click or retry charge once; there is a unique index on `(team_id, request_key)`. | `db.purchase_experiment_tx`, `logic.purchase_experiment`, `views_student.experiments` |
| L3 / B3 Round stamping | New evidence, assumptions, experiments and canvases record their `round`. | `db.add_*`, `db.save_canvas`, `_stage1_schema` |
| L3 / B4 Deadline lock | `editing_locked` is now true for committed teams **and** once the deadline passes, whether or not the team committed. | `logic.editing_locked` |
| L2 / B2 Frozen round results | New `round_results` table. Rounds are frozen at advance (`on_round_change`). Older ended rounds are frozen lazily on first view (`source='backfill'`). `round_score` returns the frozen row for ended rounds. Corrections need a reason: adjust (± points) or recompute; both are kept in `history`. | `logic.round_score/finalize_round_result/adjust_round_result/recompute_round_result`, Round Scores page, My Venture "Past round scores" |
| L4 / B5 Evidence model + credit rules | Each item records origin (Real-world / AI practice; Simulation is reserved for the app), direction, collected_on, sample n, limitations, review status, a dedupe key and history. **Credits:** base 1 on logging; release of strength × 0.5 is automatic for strength ≤ 5 with no flag, otherwise it waits for instructor review. Contradicting evidence pays the same as supporting. Duplicates are refused. Cap of 30 per round. A team can withdraw an item (credits returned). Practice items earn 0 and cannot link to an assumption. | `logic.log_evidence/review_evidence/withdraw_evidence`, `db.insert_evidence_tx/evidence_tx`, `content.EVIDENCE_*`, Evidence Ledger, **Evidence Review** (new Director page) |
| L6 / B6 Assumption status from evidence | Teams can set only Untested / Testing / Ignored. Supported or Refuted comes from the latest resolved experiment, or from ≥ 2 accepted items in one direction with total strength ≥ 10. Instructors can override with a reason ("auto" releases the override). Every status records its source. | `logic.derived_assumption_status/refresh_assumption_status/set_assumption_status_by_team/instructor_set_assumption_status`, Assumption Map, Evidence Review |
| L8 / B7 Computed, locked experiment results | Numeric success/failure thresholds plus a direction (higher or lower is better). The outcome is computed from the observed value; an override needs a reason and routes the item to review. Saving creates exactly one linked evidence row, and re-saves never pay again. A result locks after its round. | `logic.compute_outcome/record_experiment_result/experiment_locked`, `db.record_experiment_result_tx`, Learning Card |
| L9 Inconclusive | Leaves the assumption at Testing and never counts as support. | same |
| Misc | The pre-advance checklist shows how many evidence items are still waiting for review. Cohort Overview has an "In review" column. Evidence CSV export is on Evidence Review. Counted evidence (real-world, not withdrawn/duplicate/practice) feeds summaries, deliverables, badges and valuation. | `logic.pre_advance_checklist`, `db.list_counted_evidence` |

### Decisions recorded (from the course owner, 2026-11-11)
1. Grade weights: **60 / 25 / 15** (reasoning / completion / reflection), plus a **venture-outcomes bonus of up to 5%**. *(Not implemented yet. That is Stage 3, L17.)*
2. Claims **reuse the `assumptions` table**.
3. Students see **reasons, not arithmetic**, for computed evidence strength. *(Applies when interpretive strength, L5, is built in Stage 2.)*
4. Legacy data is **grandfathered**:
    - Pre-Stage-1 evidence keeps its credits and is labelled "Legacy (pre-review)"; it can't be re-reviewed.
    - Hand-set Supported/Refuted statuses stay until evidence settles them.
    - Legacy experiments without numeric thresholds keep a manual outcome selector.

### Schema changes (all additive and repeatable; `init_db` applies them)
- **`evidence`** gains: `round, origin, direction, collected_on, sample_n, limitations, experiment_id, review_status, review_note, dedupe_key, history`. There is an index on `team_id`.
- **`experiments`** gains: `round, success_value, failure_value, higher_is_better, observed_value, observed_n, computed_outcome, override_reason, result_round, evidence_id, request_key`. There is a partial unique index `ux_experiments_request`.
- **`assumptions`** gains: `round_created, status_source, status_note`.
- **`canvases`** gains: `round`.
- **New table:** `round_results(team_id, round, game_id, score, result, config, rubric_version, source, finalized_at, adjustment, adjust_reason, adjusted_at, history)`.
- **Backfill:** `dedupe_key` is filled on legacy evidence rows (NULLs only).
- **Not changed:** no column or table is dropped or rewritten, and existing credits and balances are untouched.

## How to test
```bash
pip install -r requirements.txt pytest
pytest -q tests/                                   # SQLite (default)
DATABASE_URL="postgresql://user@host:port/db" pytest -q tests/   # same suite on Postgres
```
**Results on this branch (2026-11-11, Python 3.13, Streamlit 1.67.0):**
- **SQLite:** 84 passed.
- **Local Postgres 16:** 82 passed, 2 skipped. Both skips are SQLite-only: WAL mode and the legacy-schema builder.

**Test files:**
- `tests/test_learning_integrity.py` (30): the evidence, review, experiment, status, frozen-score and deadline rules, including concurrency and retry cases.
- `tests/test_migration_legacy.py` (1): builds a database with the `70f5079` code from git history, migrates a **copy**, and checks rows, balances, statuses and repeatability.
- `tests/test_page_smoke.py` (37): headless `AppTest` renders of all 17 student and 17 Director pages, plus two click-through flows (Accept on Evidence Review; logging and the duplicate refusal on Evidence Ledger).

**Not done:**
- No browser test and no load test.
- Not run against Neon itself; Postgres was tested locally only.
- No performance re-measurement. The new pages add a few queries per render (e.g. per-assumption evidence lookups use the cached `list_evidence`).

## Migration, backup and rollback
1. **Before deploying:** Director → Backup & Restore → download a backup of the live database.
2. Deploy the branch. The first app load runs the additive migrations once per process (`init_db`).
3. **What changes for a live course:**
    - **New evidence follows the review rules:** strong claims wait for review, credits per item are lower than before, and contradicting evidence pays the same as supporting.
    - **Already-ended rounds are frozen** from current data the first time they're viewed (`source='backfill'`). If you want those frozen from a known state, view Round Scores for each ended round right after deploying.
4. **Rollback:** redeploy `main` (`70f5079`). The old code ignores the new columns and tables, so the database does **not** need restoring.
    - Behaviour after rollback: items logged under Stage 1 keep the credits they actually received. Old code would count "Withdrawn", "Duplicate" and "Practice" items as ordinary evidence.
    - For a clean rollback, restore the pre-deploy backup. That discards everything since deploy.
5. Never reset the database to apply this schema. `init_db` is idempotent, and `tests/test_migration_legacy.py` runs it twice.

## Known limitations / unresolved
- **Experiment-result writes:** evidence and credit are atomic in one transaction. The follow-on assumption-status refresh is a separate write; it is idempotent and is recomputed on the next evidence or result event if it is ever interrupted.
- **Legacy experiments:** those without numeric thresholds keep a manual outcome, with no override reason required.
- **Legacy results** have no `result_round`, so they never lock.
- **Round freezing** happens at advance; a round is not frozen at its deadline if the Director never advances.
- **Live preview:** the Round Scores sensitivity sliders affect only the open round; ended rounds show frozen scores.
- **Evidence editing:** there is no edit-in-place. Teams withdraw and re-log, and history is kept.
- **Review is not sampled:** every strength ≥ 6 or flagged item is queued. Bulk "Accept all unflagged" keeps it fast; time it in class.
- **Simulation origin** is reserved but nothing creates simulated evidence yet (deferred, Stage 4).
- **Single-process scope:** schedule and grading settings are still global across games (B8, Stage 2). The advance lock is in-process only.
- **Deprecation warnings:** Streamlit 1.67 warns about `use_container_width` and `st.components.v1.html` (the latter is past its stated removal date). These predate this branch; check before bumping Streamlit.

## Backlog (next)
- **Stage 2 — Claims as the thread:**
    - L5 interpretive strength (TBI four dimensions; reasons shown, not arithmetic)
    - L7 dependency links and At-risk propagation
    - L13 canvas dual meters and Claims map
    - L14 VP support from Claims
    - L24 iteration availability
    - L22 / B8 per-game settings
    - L23 / B15 first-attempt concept checks
- **Stage 3 — Assessment:**
    - L15 sampled review
    - L16 exceptions panel
    - L17 four-strand rubric with the decided **60/25/15 + ≤ 5% venture bonus**
    - L18 reflection tied to Claims
    - L21 cap and qualify mini-pivot, partner and lemonade rewards (B11/B17)
    - L25 schedule presets
    - L26 no-AI baseline check
- **Stage 4:** L10 means inventory and loss cap; L11 commitments and surprises; L12 interview record and practice persona; L19/L20 pitch citations and investment rationale.
- **Deferred:** simulated market, AI personas beyond scripted, file uploads, individual logins.

## Next recommended task
Stage 2, starting with **L22 / B8 per-game settings**. Schedule, grading and automation settings are global today, so two sections can't run different deadlines or weights. Then **L5 interpretive strength**, which replaces the category-only strength that Stage 1 still uses for new items.
