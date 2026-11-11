"""
views_student.py — Student/team-facing screens for Venture Foundry.

Every screen is written to be self-explanatory: a "How this page works" panel
sits at the top, and every input carries a hover-help (ⓘ) tooltip so a first-time
user can run the simulation without an instruction manual.
"""

import streamlit as st

import db
import content
import logic
import branding
import canvas_art

# A simple, recognizable AI badge (a colored dot + "AI") on every AI-logging control.
_AI_ICON = "🔵 AI"
_AI_LOG_LABEL = "🔵 AI · log use"


# --------------------------------------------------------------------------- #
# Shared guidance helpers
# --------------------------------------------------------------------------- #
def _guide(what, steps=None, terms=None, expanded=False):
    """Render a plain-language 'How this page works' panel with progressive disclosure:
    full help in early rounds, then it condenses, then it shrinks to a one-liner —
    heavy help early, lighter later once teams know the ropes."""
    cur = db.current_round()
    if cur >= 9:                       # experienced: a one-line reminder only
        st.caption("ℹ️ " + what.split(". ")[0].rstrip(".") + ".")
        return
    lighten = cur >= 5                 # mid-game: drop the step-by-step and glossary
    with st.expander("ℹ️ How this page works", expanded=expanded):
        st.markdown(what)
        if steps and not lighten:
            st.markdown("**What to do here**")
            st.markdown("\n".join(f"{i+1}. {s}" for i, s in enumerate(steps)))
        if terms and not lighten:
            st.markdown("**Key terms**")
            st.markdown("\n".join(f"- **{t}** — {d}" for t, d in terms))


def _why(tool):
    """A one-line 'why this matters' chip that ties the tool back to the goal."""
    text = content.why_matters(tool)
    if text:
        st.markdown(
            f"<div style='display:inline-block;background:rgba(13,148,136,.10);"
            f"border:1px solid rgba(13,148,136,.35);border-radius:14px;padding:3px 12px;"
            f"font-size:13px;margin:2px 0 8px;'>💡 <b>Why this matters:</b> {text}</div>",
            unsafe_allow_html=True)


def _exemplar_customer_profile():
    ex = content.EXEMPLAR_CUSTOMER_PROFILE
    with st.expander("📗 Worked example — a weak vs. a strong Customer Profile"):
        c1, c2 = st.columns(2)
        c1.markdown("**❌ Weak (vague wishes)**")
        for k, v in ex["weak"].items():
            c1.markdown(f"- **{k}:** {v}")
        c2.markdown("**✅ Strong (specific & checkable)**")
        for k, v in ex["strong"].items():
            c2.markdown(f"- **{k}:** {v}")
        st.caption(ex["note"])


def _exemplar_evidence():
    ex = content.EXEMPLAR_EVIDENCE
    with st.expander("📗 Worked example — weak vs. strong evidence (and what an LOI looks like)"):
        st.markdown(f"**❌ Weak:** {ex['weak']}")
        st.markdown(f"**✅ Strong:** {ex['strong']}")
        st.info(ex["loi"])
        st.caption(ex["note"])


def _exemplar_pivot():
    ex = content.EXEMPLAR_PIVOT
    with st.expander("📗 Worked example — an annotated, evidence-based pivot"):
        st.markdown(f"**Original assumption:** {ex['original']}")
        st.markdown(f"**Evidence that challenged it:** {ex['evidence']}")
        st.markdown(f"**Proposed change:** {ex['change']}")
        st.markdown(f"**New assumptions to test:** {ex['new_assumptions']}")
        for a in ex["annotations"]:
            st.markdown(a)


def _progress_ring(done, total, size=64):
    """An SVG donut showing round completion."""
    frac = (done / total) if total else 1.0
    r = size / 2 - 6
    circ = 2 * 3.14159 * r
    off = circ * (1 - frac)
    color = "#059669" if frac >= 1 else ("#4f46e5" if frac > 0 else "#94a3b8")
    cx = size / 2
    return (f"<svg width='{size}' height='{size}' viewBox='0 0 {size} {size}'>"
            f"<circle cx='{cx}' cy='{cx}' r='{r}' fill='none' stroke='#e5e7eb' stroke-width='8'/>"
            f"<circle cx='{cx}' cy='{cx}' r='{r}' fill='none' stroke='{color}' stroke-width='8' "
            f"stroke-linecap='round' stroke-dasharray='{circ:.1f}' stroke-dashoffset='{off:.1f}' "
            f"transform='rotate(-90 {cx} {cx})'/>"
            f"<text x='50%' y='50%' text-anchor='middle' dominant-baseline='central' "
            f"font-size='{int(size*0.26)}' font-weight='700' fill='{color}'>{done}/{total}</text>"
            "</svg>")


def _celebrate(key):
    """Fire a one-time celebration (balloons) per key, per session."""
    seen = st.session_state.setdefault("_celebrated", set())
    if key not in seen:
        seen.add(key)
        try:
            st.balloons()
        except Exception:
            pass


def _first_run_tour(team):
    """A dismissible 4-step welcome tour shown once to a new team."""
    if db.has_ack(team["id"], "tour_done") or st.session_state.get("tour_skipped"):
        return
    step = st.session_state.get("tour_step", 0)
    title, body = content.WELCOME_TOUR[step]
    with st.container(border=True):
        st.markdown(f"### {title}")
        st.markdown(body)
        st.caption(f"Step {step + 1} of {len(content.WELCOME_TOUR)}")
        cols = st.columns([1, 1, 1, 3])
        if step > 0 and cols[0].button("← Back", key="tour_back"):
            st.session_state["tour_step"] = step - 1
            st.rerun()
        if step < len(content.WELCOME_TOUR) - 1:
            if cols[1].button("Next →", type="primary", key="tour_next"):
                st.session_state["tour_step"] = step + 1
                st.rerun()
        else:
            if cols[1].button("Let's go! 🚀", type="primary", key="tour_done"):
                db.set_ack(team["id"], "tour_done")
                st.rerun()
        if cols[2].button("Skip", key="tour_skip"):
            st.session_state["tour_skipped"] = True
            db.set_ack(team["id"], "tour_done")
            st.rerun()


def _resource_bar(team):
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Capital", f"${team['capital']:,.0f}",
              help="Simulated cash. Spent on experiments and pivots. Runs out if you "
                   "over-invest, so test the cheapest way first.")
    c2.metric("Evidence Credits", f"{team['evidence_credits']:,.1f}",
              help="The simulation's main currency. You EARN credits by logging credible "
                   "evidence and SPEND them on experiments, specialists, and pivots.")
    c3.metric("Founder-hours", f"{team['founder_hours']:,.0f}",
              help="Your team's available time. Every experiment consumes hours as well "
                   "as money.")
    c4.metric("Venture Tokens", f"{team['venture_tokens']}",
              help="Used only in the Value Proposition Auction to reveal which idea you "
                   "back most confidently.")


def _refresh_team(team_id):
    return db.get_team(team_id)


def _pareto_time_chart(cats):
    """Pareto chart (sorted bars + cumulative % line) of time-by-activity."""
    data = [(l, h) for l, h in cats if h and h > 0]
    if not data:
        st.caption("No time to show yet — set an allocation.")
        return
    rows = sorted(data, key=lambda x: -x[1])
    total = sum(h for _, h in rows) or 1
    order, recs, cum = [], [], 0.0
    for l, h in rows:
        cum += h
        lab = l if len(l) <= 14 else l[:13] + "…"
        order.append(lab)
        recs.append({"Activity": l, "Label": lab, "Hours": h,
                     "Cumulative %": round(cum / total * 100)})
    # Same Pareto (bars + cumulative-% line, independent axes) as before, sent as a
    # Vega-Lite spec instead of building Altair objects on the server every rerun.
    x = {"field": "Label", "type": "nominal", "sort": order,
         "axis": {"labelAngle": 0, "title": None}}
    st.vega_lite_chart({
        "data": {"values": recs},
        "title": "Founder & team hours this round",
        "height": 280,
        "layer": [
            {"mark": {"type": "bar", "color": "#2b6cb0"},
             "encoding": {"x": x, "y": {"field": "Hours", "type": "quantitative",
                                        "title": "Hours / week"},
                          "tooltip": [{"field": "Activity"}, {"field": "Hours"}]}},
            {"mark": {"type": "line", "point": True, "color": "#f2a938"},
             "encoding": {"x": x, "y": {"field": "Cumulative %", "type": "quantitative",
                                        "title": "Cumulative %",
                                        "scale": {"domain": [0, 100]}},
                          "tooltip": [{"field": "Activity"}, {"field": "Cumulative %"}]}},
        ],
        "resolve": {"scale": {"y": "independent"}},
    }, use_container_width=True)


def _shade_row(label, done, must_update):
    """One shaded checklist row (green = done, amber = required-incomplete)."""
    if done:
        bg, border, icon = "#e7f4ea", "#34a853", "✅"
    else:
        bg, border, icon = "#fdf1d6", "#f5a623", "⬜"
    tag = " <span style='color:#b26a00;font-weight:600;'>· must complete this round</span>" \
        if (must_update and not done) else ""
    return ("<div style='background:%s;border-left:4px solid %s;padding:6px 10px;"
            "margin:4px 0;border-radius:4px;'>%s %s%s</div>" % (bg, border, icon, label, tag))


def _render_checklist(items):
    """Render a shaded checklist from [{label, done, must_update}] as one HTML block."""
    html = "".join(_shade_row(i["label"], i["done"], i.get("must_update", False)) for i in items)
    st.markdown(html, unsafe_allow_html=True)


def _page_requirements(page, team):
    """Shaded 'required this round' box for the requirements tied to this page."""
    rnd = db.current_round()
    cl = logic.round_checklist(team["id"], rnd)
    prog = [p for p in (cl["decisions"] + cl["questions"] + cl["carried"])
            if p.get("tool") == page and not p["done"]]
    if prog:
        st.markdown("**✅ Required on this page this round**")
        _render_checklist(prog)


def _committed_banner(team):
    """Shown on any editable page when the round is committed (frozen)."""
    st.warning("🔒 **This round is committed — your work is locked for scoring.** To make "
               "changes, click **↩️ Withdraw** in the sidebar. Remember to **Commit** again "
               "when you're done, or your changes won't be counted.")


def _round_gate(page, team):
    """Enforce round alignment on a tool page.

    Returns (editable: bool). Locked tools show a lock screen and stop; reference
    tools (introduced but not relevant this round, strict mode) become view-only.
    A committed round freezes ALL tools (view-only) until the team withdraws.
    Also shades this page's required deliverables when active.
    """
    rnd = db.current_round()
    state = logic.tool_state(page, rnd, team["id"])
    if state == "locked":
        wk = logic.page_unlock_round(page)
        st.warning(f"🔒 **Locked.** This tool is introduced in **Round {wk}**. "
                   f"You're in Round {rnd}. It will open when its concepts are taught.")
        st.stop()
    if logic.editing_locked(team["id"], rnd):
        _committed_banner(team)
        if state == "active":
            _page_requirements(page, team)
        return False
    editable = logic.tool_editable(page, rnd, team["id"])
    if state == "reference" and not editable:
        opens = logic.active_rounds_for_page(page)
        when = logic.rounds_phrase(opens) if opens else "a later round"
        st.info(f"👁️ **Reference only right now.** Under Strict round mode this tool is part of "
                f"**{when}**, so input is disabled here to keep everyone on the same page. Your "
                f"existing work is shown below and carries forward. (Your instructor can allow "
                f"edits any time by turning off Strict round mode.)")
    elif state == "active":
        _page_requirements(page, team)
    return editable


def _split_pick(value, options):
    """Recover a (dropdown-pick, note) pair from a stored 'pick — note' string."""
    value = value or ""
    pick, _, note = value.partition(" — ")
    if pick in options:
        return pick, note
    return options[0], value


def _ai_full_log(team, area, key, existing=None):
    """Full AI-use audit: prompt, output, HOW it was used, and a dropdown AUDIT.

    When `existing` (a log dict) is given, every field is pre-filled and editing SAVES
    changes to that log; otherwise it creates a new one. Both prompt and output are
    required. Not placed inside an st.form by callers."""
    if logic.editing_locked(team["id"]):
        _committed_banner(team)
        return
    e = existing or {}

    def _idx(opts, val, default=0):
        return opts.index(val) if val in opts else default

    assums = db.list_assumptions(team["id"])
    with st.form(f"ai_full_{key}", clear_on_submit=(existing is None)):
        if existing is not None:
            tool_area = st.text_input("Where did you use AI?", value=e.get("tool_area", ""),
                                      key=f"af_area_{key}")
        elif area:
            tool_area = area
            st.caption(f"Logging AI use for: **{tool_area}** · Round {db.current_round()}")
        else:
            tool_area = st.selectbox("Where did you use AI?", content.AI_TOOL_AREAS,
                                     key=f"af_area_{key}")
        mc1, mc2 = st.columns(2)
        ai_model = mc1.selectbox("Which AI did you use?", content.AI_MODELS,
                                 index=_idx(content.AI_MODELS, e.get("ai_model")),
                                 key=f"af_model_{key}",
                                 help="Recorded with the date & time so your log shows exactly "
                                      "which model produced this — the standard AI-use citation.")
        use_type = mc2.selectbox("How did you use the AI?", content.AI_USE_TYPES,
                                 index=_idx(content.AI_USE_TYPES, e.get("use_type")),
                                 key=f"af_use_{key}",
                                 help="An indication of the kind of help — this is recorded.")
        prompt = st.text_area("Your prompt (required)", value=e.get("prompt", ""),
                              key=f"af_p_{key}",
                              placeholder="Paste or paraphrase what you asked the AI.")
        output = st.text_area("The AI's response / key claim (required)",
                              value=e.get("ai_output", ""), key=f"af_o_{key}",
                              placeholder=content.AI_CLAIM_EXAMPLE,
                              help="What the AI produced. Treat it as opinion until verified.")
        st.markdown("**Audit** — pick from the dropdowns (fast):")
        pa, na = _split_pick(e.get("audit_a"), content.AI_AUDIT_ASSUMPTIONS)
        pu, nu = _split_pick(e.get("audit_u"), content.AI_AUDIT_UNSUPPORTED)
        pv, nv = _split_pick(e.get("verify_plan") or e.get("audit_i"), content.AI_VERIFY_METHODS)
        a1, a2 = st.columns(2)
        a_assum = a1.selectbox("Hidden assumptions?", content.AI_AUDIT_ASSUMPTIONS,
                               index=_idx(content.AI_AUDIT_ASSUMPTIONS, pa) if existing else 0,
                               key=f"af_a_{key}", help="Did you find what must be true for it to hold?")
        a_unsup = a2.selectbox("Unsupported claims?", content.AI_AUDIT_UNSUPPORTED,
                               index=_idx(content.AI_AUDIT_UNSUPPORTED, pu) if existing else 0,
                               key=f"af_u_{key}", help="Confident statements with no evidence.")
        a3, a4 = st.columns(2)
        a_data = a3.selectbox("Sources / data?", content.AI_DATA_SOURCES,
                              index=_idx(content.AI_DATA_SOURCES, e.get("data_source")),
                              key=f"af_d_{key}", help="AI often invents sources — pick honestly.")
        a_verify = a4.selectbox("How will you verify?", content.AI_VERIFY_METHODS,
                                index=_idx(content.AI_VERIFY_METHODS, pv) if existing else 0,
                                key=f"af_v_{key}", help="A real-world check — not the AI itself.")
        status = st.selectbox("Status", content.AI_STATUS_OPTIONS,
                              index=_idx(content.AI_STATUS_OPTIONS, e.get("status")),
                              key=f"af_s_{key}",
                              help="Unverified until a real test settles it. Verifying is what "
                                   "the round score rewards.")
        link_id = None
        if assums:
            opts = [None] + [a["id"] for a in assums]
            link_id = st.selectbox(
                "Link to an assumption to auto-verify (optional)", opts,
                index=_idx(opts, e.get("assumption_id")), key=f"af_link_{key}",
                format_func=lambda i: "—" if i is None
                else next((a["text"] for a in assums if a["id"] == i), "—"),
                help="When the linked assumption tests Supported/Refuted, this log flips to "
                     "Verified/Rejected automatically.")
        notes = {}
        with st.expander("Add written notes (optional)", expanded=bool(na or nu or nv or e.get("audit_t"))):
            notes["a"] = st.text_area("Assumptions — details", value=na, key=f"afn_a_{key}")
            notes["u"] = st.text_area("Unsupported claims — details", value=nu, key=f"afn_u_{key}")
            notes["i"] = st.text_area("Verification plan — details", value=nv, key=f"afn_i_{key}")
            notes["t"] = st.text_area("How you'll translate it into evidence",
                                      value=e.get("audit_t", ""), key=f"afn_t_{key}")

        def _join(pick, note):
            note = (note or "").strip()
            return f"{pick} — {note}" if note else pick

        label = "Save changes" if existing is not None else "Log AI use"
        if st.form_submit_button(label, type="primary"):
            if not prompt.strip() or not output.strip():
                st.error("Both the **prompt** and the **AI response** are required.")
            else:
                fields = {
                    "tool_area": tool_area, "use_type": use_type, "ai_model": ai_model,
                    "prompt": prompt, "ai_output": output,
                    "audit_a": _join(a_assum, notes["a"]),
                    "audit_u": _join(a_unsup, notes["u"]),
                    "audit_d": a_data, "data_source": a_data,
                    "audit_i": _join(a_verify, notes["i"]), "verify_plan": a_verify,
                    "audit_t": notes["t"], "assumption_id": link_id, "status": status,
                }
                if existing is not None:
                    db.update_ai_log(existing["id"], **fields)
                    st.session_state.pop("ai_edit_id", None)
                    st.success("AI log updated.")
                else:
                    db.add_ai_log(team["id"], {"round": db.current_round(), **fields})
                    st.success("AI use logged with its audit. It auto-verifies if you linked an "
                               "assumption; otherwise update its status once you've checked it.")
                st.rerun()


def _ai_ack_popover(team, area, key, label=_AI_ICON):
    """The (AI) button beside a field — opens the full dropdown-driven audit in a popover.
    Must NOT be placed inside an st.form."""
    if team is None or logic.editing_locked(team["id"]):
        return
    with st.popover(label, help="Log AI use here — quick dropdown audit."):
        _ai_full_log(team, area, key)


def _ai_check_notice(team=None, tool_area=None):
    """A light in-context reminder. Logging happens via the (AI) buttons next to the
    inputs, so this stays out of the way."""
    if team is None:
        return
    unv = logic.ai_unverified_count(team["id"])
    cols = st.columns([6, 1])
    tip = f"Used AI on this page? Tap the **{_AI_ICON}** button next to a field to log & audit it."
    if unv:
        tip += f"  ·  ⏳ {unv} to verify"
    cols[0].caption(tip)
    with cols[1]:
        _ai_ack_popover(team, tool_area or "Other", f"ctx_{tool_area or 'x'}", label=_AI_LOG_LABEL)


