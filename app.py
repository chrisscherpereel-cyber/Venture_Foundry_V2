"""
Venture Foundry — From hunch to hard evidence
A semester-long entrepreneurship simulation.

Run with:  streamlit run app.py

Two roles:
  • Student / Team — plays the venture (dashboard, canvases, assumptions,
    experiment marketplace, evidence ledger, events, pivots, reflections).
  • Venture Foundry Director (instructor) — sets up teams, controls rounds,
    issues market events, reviews pivot petitions, scores dashboards.

Data persists in a local SQLite database (venture_foundry.db).
Default instructor PIN: foundry  (change it in Director → Round Control).
"""

import os

import streamlit as st
import streamlit.components.v1 as components

import db
import content
import logic
import branding
import views_student as vs
import views_instructor as vi

# Browser-tab favicon: the Molten V logo (falls back to an emoji if unavailable).
_ICON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "favicon.png")


@st.cache_resource(show_spinner=False)
def _page_icon():
    """Decode the favicon once per server process instead of on every rerun."""
    if os.path.exists(_ICON_PATH):
        try:
            from PIL import Image
            img = Image.open(_ICON_PATH)
            img.load()
            return img
        except Exception:
            return _ICON_PATH
    return "🏭"


st.set_page_config(page_title="Venture Foundry — From hunch to hard evidence",
                   page_icon=_page_icon(), layout="wide")


@st.cache_resource(show_spinner=False)
def _init_db_once():
    """Create/migrate the schema once per server process (it used to run on every
    rerun of every session: ~20 statements + a dozen PRAGMA lookups per click)."""
    db.init_db()
    return True


_init_db_once()


def _sync_active_game():
    """Apply date-based auto-advance and round-change side effects for whichever game
    is currently active (a student's game, or the Director's selected game).
    Serialized per game so simultaneous page loads can't double-advance."""
    return logic.sync_active_game()


def _scroll_top_on_change(state_key, page):
    """Scroll the main pane to the top whenever the selected page changes.

    Streamlit reuses (does not remount) a components.html iframe when its HTML is
    byte-for-byte identical across reruns, so an unchanged scroll script would not
    re-execute on the next navigation. We embed a unique NAV TOKEN (the destination
    page + a monotonic counter) so the HTML differs on every navigation, which forces
    the iframe to remount and the scroll to run again — exactly once per navigation."""
    if st.session_state.get(state_key) != page:
        st.session_state[state_key] = page
        token = st.session_state.get("_nav_token", 0) + 1
        st.session_state["_nav_token"] = token
        components.html(
            f"<!-- nav:{page}:{token} -->"
            "<script>(function(){var d=window.parent.document;"
            "function top(){['section.main','[data-testid=\"stMain\"]',"
            "'[data-testid=\"stAppViewContainer\"]'].forEach(function(s){"
            "var e=d.querySelector(s); if(e){e.scrollTo(0,0);}});"
            "try{window.parent.scrollTo(0,0);}catch(e){}}"
            # run now and once more after layout settles, then stop (no continuous forcing)
            "top(); window.parent.requestAnimationFrame(top);})();</script>",
            height=0,
        )

# --------------------------------------------------------------------------- #
# Session state
# --------------------------------------------------------------------------- #
st.session_state.setdefault("role", None)          # "student" | "instructor"
st.session_state.setdefault("team_id", None)
st.session_state.setdefault("instructor_ok", False)


def logout():
    st.session_state.role = None
    st.session_state.team_id = None
    st.session_state.instructor_ok = False
    st.session_state.pop("director_viewing", None)


def _director_view_team(team_id):
    """Director previews the game exactly as a team sees it (replaces the old
    landing-page picker, which let anyone enter any team without a join code)."""
    st.session_state.role = "student"
    st.session_state.team_id = team_id
    st.session_state["director_viewing"] = True
    st.session_state.pop("student_page", None)


def _back_to_director():
    st.session_state.role = "instructor"
    st.session_state.team_id = None
    st.session_state.instructor_ok = True
    st.session_state.pop("director_viewing", None)


