#!/usr/bin/env python3
"""Single-source generator for the GitHub profile header cards.

Produces dark.svg and light.svg from one Python config so both themes can
never drift apart. The left panel is a "REPO.MAP" — when live data is
available each node is a *real* public repository (sized by stars, colored by
language, connected in a ring), otherwise it falls back to a deterministic
decorative neural constellation so the card still looks complete offline.
The right panel is a live SYSTEM.INFO readout plus a GROWTH sparkline fed by
a rolling history file (``data/profile-history.json``) appended each run.

Usage:
    python scripts/generate_profile.py            # write dark.svg + light.svg
    python scripts/generate_profile.py --no-fetch # skip the network call
    GITHUB_TOKEN=... python scripts/generate_profile.py
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# --------------------------------------------------------------------------- #
# Configuration: the ONLY place profile content should be edited.
# --------------------------------------------------------------------------- #
WIDTH, HEIGHT = 1180, 610
HANDLE = "Mylavamsikrishna123"

INFO_ROWS = [
    ("SYSTEM.INFO", None, "header"),
    ("Subject", "M VAMSI KRISHNA", "row"),
    ("Role", "AI Infrastructure Engineer", "row"),
    ("Origin", "India", "row"),
    ("Education", "M.Tech", "row"),
    ("Status", "Building + Learning + Shipping", "row"),
    ("ToolChain", "VS Code, Git, Docker", "row"),
    ("CORE.LANG", "TypeScript, Go, Rust", "row-python"),
    ("CORE.FRONTEND", "Next.js, Tailwind CSS", "row-react"),
    ("CORE.BACKEND", "Node.js, gRPC", "row-fastapi"),
    ("CORE.DATABASE", "Redis, MongoDB", "row-postgres"),
    ("CORE.INFRA", "Kubernetes, AWS, Terraform, GitHub Actions", "row-docker"),
    ("GRID.CONNECT", None, "header"),
    ("LinkedIn", "m-vamsi-krishna-l190030952", "row"),
    ("GitHub", HANDLE, "row"),
]

# Deterministic seed for the neural map so output is stable between runs.
SEED = 0x7A531


@dataclass
class RepoInfo:
    name: str
    stars: int
    language: str | None
    description: str | None
    updated: str | None


@dataclass
class LiveStats:
    public_repos: int | None = None
    total_stars: int | None = None
    followers: int | None = None
    following: int | None = None
    latest_push: str | None = None
    repos: list[RepoInfo] = field(default_factory=list)
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    )
    fetched: bool = False


# --------------------------------------------------------------------------- #
# Live data fetch (public GitHub REST API, no auth required but token helps
# rate limits). Treated as best-effort: any failure falls back to None.
# --------------------------------------------------------------------------- #
def _gh_get(url: str, timeout: float) -> dict | list | None:
    token = os.environ.get("GITHUB_TOKEN")
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "profile-generator"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None


def fetch_live_stats(handle: str, timeout: float = 5.0) -> LiveStats:
    stats = LiveStats()
    data = _gh_get(f"https://api.github.com/users/{handle}", timeout)
    if not isinstance(data, dict):
        return stats
    stats.public_repos = data.get("public_repos")
    stats.followers = data.get("followers")
    stats.following = data.get("following")
    pushed = data.get("pushed_at")
    if pushed:
        try:
            stats.latest_push = pushed[:10]
        except (TypeError, IndexError):
            stats.latest_push = None

    repos = _gh_get(
        f"https://api.github.com/users/{handle}/repos?per_page=100&sort=pushed", timeout
    )
    if isinstance(repos, list):
        for r in repos:
            stats.repos.append(RepoInfo(
                name=r.get("name", "?"),
                stars=r.get("stargazers_count", 0) or 0,
                language=r.get("language"),
                description=r.get("description"),
                updated=(r.get("pushed_at") or "")[:10] or None,
            ))
        stats.total_stars = sum(r.stars for r in stats.repos)
        # latest_push = most recent repo push (account pushed_at can be null)
        pushes = [r.updated for r in stats.repos if r.updated]
        if pushes:
            stats.latest_push = max(pushes)
    stats.fetched = True
    return stats


# --------------------------------------------------------------------------- #
# Deterministic PRNG (xorshift32) so the neural map is reproducible.
# --------------------------------------------------------------------------- #
def _make_rng(seed: int):
    x = seed & 0xFFFFFFFF
    while True:
        x ^= (x << 13) & 0xFFFFFFFF
        x ^= x >> 17
        x ^= (x << 5) & 0xFFFFFFFF
        x &= 0xFFFFFFFF
        yield x / 0xFFFFFFFF


def neural_map(x0: int, y0: int, w: int, h: int, node_count: int = 26):
    """Return (nodes, edges) forming a layered neural constellation (offline fallback)."""
    rng = _make_rng(SEED)
    layers = 5
    nodes: list[tuple[float, float]] = []
    per_layer = max(2, node_count // layers)
    margin_x = 60
    for li in range(layers):
        lx = x0 + margin_x + (w - 2 * margin_x) * (li / max(1, layers - 1))
        for ni in range(per_layer):
            jitter_x = (next(rng) - 0.5) * 18
            jitter_y = (next(rng) - 0.5) * (h - 160)
            ny = y0 + 130 + (h - 230) * (ni / max(1, per_layer - 1)) + jitter_y
            nodes.append((lx + jitter_x, ny))
    edges = []
    for i, (x, y) in enumerate(nodes):
        layer = i // per_layer
        if layer >= layers - 1:
            continue
        next_start = (layer + 1) * per_layer
        for _ in range(2):
            tgt = next_start + int(next(rng) * per_layer)
            tgt = min(tgt, len(nodes) - 1)
            edges.append(((x, y), nodes[tgt], i, tgt))
    return nodes, edges


# GitHub-ish language accent colors
LANG_COLORS = {
    "Python": "#3572A5", "Java": "#b07219", "JavaScript": "#f1e05a",
    "TypeScript": "#3178c6", "Go": "#00ADD8", "Rust": "#dea584",
    "C": "#555555", "C++": "#f34b7d", "Shell": "#89e051", "HTML": "#e34c26",
    "CSS": "#563d7c", "Jupyter Notebook": "#DA5B0B",
}


def repo_map(repos: list[RepoInfo], x0: int, y0: int, w: int, h: int):
    """Place repos as nodes on a ring inside the portrait frame.

    Each node radius scales with star count; color follows the repo language.
    Returns list of dicts: {name, cx, cy, r, color, stars, lang}.
    """
    n = len(repos)
    if n == 0:
        return []
    cx = x0 + w / 2
    cy = y0 + h / 2 + 30
    rx = (w - 120) / 2
    ry = (h - 200) / 2
    max_stars = max((r.stars for r in repos), default=0)
    placed = []
    for i, repo in enumerate(repos[:16]):  # cap at 16 for legibility
        angle = (2 * math.pi * i / n) - math.pi / 2
        px = cx + rx * math.cos(angle)
        py = cy + ry * math.sin(angle)
        # radius 5..14 by star share
        share = (repo.stars / max_stars) if max_stars else 0
        radius = 5 + share * 9
        placed.append({
            "name": repo.name, "cx": px, "cy": py, "r": radius,
            "color": LANG_COLORS.get(repo.language or "", "#22D3EE"),
            "stars": repo.stars, "lang": repo.language or "—",
        })
    return placed


# --------------------------------------------------------------------------- #
# Growth history: append a snapshot each run, keep last N for the sparkline.
# --------------------------------------------------------------------------- #
HISTORY_PATH = Path("data/profile-history.json")
HISTORY_KEEP = 30


def load_history() -> list[dict]:
    try:
        return json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def append_history(stats: LiveStats) -> list[dict]:
    history = load_history()
    history.append({
        "t": stats.generated_at,
        "repos": stats.public_repos,
        "stars": stats.total_stars,
        "followers": stats.followers,
    })
    history = history[-HISTORY_KEEP:]
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_PATH.write_text(json.dumps(history, indent=2), encoding="utf-8")
    return history


def sparkline_points(history: list[dict], field: str, x0: int, y0: int, w: int, h: int) -> str:
    """Build an SVG polyline points string for one metric's history."""
    vals = [h.get(field) for h in history if isinstance(h.get(field), (int, float))]
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1
    n = len(vals)
    pts = []
    for i, v in enumerate(vals):
        px = x0 + (w * i / (n - 1))
        py = y0 + h - (h * (v - lo) / span)
        pts.append(f"{px:.1f},{py:.1f}")
    return " ".join(pts)