def _mini_pivot_section(team):
    """Lightweight, self-approved course-correction — available every round so that
    changing your mind based on evidence is normalised early, not a late-game move."""
    cur = db.current_round()
    existing = [p for p in db.list_pivots(team["id"]) if (p.get("kind") or "formal") == "mini"]
    with st.expander(f"🔄 Changed your mind? Log a course correction (mini-pivot) · "
                     f"{len(existing)} so far"):
        st.caption("Good founders change direction when the evidence says so — the earlier and "
                   "cheaper, the better. A mini-pivot is a quick, self-approved note (no committee "
                   f"needed) and earns +{logic.MINI_PIVOT_CREDIT} Evidence Credits for the learning. "
                   "The formal Pivot Petition (investment committee) unlocks later for bigger changes.")
        if logic.editing_locked(team["id"]):
            _committed_banner(team)
        else:
            _ai_ack_popover(team, "Course correction (mini-pivot)", "minipivot_ai",
                            label=_AI_LOG_LABEL)
            with st.form("mini_pivot_form", clear_on_submit=True):
                original = st.text_input(
                    "What did you believe that turned out wrong?",
                    placeholder="We assumed busy parents would pay for weekly meal kits.")
                evidence = st.text_input(
                    "What evidence changed your mind?",
                    placeholder="4 of 5 said they'd rather buy ready-made single meals.")
                change = st.text_input(
                    "What will you change?",
                    placeholder="Switch the offer from weekly kits to grab-and-go single meals.")
                mptype = st.selectbox(
                    "Type of pivot (Lean Startup)", content.PIVOT_TYPE_NAMES,
                    index=content.PIVOT_TYPE_NAMES.index("Not sure yet"),
                    format_func=lambda n: f"{n} — {content.PIVOT_TYPE_BY_NAME[n]}",
                    help="Naming what kind of change this is keeps the correction deliberate.")
                if st.form_submit_button("Log course correction"):
                    if not (original.strip() and change.strip()):
                        st.error("Tell us what was wrong and what you'll change.")
                    else:
                        reward = logic.log_mini_pivot(team["id"], original, evidence, change, mptype)
                        st.success(f"Course correction logged. +{reward} Evidence Credits for "
                                   "learning from evidence.")
                        st.rerun()
        for p in existing:
            st.markdown(f"- **R{p.get('round','?')}:** {p['original_assum']} → "
                        f"*{p['proposed_change']}*"
                        + (f"  (evidence: {p['challenge_evid']})" if p['challenge_evid'] else ""))


def _commitment_panel(team, cur, all_items, done_n, complete):
    """Deadline + commit/decommit controls for the current round."""
    st.divider()
    st.write("### 🔒 Commit your round")
    state = logic.commitment_state(team["id"], cur)
    ds = state["deadline"]

    # When are decisions due?
    if ds["set"]:
        if ds["passed"]:
            st.error(f"⏰ **Deadline passed** — decisions were due {ds['due_text']}. "
                     "This round is locked; your last committed work is what counts.")
        else:
            st.info(f"⏰ **Decisions due {ds['due_text']}** ({ds['remaining']}). "
                    "Commit when you're ready — you can withdraw and keep editing any time "
                    "before the deadline.")
    else:
        st.warning("🗓️ **No deadline is set for this round.** Your instructor hasn't scheduled "
                   "an advance time, so decisions stay open until they move the simulation "
                   "forward. You can still commit to signal you're done.")

    # End-of-round nudges: journal + any unverified AI.
    _unv = logic.ai_unverified_count(team["id"])
    _journaled = {r["student_name"] for r in db.list_reflections(team["id"]) if r["round"] == cur}
    _nudges = []
    if not _journaled:
        _nudges.append("no **Decision Journal** entries yet this round")
    if _unv:
        _nudges.append(f"**{_unv} AI use(s) unverified**")
    if _nudges:
        st.caption("Before you commit: " + "; ".join(_nudges) + ".")

    # What's still open (must be decided) vs done.
    open_items = [p for p in all_items if not p["done"]]
    if open_items:
        with st.expander(f"⚠️ {len(open_items)} decision(s) still open — you can commit now "
                         "and finish them, or complete them first", expanded=not complete):
            for p in open_items:
                st.markdown(f"- {p['label']}  ·  *{p.get('tool','')}*")
    else:
        st.success("All of this round's decisions are complete. ✅")

    # Commit / decommit controls.
    if state["committed"]:
        st.success(f"✅ **Committed** for Round {cur}"
                   + (f" · {state['committed_at']}" if state.get("committed_at") else ""))
        if state["locked"]:
            st.caption("The deadline has passed, so this commitment is final.")
        else:
            if st.button("↩️ Withdraw commitment (keep editing)", key=f"decommit_{cur}",
                         help="Unlock your work so you can change it before the deadline."):
                ok, msg = logic.decommit_round(team["id"], cur)
                (st.success if ok else st.error)(msg)
                st.rerun()
    else:
        if state["locked"]:
            st.error("The deadline passed before you committed. Your current work will be "
                     "scored as-is — ask your instructor if you need an extension.")
        else:
            st.caption("Committing locks in this round's work for scoring. You keep full "
                       "control: withdraw any time before the deadline to make changes.")
            label = ("✅ Commit this round" if complete
                     else f"✅ Commit this round now ({done_n}/{len(all_items)} done)")
            if st.button(label, type="primary", key=f"commit_{cur}",
                         help="Lock in your decisions for this round."):
                ok, msg = logic.commit_round(team["id"], cur)
                if ok:
                    st.success("🎉 " + msg)
                    _celebrate(f"commit_{team['id']}_{cur}")
                else:
                    st.error(msg)
                st.rerun()