# --------------------------------------------------------------------------- #
# Landing / login
# --------------------------------------------------------------------------- #
def landing():
    branding.header()
    st.markdown(
        "> Students do not earn points for having a good idea. They earn resources by "
        "producing **credible evidence** that their business model could work."
    )
    st.write("A semester-long simulation integrating Strategyzer's Value Proposition "
             "Canvas, Business Model Canvas, assumption mapping, experimentation, and "
             "evidence-based pivoting.")

    tab_student, tab_instructor = st.tabs(["🎓 Enter as a Team", "🎩 Enter as Director"])

    with tab_student:
        st.write("Enter your team join code (issued by the Director).")
        code = st.text_input("Join code", key="join_code_input").strip().upper()
        if st.button("Join", type="primary"):
            team = db.get_team_by_code(code)
            if team:
                st.session_state.role = "student"
                st.session_state.team_id = team["id"]
                st.rerun()
            else:
                st.error("No team found with that code.")

    with tab_instructor:
        pin = st.text_input("Instructor PIN", type="password", key="pin_input")
        if st.button("Open Director Console", type="primary"):
            # Slow down PIN guessing: after 5 misses in this session, wait 30 s.
            import time as _time
            fails = st.session_state.get("_pin_fails", 0)
            wait = st.session_state.get("_pin_lock_until", 0) - _time.time()
            if wait > 0:
                st.error(f"Too many attempts — try again in {int(wait) + 1} s.")
            elif logic.check_pin(pin):
                st.session_state["_pin_fails"] = 0
                st.session_state.role = "instructor"
                st.session_state.instructor_ok = True
                st.rerun()
            else:
                fails += 1
                st.session_state["_pin_fails"] = fails
                if fails >= 5:
                    st.session_state["_pin_lock_until"] = _time.time() + 30
                    st.session_state["_pin_fails"] = 0
                st.error("Incorrect PIN.")


# --------------------------------------------------------------------------- #
# Student shell
# --------------------------------------------------------------------------- #
STUDENT_HOME = "Round Briefing"
STUDENT_PAGES = {
    "Round Briefing": vs.round_briefing,
    "Inbox": vs.inbox,
    "Concept Check": vs.concept_check,
    "Decision Journal": vs.reflections,
    "Founder & Opportunity": vs.founder_opportunity,
    "Founder & Team": vs.founder_skills,
    "Canvases": vs.canvases,
    "VP Auction": vs.vp_auction,
    "Assumption Map": vs.assumptions,
    "Experiment Marketplace": vs.experiments,
    "Evidence Ledger": vs.evidence,
    "Market Events": vs.market_events,
    "Pivot Petition": vs.pivots,
    "My Venture": vs.my_venture,
    "Leaderboard": vs.leaderboard,
    "Demo Day": vs.demo_day,
    "AI Assist Log": vs.ai_assist,
}
# Old page names kept as aliases so any deep-link/next-action target still resolves.
STUDENT_PAGE_ALIASES = {"Dashboard": "My Venture", "Progress": "My Venture"}

# Grouped, round-aware navigation so students see what's actionable now, not a wall
# of 18 pages. Locked tools are hidden into an "Opens later" list.
STUDENT_NAV_GROUPS = {
    "📅 This week": ["Round Briefing", "Inbox", "Concept Check", "Decision Journal"],
    "🏗️ Build your venture": ["Founder & Opportunity", "Founder & Team", "Canvases",
                              "VP Auction", "Assumption Map", "Experiment Marketplace",
                              "Evidence Ledger", "Market Events", "Pivot Petition"],
    "📈 Track & finish": ["My Venture", "Leaderboard", "Demo Day"],
}
STUDENT_NAV_UTILITY = ["AI Assist Log"]


def _set_student_page(page):
    st.session_state["student_page"] = STUDENT_PAGE_ALIASES.get(page, page)


