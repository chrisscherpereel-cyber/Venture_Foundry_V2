"""
canvas_art.py — polished, original SVG illustrations of the four framework layouts
used in Venture Foundry (Customer Profile, Value Proposition Canvas, Business Model
Canvas, and Business Model Environment Canvas).

These are original vector renderings of the standard framework structures, drawn to
look like clean printed canvases. Each SVG uses a viewBox and a single width token
so it scales crisply. Strings are flattened to one line before rendering so
Streamlit's Markdown renderer treats them as HTML, not a code block.
"""

# Shared palette
INK = "#24324d"
LINE = "#7d8aa5"
BLUE = "#eef3fb"
BAND = "#c9dcf2"
BAND2 = "#9fb9de"
TEAL = "#2bb0a4"
TEAL_SOFT = "#e2f4f1"
AMBER = "#f2a938"
AMBER_SOFT = "#fdeede"
RED = "#d9654a"
RED_SOFT = "#fbe9e4"


def _oneline(svg):
    return " ".join(line.strip() for line in svg.strip().splitlines() if line.strip())


# --------------------------------------------------------------------------- #
# Customer Profile — the circle: Gains (top-left), Customer Jobs (right), Pains
# --------------------------------------------------------------------------- #
_CUSTOMER_PROFILE = f"""
<svg viewBox="0 0 440 440" width="{{w}}" xmlns="http://www.w3.org/2000/svg"
     role="img" aria-label="Customer Profile canvas" font-family="Helvetica, Arial, sans-serif">
  <path d="M220 220 L15 220 A205 205 0 0 1 322.5 42.5 Z" fill="{TEAL_SOFT}"/>
  <path d="M220 220 L322.5 42.5 A205 205 0 0 1 322.5 397.5 Z" fill="{BLUE}"/>
  <path d="M220 220 L322.5 397.5 A205 205 0 0 1 15 220 Z" fill="{RED_SOFT}"/>
  <circle cx="220" cy="220" r="205" fill="none" stroke="{INK}" stroke-width="3"/>
  <g stroke="{INK}" stroke-width="1.6" opacity="0.7">
    <line x1="220" y1="220" x2="15" y2="220"/>
    <line x1="220" y1="220" x2="322.5" y2="42.5"/>
    <line x1="220" y1="220" x2="322.5" y2="397.5"/>
  </g>
  <!-- Gains -->
  <circle cx="120" cy="120" r="18" fill="none" stroke="{TEAL}" stroke-width="2.4"/>
  <circle cx="114" cy="116" r="2.2" fill="{TEAL}"/><circle cx="126" cy="116" r="2.2" fill="{TEAL}"/>
  <path d="M112 124 Q120 132 128 124" fill="none" stroke="{TEAL}" stroke-width="2.4" stroke-linecap="round"/>
  <text x="120" y="162" text-anchor="middle" font-size="21" font-weight="700" fill="{INK}">Gains</text>
  <!-- Pains -->
  <circle cx="120" cy="322" r="18" fill="none" stroke="{RED}" stroke-width="2.4"/>
  <circle cx="114" cy="318" r="2.2" fill="{RED}"/><circle cx="126" cy="318" r="2.2" fill="{RED}"/>
  <path d="M112 332 Q120 324 128 332" fill="none" stroke="{RED}" stroke-width="2.4" stroke-linecap="round"/>
  <text x="120" y="298" text-anchor="middle" font-size="21" font-weight="700" fill="{INK}">Pains</text>
  <!-- Jobs -->
  <g transform="translate(300,196)">
    <rect x="0" y="0" width="12" height="12" rx="2" fill="none" stroke="{INK}" stroke-width="2"/>
    <path d="M2 6 l3 3 l6 -7" fill="none" stroke="{INK}" stroke-width="2" stroke-linecap="round"/>
    <rect x="0" y="18" width="12" height="12" rx="2" fill="none" stroke="{INK}" stroke-width="2"/>
    <line x1="20" y1="6" x2="60" y2="6" stroke="{INK}" stroke-width="2.2"/>
    <line x1="20" y1="24" x2="60" y2="24" stroke="{INK}" stroke-width="2.2"/>
  </g>
  <text x="332" y="250" text-anchor="middle" font-size="20" font-weight="700" fill="{INK}">Customer</text>
  <text x="332" y="272" text-anchor="middle" font-size="20" font-weight="700" fill="{INK}">Job(s)</text>
  <!-- centre head -->
  <circle cx="220" cy="220" r="40" fill="#ffffff" stroke="{INK}" stroke-width="2.4"/>
  <circle cx="211" cy="214" r="3" fill="{INK}"/>
  <path d="M206 230 Q220 240 234 230" fill="none" stroke="{INK}" stroke-width="2.4" stroke-linecap="round"/>
</svg>
"""