# --------------------------------------------------------------------------- #
# Round Briefing — the week's learning objectives and simulation task
# --------------------------------------------------------------------------- #
def round_briefing(team):
    cur = db.current_round()
    topics = logic.topics_for_round(cur)
    titles = " + ".join(t["title"] for t in topics) if topics else ""
    st.subheader(f"📅 Round Briefing — Round {cur}" + (f": {titles}" if titles else ""))

    _first_run_tour(team)

    # ---- Do this next: one clear primary action + a progress ring -----------
    nxt = logic.next_action(team["id"], cur)
    done_n, total_n = logic.round_progress_counts(team["id"], cur)
    rc1, rc2 = st.columns([4, 1])
    with rc1:
        if nxt:
            where = f" → **{nxt['tool']}**" if nxt.get("tool") else ""
            tag = "⏪ Finish first: " if nxt.get("carried") else "👉 Your next step: "
            st.markdown(
                f"<div style='background:rgba(79,70,229,.08);border:1px solid rgba(79,70,229,.35);"
                f"border-radius:8px;padding:10px 14px;font-size:16px;'>{tag}"
                f"<b>{nxt['label']}</b>{where}</div>", unsafe_allow_html=True)
            st.caption("Do this next — then come back here for the following step.")
        else:
            st.success("🎉 You're all set for this round — everything's complete. Commit below "
                       "when you're ready.")
            _celebrate(f"roundcomplete_{team['id']}_{cur}")
    with rc2:
        st.markdown(_progress_ring(done_n, total_n, 74), unsafe_allow_html=True)

    # ---- Narrative arc: chapter banner + the investor's voice ---------------
    _pidx, _pname, _pemoji, _ptheme = logic.story_phase(cur)
    inv = content.INVESTOR
    st.markdown(
        f"<div style='border-left:4px solid #4f46e5;padding:8px 14px;margin:2px 0 10px;"
        f"background:rgba(79,70,229,.06);border-radius:6px;'>"
        f"<b>{_pemoji} Chapter {_pidx+1}: {_pname}</b> — {_ptheme}</div>",
        unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown(f"💬 **{inv['name']}**, {inv['title']}:")
        st.markdown(f"> _{logic.investor_line(team['id'])}_")

    _guide(
        "The simulation adds complexity round by round. In the first class session your "
        "instructor introduces new concepts; the simulation round is where you apply them. "
        "A single round may cover several pieces of material (your instructor decides how the "
        "curriculum is packed into the number of rounds). Start here every round: it lists the "
        "learning objectives, what's new, the tasks, and which tools to use. You'll also use "
        "generative AI — remember to verify what it produces (see the AI reminder below).",
        terms=[
            ("Learning objectives", "What you should be able to DO by the end of this round."),
            ("Concepts introduced", "New ideas taught in class this round."),
            ("This round's tasks", "The specific simulation actions to complete now."),
        ],
    )
    if not topics:
        st.info("No material is assigned to this round yet — check with your instructor.")
        return

    for i, tp in enumerate(topics):
        if i:
            st.divider()
        st.write(f"### 🎓 {tp['title']}")
        st.caption(f"In class: {tp['class_focus']}")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Learning objectives**")
            for o in tp["objectives"]:
                st.markdown(f"- {o}")
        with c2:
            st.markdown("**Concepts introduced**")
            for c in tp["concepts"]:
                st.markdown(f"- {c}")
        st.success(f"**🎯 Task:** {tp['sim_task']}  ·  **Go to:** *{tp['tool']}*")

    # ---- Explore this round's concepts --------------------------------------
    concepts = logic.round_concepts(cur)
    if concepts:
        with st.expander("📚 Explore this round's concepts (definitions + prompts)"):
            for c in concepts:
                defn, prompt = content.concept_help(c)
                st.markdown(f"**{c}** — {defn}")
                st.caption(f"➡️ {prompt}")
            st.caption("Answer these on the **Concept Check** page to cover each concept.")

    # ---- Completion checklist (shaded) --------------------------------------
    st.divider()
    cl = logic.round_checklist(team["id"], cur)
    all_items = cl["decisions"] + cl["questions"] + cl["carried"]
    done_n = sum(1 for p in all_items if p["done"])
    complete = done_n == len(all_items)
    st.write(f"### ✅ To finish Round {cur} — {done_n}/{len(all_items)} complete")
    if complete:
        st.success("Everything for this round is complete — decisions made and concepts covered. 🎉")
    else:
        st.caption("Amber items must be completed this round. Green items are done. "
                   "Every concept is covered either by a decision or by answering its question.")

    st.markdown("**Decisions to make (actions in the tools)**")
    _render_checklist(cl["decisions"])
    _concept_questions = [c for c in cl["questions"] if c.get("needs_question", True)]
    if _concept_questions:
        st.markdown("**Concepts to answer (short written answers on the Concept Check page)**")
        _render_checklist(_concept_questions)
    else:
        st.caption("✅ Every concept this round is covered by your decisions — nothing to write "
                   "on the Concept Check page.")
    if cl["carried"]:
        st.markdown("**⏪ Carried over from earlier rounds — finish these now**")
        _render_checklist([{**c, "label": f"(R{c['round']}) {c['label']}"} for c in cl["carried"]])

    # ---- Productive failure: log a course correction any round --------------
    _mini_pivot_section(team)

    # ---- Decision deadline & commitment -------------------------------------
    _commitment_panel(team, cur, all_items, done_n, complete)

    # ---- What must change vs. what can remain -------------------------------
    tool_pages = ["Founder & Opportunity", "Canvases", "VP Auction", "Assumption Map",
                  "Experiment Marketplace", "Evidence Ledger", "Market Events",
                  "Pivot Petition"]
    reference = [p for p in tool_pages if logic.tool_state(p, cur, team["id"]) == "reference"]
    locked = [p for p in tool_pages if logic.tool_state(p, cur, team["id"]) == "locked"]
    must_change = sorted({p["tool"] for p in all_items if p.get("must_update") and not p["done"]})
    cc1, cc2 = st.columns(2)
    with cc1:
        st.markdown("**✍️ Must change this round**")
        if must_change:
            for t in must_change:
                st.markdown(f"- {t}")
        else:
            st.caption("Nothing outstanding — you're up to date.")
    with cc2:
        st.markdown("**📌 Can remain (carried forward)**")
        if reference:
            for t in reference:
                st.markdown(f"- {t} — no change needed unless new evidence says so")
        else:
            st.caption("—")
    if locked:
        st.caption("🔒 Not yet available: " + ", ".join(locked))

    # What unlocks this round (excluding base tools already available)
    newly = [p for p in logic.newly_unlocked(cur) if p not in content.BASE_TOOLS]
    if newly:
        st.info("🔓 **New this round:** " + ", ".join(newly))

    st.divider()
    st.markdown("**🤖 Generative AI this round**")
    st.markdown(content.AI_PROTOCOL_SUMMARY)

    with st.expander(f"🗺️ Full {logic.total_rounds()}-round map — what opens each round"):
        st.caption("The whole journey at a glance. **🔓 marks the new tools that unlock** each "
                   "round — your current round is highlighted so you can see what just opened and "
                   "what's coming next.")
        for r in logic.round_map():
            here = r["round"] == cur
            head = f"{'👉 ' if here else ''}**Round {r['round']}**"
            if here:
                head += " · you are here"
            st.markdown(head)
            if r["titles"]:
                st.markdown("  · Covers: " + " + ".join(r["titles"]))
            if r["new_tools"]:
                st.markdown("  · 🔓 New tools: **" + ", ".join(r["new_tools"]) + "**")
            if r["concepts"]:
                st.caption("  Concepts: " + ", ".join(r["concepts"]))
            st.markdown("")


# --------------------------------------------------------------------------- #
# Inbox — in-app feedback "email" from the Director / Auto-Director
# --------------------------------------------------------------------------- #
def inbox(team):
    st.subheader("📬 Inbox")
    _guide(
        "After each round you receive a venture review here — an in-app email from the Foundry "
        "summarizing your predicted performance, what's working, where to focus, your untested "
        "risks, and a recommended next step. New messages are marked unread; open one to read "
        "the full review.",
        terms=[
            ("Venture review", "Your per-round feedback email."),
            ("Unread", "A message you haven't opened yet (shown with 🔵)."),
        ],
    )
    msgs = db.list_messages(team["id"])
    top = st.columns([3, 1])
    top[0].caption(f"{len(msgs)} message(s) · {db.unread_count(team['id'])} unread")
    if msgs and top[1].button("Mark all read"):
        db.mark_all_read(team["id"])
        st.rerun()

    if not msgs:
        st.info("No messages yet. Your first venture review arrives after this round is scored.")
        return

    for m in msgs:
        dot = "🔵 " if not m["read"] else ""
        with st.expander(f"{dot}{m['subject']} · {m['created_at']}"):
            st.caption(f"From: {m['sender']}" + (f" · Round {m['round']}" if m["round"] else ""))
            st.text(m["body"])
            cols = st.columns(2)
            if not m["read"] and cols[0].button("Mark read", key=f"msgread_{m['id']}"):
                db.mark_message_read(m["id"])
                st.rerun()
            if cols[1].button("Delete", key=f"msgdel_{m['id']}"):
                db.delete_message(m["id"])
                st.rerun()


# --------------------------------------------------------------------------- #
# Concept Check — cover every concept with a short answer (question coverage)
# --------------------------------------------------------------------------- #
def concept_check(team):
    st.subheader("🧠 Concept Check")
    _why("Concept Check")
    _guide(
        "Every concept introduced this round must be covered — but not all the same way. Most "
        "are covered automatically by the **decisions you make in the tools** (e.g. building a "
        "canvas covers 'customer jobs, pains, gains'). Concepts that need judgment get a quick "
        "**true/false understanding check** plus a one-sentence application to your venture. An "
        "answer only counts when it's **complete, meaningful, uses the course concepts, is "
        "relevant to your venture, and is evidence-based** — the live checklist shows you what's "
        "still missing.",
        terms=[
            ("Covered by a decision", "The concept is proven by doing the matching task — no "
             "writing needed."),
            ("Understanding check", "A short true/false that tests you get the idea."),
            ("Applied answer", "A sentence connecting the concept to your venture, quality-checked."),
        ],
    )
    _ai_check_notice(team, tool_area="Other")
    cur = db.current_round()
    prog = logic.concept_progress(team["id"], cur)
    if not prog:
        st.info("No concepts assigned to this round yet.")
        return
    answers = db.get_round_answers(team["id"], cur)
    locked = logic.editing_locked(team["id"], cur)

    decisions = [c for c in prog if not c.get("needs_question", True)]
    questions = [c for c in prog if c.get("needs_question", True)]

    done_n = sum(1 for p in prog if p["done"])
    st.write(f"### Coverage — {done_n}/{len(prog)} concepts this round")

    # Concepts covered by decisions — status only, no writing.
    if decisions:
        st.markdown("**✅ Covered by your decisions (no answer needed)**")
        for c in decisions:
            icon = "✅" if c["done"] else "⬜"
            where = f" — {c['action']} · *{c['tool']}*" if c.get("action") else ""
            st.markdown(f"{icon} **{c['concept']}**{'' if c['done'] else where}")
        st.divider()

    # Concepts that genuinely need a quick understanding check + applied answer.
    if not questions:
        st.success("Nothing to write this round — every concept is covered by a decision. 🎉")
    else:
        st.markdown("**🧩 Quick understanding check** — a true/false on the idea, then apply it "
                    "to your venture in a sentence.")
        for c in questions:
            _render_concept_question(team, cur, c["concept"], locked)

    # Concepts carried over from earlier rounds (same check applies).
    carried = [c for c in logic.outstanding_prior(team["id"], cur) if c.get("kind") == "question"]
    if carried:
        st.divider()
        st.markdown("**⏪ Concepts still open from earlier rounds — finish these too**")
        for c in carried:
            _render_concept_question(team, c["round"], c["concept"], locked, carried=True)

    _spaced_review(team, cur, locked)


def _autosave_review(team_id, rnd, concept, key):
    import json as _json
    v = st.session_state.get(key)
    pick = None if v is None else (v == "True")
    db.set_round_answer(team_id, rnd, concept, _json.dumps({"quiz": [pick], "text": ""}))


def _spaced_review(team, cur, locked):
    """Re-surface 1–2 earlier concept true/false checks — retrieval practice that
    moves prior concepts into durable memory. Low-stakes (doesn't gate the round)."""
    concepts = logic.spaced_review_concepts(cur, 2)
    if not concepts:
        return
    st.divider()
    st.markdown("### 🔁 Spaced review — from earlier rounds")
    st.caption("A quick memory check on concepts you've already covered. Recycling them keeps "
               "them fresh — this is low-stakes and doesn't affect this round's completion.")
    for c in concepts:
        quiz = content.CONCEPT_QUIZ.get(c, [])
        if not quiz:
            continue
        stmt, truth = quiz[0]
        stt = logic.concept_answer_status(team["id"], cur, c)
        prev = (stt["quiz"] or [None])[0]
        key = f"sr_{cur}_{c}"
        with st.container(border=True):
            st.markdown(f"**{c}**")
            defn, _ = content.concept_help(c)
            st.caption(f"📖 {defn}")
            if locked:
                st.write("Committed — review disabled.")
                continue
            choice = st.radio(f"True or false? *{stmt}*", ["True", "False"],
                              index=(None if prev is None else (0 if prev else 1)),
                              key=key, horizontal=True,
                              on_change=_autosave_review, args=(team["id"], cur, c, key))
            if choice is not None:
                if (choice == "True") == bool(truth):
                    st.success("✅ Correct — still got it.")
                else:
                    st.error("❌ Not quite — worth a quick re-read of this concept.")


def _autosave_concept(team_id, rnd, concept, tkey, qkeys):
    """Autosave a concept answer (text + true/false picks) as the student edits."""
    import json as _json
    text = st.session_state.get(tkey, "")
    picks = []
    for qk in qkeys:
        v = st.session_state.get(qk)
        picks.append(None if v is None else (v == "True"))
    db.set_round_answer(team_id, rnd, concept, _json.dumps({"quiz": picks, "text": text}))


def _render_concept_question(team, rnd, concept, locked, carried=False):
    """One reasoning concept: a true/false understanding check + a quality-checked
    applied answer. Autosaves as you type — no Save button needed."""
    stt = logic.concept_answer_status(team["id"], rnd, concept)
    defn, prompt = content.concept_help(concept)
    quiz = content.CONCEPT_QUIZ.get(concept, [])
    tag = f"(R{rnd}) " if carried else ""
    with st.container(border=True):
        st.markdown(f"{'✅' if stt['done'] else '⬜'} **{tag}{concept}**")
        st.caption(f"📖 {defn}")
        if locked:
            _committed_banner(team)
            st.write(stt["text"] or "_(no answer)_")
            return

        key = f"cq_{rnd}_{concept}"
        tkey = f"{key}_text"
        qkeys = [f"{key}_q{i}" for i in range(len(quiz))]
        _args = (team["id"], rnd, concept, tkey, qkeys)
        # True/false understanding check (autosaves on change).
        picks = []
        stored_quiz = stt["quiz"] or []
        for i, (stmt, _truth) in enumerate(quiz):
            prev = stored_quiz[i] if i < len(stored_quiz) else None
            choice = st.radio(f"True or false? *{stmt}*", ["True", "False"],
                              index=(None if prev is None else (0 if prev else 1)),
                              key=qkeys[i], horizontal=True,
                              on_change=_autosave_concept, args=_args)
            picks.append(None if choice is None else (choice == "True"))
        # Applied answer (with a per-field AI-acknowledge button beside it).
        ta, tb = st.columns([12, 1])
        with ta:
            text = st.text_area(f"➡️ {prompt}", value=stt["text"], key=tkey,
                                on_change=_autosave_concept, args=_args,
                                help="One or two sentences, using the round's concepts and "
                                     "grounded in your venture's evidence. Saves automatically.")
        with tb:
            st.write("")
            _ai_ack_popover(team, f"Concept check: {concept}", f"{key}_ai")
        # Live quality feedback.
        q = logic.answer_quality(text, concept, team["id"])
        _labels = {"complete": "complete", "meaningful": "means something",
                   "uses_concepts": "uses course concepts", "relevant": "relevant to your venture",
                   "evidence_based": "evidence-based"}
        st.caption("💾 Autosaves as you type · Answer strength: " + "  ".join(
            f"{'✅' if q['checks'][k] else '⬜'} {_labels[k]}" for k in
            ["complete", "meaningful", "uses_concepts", "relevant", "evidence_based"]))
        quiz_ok = logic.concept_quiz_correct(concept, picks) if quiz else True
        quiz_answered = (not quiz) or all(p is not None for p in picks)
        grade = logic.answer_grade(text, concept, team["id"])
        # Persistent, graded status so it's always clear where the answer stands.
        if not quiz_answered:
            st.info("⬜ Choose **True or False** above to finish this one.")
        elif not quiz_ok:
            st.error("⬜ The **true/false** isn't right yet — re-read the statement and try again.")
        else:
            _fn = {"blank": st.info, "incomplete": st.info, "not_meaningful": st.warning,
                   "developing": st.warning, "acceptable": st.success, "strong": st.success}
            _fn.get(grade["level"], st.warning)(f"{grade['icon']} {grade['headline']}")
            if grade["level"] in ("acceptable", "strong"):
                st.caption("✅ Covered." if grade["level"] == "acceptable"
                           else "🌟 Covered — top marks.")


# --------------------------------------------------------------------------- #
# Founder Skills — what the team has, and training it up
# --------------------------------------------------------------------------- #
def founder_skills(team):
    st.subheader("🛠️ Founder & Team")
    _why("Founder & Team")
    _guide(
        "Your founders can't be great at everything. Each round the founder has a fixed amount "
        "of time — a long work week — to split between RUNNING the business (experiments, "
        "canvases), TRAINING skills, and MANAGING any hires. Founders work up to 80 hours, but "
        "productivity drops past 40, and unused time is LOST — it does not carry over. When a "
        "skill the venture needs is weak, HIRE a specialist (costs money, recruiting time, and "
        "ongoing salary + management time). And founders keep LEARNING BY DOING: finishing a "
        "round's work grows the skills that round leaned on.",
        terms=[
            ("Weekly hours", "Founder time this round; resets each round (no carryover)."),
            ("Productivity", "Hours up to 40 are full value; each hour past 40 counts for less."),
            ("Training", "Spend founder-hours to raise a skill; you can undo it for a refund."),
            ("Hiring", "Money + recruiting time upfront; salary + management time each round."),
            ("Learning by doing", "Completing rounds grows the skills that round used."),
            ("Effective skill", "Founder level + hired boost — what actually counts (cap 5)."),
        ],
    )
    team = logic.sync_round_hours(_refresh_team(team["id"]))
    cur = db.current_round()
    locked = logic.editing_locked(team["id"], cur)
    if locked:
        _committed_banner(team)
    admin = logic.admin_hours(team)
    mgmt = int(logic.management_hours(team["id"]))
    bbudget = logic.build_budget(team)
    effort = logic.current_effort(team)
    color, emoji, label = logic.effort_color(effort)

    # ---- Founder effort dashboard (dynamic, colour-coded) -------------------
    st.write("### ⏱️ Founder effort this week")
    st.caption("You don't set effort directly — it's the **sum of the time you assign to tasks** "
               "(admin + managing + business development + training + hiring). Admin grows as the "
               "venture gets more complex, and managing hires costs time too. Keep total effort "
               "under 80 hours — green ≤40 (sustainable), yellow ≤60 (stretched), red ≤80 (overwork).")
    bar = min(1.0, effort / content.MAX_WEEKLY_HOURS)
    st.markdown(
        f"<div style='font-size:15px;margin:2px 0'>{emoji} <b>Founder effort: "
        f"<span style='color:{color}'>{effort} / 80 hrs</span></b> — {label}</div>"
        f"<div style='background:#e9edf5;border-radius:6px;height:14px;overflow:hidden'>"
        f"<div style='width:{bar*100:.0f}%;background:{color};height:14px'></div></div>",
        unsafe_allow_html=True)
    st.caption(f"Fixed this round: Admin **{admin}h** · Managing hires **{mgmt}h**  →  "
               f"you're assigning **{bbudget}h** to business development and "
               f"**{int(team.get('spent_train') or 0)}h** to training so far.")

    # ---- Assign time: Business development ----------------------------------
    st.divider()
    st.write("### 🧭 Assign the founder's time")
    st.caption("Set how many hours go to business development (customer discovery & experiments). "
               "Training is assigned per skill below. Everything counts toward the 80-hour effort cap.")
    maxb = logic.max_build(team)
    bc1, bc2 = st.columns([3, 1])
    new_b = bc1.slider("Business development hours (for experiments this round)",
                       int(team.get("spent_build") or 0), max(int(team.get("spent_build") or 0), maxb),
                       bbudget, 1, disabled=locked,
                       help="Hours reserved for the Experiment Marketplace this round. Can't go "
                            "below what you've already spent, or push effort over 80h.")
    proj = admin + mgmt + new_b + int(team.get("spent_train") or 0) + int(team.get("spent_other") or 0)
    pc, pe, pl = logic.effort_color(proj)
    bc1.markdown(f"<span style='color:{pc}'>{pe} Projected effort with this budget: "
                 f"<b>{proj}/80h</b> ({pl})</span>", unsafe_allow_html=True)
    if bc2.button("Save budget", type="primary" if new_b != bbudget else "secondary",
                  disabled=locked):
        logic.set_build_budget(team["id"], new_b)
        st.success("Business-dev budget saved. (Round-1 deliverable ✓)")
        st.rerun()
    st.caption(f"Business-dev hours remaining to spend on experiments: **{int(team['founder_hours'])}h**.")
    salary = sum((h["per_round"] or 0) for h in db.list_hires(team["id"]))
    if salary:
        st.caption(f"💸 Specialist salaries: **${salary:,.0f}/round** (from capital).")

    # ---- Pareto of the founder & team week ----------------------------------
    _pareto_time_chart(logic.hours_breakdown(team))
    st.caption("Where the founder & team's committed hours go this round — it updates as you set "
               "the budget, train, or hire. Unused business-dev hours are lost when the round advances.")

    skills = db.get_team_skills(team["id"])
    boosts = logic.hire_boost(team["id"])
    needs = set(logic.skills_needed_this_round(cur))

    if needs:
        need_names = ", ".join(content.FOUNDER_SKILL_BY_KEY[k]["name"] for k in needs)
        st.info(f"🎯 **This round leans on:** {need_names}. If your effective level is low there, "
                "consider training or hiring.")

    st.write("### Assign training time to skills")
    room = logic.effort_headroom(team)
    st.caption(f"Assign hours to train a skill — this counts toward the 80-hour effort cap "
               f"(**{room}h of effort left** this week). The default is a full level, but you can "
               "assign less: partial hours are **banked** and finish the level in a later round. "
               "Early levels are cheaper; higher levels cost more. Founders also learn by doing.")
    for s in content.FOUNDER_SKILLS:
        base = skills.get(s["key"], 0)
        boost = boosts.get(s["key"], 0)
        efflv = min(content.HIRE_SKILL_CAP, base + boost)
        needed = s["key"] in needs
        gap = needed and efflv <= 2
        _, xp, nxt = logic.skill_progress(team["id"], s["key"])
        with st.container(border=True):
            c1, c2 = st.columns([3, 1])
            title = f"**{s['name']}** — founder {base}/{content.SKILL_MAX}"
            if boost:
                title += f"  ·  +{boost} hired → **effective {efflv}**"
            if needed:
                title += "  · 🎯 needed now"
            c1.markdown(title)
            c1.progress(efflv / content.SKILL_MAX)
            c1.caption(f"_{s['definition']}_")
            c1.caption(f"Effect: {s['effect']}  ·  Supports **{s['dimension']}**.")
            if base < content.SKILL_MAX:
                c1.caption(f"📚 Progress to next level: **{xp}/{nxt} hrs** banked "
                           f"(a full level = {nxt}h).")
            if gap:
                c1.caption("⚠️ Needed this round but weak — assign time or hire in.")
            # Assign training / undo controls
            if base >= content.SKILL_MAX:
                c2.success("Maxed")
            else:
                remaining = max(0, nxt - xp)                 # hours to finish this level
                cap = min(remaining, room)                   # can't exceed level or effort room
                default = cap
                hrs = c2.number_input("Assign hrs", 0, max(0, cap), int(default),
                                      key=f"inv_{s['key']}", label_visibility="collapsed",
                                      disabled=locked,
                                      help=f"Hours to assign now. {remaining}h finishes this level; "
                                           f"{room}h of effort left this week.")
                if c2.button("Train", key=f"train_{s['key']}", disabled=(room <= 0 or locked)):
                    ok, msg = logic.invest_training(team["id"], s["key"], hrs)
                    (st.success if ok else st.error)(msg)
                    st.rerun()
            if xp > 0 or base > logic._card_base_level(team["id"], s["key"]):
                if c2.button("Undo", key=f"untrain_{s['key']}", disabled=locked,
                             help="Refund banked hours, or revert one trained level."):
                    ok, msg = logic.untrain_skill(team["id"], s["key"])
                    (st.success if ok else st.error)(msg)
                    st.rerun()

    # ---- Hiring -------------------------------------------------------------
    st.divider()
    st.write("### Hire specialists to fill gaps")
    st.caption("Founders rarely have every skill. Hire a specialist to raise a skill you lack — "
               "part-time is cheaper; full-time gives a bigger boost but a real salary each round.")
    hire_opts = logic.hire_options()
    hires = db.list_hires(team["id"])
    if hires:
        st.markdown("**On your team:**")
        for h in hires:
            hc1, hc2 = st.columns([4, 1])
            opt = hire_opts.get(h["kind"], {})
            hc1.markdown(f"- **{opt.get('label', h['kind'])} {h['role']}** "
                         f"(+{h['boost']} {content.FOUNDER_SKILL_BY_KEY[h['skill_key']]['name']})"
                         + (f" · ${h['per_round']:.0f}/round" if h["per_round"] else ""))
            if hc2.button("Let go", key=f"fire_{h['id']}", disabled=locked,
                          help="Remove this hire and stop the salary."):
                logic.fire_specialist(h["id"])
                st.rerun()

    if not locked:
      with st.form("hire_form", clear_on_submit=True):
        hc1, hc2 = st.columns(2)
        skill_key = hc1.selectbox(
            "Skill to strengthen", content.FOUNDER_SKILL_KEYS,
            format_func=lambda k: f"{content.SPECIALIST_ROLES[k]} ({content.FOUNDER_SKILL_BY_KEY[k]['name']})",
            help="Pick the skill you want to raise by hiring.")
        kind = hc2.selectbox(
            "Employment", list(hire_opts.keys()),
            format_func=lambda k: (
                f"{hire_opts[k]['label']} · +{hire_opts[k]['boost']} skill · "
                f"${hire_opts[k]['upfront']:.0f} + {content.HIRE_OPTIONS[k]['recruit_hours']}h to recruit · "
                f"then ${hire_opts[k]['per_round']:.0f} + {content.HIRE_OPTIONS[k]['manage_hours']}h/round"),
            help="Part-time is cheaper with a smaller boost; full-time boosts more but costs more "
                 "money and management time.")
        if st.form_submit_button("Hire specialist"):
            ok, msg = logic.hire_specialist(team["id"], skill_key, kind)
            (st.success if ok else st.error)(msg)
            st.rerun()


# --------------------------------------------------------------------------- #
# Dashboard
# --------------------------------------------------------------------------- #
def _team_identity_editor(team):
    """Pick a team name, colour, and mascot — ownership makes it theirs."""
    ident = logic.team_identity(team)
    was_set = db.has_ack(team["id"], "identity_set")
    with st.expander("🎨 Team identity — pick your name, color & mascot", expanded=not was_set):
        cc = st.columns([1, 4])
        cc[0].markdown(branding.avatar_html(ident["color"], ident["mascot"], 68),
                       unsafe_allow_html=True)
        with cc[1]:
            name = st.text_input("Team name", value=ident["display"], key=f"idname_{team['id']}")
            k1, k2 = st.columns(2)
            cidx = next((i for i, (n, h) in enumerate(content.TEAM_COLORS)
                         if h == ident["color"]), 0)
            color = k1.selectbox("Color", content.TEAM_COLORS, index=cidx,
                                 format_func=lambda t: t[0], key=f"idcolor_{team['id']}")
            midx = content.TEAM_MASCOTS.index(ident["mascot"]) \
                if ident["mascot"] in content.TEAM_MASCOTS else 0
            mascot = k2.selectbox("Mascot", content.TEAM_MASCOTS, index=midx,
                                  key=f"idmascot_{team['id']}")
        st.markdown("Preview: "
                    + branding.avatar_html(color[1], mascot, 28)
                    + f" <b>{name or ident['display']}</b>", unsafe_allow_html=True)
        if st.button("Save identity", type="primary", key=f"idsave_{team['id']}"):
            db.update_team(team["id"], display_name=(name.strip() or ident["display"]),
                           color=color[1], mascot=mascot)
            db.set_ack(team["id"], "identity_set")
            st.success("Looking sharp! 🎉")
            st.rerun()


def my_venture(team):
    """Combined 'My Venture' page — the dashboard and the progress/trophy views under
    two tabs, so the sidebar isn't split across two overlapping status pages."""
    st.subheader("📊 My Venture")
    t1, t2 = st.tabs(["Dashboard", "Progress & badges"])
    with t1:
        dashboard(team)
    with t2:
        progress(team)


def dashboard(team):
    ident = logic.team_identity(team)
    st.markdown(branding.team_badge_html(team, 52) + " <span style='opacity:.6'>— Venture "
                "Dashboard</span>", unsafe_allow_html=True)
    lvl, tot = logic.founder_level(team["id"])
    st.caption(f"Stage: **{team['stage']}**  ·  Round {db.current_round()}  ·  "
               f"🧑‍🚀 Founder Level {lvl}  ·  Join code `{team['join_code']}`")
    _why("Dashboard")
    _team_identity_editor(team)
    _guide(
        "This is your venture's home screen. It shows what you own (top row), what your "
        "venture is worth, how the Director has scored you, and where your biggest risks "
        "are. You don't enter anything here — it summarizes everything you do on the other "
        "pages. Check it at the start and end of every round.",
        terms=[
            ("Venture Valuation", "A simulated score, not a real dollar figure. It rewards "
             "evidence and coherence, not a flashy idea."),
            ("Performance dimensions", "Ten qualities the Director grades 0–100 each round."),
            ("High-risk untested", "Important assumptions you have not backed with evidence — "
             "the fastest way to lose the game is to ignore these."),
        ],
    )
    _resource_bar(team)

    val = logic.compute_valuation(team["id"])
    cov_pct = val["evidence_coverage"] * 100
    st.divider()
    vc1, vc2 = st.columns([1, 2])
    with vc1:
        st.metric("Venture Valuation", f"${val['valuation']:,.0f}",
                  help="What your venture is worth RIGHT NOW. A brand-new idea is worth $0 — you "
                       "earn value through the decisions you make and the evidence you gather. "
                       "It grows as you build your model, test assumptions, and log strong evidence.")
        st.caption(f"Potential ${val['potential_valuation']:,.0f} × "
                   f"{cov_pct:.0f}% evidence-backed − risk")
        st.progress(val["evidence_coverage"],
                    text=f"Evidence coverage: {cov_pct:.0f}%")
    with vc2:
        st.write("**How this is built.** Your *potential* value is the opportunity size scaled "
                 "by the Director's confidence/coherence/execution multipliers (each ×0.50 weak "
                 "→ ×1.50 strong). That potential is then **discounted by evidence coverage** — "
                 "the share of your model you've actually proven — so an unproven idea is worth "
                 "little until the evidence comes in:")
        st.write(
            f"- Market potential: ${val['market_potential']:,.0f}\n"
            f"- Evidence confidence: ×{val['evidence_confidence']}\n"
            f"- Business-model coherence: ×{val['bm_coherence']}\n"
            f"- Execution factor: ×{val['execution_factor']}\n"
            f"- **Potential valuation (if fully proven): ${val['potential_valuation']:,.0f}**\n"
            f"- **Evidence coverage: ×{val['evidence_coverage']:.2f}** "
            f"({cov_pct:.0f}% — raise it by testing important assumptions and logging strong evidence)\n"
            f"- Unresolved-risk penalty: −${val['unresolved_risk']:,.0f}"
        )
        if cov_pct <= 0:
            st.caption("💡 Your venture is worth **$0** right now — a good idea earns nothing until "
                       "you work on it. Draft your model, name your assumptions, then test them and "
                       "log evidence to grow this number.")
        elif cov_pct < 25:
            st.caption("💡 Your valuation is low because little is proven yet — that's by design. "
                       "Test your riskiest assumptions and log behavioral evidence to earn more.")

    st.divider()
    st.write("### Performance dimensions")
    st.caption("Set by the Director each round (0–100). Empty bars just mean 'not scored yet.'")
    scores = db.latest_scores(team["id"])
    if not scores:
        st.info("No dashboard scores yet — the Venture Foundry Director sets these each round.")
    else:
        for name, meaning in content.DASHBOARD_DIMENSIONS:
            s = scores.get(name)
            cols = st.columns([2, 5, 1])
            cols[0].write(f"**{name}**")
            cols[1].progress(int(s) if s is not None else 0)
            cols[2].write(f"{s:.0f}" if s is not None else "—")
            cols[1].caption(meaning)

    st.divider()
    st.write("### Risk snapshot")
    esum = logic.evidence_summary(team["id"])
    arep = logic.assumption_risk_report(team["id"])
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Evidence items", esum["count"],
              help="How many pieces of evidence you've logged on the Evidence Ledger page.")
    m2.metric("Behavioral evidence", esum["behavioral"],
              help="Evidence based on what customers actually DID (strength 6+). Worth far "
                   "more than opinions.")
    m3.metric("Assumptions untested", arep["untested"],
              help="Beliefs you have not yet tested on the Assumption Map page.")
    m4.metric("High-risk untested", len(arep["exposed"]),
              help="Important assumptions with no evidence. Test these first.")
    if arep["exposed"]:
        st.warning(
            "⚠️ High-importance assumptions with no evidence — these can invalidate the "
            "venture if they fail:\n\n"
            + "\n".join(f"- {a['text']} ({a['risk_type']})" for a in arep["exposed"])
        )

    with st.expander("Transaction ledger — every time you gained or spent resources"):
        txns = db.list_transactions(team["id"], limit=50)
        if txns:
            st.dataframe(
                [{"When": t["created_at"], "Kind": t["kind"], "$": t["money"],
                  "Credits": t["credits"], "Hours": t["hours"], "Note": t["description"]}
                 for t in txns],
                use_container_width=True, hide_index=True,
            )
        else:
            st.caption("No transactions yet.")