def _student_nav(team):
    """Grouped button nav. Shows only tools available this round; locked tools go to an
    'Opens later' expander. Exactly one page is highlighted (a primary button)."""
    rnd = db.current_round()
    cur = st.session_state.get("student_page", STUDENT_HOME)
    cur = STUDENT_PAGE_ALIASES.get(cur, cur)
    if cur not in STUDENT_PAGES:
        cur = STUDENT_HOME
    unread = db.unread_count(team["id"])
    committed = logic.commitment_state(team["id"], rnd)["committed"]

    def _label(page):
        if page == "Round Briefing":
            return "🏠 This week " + ("✅" if committed else "⚠️")
        if page == "Inbox":
            return f"Inbox 🔵{unread}" if unread else "Inbox"
        return page

    def _btn(page):
        st.button(_label(page), key=f"snav_{page}", use_container_width=True,
                  type=("primary" if page == cur else "secondary"),
                  on_click=_set_student_page, args=(page,))

    locked = []
    for title, pages in STUDENT_NAV_GROUPS.items():
        shown = []
        for p in pages:
            if logic.tool_state(p, rnd, team["id"]) == "locked":
                locked.append(p)
            else:
                shown.append(p)
        if not shown:
            continue
        st.caption(title)
        for p in shown:
            _btn(p)
    st.caption("🔧 Tools")
    for p in STUDENT_NAV_UTILITY:
        _btn(p)
    if locked:
        with st.expander(f"🔒 Opens later ({len(locked)})"):
            st.caption("These tools unlock as the simulation advances — nothing to do here yet.")
            for p in sorted(locked, key=lambda x: logic.page_unlock_round(x)):
                st.markdown(f"🔒 **{p}** · opens Round {logic.page_unlock_round(p)}")
    return cur


def _next_action_strip(team, page):
    """A thin 'you are here / do this next' strip at the top of each tool page, so the
    student's next move travels with them instead of living only in the sidebar."""
    if page in ("Round Briefing", "My Venture", "Leaderboard", "Demo Day"):
        return   # these pages already carry their own guidance
    rnd = db.current_round()
    nxt = logic.next_action(team["id"], rnd)
    c1, c2 = st.columns([5, 2])
    if nxt and nxt.get("label"):
        c1.caption(f"📍 Round {rnd}  ·  👉 **Next:** {nxt['label']}"
                   + (f" → {nxt['tool']}" if nxt.get("tool") else ""))
        target = STUDENT_PAGE_ALIASES.get(nxt.get("tool"), nxt.get("tool"))
        if target and target in STUDENT_PAGES and target != page:
            c2.button("Go to next ▸", key="nextstrip_go",
                      on_click=_set_student_page, args=(target,))
    else:
        c1.caption(f"📍 Round {rnd}  ·  ✅ You're caught up this round.")


def _sidebar_todo(team):
    """A compact 'what still needs doing this round' tracker in the sidebar."""
    rnd = db.current_round()
    cl = logic.round_checklist(team["id"], rnd)
    items = list(cl["decisions"]) + list(cl["questions"]) + list(cl["carried"])
    # Reading new Inbox mail is a to-do too (it carries this round's feedback/hints).
    unread = db.unread_count(team["id"])
    if unread:
        items.append({"label": f"Read {unread} new Inbox message(s)", "tool": "Inbox",
                      "done": False})
    # Any AI use still unverified is a to-do (verification is what earns credit).
    ai_unv = logic.ai_unverified_count(team["id"])
    if ai_unv:
        items.append({"label": f"Verify {ai_unv} AI use(s)", "tool": "AI Assist Log",
                      "done": False})
    if not items:
        return
    done = sum(1 for i in items if i["done"])
    total = len(items)
    st.progress(done / total if total else 1.0, text=f"Round {rnd} to-do: {done}/{total} done")
    nxt = logic.next_action(team["id"], rnd)
    if nxt:
        where = f" → {nxt['tool']}" if nxt.get("tool") else ""
        st.caption(f"👉 **Next:** {nxt['label']}{where}")
        target = STUDENT_PAGE_ALIASES.get(nxt.get("tool"), nxt.get("tool"))
        if target and target in STUDENT_PAGES:
            st.button(f"Go to {target} ▸", key="todo_next_go", use_container_width=True,
                      on_click=_set_student_page, args=(target,))
    open_items = [i for i in items if not i["done"]]
    if open_items:
        with st.expander(f"📝 {len(open_items)} still to do"):
            for i in open_items:
                tool = i.get("tool", "")
                carried = " ⏪" if i.get("carried") else ""
                label = i.get("label", i.get("concept", ""))
                st.caption(f"⬜ {label}" + (f" · *{tool}*" if tool else "") + carried)
    else:
        st.caption("✅ Everything for this round is done.")