# --------------------------------------------------------------------------- #
# Value Proposition Canvas — value map (square) fits customer profile (circle)
# --------------------------------------------------------------------------- #
_VPC = f"""
<svg viewBox="0 0 780 420" width="{{w}}" xmlns="http://www.w3.org/2000/svg"
     role="img" aria-label="Value Proposition Canvas" font-family="Helvetica, Arial, sans-serif">
  <text x="175" y="34" text-anchor="middle" font-size="19" font-weight="700" fill="{INK}">Value Map</text>
  <text x="595" y="34" text-anchor="middle" font-size="19" font-weight="700" fill="{INK}">Customer Profile</text>
  <!-- square value map: three clean zones, no crossing lines -->
  <rect x="40" y="55" width="290" height="290" rx="10" fill="{BLUE}" stroke="{INK}" stroke-width="2.6"/>
  <line x1="235" y1="55" x2="235" y2="345" stroke="{LINE}" stroke-width="1.4" opacity="0.55"/>
  <line x1="40" y1="200" x2="235" y2="200" stroke="{LINE}" stroke-width="1.4" opacity="0.55"/>
  <text x="137" y="122" text-anchor="middle" font-size="15" font-weight="700" fill="{TEAL}">Gain</text>
  <text x="137" y="141" text-anchor="middle" font-size="15" font-weight="700" fill="{TEAL}">Creators</text>
  <text x="137" y="272" text-anchor="middle" font-size="15" font-weight="700" fill="{RED}">Pain</text>
  <text x="137" y="291" text-anchor="middle" font-size="15" font-weight="700" fill="{RED}">Relievers</text>
  <text x="282" y="193" text-anchor="middle" font-size="12.5" font-weight="700" fill="{INK}">Products</text>
  <text x="282" y="210" text-anchor="middle" font-size="12.5" font-weight="700" fill="{INK}">&amp; Services</text>
  <!-- fit arrow -->
  <path d="M345 200 L430 200" stroke="{AMBER}" stroke-width="4" marker-end="url(#vparrow)"/>
  <defs><marker id="vparrow" markerWidth="10" markerHeight="10" refX="7" refY="5" orient="auto">
    <path d="M0 0 L9 5 L0 10 z" fill="{AMBER}"/></marker></defs>
  <text x="388" y="188" text-anchor="middle" font-size="12" font-weight="700" fill="{AMBER}">fit</text>
  <!-- customer circle -->
  <g transform="translate(595,200)">
    <path d="M0 0 L-150 0 A150 150 0 0 1 75 -129.9 Z" fill="{TEAL_SOFT}"/>
    <path d="M0 0 L75 -129.9 A150 150 0 0 1 75 129.9 Z" fill="{BLUE}"/>
    <path d="M0 0 L75 129.9 A150 150 0 0 1 -150 0 Z" fill="{RED_SOFT}"/>
    <circle cx="0" cy="0" r="150" fill="none" stroke="{INK}" stroke-width="2.6"/>
    <g stroke="{INK}" stroke-width="1.4" opacity="0.7">
      <line x1="0" y1="0" x2="-150" y2="0"/><line x1="0" y1="0" x2="75" y2="-129.9"/>
      <line x1="0" y1="0" x2="75" y2="129.9"/>
    </g>
    <text x="-72" y="-58" text-anchor="middle" font-size="14" font-weight="700" fill="{INK}">Gains</text>
    <text x="-72" y="70" text-anchor="middle" font-size="14" font-weight="700" fill="{INK}">Pains</text>
    <text x="92" y="6" text-anchor="middle" font-size="13" font-weight="700" fill="{INK}">Jobs</text>
    <circle cx="0" cy="0" r="30" fill="#ffffff" stroke="{INK}" stroke-width="2.2"/>
    <circle cx="-7" cy="-4" r="2.4" fill="{INK}"/>
    <path d="M-11 8 Q0 16 11 8" fill="none" stroke="{INK}" stroke-width="2.2" stroke-linecap="round"/>
  </g>
</svg>
"""


# --------------------------------------------------------------------------- #
# Business Model Canvas — the canonical nine-block grid
# --------------------------------------------------------------------------- #
def _bmc_block(x, y, w, h, color, title):
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{BLUE}" '
            f'stroke="{INK}" stroke-width="2"/>'
            f'<rect x="{x}" y="{y}" width="{w}" height="24" rx="8" fill="{color}"/>'
            f'<rect x="{x}" y="{y+14}" width="{w}" height="10" fill="{color}"/>'
            f'<text x="{x+10}" y="{y+17}" font-size="12.5" font-weight="700" fill="#ffffff">{title}</text>')


_BMC = (
    '<svg viewBox="0 0 920 520" width="{w}" xmlns="http://www.w3.org/2000/svg" '
    'role="img" aria-label="Business Model Canvas" font-family="Helvetica, Arial, sans-serif">'
    + _bmc_block(10, 10, 172, 372, "#5b6b8c", "Key Partners")
    + _bmc_block(188, 10, 172, 181, "#5b6b8c", "Key Activities")
    + _bmc_block(188, 201, 172, 181, "#5b6b8c", "Key Resources")
    + _bmc_block(366, 10, 188, 372, TEAL, "Value Propositions")
    + _bmc_block(560, 10, 172, 181, "#c98a2b", "Customer Relations")
    + _bmc_block(560, 201, 172, 181, "#c98a2b", "Channels")
    + _bmc_block(738, 10, 172, 372, "#c98a2b", "Customer Segments")
    + _bmc_block(10, 392, 442, 118, "#3f4a63", "Cost Structure")
    + _bmc_block(462, 392, 448, 118, TEAL, "Revenue Streams")
    + '</svg>'
)