# --------------------------------------------------------------------------- #
# Progress — the team's own learning trend, so it can self-regulate
# --------------------------------------------------------------------------- #

def _trend_chart(df, cols):
    """A multi-line chart like st.line_chart, but from a small Vega-Lite spec.
    st.line_chart builds an Altair object tree server-side (~70 ms per chart on
    every rerun); passing the spec directly renders the same chart in the browser
    for a fraction of the server CPU."""
    data = df[cols].reset_index()
    st.vega_lite_chart(data, {
        "transform": [{"fold": cols, "as": ["Metric", "Value"]}],
        "mark": {"type": "line", "point": True},
        "encoding": {
            "x": {"field": "Round", "type": "quantitative", "axis": {"tickMinStep": 1}},
            "y": {"field": "Value", "type": "quantitative", "title": None},
            "color": {"field": "Metric", "type": "nominal", "title": None,
                      "legend": {"orient": "bottom"}},
            "tooltip": [{"field": "Round", "type": "quantitative"},
                        {"field": "Metric", "type": "nominal"},
                        {"field": "Value", "type": "quantitative"}],
        },
    }, use_container_width=True)


def progress(team):
    st.subheader("📈 Learning Progress")
    _why("Progress")

    # ---- Trophy case: level, streak, badges ---------------------------------
    lvl, tot = logic.founder_level(team["id"])
    streak = logic.commit_streak(team["id"])
    badges = logic.badge_progress(team["id"])
    earned = [b for b in badges if b["earned"]]
    tc1, tc2, tc3 = st.columns(3)
    tc1.metric("🧑‍🚀 Founder Level", lvl, help="Grows as your founders train and learn by doing.")
    tc2.metric("🏅 Badges", f"{len(earned)}/{len(badges)}")
    tc3.metric("🔥 Commit streak", f"{streak} round(s)",
               help="Consecutive rounds you committed your work.")
    st.markdown("**🏆 Trophy case**")
    cols = st.columns(5)
    for i, b in enumerate(badges):
        with cols[i % 5]:
            if b["earned"]:
                st.markdown(f"<div style='font-size:30px'>{b['emoji']}</div>"
                            f"<b>{b['name']}</b>", unsafe_allow_html=True)
                st.caption(b["desc"])
            else:
                st.markdown("<div style='font-size:30px;filter:grayscale(1);opacity:.35'>"
                            f"{b['emoji']}</div><span style='opacity:.5'>{b['name']}</span>",
                            unsafe_allow_html=True)
                st.caption("🔒 " + b["desc"])
    st.divider()

    _guide(
        "This is your learning made visible — not a score to game, but a mirror. It tracks how "
        "your evidence is getting stronger, how much of your model you've actually tested, how "
        "often you've changed direction based on evidence, and whether you're verifying the AI "
        "you use. Watch these trend UP over the semester.",
        terms=[
            ("Behavioral vs. opinion", "What customers DID vs. what they SAID. Behavior is stronger."),
            ("Test coverage", "Share of your important assumptions you've actually tested."),
            ("Evidence coverage", "How much of your venture's value is backed by evidence (drives valuation)."),
            ("Course corrections", "Times you changed direction based on evidence (mini + formal pivots)."),
        ],
    )
    m = logic.learning_metrics(team["id"])
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Behavioral evidence", m["behavioral"],
              help="Strength-6+ evidence based on what customers did.")
    c1.metric("Opinion-only", m["opinion"], help="Weak (strength ≤2) 'they said' evidence.")
    c2.metric("Behavioral ratio", f"{m['behavioral_ratio']*100:.0f}%",
              help="Share of your evidence that is behavioral. Aim to raise it.")
    c2.metric("Avg evidence strength", m["avg_strength"])
    c3.metric("Assumption test coverage", f"{m['test_coverage']*100:.0f}%",
              help="Important assumptions you've tested (Supported/Refuted).")
    c3.metric("Evidence coverage", f"{m['evidence_coverage']*100:.0f}%",
              help="How much of your value is evidence-backed — this drives your valuation.")
    c4.metric("Course corrections", m["pivots_evidence"],
              help="Evidence-driven changes of direction (mini-pivots, refuted assumptions, approved pivots).")
    c4.metric("AI verification",
              f"{m['ai_verification']*100:.0f}%" if m["ai_verification"] is not None else "—",
              help="Share of your AI uses you actually evaluated. '—' means you haven't logged AI yet.")

    # ---- Trend over rounds ---------------------------------------------------
    trend = logic.metrics_trend(team["id"])
    st.divider()
    st.write("### Your trend over the rounds")
    if len(trend) < 2:
        st.info("Your trend chart fills in as the rounds advance — check back after Round 1. "
                "The numbers above are your live snapshot for this round.")
    rows = [{
        "Round": t["round"],
        "Behavioral evidence": t.get("behavioral", 0),
        "Opinion-only": t.get("opinion", 0),
        "Test coverage %": round(t.get("test_coverage", 0) * 100),
        "Evidence coverage %": round(t.get("evidence_coverage", 0) * 100),
        "Course corrections": t.get("pivots_evidence", 0),
    } for t in trend]
    try:
        import pandas as pd
        df = pd.DataFrame(rows).set_index("Round")
        st.caption("Evidence quality — behavioral should outgrow opinion over time:")
        _trend_chart(df, ["Behavioral evidence", "Opinion-only"])
        st.caption("How proven your model is — test coverage and evidence coverage should climb:")
        _trend_chart(df, ["Test coverage %", "Evidence coverage %"])
        st.caption("Evidence-driven course corrections (changing your mind is a strength):")
        _trend_chart(df, ["Course corrections"])
    except Exception:
        st.table(rows)


# --------------------------------------------------------------------------- #
# Cohort leaderboard (anonymized) + Demo Day
# --------------------------------------------------------------------------- #
@st.cache_data(ttl=30, max_entries=64, show_spinner=False)
def _leaderboard_rows(game_id, metric, rnd):
    """Cohort standings are identical for every student in a game, so compute them
    once per game/metric/round and share for up to 30 s, instead of every student
    recomputing every team's score on every click. `rnd` is part of the key so a
    round advance is reflected immediately. Only the fields the page displays are
    kept (no rosters / join codes held in the shared cache)."""
    rows = logic.leaderboard(game_id, metric)
    keep = ("id", "name", "display_name", "mascot", "color")
    return [{**r, "team": {k: r["team"].get(k) for k in keep}} for r in rows]


def leaderboard(team):
    st.subheader("🏆 Cohort Leaderboard")
    st.caption("Where your venture stands against the rest of the cohort. Anonymized — you see "
               "everyone's standing but only your own name. Climb by earning evidence.")
    metric = st.radio("Rank by", list(logic.LEADERBOARD_METRICS.keys()),
                      format_func=lambda k: logic.LEADERBOARD_METRICS[k], horizontal=True,
                      key="lb_metric")
    rows = _leaderboard_rows(team.get("game_id"), metric, db.current_round())
    mine = next((r for r in rows if r["team"]["id"] == team["id"]), None)
    if mine:
        c1, c2 = st.columns(2)
        c1.metric("Your rank", f"#{mine['rank']} of {len(rows)}")
        _v = {"round_score": f"{mine['round_score']:.0f}/100",
              "valuation": f"${mine['valuation']:,.0f}",
              "coverage": f"{mine['coverage']*100:.0f}%"}[metric]
        c2.metric(logic.LEADERBOARD_METRICS[metric], _v)
    st.divider()
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    for r in rows:
        is_me = r["team"]["id"] == team["id"]
        ident = logic.team_identity(r["team"])
        name = (f"{ident['mascot']} **You** ({ident['display']})" if is_me
                else f"{ident['mascot']} Team {r['rank']}")
        val = {"round_score": f"{r['round_score']:.0f}/100",
               "valuation": f"${r['valuation']:,.0f}",
               "coverage": f"{r['coverage']*100:.0f}%"}[metric]
        badge = medals.get(r["rank"], f"#{r['rank']}")
        line = f"{badge}  {name} — **{val}**  ·  🏅 {r['badges']}"
        if is_me:
            st.success(line)
        else:
            st.markdown(line)


def _pitch_builder(team, gid):
    """The Pitch Canvas (Beckett) builder — a one-page structure for the Demo Day
    pitch, auto-fillable from the team's own accumulated work."""
    st.write("### 🎯 Build your pitch — the Pitch Canvas")
    st.caption("A strong pitch is structured, not a wall of text. Fill each block below (keep it "
               "short). The ✨ button drafts blocks from your real work — Customer Profile, VPC, "
               "Business Model Canvas, Evidence Ledger, and your valuation — so your pitch stands "
               "on evidence, not adjectives.")
    saved = db.get_pitch_canvas(team["id"])
    p = db.get_pitch(team["id"]) or {}
    # one-click autofill of empty blocks
    if st.button("✨ Draft from my work (fills empty blocks)", key="pitch_autofill"):
        af = logic.pitch_canvas_autofill(team["id"])
        for k, v in af.items():
            if not (saved.get(k) or "").strip():
                saved[k] = v
        # persist immediately so the form shows the drafts
        db.save_pitch(team["id"], gid,
                      saved.get("simple_statement", p.get("headline", "")),
                      saved.get("product", p.get("pitch", "")),
                      saved.get("traction", p.get("best_evidence", "")),
                      saved.get("call_to_action", p.get("ask", "")), canvas=saved)
        st.rerun()

    score = logic.pitch_canvas_score(saved)
    st.progress(score["pct"], text=f"Pitch completeness: {score['done']}/{score['total']} blocks "
                f"· core blocks {score['core_done']}/{score['core_total']}")
    if score["missing_core"]:
        st.caption("Still needed for a complete pitch: **" + ", ".join(score["missing_core"]) + "**.")
    elif score["ready"]:
        st.success("✅ Your core pitch is complete — polish the wording and you're ready to present.")

    locked = logic.editing_locked(team["id"])
    with st.form("pitch_canvas_form"):
        vals = {}
        for key, title, prompt, src in content.PITCH_CANVAS_BLOCKS:
            core = key in content.PITCH_CORE_BLOCKS
            lbl = f"{'⭐ ' if core else ''}{title}"
            vals[key] = st.text_area(lbl, value=saved.get(key, ""), key=f"pc_{key}",
                                     height=70, help=prompt + (f"  ·  Auto-fill source: {src}." if src else ""),
                                     disabled=locked)
        if st.form_submit_button("💾 Save pitch", type="primary", disabled=locked):
            db.save_pitch(team["id"], gid,
                          vals.get("simple_statement", ""), vals.get("product", ""),
                          vals.get("traction", ""), vals.get("call_to_action", ""), canvas=vals)
            st.success("Pitch saved.")
            st.rerun()
    st.caption("⭐ = core block. The blocks map to a classic investor pitch: hook → problem → "
               "solution → why-you're-different → proof → how-you-make-money → the ask.")


def demo_day(team):
    st.subheader("🎤 Demo Day — Evidence Exchange")
    _why("Progress")
    gid = team.get("game_id")
    is_open = logic.demo_is_open(gid)
    if not is_open:
        st.info("🔒 The Evidence Exchange opens near the end of the semester — your instructor "
                "starts it. Until then, keep building evidence, and you can draft your pitch below.")
    else:
        st.success("🎉 The Evidence Exchange is OPEN — polish your pitch, then read and vote on "
                   "your peers' ventures.")

    # ---- Your pitch — the Pitch Canvas builder -------------------------------
    _pitch_builder(team, gid)

    if not is_open:
        return

    # ---- Invest in peers -----------------------------------------------------
    st.divider()
    st.write("### 💰 Invest in the strongest ventures")
    cfg = logic.demo_config(gid)
    state = logic.demo_investment_state(gid, team["id"])
    st.caption(f"You're a syndicate with **${cfg['fund']:,}** to invest across OTHER teams' "
               f"ventures (not your own). Put your money where the **evidence** is strongest — "
               f"and spread it across at least **{cfg['min_teams']}** ventures.")
    mc1, mc2, mc3 = st.columns(3)
    mc1.metric("Fund", f"${cfg['fund']:,}")
    mc2.metric("Invested", f"${state['spent']:,}")
    mc3.metric("Remaining", f"${state['remaining']:,}",
               delta=None if state["remaining"] >= 0 else "over budget")
    if state["over_budget"]:
        st.error("You've allocated more than your fund — reduce some amounts.")
    elif state["backed"] < cfg["min_teams"]:
        st.warning(f"Spread your investment across at least {cfg['min_teams']} ventures "
                   f"(currently backing {state['backed']}).")
    elif state["ok"]:
        st.success("✅ Your allocation meets the rules. You can still rebalance any time.")

    peers = [pp for pp in db.list_pitches(gid) if pp["team_id"] != team["id"]]
    if not peers:
        st.info("No other pitches submitted yet — check back once teams have saved theirs.")
    invested = state["invested"]
    for pp in peers:
        other = db.get_team(pp["team_id"])
        ident = logic.team_identity(other)
        with st.container(border=True):
            st.markdown(f"**{ident['mascot']} {pp.get('headline') or 'Untitled venture'}**")
            if pp.get("pitch"):
                st.write(pp["pitch"])
            if pp.get("best_evidence"):
                st.caption(f"💪 Strongest evidence: {pp['best_evidence']}")
            if pp.get("ask"):
                st.caption(f"🙋 Ask: {pp['ask']}")
            cur_amt = int(invested.get(pp["team_id"], 0))
            ac1, ac2 = st.columns([3, 1])
            amt = ac1.number_input(f"Invest in {ident['display']} ($)", 0, cfg["fund"], cur_amt,
                                   step=50, key=f"inv_{pp['team_id']}")
            if ac2.button("Save", key=f"invsave_{pp['team_id']}"):
                db.set_investment(gid, team["id"], pp["team_id"], int(amt))
                st.rerun()

    # ---- Live results --------------------------------------------------------
    st.divider()
    st.write("### 🏆 Live leaderboard — dollars raised")
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    res = logic.demo_results(gid)
    for r in res["rows"]:
        ident = logic.team_identity(r["team"])
        me = r["team"]["id"] == team["id"]
        label = f"{ident['mascot']} **You** ({ident['display']})" if me else \
            f"{ident['mascot']} {ident['display']}"
        st.markdown(f"{medals.get(r['rank'], '#'+str(r['rank']))} {label} — "
                    f"**${r['raised']:,}** from {r['backers']} backer(s)")


# --------------------------------------------------------------------------- #
# Founder & Opportunity
# --------------------------------------------------------------------------- #
def _score_bar(label, val):
    """A compact 0–5 score row with a filled bar."""
    filled = "█" * int(round(val)) + "░" * (5 - int(round(val)))
    st.markdown(f"**{label}:** `{filled}` {val:.1f}/5")


def _venture_name_section(team, editable):
    """Name your venture, and get a creativity / brand-value / fit evaluation."""
    st.write("### 🏷️ Name your venture")
    st.caption("A great name is memorable, easy to say, and hints at the value you create for "
               "your customer. Enter a name to score it on **creativity**, **brand value**, and "
               "**fit** with your customer and venture. You can rename and re-score anytime.")
    saved = db.get_venture_name(team["id"])
    cur_name = saved.get("name", "")
    if cur_name:
        st.success(f"Current venture name: **{cur_name}**")
    _ai_ack_popover(team, "Venture name", "vname_ai", label=_AI_LOG_LABEL)
    with st.form("venture_name_form", clear_on_submit=False):
        name = st.text_input("Venture name", value=cur_name,
                             placeholder="e.g. FoodLoop, MendKit, GreenGrable",
                             disabled=not editable)
        submitted = st.form_submit_button("Score & save name", type="primary",
                                          disabled=not editable)
    if submitted:
        if not name.strip():
            st.error("Enter a name to score it.")
        else:
            ev = logic.evaluate_venture_name(name, team["id"])
            db.set_venture_name(team["id"], name.strip(), ev)
            st.rerun()
    # Show the latest evaluation.
    scores = saved.get("scores") or {}
    if cur_name and scores:
        with st.container(border=True):
            st.markdown(f"#### Evaluation of “{cur_name}”")
            oc1, oc2 = st.columns([1, 2])
            with oc1:
                st.metric("Overall", f"{scores.get('overall', 0):.1f}/5")
            with oc2:
                _score_bar("Creativity", scores.get("creativity", 0))
                _score_bar("Brand value", scores.get("brand", 0))
                _score_bar("Customer / venture fit", scores.get("fit", 0))
            for n in scores.get("notes", []):
                st.caption(f"• {n}")
            if scores.get("ai"):
                st.markdown(f"🔵 **Brand strategist's note:** {scores['ai']}")
            elif logic.ai_available():
                st.caption("Re-save to include an AI brand critique.")