def _sidebar_commit_status(team):
    """Commit/withdraw controls + deadline banner, always visible in the team sidebar."""
    rnd = db.current_round()
    state = logic.commitment_state(team["id"], rnd)
    ds = state["deadline"]

    if state["committed"]:
        if state["locked"]:
            st.success(f"✅ Round {rnd} committed · locked")
            st.caption("The deadline has passed — this round is final.")
        else:
            st.success(f"🔒 Round {rnd} committed — editing locked")
            if st.button("↩️ Withdraw to edit", use_container_width=True,
                         help="Unlock every tool so you can change your work. Re-commit when done."):
                ok, msg = logic.decommit_round(team["id"], rnd)
                st.rerun()
    else:
        if state["locked"]:
            st.error(f"🔒 Round {rnd} closed — not committed")
            st.caption("The deadline passed before you committed.")
        else:
            if ds["set"]:
                st.warning(f"⚠️ Round {rnd} not committed · due in {ds['remaining']}")
            else:
                st.warning(f"⚠️ Round {rnd} not committed")
            if st.button("✅ Commit round", type="primary", use_container_width=True,
                         help="Lock in this round's work for scoring. Every tool becomes "
                              "view-only until you withdraw."):
                ok, msg = logic.commit_round(team["id"], rnd)
                st.rerun()
            st.caption("Committing locks all tools. You can withdraw any time before the deadline.")


def student_shell():
    team = db.get_team(st.session_state.team_id)
    if not team:
        st.error("Team no longer exists.")
        logout()
        st.stop()
    # A student plays inside their team's game — advance that game, not others.
    db.set_active_game(team.get("game_id"))
    _sync_active_game()
    team = db.get_team(team["id"])   # round may have advanced

    # Celebrate any newly-earned badges.
    for code in logic.sync_badges(team["id"]):
        b = content.BADGE_BY_CODE.get(code, {})
        try:
            st.toast(f"🏅 Badge unlocked: {b.get('emoji','')} {b.get('name', code)}!")
        except Exception:
            pass

    ident = logic.team_identity(team)
    level, _ = logic.founder_level(team["id"])
    streak = logic.commit_streak(team["id"])
    n_badges = len(logic.team_badges(team["id"]))
    with st.sidebar:
        branding.sidebar_logo()
        st.markdown(branding.team_badge_html(team, 44), unsafe_allow_html=True)
        st.caption(f"Round {db.current_round()} · {team['stage']}  ·  "
                   f"🧑‍🚀 Lvl {level} · 🏅 {n_badges}"
                   + (f" · 🔥 {streak}-round streak" if streak >= 2 else ""))
        st.metric("Credits", f"{team['evidence_credits']:.1f}")
        _sidebar_todo(team)
        _sidebar_commit_status(team)
        st.divider()
        page = _student_nav(team)
        with st.expander("Perspectives (rotate each round)"):
            st.caption("Six critical lenses your team rotates through. You take one each round in "
                       "the Decision Journal — see its full description there.")
            for pr in content.PERSPECTIVES:
                st.caption(f"{pr['icon']} **{pr['name']}** — {pr['lens']}")
        if st.session_state.get("director_viewing") and st.session_state.get("instructor_ok"):
            st.button("↩️ Back to Director console", on_click=_back_to_director,
                      type="primary", use_container_width=True)
        st.button("Log out", on_click=logout)

    _scroll_top_on_change("_student_page", page)
    _next_action_strip(team, page)
    STUDENT_PAGES[page](team)


# --------------------------------------------------------------------------- #
# Instructor shell
# --------------------------------------------------------------------------- #
INSTRUCTOR_HOME = "🏠 Start here"
INSTRUCTOR_PAGES = {
    INSTRUCTOR_HOME: vi.director_home,
    "Games": vi.games_console,
    "Cohort Overview": vi.overview,
    "Auto-Director": vi.auto_director,
    "Team Setup": vi.team_setup,
    "Schedule & Timing": vi.schedule,
    "Round Control": vi.round_control,
    "Resources": vi.resources,
    "Market Events": vi.events,
    "VP Auction": vi.vp_auction,
    "Pivot Committee": vi.pivot_committee,
    "Dashboard Scoring": vi.scoring,
    "Round Scores": vi.round_scores,
    "Misconception Radar": vi.misconception_radar,
    "Demo Day": vi.demo_day_admin,
    "Backup & Restore": vi.backup_restore,
}