# --------------------------------------------------------------------------- #
# Business Model Environment Canvas — trends (outer) & disruptive forces (inner)
# --------------------------------------------------------------------------- #
def _env_satellite(cx, cy, color, l1, l2):
    return (f'<circle cx="{cx}" cy="{cy}" r="30" fill="{color}" stroke="{INK}" stroke-width="1.6"/>'
            f'<text x="{cx}" y="{cy-2}" text-anchor="middle" font-size="10.5" font-weight="700" fill="#ffffff">{l1}</text>'
            f'<text x="{cx}" y="{cy+11}" text-anchor="middle" font-size="10.5" font-weight="700" fill="#ffffff">{l2}</text>')


_ENVIRONMENT = f"""
<svg viewBox="0 0 760 560" width="{{w}}" xmlns="http://www.w3.org/2000/svg"
     role="img" aria-label="Business Model Environment Canvas" font-family="Helvetica, Arial, sans-serif">
  <circle cx="380" cy="285" r="250" fill="none" stroke="{BAND2}" stroke-width="2" stroke-dasharray="4 6"/>
  <circle cx="380" cy="285" r="185" fill="{BAND}" stroke="{INK}" stroke-width="2"/>
  <circle cx="380" cy="285" r="120" fill="{BLUE}" stroke="{INK}" stroke-width="1.6" stroke-dasharray="3 4"/>
  <text x="380" y="118" text-anchor="middle" font-size="13" font-weight="700" fill="{INK}" letter-spacing="1">EMERGING TRENDS</text>
  <text x="380" y="466" text-anchor="middle" font-size="13" font-weight="700" fill="{INK}" letter-spacing="1">DISRUPTIVE FORCES</text>
  <!-- five forces -->
  <rect x="330" y="150" width="100" height="30" rx="6" fill="#ffffff" stroke="{INK}" stroke-width="1.6"/>
  <text x="380" y="170" text-anchor="middle" font-size="11" font-weight="700" fill="{INK}">New Entrants</text>
  <rect x="212" y="270" width="90" height="30" rx="6" fill="#ffffff" stroke="{INK}" stroke-width="1.6"/>
  <text x="257" y="290" text-anchor="middle" font-size="11" font-weight="700" fill="{INK}">Suppliers</text>
  <rect x="458" y="270" width="90" height="30" rx="6" fill="#ffffff" stroke="{INK}" stroke-width="1.6"/>
  <text x="503" y="290" text-anchor="middle" font-size="11" font-weight="700" fill="{INK}">Customers</text>
  <rect x="330" y="390" width="100" height="30" rx="6" fill="#ffffff" stroke="{INK}" stroke-width="1.6"/>
  <text x="380" y="410" text-anchor="middle" font-size="11" font-weight="700" fill="{INK}">Substitutes</text>
  <rect x="338" y="262" width="84" height="46" rx="6" fill="{INK}"/>
  <text x="380" y="282" text-anchor="middle" font-size="10" font-weight="700" fill="#ffffff">Industry</text>
  <text x="380" y="296" text-anchor="middle" font-size="10" font-weight="700" fill="#ffffff">Rivalry</text>
  <g stroke="{AMBER}" stroke-width="3" fill="none">
    <path d="M380 188 L380 254" marker-end="url(#ea)"/>
    <path d="M310 285 L330 285" marker-end="url(#ea)"/>
    <path d="M450 285 L430 285" marker-end="url(#ea)"/>
    <path d="M380 382 L380 316" marker-end="url(#ea)"/>
  </g>
  <defs><marker id="ea" markerWidth="10" markerHeight="10" refX="7" refY="5" orient="auto">
    <path d="M0 0 L9 5 L0 10 z" fill="{AMBER}"/></marker></defs>
  <!-- six environment satellites -->
  {_env_satellite(380, 55, TEAL, 'Customer', 'Trends')}
  {_env_satellite(120, 150, '#5b6b8c', 'Technology', 'Trends')}
  {_env_satellite(640, 150, '#5b6b8c', 'Mega', 'Trends')}
  {_env_satellite(120, 420, '#c98a2b', 'Market', 'Forces')}
  {_env_satellite(640, 420, '#c98a2b', 'Macro', 'Forces')}
  {_env_satellite(380, 515, '#3f4a63', 'Industry', 'Forces')}
</svg>
"""


DIAGRAMS = {
    "customer_profile": _CUSTOMER_PROFILE,
    "vpc": _VPC,
    "bmc": _BMC,
    "environment": _ENVIRONMENT,
}

# Default render widths (px) per canvas.
WIDTHS = {"customer_profile": 380, "vpc": 620, "bmc": 680, "environment": 560}


def svg(ctype, width=None):
    raw = DIAGRAMS.get(ctype)
    if not raw:
        return ""
    w = width or WIDTHS.get(ctype, 520)
    return _oneline(raw).replace("{w}", str(w))