def _effectuation_panel(team, editable):
    """Effectuation mechanics — affordable loss + crazy-quilt partner pre-commitments."""
    st.write("### 🧭 Effectuation — play from your means")
    st.caption("Expert founders reason from what they can afford to lose and who will commit to "
               "them — then treat surprises as raw material. Two of those levers live here.")
    al = logic.affordable_loss_status(team)
    m1, m2, m3 = st.columns(3)
    m1.metric("Affordable loss (your card)", f"${al['cap']:,.0f}",
              help="The budget you set out able to lose — your risk ceiling. Spend against THIS, "
                   "not against a hoped-for return.")
    m2.metric("Capital remaining", f"${al['remaining']:,.0f}")
    m3.metric("Spent so far", f"${al['spent']:,.0f}")
    if al["cap"] and al["spent"] > al["cap"] * 0.8:
        st.warning("You're near your affordable-loss ceiling — favour cheaper tests from here.")

    st.markdown("**🧩 Partners & pre-commitments (crazy quilt)**")
    st.caption(f"Log a self-selected partner or customer who has actually pre-committed — a "
               f"stocking agreement, an intro, a letter of intent. Each earns "
               f"+{logic.PARTNER_CREDIT} Evidence Credits; real commitments are strong signals.")
    if editable and not logic.editing_locked(team["id"]):
        with st.form("partner_form", clear_on_submit=True):
            pc = st.columns([2, 3, 3])
            name = pc[0].text_input("Partner / customer")
            commit = pc[1].text_input("What did they pre-commit to?")
            evid = pc[2].text_input("Evidence (email, signature, intro…)")
            if st.form_submit_button("➕ Log pre-commitment"):
                if name.strip() and commit.strip():
                    r = logic.log_partner_commitment(team["id"], name, commit, evid)
                    st.success(f"Logged. +{r} Evidence Credits for a real commitment.")
                    st.rerun()
                else:
                    st.error("Add at least the partner and what they committed to.")
    partners = db.list_partners(team["id"])
    if partners:
        for pp in partners:
            line = f"- **{pp['name']}** — {pp['commitment']}"
            if (pp.get("evidence") or "").strip():
                line += f"  ·  _{pp['evidence']}_"
            st.markdown(line)
    else:
        st.caption("No pre-commitments logged yet.")


def founder_opportunity(team):
    st.subheader("🧭 Founder & Opportunity Formation")
    _why("Founder & Opportunity")
    editable = _round_gate("Founder & Opportunity", team)
    _ai_check_notice(team, tool_area="Other")
    _guide(
        "You are founders newly accepted into the Venture Foundry accelerator. You do NOT "
        "start with a product — you start with a broad **opportunity territory** and a "
        "**founder card** listing your team's skills, money, and time. Your first job is to "
        "invent at least three possible ventures inside that territory and score each one, "
        "so you commit deliberately instead of falling in love with the first idea.",
        steps=[
            "Read your founder card and opportunity territory below.",
            "Add three or more candidate ventures using the form.",
            "Score each on the five sliders (1 = poor, 5 = excellent).",
            "Compare them and discuss which to pursue — higher total scores are stronger bets.",
        ],
        terms=[
            ("Opportunity territory", "A problem area (e.g. 'reducing food waste'), not a "
             "product. Many ventures could live inside it."),
            ("Founder card", "Your fixed constraints for the semester: skills, network, "
             "budget you can afford to lose, and hours available."),
            ("Founder–opportunity fit", "How well your specific skills and network match "
             "what this venture would need."),
        ],
    )

    card = db.get_founder_card(team["id"])
    st.write("### Your founder card")
    if card:
        with st.container(border=True):
            hc1, hc2 = st.columns([1, 6])
            hc1.markdown(
                "<div style='font-size:44px;text-align:center;line-height:1'>🧑‍🚀</div>",
                unsafe_allow_html=True)
            hc2.markdown(f"### {card.get('name','—')}")
            hc2.caption(f"Founding team · {team['name']} · Risk appetite: "
                        f"{card.get('risk','—')}")
            # Founding-team backstory — names the real students if a roster was imported.
            _members = logic.team_member_names(team)
            _story = content.founder_backstory(card, _members)
            if _story:
                st.markdown(f"> {_story}")
            st.caption("Click the ❓ beside any attribute to learn what it means and how it "
                       "shapes play.")
            rows = [
                ("🛠 Skills", card.get("skills", "—"), "skills"),
                ("🔗 Networks", card.get("networks", "—"), "networks"),
                ("💵 Budget you can afford to lose", f"${card.get('budget','—')}", "budget"),
                ("⏳ Founder-time this week", f"{logic.current_effort(team)}h effort "
                 f"(cap 80h — set by your task allocation)", "hours"),
                ("🎲 Risk tolerance", card.get("risk", "—"), "risk"),
                ("⚖️ Ethical boundary", card.get("ethics", "—"), "ethics"),
            ]
            for label, value, key in rows:
                rc1, rc2 = st.columns([20, 1])
                rc1.markdown(f"**{label}:** {value}")
                with rc2.popover("❓"):
                    st.markdown(content.FOUNDER_ATTR_HELP[key])
            st.caption("↳ On the **Founder & Team** page: plan the founder's **time allocation**, "
                       "grow skills by training, and hire specialists to fill gaps.")
    else:
        st.caption("The Director has not yet assigned a founder card.")

    st.write(f"### Opportunity territory\n**{team['opportunity'] or '—'}**")
    st.caption("📬 Your welcome email in the **Inbox** maps out how to get started in this "
               "territory and how to make a strong first round.")

    st.divider()
    _venture_name_section(team, editable)

    st.divider()
    _effectuation_panel(team, editable)

    st.divider()
    if db.has_ack(team["id"], "founder_review"):
        st.success("✅ Your team has marked the founder card & territory as reviewed.")
    else:
        st.info("Round 1 task: read your founder card, skills, and territory above with your "
                "whole team, then confirm you've reviewed them.")
        if st.button("✔ Mark founder card & territory as reviewed", disabled=not editable):
            db.set_ack(team["id"], "founder_review")
            st.rerun()

    st.divider()
    st.write("### Candidate ventures")
    # Candidate ventures belong to the Opportunity-framing round. Under Strict mode
    # they're view-only until that round is active (or overdue).
    _cur = db.current_round()
    _opp_now = any(tp["key"] == "opportunity_framing" for tp in logic.topics_for_round(_cur))
    _opp_carried = any(d.get("check") == "ventures_ge_3"
                       for d in logic.outstanding_prior(team["id"], _cur))
    ventures_editable = editable and (not logic.strict_round_mode() or _opp_now or _opp_carried)
    if not ventures_editable:
        _opp_rounds = logic.rounds_for_topic("opportunity_framing")
        _opp_when = logic.rounds_phrase(_opp_rounds) if _opp_rounds else "the Opportunity-framing round"
        st.info(f"🔒 Generating and scoring 3+ ventures is the **Opportunity framing** task — it "
                f"opens in **{_opp_when}**. For now it's view-only (input disabled). Your instructor "
                f"can allow early edits by turning off Strict round mode.")
    else:
        st.caption("Generate at least three ventures and score each — comparing options "
                   "deliberately is a constrained decision, not free brainstorming.")

    ventures = db.get_ventures(team["id"])
    for i, v in enumerate(ventures):
        with st.expander(f"Venture {i+1}: {v.get('name','(unnamed)')}"):
            st.write(f"**Customer importance:** {v.get('importance','—')}/5")
            st.write(f"**Founder–opportunity fit:** {v.get('fit','—')}/5")
            st.write(f"**Access to customers:** {v.get('access','—')}/5")
            st.write(f"**Evidence availability:** {v.get('evidence','—')}/5")
            st.write(f"**Experiment affordability:** {v.get('afford','—')}/5")
            st.write(f"**Notes:** {v.get('notes','')}")
            if ventures_editable and st.button(
                    "Remove", key=f"rmv_{i}", help="Delete this candidate venture."):
                ventures.pop(i)
                db.set_ventures(team["id"], ventures)
                st.rerun()

    if not ventures_editable:
        return
    _ai_ack_popover(team, "Candidate ventures", "venture_ai", label=_AI_LOG_LABEL)
    with st.form("add_venture", clear_on_submit=True):
        st.write("**Add a candidate venture**")
        name = st.text_input(
            "Venture name / one-line description",
            help="A short pitch of one possible business inside your territory, e.g. "
                 "'App that resells near-expiry grocery items to students.'")
        c1, c2, c3 = st.columns(3)
        importance = c1.slider(
            "Customer importance", 1, 5, 3,
            help="How badly does the customer need this solved? 1 = nice-to-have, "
                 "5 = urgent, painful problem.")
        fit = c2.slider(
            "Founder–opportunity fit", 1, 5, 3,
            help="How well do YOUR skills and network match this venture? 5 = perfect fit.")
        access = c3.slider(
            "Access to customers", 1, 5, 3,
            help="Can you actually reach these customers to interview and sell? "
                 "5 = easy access.")
        c4, c5 = st.columns(2)
        evidence = c4.slider(
            "Evidence availability", 1, 5, 3,
            help="How easily could you gather real evidence about this idea? "
                 "5 = evidence is easy to collect.")
        afford = c5.slider(
            "Experiment affordability", 1, 5, 3,
            help="Can you test this cheaply with your money and hours? "
                 "5 = very cheap to test.")
        notes = st.text_area(
            "Notes",
            help="Anything else worth remembering about this option — risks, ideas, "
                 "who to talk to.")
        if st.form_submit_button("Add venture", disabled=not ventures_editable,
                                 help="Save this candidate venture to your list.") and name:
            ventures.append({"name": name, "importance": importance, "fit": fit,
                             "access": access, "evidence": evidence, "afford": afford,
                             "notes": notes})
            db.set_ventures(team["id"], ventures)
            st.success("Venture added.")
            st.rerun()


# --------------------------------------------------------------------------- #
# Canvases (versioned)
# --------------------------------------------------------------------------- #
_CANVAS_DEFS = {
    "customer_profile": ("Customer Profile", content.CUSTOMER_PROFILE_BLOCKS),
    "vpc": ("Value Proposition Canvas", content.VPC_BLOCKS),
    "bmc": ("Business Model Canvas", content.BMC_BLOCKS),
    "environment": ("Business Model Environment Canvas", content.ENVIRONMENT_BLOCKS),
}

_CANVAS_HELP = {
    "customer_profile": "Describes ONE customer segment: the jobs they're trying to get "
                        "done, the pains they suffer, and the gains they want. Fill this in "
                        "from real interviews, not guesses.",
    "vpc": "The Value Proposition Canvas maps how your offer relieves specific pains and "
           "creates specific gains for that customer. A good value proposition 'fits' the "
           "customer profile.",
    "bmc": "The Business Model Canvas describes the whole business on nine blocks — who you "
           "serve, what you offer, how you reach and keep them, how you make money, and what "
           "it costs. The nine blocks depend on each other, so a change in one affects others.",
    "environment": "The Business Model Environment Canvas scans the world around your model: "
                   "customer, technology and mega trends, market/industry/macro forces, and the "
                   "disruptive competitive forces at the centre. Use it to spot threats and "
                   "opportunities before they hit.",
}


# High-quality vector illustration drawn above each canvas (see canvas_art.py).
def _canvas_diagram(ctype):
    svg = canvas_art.svg(ctype)
    if svg:
        st.markdown(f"<div style='text-align:center;margin:6px 0 10px;'>{svg}</div>",
                    unsafe_allow_html=True)


def _cbox(parent, title, key, prefill, height=120, hint=""):
    """Render one canvas block (bordered box, title, textarea) and return its value.

    `parent` may be the `st` module or a column — both expose .container()/.text_area(),
    so we call methods directly rather than using a `with` block (the module isn't a
    context manager).
    """
    box = parent.container(border=True)
    box.markdown(f"**{title}**")
    if hint:
        box.caption(hint)
    return box.text_area(title, value=prefill, key=key, height=height,
                         label_visibility="collapsed")


def _jtbd_builder(team, ctype, val):
    """Jobs-to-Be-Done job-statement builder — compose a real 'job' (situation →
    motivation → outcome, with functional/social/emotional dimensions) and drop it
    into the Customer Jobs box. Kept in a bordered container (not an expander) so it
    doesn't collapse while you type."""
    key = f"{ctype}_customer_jobs"
    with st.container(border=True):
        st.markdown("**🧩 Job-statement builder — Jobs to Be Done**")
        st.caption("A strong customer job isn't a feature — it's what the customer is trying to get "
                   "done. Fill the three parts, tag the dimensions, then add it to Customer Jobs.")
        c1, c2, c3 = st.columns(3)
        situation = c1.text_input("When… (situation / trigger)", key="jtbd_sit",
                                  placeholder="it's 6pm on a weeknight")
        motivation = c2.text_input("I want to… (motivation)", key="jtbd_mot",
                                   placeholder="get a healthy dinner ready fast")
        outcome = c3.text_input("so I can… (outcome)", key="jtbd_out",
                                placeholder="feel calm, not stressed")
        dims = st.multiselect("Job dimensions", content.JTBD_DIMENSION_NAMES, key="jtbd_dims",
                              help="Most jobs have a functional core plus social and/or emotional sides.")
        preview = content.compose_job_statement(situation, motivation, outcome, dims)
        st.markdown(f"📝 **Preview:** {preview}")
        if st.button("➕ Add to Customer Jobs", key="jtbd_add", type="primary"):
            cur_txt = st.session_state.get(key, val("customer_jobs")) or ""
            st.session_state[key] = (cur_txt + ("\n" if cur_txt.strip() else "") + preview)
            st.rerun()
        st.caption("Dimensions — " + "  ·  ".join(f"**{n}**: {d}" for n, d in content.JTBD_DIMENSIONS))


def _customer_profile_layout(ctype, val):
    """Strategyzer Customer Profile (the circle): Gains top-left, Jobs right, Pains bottom-left."""
    st.caption("The customer 'circle' — Gains at the top-left, Customer Jobs on the right, "
               "Pains at the bottom-left, just like the Strategyzer profile.")
    data = {}
    left, right = st.columns([1, 1])
    data["gains"] = _cbox(left, "🙂 Gains", f"{ctype}_gains", val("gains"),
                          130, "Benefits and positive outcomes the customer wants.")
    data["pains"] = _cbox(left, "🙁 Pains", f"{ctype}_pains", val("pains"),
                          130, "Frustrations, risks, and obstacles they experience.")
    data["customer_jobs"] = _cbox(right, "☑ Customer Job(s)", f"{ctype}_customer_jobs",
                                  val("customer_jobs"), 292,
                                  "Functional, social, and emotional jobs they're trying to get done.")
    return data


def _environment_layout(ctype, val):
    """Business Model Environment Canvas — trends (top) and forces (bottom) around the model."""
    st.caption("Scan the environment around your model. TRENDS (what's emerging) across the top; "
               "FORCES (what's acting on you now) across the bottom; the disruptive competitive "
               "forces sit at the centre.")
    data = {}
    st.markdown("**⬆ Emerging trends**")
    t = st.columns(3)
    data["customer_trends"] = _cbox(t[0], "👥 Customer Trends", f"{ctype}_customer_trends",
                                    val("customer_trends"), 130, content.ENVIRONMENT_BLOCKS[0][2])
    data["technology_trends"] = _cbox(t[1], "💻 Technology Trends", f"{ctype}_technology_trends",
                                      val("technology_trends"), 130, content.ENVIRONMENT_BLOCKS[1][2])
    data["mega_trends"] = _cbox(t[2], "🌍 Dynamic Mega Trends", f"{ctype}_mega_trends",
                                val("mega_trends"), 130, content.ENVIRONMENT_BLOCKS[2][2])
    st.markdown("**◎ Disruptive / competitive forces (centre)**")
    data["disruptive_forces"] = _cbox(st, "⚔ Disruptive / Competitive Forces",
                                      f"{ctype}_disruptive_forces", val("disruptive_forces"),
                                      110, content.ENVIRONMENT_BLOCKS[6][2])
    st.markdown("**⬇ Forces acting now**")
    f = st.columns(3)
    data["market_forces"] = _cbox(f[0], "📈 Market Forces", f"{ctype}_market_forces",
                                  val("market_forces"), 130, content.ENVIRONMENT_BLOCKS[4][2])
    data["industry_forces"] = _cbox(f[1], "🏭 Industry Forces", f"{ctype}_industry_forces",
                                    val("industry_forces"), 130, content.ENVIRONMENT_BLOCKS[5][2])
    data["macro_forces"] = _cbox(f[2], "💱 Macro-Economic Forces", f"{ctype}_macro_forces",
                                 val("macro_forces"), 130, content.ENVIRONMENT_BLOCKS[3][2])
    return data


def _vpc_layout(ctype, val):
    """Value Proposition Canvas: value map (square, left) + customer profile (circle, right)."""
    st.caption("Left = **Value Map** (the square, your offer). Right = **Customer Profile** "
               "(the circle, the customer). A good value proposition 'fits': gain creators → "
               "gains, pain relievers → pains, products & services → jobs.")
    left, right = st.columns(2)
    data = {}
    left.markdown("#### ▮ Value Map")
    data["gain_creators"] = _cbox(left, "➕ Gain Creators (top)", f"{ctype}_gain_creators",
                                  val("gain_creators"), 100,
                                  "How your offer produces the gains customers want.")
    data["products_services"] = _cbox(left, "📦 Products & Services (centre)",
                                      f"{ctype}_products_services", val("products_services"),
                                      100, "What you offer that addresses the customer's jobs.")
    data["pain_relievers"] = _cbox(left, "🩹 Pain Relievers (bottom)", f"{ctype}_pain_relievers",
                                   val("pain_relievers"), 100,
                                   "How your offer eases specific customer pains.")
    right.markdown("#### ◯ Customer Profile")
    data["gains_created"] = _cbox(right, "😀 Gains (top)", f"{ctype}_gains_created",
                                  val("gains_created"), 100, "The specific gains you create.")
    data["jobs_addressed"] = _cbox(right, "🎯 Customer Jobs (centre)", f"{ctype}_jobs_addressed",
                                   val("jobs_addressed"), 100, "The jobs this proposition targets.")
    data["pains_reduced"] = _cbox(right, "😣 Pains (bottom)", f"{ctype}_pains_reduced",
                                  val("pains_reduced"), 100, "The specific pains you reduce.")
    return data