# Grouped navigation so a first-time director isn't faced with 14 flat pages.
INSTRUCTOR_NAV_GROUPS = {
    "⚙️ Set up (once)": ["Games", "Team Setup", "Schedule & Timing"],
    "▶️ Run each round": ["Round Control", "Round Scores", "Auto-Director", "Backup & Restore"],
    "📊 See how it's going": ["Cohort Overview", "Misconception Radar", "Demo Day"],
}
INSTRUCTOR_NAV_ADVANCED = ["Resources", "Market Events", "VP Auction",
                           "Pivot Committee", "Dashboard Scoring"]


def _set_instr_page(page):
    st.session_state["instr_page"] = page


def _instructor_nav():
    """Grouped Director sidebar nav built from buttons — exactly one page is ever
    highlighted (the active one is a primary button), which avoids the multi-radio
    'two selections at once' problem. Returns the selected page name."""
    home = INSTRUCTOR_HOME
    cur = st.session_state.get("instr_page", home)

    def _navbtn(page, label=None):
        st.button(label or page, key=f"navbtn_{page}", use_container_width=True,
                  type=("primary" if page == cur else "secondary"),
                  on_click=_set_instr_page, args=(page,))

    _navbtn(home, "🏠 Start here")
    for title, pages in INSTRUCTOR_NAV_GROUPS.items():
        st.caption(title)
        for p in pages:
            _navbtn(p)
    with st.expander("🔧 Advanced / manual (optional)", expanded=cur in INSTRUCTOR_NAV_ADVANCED):
        st.caption("Only needed if you run these steps by hand — automation covers them.")
        for p in INSTRUCTOR_NAV_ADVANCED:
            _navbtn(p)
    return cur


def instructor_shell():
    # Pick which game the Director is managing (each runs independently).
    games = db.list_games()
    if not games:
        db.create_game("Game 1")
        games = db.list_games()
    saved = st.session_state.get("active_game_id")
    ids = [g["id"] for g in games]
    if saved not in ids:
        saved = ids[0]
    with st.sidebar:
        branding.sidebar_logo()
        st.header("🎩 Venture Foundry Director")
        gsel = st.selectbox(
            "Active game", ids, index=ids.index(saved),
            format_func=lambda i: next(g["name"] for g in games if g["id"] == i),
            help="Manage one game at a time. Each game advances on its own round.")
        st.session_state["active_game_id"] = gsel
        db.set_active_game(gsel)
        _sync_active_game()
        diff = db.get_setting("difficulty", "not set")
        st.caption(f"Round {db.current_round()} of {logic.total_rounds()} · "
                   f"{len(db.list_teams())} team(s) · Difficulty: {diff}")
        st.divider()
        page = _instructor_nav()
        st.divider()
        teams_here = db.list_teams()
        if teams_here:
            with st.expander("👀 View the game as a team"):
                vt = st.selectbox("Team", [t["id"] for t in teams_here], key="view_as_team",
                                  format_func=lambda i: next(
                                      f"{t['name']} ({t['join_code']})"
                                      for t in teams_here if t["id"] == i))
                st.button("Open team view", on_click=_director_view_team, args=(vt,),
                          use_container_width=True)
        with st.expander("Director's questions"):
            for q in [
                "What must be true for this to work?",
                "Which assumption could invalidate the entire model?",
                "What evidence supports that claim?",
                "Is that evidence about intentions or behavior?",
                "What is the least expensive way to test it?",
                "What result would cause you to change direction?",
            ]:
                st.caption(f"• {q}")
        st.button("Log out", on_click=logout)

    _scroll_top_on_change("_instructor_page", page)
    INSTRUCTOR_PAGES[page]()


# --------------------------------------------------------------------------- #
# Router
# --------------------------------------------------------------------------- #
# Serve repeated reads within this run from memory (see db.run_memo). Always
# cleared in `finally`, including when st.rerun()/st.stop() interrupt the run.
db.begin_request()
try:
    if st.session_state.role == "student":
        student_shell()
    elif st.session_state.role == "instructor" and st.session_state.instructor_ok:
        instructor_shell()
    else:
        landing()
finally:
    db.end_request()