# --------------------------------------------------------------------------- #
# Theme palette
# --------------------------------------------------------------------------- #
THEMES = {
    "dark": {
        "bg": "#0A101F", "titlebar": "#161B2D", "frame": "#22D3EE",
        "header": "#22D3EE", "label": "#94A3B8", "value": "#F8FAFC",
        "edge": "#22D3EE", "node": "#10B981", "stat": "#A78BFA",
        "live": "#10B981", "stroke_bg": "#0A101F",
    },
    "light": {
        "bg": "#F8FAFC", "titlebar": "#E2E8F0", "frame": "#0891B2",
        "header": "#0891B2", "label": "#475569", "value": "#0F172A",
        "edge": "#0891B2", "node": "#059669", "stat": "#6D28D9",
        "live": "#059669", "stroke_bg": "#F8FAFC",
    },
}


def _esc(text: str | None) -> str:
    if text is None:
        return ""
    return (text.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def render(theme_name: str, stats: LiveStats, history: list[dict]) -> str:
    t = THEMES[theme_name]
    out: list[str] = []
    out.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
        f'viewBox="0 0 {WIDTH} {HEIGHT}" role="img" '
        f'aria-label="M VAMSI KRISHNA - AI Infrastructure Engineer">'
    )
    out.append(
        "  <defs>\n    <style>\n"
        "      @keyframes pulse { 0%,100% {opacity:1} 50% {opacity:0.3} }\n"
        "      @keyframes blink { 0%,100% {opacity:1} 50% {opacity:0} }\n"
        "      @keyframes fadeIn { from {opacity:0} to {opacity:1} }\n"
        "      @keyframes flow { to {stroke-dashoffset:-40} }\n"
        "      @keyframes draw { from {stroke-dashoffset:400} to {stroke-dashoffset:0} }\n"
        f"      .terminal-bg {{ fill: {t['bg']}; }}\n"
        f"      .portrait-frame {{ fill: none; stroke: {t['frame']}; stroke-width: 2; rx: 8; }}\n"
        "      .info-panel { font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace; }\n"
        f"      .header {{ fill: {t['header']}; font-size: 13px; font-weight: 600; }}\n"
        f"      .row-label {{ fill: {t['label']}; font-size: 14px; }}\n"
        f"      .row-value {{ fill: {t['value']}; font-size: 14px; }}\n"
        "      .live-badge { fill: #EF4444; font-size: 12px; font-weight: 700; animation: pulse 1.5s ease-in-out infinite; }\n"
        f"      .handle-pill {{ fill: {t['live']}; font-size: 14px; font-weight: 600; }}\n"
        f"      .neural-edge {{ stroke: {t['edge']}; stroke-width: 0.6; opacity: 0.5; stroke-dasharray: 4 4; animation: flow 2s linear infinite; }}\n"
        f"      .neural-node {{ fill: {t['node']}; }}\n"
        f"      .repo-node {{ stroke: {t['bg']}; stroke-width: 1.2; }}\n"
        f"      .repo-link {{ stroke: {t['edge']}; stroke-width: 0.7; opacity: 0.35; }}\n"
        f"      .repo-label {{ fill: {t['value']}; font-size: 9px; font-family: 'JetBrains Mono', monospace; }}\n"
        f"      .stat-val {{ fill: {t['stat']}; font-size: 13px; font-weight: 600; }}\n"
        f"      .spark {{ fill: none; stroke: {t['stat']}; stroke-width: 1.4; stroke-linecap: round; stroke-linejoin: round; animation: draw 2s ease-out forwards; stroke-dasharray: 400; }}\n"
        f"      .spark-fill {{ fill: {t['stat']}; opacity: 0.12; }}\n"
        f"      .foot {{ fill: {t['label']}; font-size: 10px; }}\n"
        "    </style>\n  </defs>"
    )

    # background + title bar
    out.append(f'  <rect class="terminal-bg" width="{WIDTH}" height="{HEIGHT}"/>')
    out.append(f'  <rect x="0" y="0" width="{WIDTH}" height="36" fill="{t["titlebar"]}"/>')
    out.append('  <text x="16" y="24" class="header">profile.sh --live</text>')
    out.append('  <circle cx="1140" cy="18" r="6" fill="#EF4444" class="live-badge" style="animation-delay:0s"/>')
    out.append(
        f'  <text x="1020" y="24" class="handle-pill" '
        f'style="paint-order: stroke fill; stroke:{t["stroke_bg"]}; stroke-width:3px">@{HANDLE}</text>'
    )

    # portrait frame
    out.append('  <rect x="20" y="56" width="430" height="534" class="portrait-frame"/>')

    # Repo map (real repos) OR fallback decorative neural map when offline.
    use_repos = stats.fetched and bool(stats.repos)
    if use_repos:
        out.append(f'  <text x="40" y="84" class="header" style="fill:{t["header"]}">REPO.MAP</text>')
        placed = repo_map(stats.repos, 20, 56, 430, 534)
        out.append('  <g id="repo-map" style="animation: fadeIn 1.6s ease-out forwards">')
        # ring links connecting consecutive repos
        for i in range(len(placed)):
            a, b = placed[i], placed[(i + 1) % len(placed)]
            out.append(
                f'    <line class="repo-link" x1="{a["cx"]:.1f}" y1="{a["cy"]:.1f}" '
                f'x2="{b["cx"]:.1f}" y2="{b["cy"]:.1f}"/>'
            )
        for i, n in enumerate(placed):
            delay = 0.3 + (i % 8) * 0.1
            out.append(
                f'    <circle class="repo-node" cx="{n["cx"]:.1f}" cy="{n["cy"]:.1f}" r="{n["r"]:.1f}" '
                f'fill="{n["color"]}" style="animation: pulse 2.8s ease-in-out infinite; animation-delay:{delay}s"/>'
            )
            # label offset outward from center
            out.append(
                f'    <text class="repo-label" x="{n["cx"]:.1f}" y="{n["cy"] - n["r"] - 3:.1f}" '
                f'text-anchor="middle">{_esc(n["name"])}</text>'
            )
        legend = " · ".join(sorted({n["lang"] for n in placed}))[:60]
        out.append(f'    <text class="repo-label" x="235" y="572" text-anchor="middle">{_esc(legend)}</text>')
        out.append('  </g>')
    else:
        out.append(f'  <text x="40" y="84" class="header" style="fill:{t["header"]}">NEURAL.MAP</text>')
        nodes, edges = neural_map(20, 56, 430, 534)
        out.append('  <g id="neural-map" style="animation: fadeIn 1.6s ease-out forwards">')
        for i, (src, dst, _a, _b) in enumerate(edges):
            out.append(
                f'    <line class="neural-edge" x1="{src[0]:.1f}" y1="{src[1]:.1f}" '
                f'x2="{dst[0]:.1f}" y2="{dst[1]:.1f}" style="animation-delay:{0.2 + (i % 6) * 0.15}s"/>'
            )
        for i, (x, y) in enumerate(nodes):
            r = 2.0 + (i % 3) * 0.6
            delay = 0.4 + (i % 8) * 0.12
            out.append(
                f'    <circle class="neural-node" cx="{x:.1f}" cy="{y:.1f}" r="{r}" '
                f'style="animation: pulse 2.4s ease-in-out infinite; animation-delay:{delay}s"/>'
            )
        out.append('  </g>')

    # info panel
    out.append('  <g class="info-panel" transform="translate(470, 56)">')
    y = 0
    for label, value, kind in INFO_ROWS:
        if kind == "header":
            out.append(f'    <g transform="translate(0, {y})"><text x="0" y="0" class="header">{_esc(label)}</text></g>')
            y += 23
        else:
            out.append(
                f'    <g transform="translate(0, {y})">'
                f'<text x="0" y="0" class="row-label">{_esc(label)}</text>'
                f'<text x="120" y="0" class="row-value">{_esc(value)}</text></g>'
            )
            y += 23

    # live stats block
    y += 14
    out.append(f'    <g transform="translate(0, {y})"><text x="0" y="0" class="header">LIVE.METRICS</text></g>')
    y += 23
    repos = stats.public_repos if stats.public_repos is not None else "—"
    stars = stats.total_stars if stats.total_stars is not None else "—"
    followers = stats.followers if stats.followers is not None else "—"
    pushed = stats.latest_push or "—"
    live_tag = "● live" if stats.fetched else "○ cached"
    for label, val in [("PublicRepos", repos), ("TotalStars", stars), ("Followers", followers), ("LastPush", pushed)]:
        out.append(
            f'    <g transform="translate(0, {y})">'
            f'<text x="0" y="0" class="row-label">{label}</text>'
            f'<text x="120" y="0" class="stat-val">{_esc(str(val))}</text></g>'
        )
        y += 21

    # growth sparkline (followers trajectory) — only the followers metric to
    # keep the panel tidy; needs >=2 history points.
    y += 8
    out.append(f'    <g transform="translate(0, {y})"><text x="0" y="0" class="header">GROWTH</text></g>')
    sp_x, sp_y, sp_w, sp_h = 120, y - 2, 250, 22
    pts = sparkline_points(history, "followers", sp_x, sp_y, sp_w, sp_h)
    if pts:
        # filled area under the line
        first_x = pts.split(",")[0]
        last_x = pts.split(" ")[-1].split(",")[0]
        area_pts = f"{first_x},{sp_y + sp_h} " + pts + f" {last_x},{sp_y + sp_h}"
        out.append(f'    <polygon class="spark-fill" points="{area_pts}"/>')
        out.append(f'    <polyline class="spark" points="{pts}"/>')
        out.append(f'    <text x="{sp_x + sp_w + 8:.0f}" y="{sp_y + sp_h - 2:.0f}" class="stat-val">{followers}</text>')
        out.append(f'    <text x="0" y="{sp_y + sp_h - 2:.0f}" class="foot">{len(history)}d · followers</text>')
    else:
        out.append(f'    <text x="0" y="{sp_y + sp_h - 2:.0f}" class="foot">collecting trajectory… (needs 2+ runs)</text>')
    y = sp_y + sp_h + 14

    out.append(
        f'    <g transform="translate(0, {y})">'
        f'<text x="0" y="0" class="foot">{live_tag} · generated {stats.generated_at}</text></g>'
    )
    out.append('  </g>')
    out.append('</svg>')
    return "\n".join(out) + "\n"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Generate profile header SVGs.")
    parser.add_argument("--no-fetch", action="store_true", help="skip live GitHub API fetch")
    parser.add_argument("--no-history", action="store_true", help="do not append to/refresh growth history")
    parser.add_argument("--out-dir", default=".", help="output directory for dark.svg/light.svg")
    args = parser.parse_args()

    stats = LiveStats() if args.no_fetch else fetch_live_stats(HANDLE)
    if not stats.fetched:
        print("warn: live fetch unavailable, using cached placeholders", file=sys.stderr)

    history = load_history()
    if stats.fetched and not args.no_history:
        history = append_history(stats)

    out_dir = args.out_dir
    for theme in ("dark", "light"):
        svg = render(theme, stats, history)
        path = os.path.join(out_dir, f"{theme}.svg")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(svg)
        print(f"wrote {path} ({len(svg)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