def _bmc_layout(ctype, val):
    """Business Model Canvas in its canonical nine-block grid."""
    st.caption("The nine blocks in their standard Strategyzer positions. Infrastructure on the "
               "left, customers on the right, value in the centre, finances along the bottom. "
               "Remember: the blocks depend on each other.")
    data = {}
    top = st.columns(5)
    data["key_partners"] = _cbox(top[0], "🤝 Key Partners", f"{ctype}_key_partners",
                                 val("key_partners"), 240, "Who helps you?")
    data["key_activities"] = _cbox(top[1], "⚙️ Key Activities", f"{ctype}_key_activities",
                                   val("key_activities"), 100, "What you must do well.")
    data["key_resources"] = _cbox(top[1], "🏭 Key Resources", f"{ctype}_key_resources",
                                  val("key_resources"), 100, "Assets the model requires.")
    data["value_propositions"] = _cbox(top[2], "💡 Value Propositions", f"{ctype}_value_propositions",
                                       val("value_propositions"), 240, "The value you deliver.")
    data["customer_relationships"] = _cbox(top[3], "❤️ Customer Relationships",
                                           f"{ctype}_customer_relationships",
                                           val("customer_relationships"), 100,
                                           "The relationship each segment expects.")
    data["channels"] = _cbox(top[3], "🚚 Channels", f"{ctype}_channels", val("channels"),
                             100, "How you reach and deliver to customers.")
    data["customer_segments"] = _cbox(top[4], "👥 Customer Segments", f"{ctype}_customer_segments",
                                      val("customer_segments"), 240, "For whom you create value.")
    bottom = st.columns(2)
    data["cost_structure"] = _cbox(bottom[0], "💸 Cost Structure", f"{ctype}_cost_structure",
                                   val("cost_structure"), 100, "The dominant costs.")
    data["revenue_streams"] = _cbox(bottom[1], "💰 Revenue Streams", f"{ctype}_revenue_streams",
                                    val("revenue_streams"), 100, "How you earn revenue.")
    return data


def canvases(team):
    st.subheader("🗂️ Canvases")
    _why("Canvases")
    editable = _round_gate("Canvases", team)
    cur = db.current_round()
    _guide(
        "These are the real Strategyzer canvases, laid out as they appear on paper. Treat every "
        "box as a **hypothesis** you'll later test, not a fact. Each time you learn something, "
        "save a NEW version with a note on what changed — the simulation grades how your "
        "thinking evolves. Each canvas is staged to its own round: "
        f"Customer Profile (R{logic.canvas_unlock_round('customer_profile')}), "
        f"Value Proposition Canvas (R{logic.canvas_unlock_round('vpc')}), "
        f"Business Model Canvas (R{logic.canvas_unlock_round('bmc')}), "
        f"Environment Canvas (R{logic.canvas_unlock_round('environment')}). "
        "Under Strict round mode you can only EDIT the canvas that belongs to the current round.",
        steps=[
            "Work on the canvas that's in focus this round (shown below).",
            "Fill the boxes in their canonical positions. Empty is fine early on.",
            "Add a short 'what changed / why' note, then Save to create a dated version.",
            "Return after experiments and save new versions as evidence comes in.",
        ],
        terms=[
            ("Customer Profile", "The circle: jobs, pains, and gains of one segment."),
            ("Value Proposition Canvas", "Value map (square) + customer profile (circle) — the 'fit'."),
            ("Business Model Canvas", "The nine blocks of the whole business."),
            ("Environment Canvas", "The trends and forces surrounding the model (UNITE scan)."),
        ],
    )
    _ai_check_notice(team, tool_area="Business Model")

    focuses = logic.canvas_focus_for_round(cur)   # list (a round may cover several)
    focus_names = [_CANVAS_DEFS[f][0] for f in focuses if f in _CANVAS_DEFS]
    if focus_names:
        st.info("🎯 **This round's canvas focus:** " + ", ".join(focus_names))

    canvas_keys = list(_CANVAS_DEFS.keys())
    default_idx = canvas_keys.index(focuses[0]) if focuses and focuses[0] in canvas_keys else 0
    ctype = st.selectbox(
        "Canvas type", canvas_keys, index=default_idx,
        format_func=lambda k: _CANVAS_DEFS[k][0],
        help="Customer Profile → Value Proposition Canvas → Business Model Canvas → "
             "Environment Canvas is the guided order; each belongs to its own round.",
    )
    title, blocks = _CANVAS_DEFS[ctype]
    if ctype == "customer_profile":
        _exemplar_customer_profile()

    # Per-canvas editability: under strict mode a canvas is editable only in its round.
    canvas_ok = logic.canvas_editable(ctype, cur, team["id"]) and editable
    unlock = logic.canvas_unlock_round(ctype)
    _focus_rounds = logic.active_rounds_for_canvas(ctype)
    _focus_when = logic.rounds_phrase(_focus_rounds) if _focus_rounds else f"Round {unlock}"
    if cur < unlock:
        st.warning(f"🔒 The {title} is introduced in **Round {unlock}**. It's view-only "
                   f"(input disabled) until then.")
    elif not canvas_ok and editable:
        st.info(f"👁️ The {title} is the focus in **{_focus_when}**, not this round, so its "
                f"input is disabled now. Your saved versions are shown below and carry forward.")

    _canvas_diagram(ctype)
    st.caption(_CANVAS_HELP[ctype])

    existing = db.list_canvases(team["id"], ctype)
    latest = existing[-1] if existing else None

    def val(key):
        return latest["data"].get(key, "") if latest else ""

    st.write(f"### {title}")
    # Inline validation: how complete is the latest saved version?
    _filled = sum(1 for key, _lbl, _ in blocks if str(val(key)).strip())
    _total = len(blocks)
    st.markdown(_progress_ring(_filled, _total, 40)
                + f" <span style='opacity:.75'>{_filled}/{_total} blocks filled — empty is fine "
                "early; fill them from real evidence.</span>", unsafe_allow_html=True)
    if existing:
        st.caption(f"{len(existing)} version(s) saved. Editing starts from the latest.")

    if canvas_ok and ctype == "customer_profile":
        _jtbd_builder(team, ctype, val)

    if canvas_ok:
        _ai_ack_popover(team, f"Canvas: {title}", f"canvas_ai_{ctype}", label=_AI_LOG_LABEL)
        with st.form(f"canvas_{ctype}", clear_on_submit=False):
            if ctype == "customer_profile":
                data = _customer_profile_layout(ctype, val)
            elif ctype == "vpc":
                data = _vpc_layout(ctype, val)
            elif ctype == "environment":
                data = _environment_layout(ctype, val)
            else:
                data = _bmc_layout(ctype, val)

            st.divider()
            vlabel = st.text_input(
                "Version label (optional)", value=f"{title} v{len(existing)+1}",
                help="A name for this snapshot, e.g. 'after 5 interviews'. Auto-filled for you.")
            note = st.text_input(
                "What changed / why (evidence-driven?)",
                help="One line on what you changed and what evidence prompted it. This is graded — "
                     "it shows your thinking evolved for a reason.")
            if st.form_submit_button(f"Save new {title} version",
                                     help="Store the current boxes as a new dated version."):
                v = db.save_canvas(team["id"], ctype, data, vlabel, note)
                st.success(f"Saved {title} version {v}.")
                st.rerun()
    elif latest:
        st.caption("Latest saved version (read-only this round):")
        for key, label, _ in blocks:
            st.markdown(f"**{label}**")
            st.write(latest["data"].get(key) or "_(empty)_")

    if existing:
        st.divider()
        st.write("### Version history")
        for cv in reversed(existing):
            with st.expander(f"v{cv['version']} · {cv['label']} · {cv['created_at']}"):
                if cv["note"]:
                    st.caption(f"Change note: {cv['note']}")
                for key, label, _ in blocks:
                    st.markdown(f"**{label}**")
                    st.write(cv["data"].get(key) or "_(empty)_")


# --------------------------------------------------------------------------- #
# Assumption map / market
# --------------------------------------------------------------------------- #
def assumptions(team):
    st.subheader("🎯 Assumption Map & Market")
    _why("Assumption Map")
    editable = _round_gate("Assumption Map", team)
    _ai_check_notice(team, tool_area="Assumptions")
    _guide(
        "Every box on your canvases hides an assumption — something that must be TRUE for the "
        "venture to work. Here you list those assumptions and rank them. The simulation "
        "penalizes you if an assumption you called important turns out false and you never "
        "tested it, so this page tells you what to test next.",
        steps=[
            "Write each assumption as a statement that must be true (see the example).",
            "Pick its risk type and set the three sliders.",
            "Add it. The list auto-sorts by priority (important + little evidence = top).",
            "Take the top assumptions to the Experiment Marketplace to test them.",
            "Update an assumption's status as you learn (Supported / Refuted).",
        ],
        terms=[
            ("Desirability", "Do customers actually want it?"),
            ("Feasibility", "Can we build and deliver it?"),
            ("Viability", "Can we make money — will they pay, do the costs work?"),
            ("Adaptability", "Will it survive competitors, rules, and change?"),
            ("Priority", "Importance × how little evidence you have. High = test this first."),
        ],
    )

    if editable:
        _ai_ack_popover(team, "Assumption Map", "asm_ai", label=_AI_LOG_LABEL)
        with st.form("add_assumption", clear_on_submit=True):
            text = st.text_input(
                "Assumption (state it as something that must be true)",
                placeholder="Customers will pay at least $20/month for this.",
                help="Phrase it as a testable claim. Good: 'Coffee shops will pay $49/mo.' "
                     "Bad: 'Pricing.'")
            c1, c2, c3, c4 = st.columns(4)
            risk = c1.selectbox(
                "Risk type", content.RISK_TYPES,
                help="Which kind of risk is this? Desirability = do they want it; Feasibility = "
                     "can we build it; Viability = does the money work; Adaptability = will it last.")
            importance = c2.slider(
                "Importance", 1, 5, 3,
                help="If this assumption is FALSE, how badly is the venture hurt? "
                     "5 = the whole venture collapses.")
            evidence_level = c3.slider(
                "Existing evidence", 1, 5, 1,
                help="How much solid evidence do you already have for this? "
                     "1 = only a hunch, 5 = strong proof.")
            testability = c4.slider(
                "Testability", 1, 5, 3,
                help="How easily can you test this cheaply and quickly? 5 = very easy to test.")
            if st.form_submit_button("Add assumption",
                                     help="Save this assumption to your map.") and text:
                db.add_assumption(team["id"], text, risk, importance, evidence_level, testability)
                st.success("Assumption added.")
                st.rerun()

    assums = db.list_assumptions(team["id"])
    if not assums:
        st.info("No assumptions yet. Add the beliefs your venture depends on using the form above.")
        return

    st.divider()
    st.write("### Prioritization — importance vs. evidence")
    st.caption("Sorted so the riskiest untested beliefs are at the top. "
               "Priority = importance × (6 − existing evidence).")
    for a in assums:
        priority = a["importance"] * (6 - a["evidence_level"])
        with st.expander(
            f"[{a['status']}] {a['text']}  ·  {a['risk_type']}  ·  priority {priority}"
        ):
            c1, c2, c3 = st.columns(3)
            c1.write(f"Importance: {a['importance']}/5")
            c2.write(f"Existing evidence: {a['evidence_level']}/5")
            c3.write(f"Testability: {a['testability']}/5")
            new_status = st.selectbox(
                "Status", ["Untested", "Testing", "Supported", "Refuted", "Ignored"],
                index=["Untested", "Testing", "Supported", "Refuted", "Ignored"].index(a["status"]),
                key=f"astatus_{a['id']}", disabled=not editable,
                help="Untested = no evidence yet; Testing = experiment running; "
                     "Supported/Refuted = evidence came back; Ignored = you chose not to test "
                     "(risky if it's important).",
            )
            if editable:
                cc1, cc2 = st.columns(2)
                if cc1.button("Update status", key=f"aupd_{a['id']}",
                              help="Save the status you selected."):
                    db.update_assumption(a["id"], status=new_status)
                    st.rerun()
                if cc2.button("Delete", key=f"adel_{a['id']}",
                              help="Remove this assumption."):
                    db.delete_assumption(a["id"])
                    st.rerun()


# --------------------------------------------------------------------------- #
# Experiment marketplace
# --------------------------------------------------------------------------- #
def experiments(team):
    st.subheader("🧪 Experiment Marketplace")
    _why("Experiment Marketplace")
    editable = _round_gate("Experiment Marketplace", team)
    _guide(
        "This is where you buy tests for your assumptions. Each experiment card costs money, "
        "hours, and Evidence Credits, and gives evidence of a certain strength. The key "
        "discipline: you must write down what result would count as success or failure BEFORE "
        "you run it, so you can't move the goalposts afterward.",
        steps=[
            "Pick an experiment card and read its cost, strength, and best-fit risk type.",
            "Choose which assumption it tests.",
            "Write a hypothesis, a metric, and success + failure thresholds.",
            "Write your decision rule (what you'll do for each outcome).",
            "Purchase & design it — resources are deducted and the assumption is marked 'Testing.'",
            "Run the test in the real world, then record the result and outcome below.",
        ],
        terms=[
            ("Evidence strength", "How convincing this test is, 0–10. Behavior beats opinions."),
            ("Metric", "The single number you'll measure, e.g. '# who request a trial.'"),
            ("Threshold", "The line that defines success vs. failure, set in advance."),
            ("Decision rule", "What you'll DO for each outcome — persevere, pivot, or stop."),
        ],
    )
    team = logic.sync_round_hours(_refresh_team(team["id"]))
    _resource_bar(team)
    _ai_check_notice(team, tool_area="Experiment design")

    assums = db.list_assumptions(team["id"])
    if not assums:
        st.warning("Add assumptions first on the **Assumption Map** page — every experiment "
                   "must test a specific assumption.")
    st.divider()

    st.write("### Buy & design an experiment")
    card_name = st.selectbox(
        "Experiment card", [c["name"] for c in content.EXPERIMENT_CARDS], disabled=not editable,
        help="Each card is a different way to test a belief. Cheaper cards give weaker "
             "evidence; behavior-based cards (preorder, letter of intent) give the strongest.")
    card = content.EXPERIMENT_CARD_MAP[card_name]
    ic1, ic2, ic3, ic4 = st.columns(4)
    ic1.metric("Money", f"${card['money']}", help="Capital this experiment costs.")
    ic2.metric("Hours", f"{card['hours']}", help="Founder-hours this experiment consumes.")
    ic3.metric("Credits", f"{card['credits']}", help="Evidence Credits this experiment costs.")
    ic4.metric("Evidence strength", f"{card['strength']}/10",
               help="How strong the resulting evidence is if the test is done well.")
    _phase = content.experiment_phase(card_name)
    _phicon = "🔎" if _phase == "Discovery" else "✅"
    st.markdown(f"{_phicon} **{_phase}** experiment  ·  **{content.strength_label(card['strength'])}** "
                f"evidence  ·  best for **{card['suits']}** assumptions")
    st.caption(f"Min sample: {card['sample']} · Watch for bias: {card['bias']}")
    with st.expander("🔬 Discovery vs. Validation (Testing Business Ideas)"):
        st.caption("**Discovery** tests are cheap and fast — they explore whether a problem/solution "
                   "is real (interviews, observation, prototypes, landing pages). **Validation** tests "
                   "cost more but give stronger evidence by asking for real commitment (pre-orders, "
                   "letters of intent, concierge, sales). Rule of thumb: **test cheap first, then "
                   "escalate** to a stronger test once discovery looks promising.")

    if editable:
      _ai_ack_popover(team, "Experiment Marketplace", "exp_ai", label=_AI_LOG_LABEL)
      with st.form("buy_experiment", clear_on_submit=True):
        if assums:
            assum_id = st.selectbox(
                "Assumption tested",
                [a["id"] for a in assums],
                format_func=lambda i: next(a["text"] for a in assums if a["id"] == i),
                help="Which belief will this experiment test? Pick the riskiest untested one.")
        else:
            assum_id = None
        hypothesis = st.text_area(
            "Hypothesis",
            placeholder="We believe independent coffee shops will pay $49/mo for automated inventory forecasting.",
            help="Your specific, falsifiable prediction. Start with 'We believe…' and include "
                 "who, what, and how much.")
        metric = st.text_input(
            "Metric", placeholder="Number of shop owners requesting a trial",
            help="The one number you'll measure to judge the hypothesis.")
        c1, c2 = st.columns(2)
        success = c1.text_input(
            "Success threshold", placeholder="≥5 request a trial and ≥2 share sales data",
            help="The result that would make you believe the assumption. Set it BEFORE testing.")
        failure = c2.text_input(
            "Failure threshold", placeholder="≤1 requests a trial",
            help="The result that would make you reject the assumption. Set it BEFORE testing.")
        decision = st.text_input(
            "Decision rule",
            placeholder="If supported, build clickable prototype; if refuted, revisit segment",
            help="What you will actually DO depending on the outcome.")
        st.markdown("**🔮 Predict before you run it** — commit to a forecast now; you'll compare "
                    "it to reality afterward. Making and checking predictions is how founders "
                    "build judgment (and catch their own overconfidence).")
        pc1, pc2 = st.columns(2)
        predicted = pc1.selectbox(
            "Your prediction", ["Supported", "Refuted", "Inconclusive"],
            help="Do you expect this test to SUPPORT or REFUTE the assumption? Be honest — a "
                 "prediction you're afraid to be wrong about is the most useful one.")
        confidence = pc2.slider(
            "Confidence in your prediction (%)", 50, 100, 70,
            help="How sure are you? 50 = a coin flip; 100 = certain. You'll see later how your "
                 "confidence compared to how often you were actually right.")
        submitted = st.form_submit_button(
            "Purchase & design experiment",
            help="Deducts the cost and saves the experiment. The assumption becomes 'Testing.'")
        if submitted:
            if assum_id is None:
                st.error("Add an assumption to test first (Assumption Map page).")
            elif not hypothesis or not success or not failure:
                st.error("Hypothesis, success threshold, and failure threshold are required.")
            else:
                ok, msg, _ = logic.purchase_experiment(
                    team["id"], card, assum_id, hypothesis, metric, success, failure, decision,
                    predicted_outcome=predicted, confidence=int(confidence))
                if ok:
                    db.update_assumption(assum_id, status="Testing")
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)

    st.divider()
    st.write("### Your experiments")
    st.caption("Run each test in the real world, then come back and record what happened.")

    # Calibration scoreboard — forecast vs. reality across resolved experiments.
    cal = logic.calibration_summary(team["id"])
    if cal["n"]:
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Predictions scored", cal["n"],
                  help="Resolved experiments where you made a prediction.")
        k2.metric("Hit rate", f"{cal['hit_rate']:.0f}%",
                  help="How often your prediction matched the actual outcome.")
        k3.metric("Avg confidence", f"{cal['avg_confidence']:.0f}%",
                  help="How sure you said you were, on average.")
        gap = cal["overconfidence_gap"]
        k4.metric("Calibration gap", f"{gap:+.0f}",
                  help="Avg confidence minus hit rate. Positive = overconfident; near 0 = "
                       "well-calibrated; negative = under-confident.")
        if gap is not None and gap >= 15:
            st.warning("🔎 You've been **more confident than correct** — a classic founder trap. "
                       "Treat your strong hunches as the ones most worth testing cheaply first.")
        elif gap is not None and gap <= -15:
            st.info("You've been **more right than you felt** — trust your evidence a bit more, "
                    "and don't over-test what you already know.")
        elif gap is not None:
            st.success("Nicely calibrated — your confidence roughly matches how often you're right.")

    exps = db.list_experiments(team["id"])
    if not exps:
        st.caption("No experiments yet.")
    for e in exps:
        with st.expander(f"[{e['outcome']}] {content.experiment_phase(e['card_type'])} · "
                         f"{e['card_type']} — {e['hypothesis'][:55]}"):
            st.write(f"**Metric:** {e['metric']}")
            st.write(f"**Success threshold:** {e['success_threshold']}")
            st.write(f"**Failure threshold:** {e['failure_threshold']}")
            st.write(f"**Decision rule:** {e['decision_rule']}")
            st.write(f"**Cost:** ${e['cost_money']} · {e['cost_time']}h · {e['cost_credits']} credits · "
                     f"strength {e['evidence_strength']}/10")
            # Prediction vs. actual (the calibration payoff).
            if e.get("predicted_outcome"):
                line = f"**🔮 You predicted:** {e['predicted_outcome']}"
                if e.get("confidence") is not None:
                    line += f" · {e['confidence']}% confident"
                st.write(line)
                pc = logic.prediction_correct(e)
                if pc is True:
                    st.success(f"✅ Your prediction was right — actual outcome was **{e['outcome']}**.")
                elif pc is False:
                    st.error(f"❌ Reality disagreed — you predicted **{e['predicted_outcome']}** but "
                             f"the outcome was **{e['outcome']}**. That gap is the lesson.")
            if not editable:
                st.write(f"**Observed:** {e['result'] or '_(not recorded)_'}")
                if e.get("learned"):
                    st.write(f"**Learned:** {e['learned']}")
                if e.get("decision"):
                    st.write(f"**Decision:** {e['decision']}")
                continue
            # ---- Learning Card (Strategyzer): believed → tested → observed → learned → decide
            st.markdown("**🃏 Learning Card** — capture the result as a decision, not just a note.")
            st.caption(f"We believed: *{e['hypothesis']}*  ·  We tested with: *{e['card_type']}*  "
                       f"·  measuring *{e['metric']}* (success: {e['success_threshold'] or '—'}).")
            result = st.text_area(
                "Observed — the measured result", value=e["result"] or "", key=f"res_{e['id']}",
                help="The numbers/behavior you actually saw. Compare it to your thresholds.")
            learned = st.text_area(
                "Learned — the insight", value=e.get("learned") or "", key=f"learn_{e['id']}",
                help="What does this evidence tell you about the assumption and the model?")
            oc1, oc2 = st.columns(2)
            outcome = oc1.selectbox(
                "Outcome", ["Designed", "Running", "Supported", "Refuted", "Inconclusive"],
                index=["Designed", "Running", "Supported", "Refuted", "Inconclusive"].index(e["outcome"]),
                key=f"outc_{e['id']}",
                help="Compare the result to your thresholds. Supported/Refuted will auto-update "
                     "the linked assumption. Inconclusive = the test didn't settle it.")
            decision = oc2.selectbox(
                "Decide — next action",
                ["—", "Persevere (keep this belief)", "Pivot (change the model)",
                 "Run a stronger test", "Stop / drop this idea"],
                index=(["—", "Persevere (keep this belief)", "Pivot (change the model)",
                        "Run a stronger test", "Stop / drop this idea"].index(e["decision"])
                       if e.get("decision") in ["Persevere (keep this belief)", "Pivot (change the model)",
                                                "Run a stronger test", "Stop / drop this idea"] else 0),
                key=f"dec_{e['id']}", help="What will you DO because of this evidence?")
            if st.button("Save Learning Card", key=f"saveres_{e['id']}",
                         help="Store the result, insight, and decision; updates the linked assumption."):
                db.update_experiment(e["id"], result=result, outcome=outcome,
                                     learned=learned, decision=("" if decision == "—" else decision))
                if e["assumption_id"] and outcome in ("Supported", "Refuted"):
                    db.update_assumption(e["assumption_id"], status=outcome)
                st.success("Saved.")
                st.rerun()


