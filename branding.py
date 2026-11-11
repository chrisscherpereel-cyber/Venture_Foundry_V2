"""
branding.py — Venture Foundry visual identity.

Holds the simulation's custom logo (an inline SVG: a molten "V" being cast in a
mold, with a spark of insight) and small helpers to render it in the app.
Tagline: "From hunch to hard evidence."

IMPORTANT: Streamlit's Markdown renderer treats any line indented 4+ spaces as a
code block, which would print raw HTML/SVG to the screen. So every string we hand
to st.markdown is collapsed to a single unindented line via _oneline() before use.
"""

import streamlit as st

TAGLINE = "From hunch to hard evidence"

# Raw logo artwork (the "Molten V"). Kept multi-line here for readability;
# _oneline() flattens it before it reaches st.markdown. assets/logo.svg matches.
_LOGO_SVG = """
<svg viewBox="0 0 120 120" xmlns="http://www.w3.org/2000/svg" role="img"
     aria-label="Venture Foundry logo" width="{w}" height="{w}"
     style="display:block;flex:0 0 auto;">
  <path d="M34 42 L60 88 L86 42" fill="none" stroke="#f2a938" stroke-width="12"
        stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M28 36 h16 M28 36 v16" fill="none" stroke="#24324d" stroke-width="6"
        stroke-linecap="round"/>
  <path d="M92 36 h-16 M92 36 v16" fill="none" stroke="#24324d" stroke-width="6"
        stroke-linecap="round"/>
  <path d="M60 20 L62 27 L69 29 L62 31 L60 38 L58 31 L51 29 L58 27 Z" fill="#f2a938"/>
</svg>
"""


def _oneline(html):
    """Collapse markup to a single line with no leading indentation.

    This is what prevents Streamlit's Markdown parser from rendering the HTML as a
    literal code block.
    """
    return " ".join(line.strip() for line in html.strip().splitlines() if line.strip())


def logo_svg(width=64):
    """Return the logo SVG markup, flattened and sized to `width` pixels."""
    return _oneline(_LOGO_SVG).replace("{w}", str(width))


def header(subtitle=None):
    """Large logo + wordmark for the landing page."""
    subtitle = (subtitle or TAGLINE).upper()
    html = (
        '<div style="display:flex;align-items:center;gap:16px;margin:4px 0 8px;">'
        + logo_svg(76)
        + '<div style="line-height:1.15;">'
        + '<div style="font-size:30px;font-weight:800;letter-spacing:.5px;">VENTURE FOUNDRY</div>'
        + f'<div style="font-size:13px;letter-spacing:2.5px;opacity:.65;">{subtitle}</div>'
        + '</div></div>'
    )
    st.markdown(html, unsafe_allow_html=True)


def avatar_html(color, mascot, size=40, border=True):
    """A team's identity badge: a coloured disc with the team's mascot emoji."""
    bd = "box-shadow:0 0 0 2px rgba(255,255,255,.5);" if border else ""
    return _oneline(
        f'<span style="display:inline-flex;width:{size}px;height:{size}px;border-radius:50%;'
        f'background:{color};align-items:center;justify-content:center;'
        f'font-size:{int(size*0.55)}px;{bd}vertical-align:middle;">{mascot}</span>')


def team_badge_html(team, size=40):
    """Avatar + display name inline, using the team's chosen identity."""
    import logic  # local import to avoid a cycle at module load
    ident = logic.team_identity(team)
    return _oneline(
        '<div style="display:flex;align-items:center;gap:10px;">'
        + avatar_html(ident["color"], ident["mascot"], size)
        + f'<div style="font-size:{max(14, int(size*0.42))}px;font-weight:700;">'
        + f'{ident["display"]}</div></div>')


def sidebar_logo(caption=""):
    """Compact logo + wordmark for a sidebar."""
    html = (
        '<div style="display:flex;align-items:center;gap:10px;margin-bottom:6px;">'
        + logo_svg(38)
        + '<div style="line-height:1.1;">'
        + '<div style="font-size:15px;font-weight:800;letter-spacing:.4px;">VENTURE FOUNDRY</div>'
        + f'<div style="font-size:9px;letter-spacing:1.5px;opacity:.6;">{TAGLINE.upper()}</div>'
        + '</div></div>'
    )
    st.markdown(html, unsafe_allow_html=True)
    if caption:
        st.caption(caption)