# --------------------------------------------------------------------------- #
# Evidence ledger
# --------------------------------------------------------------------------- #
def _mom_test_coach():
    """Interview coaching (The Mom Test): a live question checker plus the rules and
    the commitment ladder. Coaching only — nothing is stored."""
    with st.expander("🧪 Interview coach — “The Mom Test” (check a question before you ask it)"):
        st.caption("Good evidence starts with good questions. The Mom Test's rules keep you from "
                   "collecting polite lies:")
        for r in content.MOM_TEST_RULES:
            st.markdown(f"- {r}")
        q = st.text_input("Paste a question you plan to ask a customer",
                          key="momtest_q", placeholder="e.g. Tell me about the last time you tried to solve this.")
        res = logic.mom_test_check(q)
        if res["score"] is not None:
            fn = st.success if res["score"] >= 70 else (st.warning if res["score"] >= 40 else st.error)
            fn(f"{res['score']}/100 — {res['verdict']}")
            for iss in res["issues"]:
                st.markdown(f"  • ⚠️ “…{iss['pattern']}…” — {iss['why']}  \n    ↳ *Try instead:* {iss['better']}")
            if res["good"]:
                st.caption("👍 Grounded in real behavior: " + ", ".join(f"“{g}”" for g in res["good"]))
        st.markdown("**Commitment ladder** — a real signal is a commitment, not a compliment:")
        for name, desc in content.EVIDENCE_SIGNALS:
            st.markdown(f"- **{name}** — {desc}")


def evidence(team):
    st.subheader("📒 Evidence Ledger")
    _why("Evidence Ledger")
    _exemplar_evidence()
    editable = _round_gate("Evidence Ledger", team)
    _ai_check_notice(team, tool_area="Other")
    _guide(
        "This is your proof file and your income source. Every time you gather real evidence, "
        "log it here. The simulation pays you Evidence Credits equal to the evidence's strength "
        "on the ladder below — so a signed letter of intent (9) is worth far more than a "
        "friend saying 'cool idea' (1). Behavior beats opinion.",
        steps=[
            "Open the ladder below to see how evidence is valued.",
            "Describe what you learned in one line.",
            "Pick the evidence type that matches HOW you learned it.",
            "Add the source and optionally link it to an assumption.",
            "Log it — you're paid credits automatically based on strength.",
        ],
        terms=[
            ("Behavioral evidence", "Based on what customers DID (bought, signed, tried). "
             "Strength 6+."),
            ("Opinion evidence", "Based on what people SAID they might do. Strength 0–2, "
             "easy to get but weak."),
            ("Evidence Credits", "Currency you earn here and spend on experiments and pivots."),
        ],
    )

    with st.expander("📊 Evidence-strength ladder — how each type is valued"):
        st.table([{"Evidence": lbl, "Value (0–10)": val} for lbl, val in content.EVIDENCE_LADDER])

    _mom_test_coach()

    assums = db.list_assumptions(team["id"])
    # Inputs live OUTSIDE a form so the misclassification check updates as you type —
    # the point is to make you weigh "behavior vs opinion" before you log.
    if editable:
        _hdr, _aicol = st.columns([8, 1])
        _hdr.write("### Log a piece of evidence")
        with _aicol:
            _ai_ack_popover(team, "Evidence Ledger", "ev_ai")
        description = st.text_input(
            "What did you learn? (one line)", key="ev_desc",
            placeholder="3 of 5 shop owners asked to join a paid pilot.",
            help="A short factual summary of the evidence, not your interpretation.")
        etype = st.selectbox(
            "Evidence type", [lbl for lbl, _ in content.EVIDENCE_LADDER], key="ev_type",
            help="Choose based on HOW you learned it. Higher on the list = stronger = more "
                 "credits. Be honest: a hallway 'sounds good' is an opinion, not behavior.")
        source = st.text_input(
            "Source", key="ev_src", placeholder="e.g., Interview with 3 coffee-shop owners",
            help="Where the evidence came from — who, how many, and when.")
        justification = st.text_input(
            "Why is this that strength? (behavior vs. opinion)", key="ev_just",
            placeholder="They physically pre-paid a $20 deposit — that's an action, not a "
                        "stated intention.",
            help="Required. In one line, justify the strength you picked. Naming what the "
                 "customer DID (vs. said) is how you learn to tell strong evidence from weak.")
        strength = content.EVIDENCE_LADDER_MAP.get(etype, 0)
        st.caption(f"Selected strength: **{strength}/10** → "
                   f"{'behavioral (what they did)' if strength >= 6 else 'opinion/intention (what they said)' if strength <= 2 else 'mid-ladder'}")

        # Live misclassification nudge — compares your wording to the strength you chose.
        flags = logic.evidence_flags(description, source, strength) if description else []
        for f in flags:
            st.warning("🔎 " + f)

        if assums:
            assum_id = st.selectbox(
                "Related assumption (optional)",
                [None] + [a["id"] for a in assums], key="ev_assum",
                format_func=lambda i: "—" if i is None else next(a["text"] for a in assums if a["id"] == i),
                help="Link this evidence to the assumption it supports or challenges.")
        else:
            assum_id = None

        can_log = bool(description.strip()) and bool(justification.strip())
        if not can_log:
            st.caption("Enter a one-line learning **and** a justification to log.")
        if st.button("Log evidence", type="primary", disabled=not can_log,
                     help="Records the evidence and pays you credits equal to its strength."):
            award, strn = logic.log_evidence_and_award(
                team["id"], description, etype, source, assum_id, justification)
            msg = f"Logged. Strength {strn}/10 → earned {award} Evidence Credits."
            if flags:
                st.warning(msg + " (Heads up: it was flagged for a possible strength mismatch — "
                                  "your instructor can see the flag too.)")
            else:
                st.success(msg)
            for k in ("ev_desc", "ev_src", "ev_just"):
                st.session_state.pop(k, None)
            st.rerun()

    st.divider()
    esum = logic.evidence_summary(team["id"])
    ev = db.list_evidence(team["id"])
    flagged = sum(1 for e in ev
                  if logic.evidence_flags(e["description"], e["source"], e["strength"]))
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Items", esum["count"], help="Total pieces of evidence logged.")
    c2.metric("Avg strength", esum["avg_strength"],
              help="Average strength of your evidence. Aim to raise this over time.")
    c3.metric("Behavioral", esum["behavioral"], help="Evidence of strength 6+ (what people did).")
    c4.metric("Opinion-only", esum["opinion"], help="Weak evidence of strength ≤2 (what people said).")
    c5.metric("⚠️ Flagged", flagged,
              help="Items whose wording may not match the strength you chose. Open the list "
                   "below to review and re-log if needed.")

    if ev:
        st.write("### Your evidence")
        for e in ev:
            efl = logic.evidence_flags(e["description"], e["source"], e["strength"])
            icon = "⚠️" if efl else "•"
            with st.expander(f"{icon} [{e['strength']}/10] {e['description'][:70]}"):
                st.write(f"**Type:** {e['evidence_type']}  ·  **Credits:** {e['credits_award']}")
                st.write(f"**Source:** {e['source'] or '—'}")
                if e.get("justification"):
                    st.write(f"**Why this strength:** {e['justification']}")
                for f in efl:
                    st.warning("🔎 " + f)


# --------------------------------------------------------------------------- #
# Value Proposition Auction
# --------------------------------------------------------------------------- #
def vp_auction(team):
    st.subheader("💠 Value Proposition Auction")
    _why("VP Auction")
    editable = _round_gate("VP Auction", team)
    _ai_check_notice(team, tool_area="Value Proposition")
    _guide(
        f"You created several value propositions — now show which you back most. You have "
        f"{content.VENTURE_TOKEN_POOL} Venture Tokens to spread across them. Betting big on an "
        "idea your evidence doesn't support costs you credits (an Overconfidence Tax). Moving "
        "your tokens toward better-supported ideas after you learn earns you credits (a Learning "
        "Dividend). This rewards changing your mind when the evidence says so.",
        steps=[
            f"Create at least {content.MIN_VALUE_PROPS} value propositions (form below).",
            "Set each one's evidence support (0–10) to match what your Evidence Ledger shows.",
            f"Allocate your {content.VENTURE_TOKEN_POOL} tokens across them.",
            "Watch the live preview: aim for high Alignment, low Tax.",
            "Submit. Net credits (dividend − tax) are applied and the round is recorded.",
        ],
        terms=[
            ("Value proposition", "One specific way you create value for the customer segment."),
            ("Evidence support", "How well real evidence backs this proposition, 0–10."),
            ("Alignment", "Your tokens weighted by evidence support. High = you're backing "
             "what the evidence supports."),
            ("Overconfidence Tax", "Credit penalty for putting tokens on weakly-supported ideas."),
            ("Learning Dividend", "Credit reward for shifting tokens toward evidence vs. last time."),
        ],
    )

    props = db.list_value_props(team["id"])

    if not editable:
        # Reference-only this round: show existing work read-only, no inputs.
        st.write("### Your value propositions")
        if props:
            for p in props:
                st.write(f"- **{p['name']}** · evidence {p['evidence_strength']}/10 · "
                         f"{p['tokens']} tokens")
        else:
            st.caption("No value propositions logged yet.")
        results = db.list_vp_results(team["id"])
        if results:
            st.divider()
            st.write("### Auction history")
            st.dataframe(
                [{"When": r["created_at"], "Round": r["round"], "Tokens": r["total_tokens"],
                  "Alignment": r["alignment"], "Prev": r["prev_alignment"],
                  "Tax": r["tax"], "Dividend": r["dividend"], "Net": r["net_credits"]}
                 for r in results],
                use_container_width=True, hide_index=True,
            )
        return

    # ---- Manage propositions -------------------------------------------------
    st.write("### Your value propositions")
    st.caption("Set each proposition's evidence support (0–10) to reflect your evidence "
               "ledger. The Director can override this to match real evidence quality.")
    for p in props:
        with st.expander(f"{p['name']}  ·  evidence {p['evidence_strength']}/10  ·  "
                         f"{p['tokens']} tokens"):
            st.write(p["description"] or "_(no description)_")
            new_ev = st.slider(
                "Evidence support", 0, 10, int(p["evidence_strength"]),
                key=f"vpev_{p['id']}",
                help="How strongly does real evidence back this proposition? 0 = pure hope, "
                     "10 = customers are paying. Be honest — the Director can override it.")
            c1, c2 = st.columns(2)
            if c1.button("Update evidence", key=f"vpupd_{p['id']}", disabled=not editable,
                         help="Save the evidence-support level you set."):
                db.update_value_prop(p["id"], evidence_strength=new_ev)
                st.rerun()
            if c2.button("Delete", key=f"vpdel_{p['id']}", disabled=not editable,
                         help="Remove this proposition."):
                db.delete_value_prop(p["id"])
                st.rerun()

    _ai_ack_popover(team, "VP Auction", "vp_ai", label=_AI_LOG_LABEL)
    with st.form("add_vp", clear_on_submit=True):
        st.write("**Add a value proposition**")
        name = st.text_input(
            "Name", help="A short label for this proposition, e.g. 'Subscription forecasting.'")
        desc = st.text_area(
            "Products/services · pain relievers · gain creators",
            help="Describe what you offer and how it eases the customer's pains and creates "
                 "gains.")
        ev = st.slider(
            "Evidence support (0–10)", 0, 10, 0,
            help="Start at 0 if untested. Raise it only as real evidence comes in.")
        if st.form_submit_button("Add proposition", disabled=not editable,
                                 help="Save this proposition to the auction.") and name:
            db.add_value_prop(team["id"], name, desc, ev)
            st.rerun()

    if len(props) < content.MIN_VALUE_PROPS:
        st.warning(f"Add at least {content.MIN_VALUE_PROPS} propositions to run the auction "
                   f"(you have {len(props)}). Competing options stop you from locking onto the "
                   "first idea.")
        return

    # ---- Allocate tokens -----------------------------------------------------
    st.divider()
    st.write(f"### Allocate {content.VENTURE_TOKEN_POOL} Venture Tokens")
    st.caption("Put more tokens on the propositions you're most confident in. The preview "
               "updates as you type.")
    allocations = {}
    cols = st.columns(min(len(props), 4))
    for i, p in enumerate(props):
        with cols[i % len(cols)]:
            allocations[p["id"]] = st.number_input(
                p["name"], min_value=0, max_value=content.VENTURE_TOKEN_POOL,
                value=int(p["tokens"]), step=5, key=f"vptok_{p['id']}",
                help=f"Tokens on '{p['name']}' (evidence {p['evidence_strength']}/10). "
                     "All allocations must sum to no more than the pool.")
    total = sum(allocations.values())
    remaining = content.VENTURE_TOKEN_POOL - total
    (st.error if remaining < 0 else st.caption)(
        f"Allocated {total} / {content.VENTURE_TOKEN_POOL} · {remaining} remaining")

    preview = logic.preview_vp_auction(team["id"], allocations)
    if preview.get("ok"):
        pc1, pc2, pc3, pc4 = st.columns(4)
        pc1.metric("Alignment", preview["alignment"],
                   help="0–1. Your tokens weighted by evidence support. Higher is better.")
        pc2.metric("Overconfidence Tax", f"-{preview['tax']}",
                   help="Credits you'll lose for backing weakly-supported propositions.")
        pc3.metric("Learning Dividend", f"+{preview['dividend']}",
                   help="Credits you'll gain for shifting toward evidence vs. your last auction.")
        pc4.metric("Net credits", preview["net"],
                   help="Dividend minus tax. This is applied when you submit.")
        st.caption("Preview only — nothing is charged until you submit.")
        if st.button("Submit auction round", type="primary", disabled=not editable,
                     help="Locks in this allocation and applies the net credit change."):
            res = logic.run_vp_auction(team["id"], allocations, db.current_round())
            if res.get("committed"):
                st.success(f"Auction resolved. Net change: {res['net']} Evidence Credits "
                           f"(tax {res['tax']}, dividend {res['dividend']}).")
                st.rerun()
            else:
                st.error(res.get("reason", "Could not run auction."))
    else:
        st.info(preview.get("reason", ""))

    # ---- History -------------------------------------------------------------
    results = db.list_vp_results(team["id"])
    if results:
        st.divider()
        st.write("### Auction history")
        st.dataframe(
            [{"When": r["created_at"], "Round": r["round"], "Tokens": r["total_tokens"],
              "Alignment": r["alignment"], "Prev": r["prev_alignment"],
              "Tax": r["tax"], "Dividend": r["dividend"], "Net": r["net_credits"]}
             for r in results],
            use_container_width=True, hide_index=True,
        )


# --------------------------------------------------------------------------- #
# Market events
# --------------------------------------------------------------------------- #
def market_events(team):
    st.subheader("📡 Market Events")
    _why("Market Events")
    _round_gate("Market Events", team)
    _guide(
        "Each round the Director introduces a market event — a competitor move, a rule change, "
        "a cost shock. These aren't random punishments: each one targets an assumption hidden "
        "in your canvas. Read the event, find which of your assumptions it threatens, and "
        "respond by testing, adjusting your model, or filing a pivot. Then try the **lemonade** "
        "move: turn the surprise into an opportunity.",
        terms=[
            ("Assumption exposed", "The belief this event puts pressure on. Go check whether "
             "you have evidence for it."),
            ("Lemonade", "An effectuation principle: leverage surprises and setbacks instead of "
             "just defending against them."),
            ("Broadcast", "An event sent to all teams at once."),
        ],
    )
    evs = db.list_events(team["id"])
    if not evs:
        st.info("No market events yet. The Director issues these starting around week 7.")
        return
    locked = logic.editing_locked(team["id"])
    for e in evs:
        scope = "All teams" if e["team_id"] is None else "Your team"
        icon = "✅" if e["resolved"] else "🔔"
        intro, tail = logic.story_event_text(e["category"], e["exposes"])
        with st.expander(f"{icon} Round {e['round']} · {e['category']} · {scope}"):
            st.markdown(f"**{intro}** {e['text']}{tail}")
            if e["exposes"]:
                st.caption(f"🎯 Assumption exposed: {e['exposes']} — check your evidence for it.")
            if (e.get("exploit") or "").strip():
                st.success(f"🍋 Your opportunity play: {e['exploit']}")
            if not locked:
                with st.form(f"exploit_{e['id']}", clear_on_submit=False):
                    txt = st.text_input(
                        "🍋 Turn this into an opportunity (lemonade)", value=e.get("exploit") or "",
                        help=f"How could this surprise become an advantage? First save earns "
                             f"+{logic.LEMONADE_CREDIT} Evidence Credits.")
                    if st.form_submit_button("Save opportunity play") and txt.strip():
                        r = logic.exploit_event(team["id"], e["id"], txt)
                        st.success("Saved." + (f" +{r} Evidence Credits." if r else ""))
                        st.rerun()


# --------------------------------------------------------------------------- #
# Pivot petition
# --------------------------------------------------------------------------- #
def pivots(team):
    st.subheader("🔀 Pivot Petition")
    _why("Pivot Petition")
    _exemplar_pivot()
    editable = _round_gate("Pivot Petition", team)
    _ai_check_notice(team, tool_area="Pivot reasoning")
    _guide(
        "A pivot is a deliberate change of direction backed by evidence — not just swapping to "
        "a new idea because the old one struggled. You can't simply declare a pivot; you file a "
        "petition and the investment committee (the Director) approves, approves conditionally, "
        "asks for more evidence, or rejects it. Fill in every field so the committee can see the "
        "change is driven by learning.",
        steps=[
            "Name the original assumption that turned out to be wrong.",
            "Cite the evidence that challenged it.",
            "Say which canvas block changes and what the change is.",
            "List the new assumptions the change creates and the evidence you'd need.",
            "Submit — then check back for the committee's decision.",
        ],
        terms=[
            ("Pivot", "A structured change to the business model based on what you learned."),
            ("Affected block", "Which canvas box changes (e.g. Customer Segment, Channel)."),
            ("Committee decision", "Approved, Conditional, Needs Evidence, Rejected, or "
             "'Random Change' if it looks unjustified."),
        ],
    )

    if editable:
      _ai_ack_popover(team, "Pivot Petition", "pivot_ai", label=_AI_LOG_LABEL)
      with st.form("pivot_form", clear_on_submit=True):
        original = st.text_area(
            "Original assumption",
            help="The belief you built on that the evidence has now undermined.")
        challenge = st.text_area(
            "Evidence that challenged it",
            help="What did you learn that shows the original assumption was wrong?")
        block = st.text_input(
            "Value Proposition / Business Model block affected",
            help="Which canvas box changes — e.g. Customer Segment, Channel, Revenue Stream.")
        ptype = st.selectbox(
            "Type of pivot (Lean Startup)", content.PIVOT_TYPE_NAMES,
            index=content.PIVOT_TYPE_NAMES.index("Not sure yet"),
            format_func=lambda n: f"{n} — {content.PIVOT_TYPE_BY_NAME[n]}",
            help="Classifying the pivot forces clarity about WHAT is changing. A disciplined "
                 "pivot keeps one foot on validated learning and changes one thing deliberately.")
        change = st.text_area(
            "Proposed change",
            help="Exactly what you want to change the model to.")
        cost = st.number_input(
            "Cost of the change ($)", min_value=0.0, value=0.0, step=50.0,
            help="Estimated capital the pivot requires. The committee may charge this if approved.")
        new_assums = st.text_area(
            "New assumptions this creates",
            help="A pivot creates fresh beliefs to test. List them here.")
        needed = st.text_area(
            "Evidence required to support the new direction",
            help="What evidence would prove the new direction works?")
        if st.form_submit_button("Submit pivot petition",
                                 help="Send this to the investment committee for a decision."):
            if not original or not change:
                st.error("Original assumption and proposed change are required.")
            else:
                db.add_pivot(team["id"], {
                    "original_assum": original, "challenge_evid": challenge,
                    "affected_block": block, "proposed_change": change,
                    "change_cost": cost, "new_assumptions": new_assums,
                    "evidence_needed": needed, "pivot_type": ptype,
                })
                st.success("Petition submitted to the investment committee.")
                st.rerun()

    st.divider()
    st.write("### Your petitions")
    st.caption("Watch the status and read the committee's note.")
    for p in db.list_pivots(team["id"]):
        with st.expander(f"[{p['status']}] {p['proposed_change'][:60]} · {p['created_at']}"):
            st.write(f"**Original assumption:** {p['original_assum']}")
            st.write(f"**Challenging evidence:** {p['challenge_evid']}")
            st.write(f"**Affected block:** {p['affected_block']}")
            if p.get("pivot_type"):
                st.write(f"**Pivot type:** {p['pivot_type']}")
            st.write(f"**Proposed change:** {p['proposed_change']}")
            st.write(f"**Change cost:** ${p['change_cost']:,.0f}")
            st.write(f"**New assumptions:** {p['new_assumptions']}")
            st.write(f"**Evidence needed:** {p['evidence_needed']}")
            if p["committee_note"]:
                st.info(f"Committee: {p['committee_note']}")


# --------------------------------------------------------------------------- #
# Reflections (individual accountability)
# --------------------------------------------------------------------------- #
def _journal_perspective(team, name, cur):
    """Choose/show the student's perspective (lens) for this round's journal entry.
    Director sets Random (auto-assign to roster members) or Team-controlled (self-pick)."""
    if not name.strip():
        return None
    gid = team.get("game_id")
    mode = logic.perspective_mode(gid)
    st.markdown("#### 🎭 Your perspective this round")
    auto = logic.assigned_perspective(team, name, cur) if mode == "random" else None
    if auto:
        persp = auto
        st.info(f"{persp['icon']} You've been assigned **{persp['name']}** this round "
                "(random rotation set by your instructor).")
    else:
        if mode == "random":
            st.caption("Random assignment needs an imported roster — pick your perspective for now.")
        used = logic.perspectives_used_this_round(team["id"], cur)
        names = content.PERSPECTIVE_NAMES
        existing = db.get_reflection(team["id"], name, cur) or {}
        default = existing.get("perspective") or next((n for n in names if n not in used), names[0])
        idx = names.index(default) if default in names else 0
        pick = st.selectbox("Take a perspective", names, index=idx,
                            format_func=lambda n: f"{content.perspective_by_name(n)['icon']} {n}",
                            help="Rotate perspectives across rounds so you practice all six.")
        persp = content.perspective_by_name(pick)
        if used:
            st.caption("Already taken by teammates this round: " + ", ".join(sorted(used)) + ".")
    st.markdown(f"**🔎 Your lens:** {persp['lens']}")
    with st.expander(f"What does the {persp['name']} do? (full description)"):
        st.markdown(persp["detail"])
    return persp


def reflections(team):
    st.subheader("📝 Entrepreneurial Decision Journal")
    _why("Decision Journal")
    cur = db.current_round()
    topics = logic.topics_for_round(cur)
    focus_key = topics[0]["key"] if topics else None
    focus_q = content.journal_focus(focus_key)
    _guide(
        "Your own 2-minute journal — individual, so learning isn't just the team's. Three quick "
        "prompts plus one that changes with this round's focus. It's pre-filled with what you did "
        "this round so it's fast, and you can come back and edit your entry anytime.",
        terms=[
            ("Round focus", "One prompt tailored to what this round is about."),
            ("My contribution", "What YOU specifically did — this protects against free-riding."),
        ],
    )

    _ai_check_notice(team, tool_area="Investor narrative")

    # Remember who's writing so they don't retype every round. If the team was
    # imported with a roster, offer those member names as a picker.
    members = logic.team_member_names(team)
    if members:
        opts = members + ["✍️ Someone else…"]
        prev = st.session_state.get("journal_name", "")
        idx = opts.index(prev) if prev in members else 0
        pick = st.selectbox("Your name", opts, index=idx,
                            help="Pick your name from the team roster.")
        if pick == "✍️ Someone else…":
            name = st.text_input("Type your name", value=("" if prev in members else prev))
        else:
            name = pick
    else:
        name = st.text_input("Your name", value=st.session_state.get("journal_name", ""),
                             help="Remembered for this session so you don't retype it.")
    if name:
        st.session_state["journal_name"] = name

    # Ground the reflection in what actually happened this round.
    m = logic.learning_metrics(team["id"])
    rs = logic.round_score(team["id"], cur)
    st.caption(
        f"📌 **This round so far** — behavioral evidence {m['behavioral']} · opinion {m['opinion']} "
        f"· test coverage {m['test_coverage']*100:.0f}% · course corrections {m['pivots_evidence']} "
        f"· round score {rs['score']:.0f}/100. Use these as a memory jog.")

    # Close last round's loop: did you do what you said you would?
    prev = db.get_reflection(team["id"], name, cur - 1) if name and cur > 1 else None
    if prev and (prev.get("differently") or "").strip():
        st.info(f"↩️ Last round you wrote you'd do differently: *“{prev['differently']}”* — did you?")

    if logic.editing_locked(team["id"]):
        _committed_banner(team)
    else:
        existing = db.get_reflection(team["id"], name, cur) if name else None
        ex = existing or {}
        if existing:
            st.caption("✏️ Editing your existing entry for this round.")
        persp = _journal_perspective(team, name, cur) if name else None
        _ai_ack_popover(team, "Decision Journal", "journal_ai", label=_AI_LOG_LABEL)
        with st.form("reflection_form", clear_on_submit=False):
            vals = {}
            for keyname, label, stem in content.journal_core(cur):
                vals[keyname] = st.text_area(label, value=ex.get(keyname, ""),
                                             placeholder=stem, key=f"jr_{keyname}_{cur}")
            focus_answer = st.text_area(f"🎯 {focus_q}", value=ex.get("focus_answer", ""),
                                        key=f"jr_focus_{cur}",
                                        help="This prompt changes with the round's topic.")
            persp_note = ""
            if persp:
                persp_note = st.text_area(
                    f"{persp['icon']} As {persp['name']}: {persp['lens']}",
                    value=ex.get("perspective_note", ""), key=f"jr_persp_{cur}",
                    help="Answer this round's key decision from your assigned perspective.")
            with st.expander("Add more (optional)"):
                for keyname, label, stem in content.JOURNAL_OPTIONAL:
                    vals[keyname] = st.text_area(label, value=ex.get(keyname, ""),
                                                 placeholder=stem, key=f"jr_{keyname}_{cur}")
            if st.form_submit_button("Save my entry", type="primary"):
                if not name.strip():
                    st.error("Enter your name first (top of page).")
                elif not (vals["expected"].strip() and vals["occurred"].strip()
                          and vals["differently"].strip()):
                    st.error("The three core prompts are required — a sentence each is plenty.")
                else:
                    db.add_reflection(team["id"], {
                        "student_name": name, "round": cur,
                        "expected": vals["expected"], "occurred": vals["occurred"],
                        "differently": vals["differently"],
                        "assumption": vals.get("assumption", ""),
                        "overlooked": vals.get("overlooked", ""),
                        "contribution": vals.get("contribution", ""),
                        "focus_prompt": focus_q, "focus_answer": focus_answer,
                        "perspective": persp["name"] if persp else "",
                        "perspective_note": persp_note,
                    })
                    st.success("Saved. Come back to edit it anytime before the round advances.")
                    st.rerun()

    # Who on the team has journaled this round?
    this_round = [r for r in db.list_reflections(team["id"]) if r["round"] == cur]
    if this_round:
        st.caption("✅ Journaled this round: " + ", ".join(sorted(
            {r["student_name"] for r in this_round if r["student_name"]})))

    st.divider()
    refs = db.list_reflections(team["id"])
    if refs:
        st.write(f"### {len(refs)} entry(ies) on record")
        for r in refs:
            _ptag = f" · 🎭 {r['perspective']}" if (r.get('perspective') or '').strip() else ""
            with st.expander(f"{r['student_name']} · Round {r['round']}{_ptag} · {r['created_at']}"):
                if (r.get('perspective') or '').strip():
                    st.write(f"**As {r['perspective']}:** {r.get('perspective_note') or '—'}")
                st.write(f"**Expected:** {r['expected']}")
                st.write(f"**Occurred:** {r['occurred']}")
                if (r.get('focus_prompt') or '').strip():
                    st.write(f"**{r['focus_prompt']}** {r.get('focus_answer') or '—'}")
                st.write(f"**Differently:** {r['differently']}")
                for lbl, col in (("Assumption", "assumption"), ("Overlooked", "overlooked"),
                                 ("My contribution", "contribution")):
                    if (r.get(col) or "").strip():
                        st.write(f"**{lbl}:** {r[col]}")


# --------------------------------------------------------------------------- #
# AI Assist Log — generative AI use + AUDIT verification
# --------------------------------------------------------------------------- #
def ai_assist(team):
    st.subheader(f"{_AI_ICON} AI Assist Log")
    _why("AI Assist Log")
    _guide(
        "You're expected to use generative AI every round — to draft canvases, brainstorm "
        "propositions, design experiments, and more. But fluent AI text is NOT evidence: it's "
        "confident opinion until you verify it. Every AI use gets a **full audit** — the prompt, "
        "the AI's output, how you used it, and a quick dropdown check — then verify it later. "
        "Link the claim to an assumption and it **auto-verifies** when your test settles. Only "
        "the checking is rewarded, not the usage.",
        steps=[
            "Log the prompt, the AI's output, and how you used it.",
            "Run the audit with the dropdowns (add notes only if you want).",
            "Link it to the assumption it relates to, so it auto-verifies when you test that.",
            "Run the real test, then set the status (or it flips automatically).",
        ],
        terms=[
            ("How used", "The kind of help — brainstorm, draft, summarize, critique, analyze, etc."),
            ("Audit", "Dropdown checks: assumptions, unsupported claims, sources, and how you'll verify."),
            ("Auto-verify", "A linked assumption that tests Supported/Refuted flips this log for you."),
        ],
    )
    with st.expander("What's the AUDIT check? (reference)"):
        st.markdown(content.AI_PROTOCOL_SUMMARY)
    # Auto-verify anything whose linked test has since resolved.
    flipped = logic.sync_ai_logs(team["id"])
    if flipped:
        st.info(f"✅ {flipped} AI log(s) auto-updated because their linked test resolved.")

    rate = logic.ai_verification_rate(team["id"])
    unv = logic.ai_unverified_count(team["id"])
    if rate is not None:
        st.progress(rate, text=f"AI verification rate: {rate*100:.0f}% — this is what the score "
                               "rewards (evaluating AI), not how much AI you use.")
    if unv:
        st.warning(f"⏳ **{unv} AI use(s) still unverified.** Link each to an assumption and run "
                   "the test, or set its status once you've checked it.")

    # An entry being edited is rendered here (outside the list — expanders can't nest).
    edit_id = st.session_state.get("ai_edit_id")
    edit_log = None
    if edit_id:
        edit_log = next((x for x in db.list_ai_logs(team["id"]) if x["id"] == edit_id), None)

    st.divider()
    if edit_log is not None and not logic.editing_locked(team["id"]):
        st.write("### ✏️ Edit AI log entry")
        if st.button("← Cancel edit", key="ai_cancel_edit"):
            st.session_state.pop("ai_edit_id", None)
            st.rerun()
        _ai_full_log(team, None, f"edit_{edit_id}", existing=edit_log)
    else:
        st.write("### Log AI use")
        st.caption("Record the prompt, the AI's response, and how you used it — then run a quick "
                   "dropdown audit. Logging AI is about *evaluating* it, not using it. Link a claim "
                   "to an assumption and it **auto-verifies** when your test settles.")
        _ai_full_log(team, None, "ailog")

    logs = db.list_ai_logs(team["id"])
    if logs:
        st.divider()
        st.write(f"### Your AI log — {len(logs)} entries · {unv} unverified")
        _locked = logic.editing_locked(team["id"])
        assum_by_id = {a["id"]: a["text"] for a in db.list_assumptions(team["id"])}
        _STATUS_BTN = [("✅ Verified", "Verified"), ("❌ Rejected", "Rejected"),
                       ("✏️ Modified", "Modified"), ("⏳ Unverified", "Unverified")]
        for l in logs:
            icon = {"Verified": "✅", "Rejected": "❌", "Modified": "✏️"}.get(l["status"], "⏳")
            _use = f" · {l['use_type']}" if l.get("use_type") else ""
            _mdl = f" · {l['ai_model']}" if l.get("ai_model") else ""
            with st.expander(f"{icon} R{l['round']} · {l['tool_area']}{_mdl}{_use} · {l['status']}"):
                # Standard AI-use statement — auto-records the model and date/time.
                _mdl_txt = l.get("ai_model") or "an AI assistant"
                _when = l.get("created_at") or "—"
                st.markdown(f"🧾 **AI-use statement:** Used **{_mdl_txt}** on **{_when}** "
                            f"to {(l.get('use_type') or 'assist').lower()} for *{l['tool_area']}*.")
                if l.get("prompt"):
                    st.write(f"**Prompt:** {l['prompt']}")
                st.write(f"**AI output:** {l['ai_output'] or '—'}")
                if l.get("use_type"):
                    st.caption(f"How used: {l['use_type']}")
                audit_rows = [("Assumptions", l.get("audit_a")),
                              ("Unsupported claims", l.get("audit_u")),
                              ("Sources / data", l.get("data_source") or l.get("audit_d")),
                              ("Verify", l.get("verify_plan") or l.get("audit_i")),
                              ("Translate to evidence", l.get("audit_t"))]
                st.markdown("**Audit:** " + " · ".join(
                    f"{lbl}: {v}" for lbl, v in audit_rows if (v or "").strip()) or "—")
                if l.get("assumption_id") and l["assumption_id"] in assum_by_id:
                    st.caption(f"🔗 Linked to assumption: *{assum_by_id[l['assumption_id']]}* "
                               "(auto-verifies when tested)")
                if not _locked:
                    if st.button("✏️ Edit all fields", key=f"aiedit_{l['id']}"):
                        st.session_state["ai_edit_id"] = l["id"]
                        st.rerun()
                    st.caption("Or set the outcome with one click:")
                    cols = st.columns(len(_STATUS_BTN) + 1)
                    for i, (lbl, val) in enumerate(_STATUS_BTN):
                        if cols[i].button(lbl, key=f"aibtn_{val}_{l['id']}",
                                          disabled=(l["status"] == val)):
                            db.update_ai_log(l["id"], status=val)
                            st.rerun()
                    if cols[-1].button("🗑️", key=f"aidl_{l['id']}", help="Delete this log"):
                        db.delete_ai_log(l["id"])
                        st.rerun()
