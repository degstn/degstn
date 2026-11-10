#!/usr/bin/env python3
"""Build dark.svg and light.svg for the profile README.

The picture is a terminal window that has just run `neofetch`: the ASCII
logo from art.txt on the left, "Key: value" lines on the right. A few of
the values are live numbers pulled from the GitHub API on every build.

    python3 build.py            rebuild if anything changed
    python3 build.py --force    rebuild no matter what
    python3 build.py --offline  skip the API and reuse stats.json

Standard library only. .github/workflows/readme.yml runs it once a day and
commits the result when something actually changed.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import urllib.request
from collections import Counter
from datetime import date, datetime, timezone
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

# ── Edit me ──────────────────────────────────────────────────────────────────

LOGIN = "degstn"                 # GitHub account the numbers come from
USER, HOST = "drew", "degstn"    # the drew@degstn line above the info
MACHINE = "MacBook-Pro"          # hostname in the shell prompt
TITLE = "degstn"                 # window title
COMMAND = "neofetch"
TIMEZONE = "America/New_York"    # for the "Last login" stamp

# One "Key: value" per line. Two spaces start another pair on the same line.
# {placeholders} are filled in from the GitHub API:
#   {uptime} {languages} {repos} {stars} {commits} {followers} {last_push}
INFO = """
OS: macOS 27 arm64
Host: MacBook Pro (M5 Max)
Uptime: {uptime} on GitHub
Shell: zsh
School: Lehigh University
Major: Materials Science & Eng., IBE Honors
Minor: Physics
Work: Founder, Aremac
Languages: {languages}
Camera: Hasselblad X2D 100C, Canon R5
Fabrication: Fusion 360, Bambu H2D
Web: degstn.com
Email: d@degstn.com
X: @aegstn
Instagram: @ntsged
LinkedIn: in/degstn
Repos: {repos}  Commits: {commits}  Followers: {followers}
Last push: {last_push}
"""

PINNED_LANGUAGES = ["Swift"]     # always listed first; the rest come from your repos
MAX_LANGUAGES = 4

# Key color per theme, and the two colors the logo fades between (top, bottom).
ACCENT = {"dark": "#FF6A2B", "light": "#CC3D00"}
LOGO = {"dark": ("#FF9A52", "#FF5A1F"), "light": ("#E0561A", "#B83200")}

# The logo is art.txt: any ASCII art works, one line per row.

# ── Look ─────────────────────────────────────────────────────────────────────

FONT_SIZE = 14
CELL_W = 8.4                     # 0.6em: the advance of SF Mono and Menlo at 14px
CELL_H = 17
BASELINE = 13
COLS = 80                        # the window grows if a line needs more
ART_INDENT, ART_GAP = 2, 4       # columns left of the logo, and between logo and info

PAD_X, PAD_TOP, PAD_BOTTOM = 14, 10, 12
TITLEBAR = 28
RADIUS = 10
MARGIN_X, MARGIN_TOP, MARGIN_BOTTOM = 26, 14, 40   # room for the window shadow

MONO = 'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, "Liberation Mono", "DejaVu Sans Mono", monospace'
SANS = '-apple-system, BlinkMacSystemFont, "SF Pro Text", "Helvetica Neue", "Segoe UI", Arial, sans-serif'

THEMES = {
    "dark": {
        "body": "#1E1E1E", "bar_top": "#3E3E40", "bar_bottom": "#343436", "bar_line": "#111111",
        "title": "#C9C9C9", "edge": ("#000000", 0.55), "rim": ("#FFFFFF", 0.13), "shadow": 0.5,
        "fg": "#E6E6E6", "cursor": "#A0A0A0",
        "ansi": ["#3A3A3C", "#FF453A", "#30D158", "#FFD60A", "#0A84FF", "#BF5AF2", "#64D2FF", "#D1D1D6",
                 "#636366", "#FF6961", "#5EE07F", "#FFE04D", "#409CFF", "#DA8FFF", "#8FE0FF", "#F2F2F7"],
    },
    "light": {
        "body": "#FFFFFF", "bar_top": "#F4F4F4", "bar_bottom": "#E6E6E6", "bar_line": "#CFCFCF",
        "title": "#3A3A3A", "edge": ("#000000", 0.2), "rim": None, "shadow": 0.22,
        "fg": "#1F1F1F", "cursor": "#7A7A7A",
        "ansi": ["#1C1C1E", "#FF3B30", "#34C759", "#FFCC00", "#007AFF", "#AF52DE", "#32ADE6", "#C7C7CC",
                 "#8E8E93", "#FF6259", "#5DD57C", "#FFD633", "#3395FF", "#BF75E5", "#5BBDEB", "#E5E5EA"],
    },
}

ROOT = Path(__file__).resolve().parent
ART_FILE = ROOT / "art.txt"
STATS_FILE = ROOT / "stats.json"
API = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")


# ── GitHub numbers ───────────────────────────────────────────────────────────

def github(path: str):
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": f"{LOGIN}-profile-readme",
    }
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(API + path, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def fetch_stats(previous: dict) -> dict:
    """Public numbers for LOGIN. Any call that fails keeps its previous value."""
    stats = dict(previous)

    def profile():
        user = github(f"/users/{LOGIN}")
        stats["repos"] = user["public_repos"]
        stats["followers"] = user["followers"]
        stats["created"] = user["created_at"][:10]

    def repositories():
        repos, page = [], 1
        while True:
            batch = github(f"/users/{LOGIN}/repos?type=owner&per_page=100&page={page}")
            repos.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        stats["stars"] = sum(repo["stargazers_count"] for repo in repos)
        # Your own work only: no forks, and not this profile repo (the bot pushes to it).
        own = [r for r in repos if not r["fork"] and r["name"].lower() != LOGIN.lower()]
        own.sort(key=lambda r: r["pushed_at"] or "", reverse=True)
        # Most repos first; ties keep the order above, so the most recently pushed wins.
        counts = Counter(r["language"] for r in own if r["language"])
        stats["languages"] = sorted(counts, key=lambda language: -counts[language])
        if own and own[0]["pushed_at"]:
            pushed = datetime.fromisoformat(own[0]["pushed_at"].replace("Z", "+00:00"))
            local = pushed.astimezone(ZoneInfo(TIMEZONE))
            stats["last_push"] = {"repo": own[0]["name"], "date": local.date().isoformat()}

    def commits():
        stats["commits"] = github(f"/search/commits?q=author:{LOGIN}&per_page=1")["total_count"]

    for label, step in (("profile", profile), ("repositories", repositories), ("commit count", commits)):
        try:
            step()
        except Exception as error:  # a flaky network or a rate limit shouldn't break the README
            print(f"warning: {label} unavailable ({error}); keeping the last known value")
    return stats


def uptime(since: date, today: date) -> str:
    years, months = today.year - since.year, today.month - since.month
    if today.day < since.day:
        months -= 1
    if months < 0:
        years, months = years - 1, months + 12
    parts = [f"{n} {unit}{'' if n == 1 else 's'}" for n, unit in ((years, "year"), (months, "month")) if n]
    return ", ".join(parts) or "less than a month"


def placeholder_values(stats: dict, today: date) -> dict:
    languages = list(PINNED_LANGUAGES)
    languages += [language for language in stats.get("languages", []) if language not in languages]
    values = {
        "uptime": uptime(date.fromisoformat(stats["created"]), today),
        "languages": ", ".join(languages[:MAX_LANGUAGES]),
        "repos": f"{stats['repos']:,}",
        "stars": f"{stats.get('stars', 0):,}",
        "commits": f"{stats['commits']:,}",
        "followers": f"{stats['followers']:,}",
        "last_push": "",
    }
    push = stats.get("last_push")
    if push:
        day = date.fromisoformat(push["date"])
        year = "" if day.year == today.year else f", {day.year}"
        values["last_push"] = f"{push['repo']}, {day:%b} {day.day}{year}"
    return values


def fill_in(text: str, values: dict) -> str:
    for name, value in values.items():
        text = text.replace("{" + name + "}", value)
    return text


# ── Drawing ──────────────────────────────────────────────────────────────────

def num(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def mix(start: str, end: str, t: float) -> str:
    a = [int(start[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(end[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02X}" for x, y in zip(a, b))


class Screen:
    """Text and color blocks on a character grid, theme-free until render()."""

    def __init__(self):
        self.text = []     # (row, col, string, style, fade)
        self.blocks = []   # (row, col, width, color)
        self.rows = 0
        self.cols = 0

    def put(self, row, col, string, style="", fade=None):
        self.text.append((row, col, string, style, fade))
        self.rows = max(self.rows, row + 1)
        self.cols = max(self.cols, col + len(string))

    def block(self, row, col, width, color):
        self.blocks.append((row, col, width, color))
        self.rows = max(self.rows, row + 1)
        self.cols = max(self.cols, col + width)


def info_rows(values: dict):
    """INFO as rows of (col, string, style) segments, keys styled "k"."""
    rows = []
    for line in INFO.strip().splitlines():
        row, col = [], 0
        for part in re.split(r"(\s{2,})", fill_in(line.strip(), values)):
            if part and not part.isspace():
                key, colon, value = part.partition(": ")
                if colon:
                    row.append((col, key, "k"))
                    row.append((col + len(key), ":", ""))
                    row.append((col + len(key) + 2, value, ""))
                else:
                    row.append((col, part, ""))
            col += len(part)
        rows.append(row)
    return rows


def compose(values: dict, now: datetime) -> Screen:
    art = [line.rstrip() for line in ART_FILE.read_text(encoding="utf-8").splitlines()]
    while art and not art[-1]:
        art.pop()
    info = info_rows(values)
    info_col = ART_INDENT + max(map(len, art)) + ART_GAP if art else 0
    prompt = f"{USER}@{MACHINE} ~ %"

    screen = Screen()
    screen.put(0, 0, f"Last login: {now:%a %b} {now.day:2d} {now:%H:%M:%S} on ttys000")
    screen.put(1, 0, f"{prompt} {COMMAND}")

    top = 3
    height = max(len(art), len(info) + 5)   # name, rule, the lines, a blank, two rows of blocks
    art_top = top + (height - len(art)) // 2
    for i, line in enumerate(art):
        screen.put(art_top + i, ART_INDENT, line, "a", fade=i / max(1, len(art) - 1))

    screen.put(top, info_col, USER, "k")
    screen.put(top, info_col + len(USER), "@")
    screen.put(top, info_col + len(USER) + 1, HOST, "k")
    screen.put(top + 1, info_col, "-" * len(f"{USER}@{HOST}"))
    for i, row in enumerate(info):
        for col, string, style in row:
            screen.put(top + 2 + i, info_col + col, string, style)
    for i in range(16):
        screen.block(top + len(info) + 3 + i // 8, info_col + (i % 8) * 3, 3, i)

    screen.put(top + height + 1, 0, prompt)
    screen.block(top + height + 1, len(prompt) + 1, 1, "cursor")
    return screen


def render(screen: Screen, theme: str, description: str) -> str:
    t = THEMES[theme]
    cols = max(COLS, screen.cols + 1)
    win_w = cols * CELL_W + 2 * PAD_X
    win_h = TITLEBAR + PAD_TOP + screen.rows * CELL_H + PAD_BOTTOM
    width, height = win_w + 2 * MARGIN_X, win_h + MARGIN_TOP + MARGIN_BOTTOM
    x0, y0 = MARGIN_X, MARGIN_TOP
    window = f'x="{x0}" y="{y0}" width="{num(win_w)}" height="{num(win_h)}" rx="{RADIUS}"'

    def outline(inset, color, opacity):
        return (f'<rect x="{x0 + inset}" y="{y0 + inset}" width="{num(win_w - 2 * inset)}" height="{num(win_h - 2 * inset)}" '
                f'rx="{RADIUS - inset}" fill="none" stroke="{color}" stroke-opacity="{opacity}"/>')

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{num(width)}" height="{num(height)}" '
        f'viewBox="0 0 {num(width)} {num(height)}" role="img" aria-labelledby="title desc">',
        f'<title id="title">{escape(f"{TITLE}: a terminal window running {COMMAND}")}</title>',
        f'<desc id="desc">{escape(description)}</desc>',
        "<style>"
        f".t{{font:{FONT_SIZE}px {MONO};fill:{t['fg']};font-variant-ligatures:none}}"
        f".k{{fill:{ACCENT[theme]};font-weight:700}}"
        ".a{font-weight:700}"
        f".title{{font:600 13px {SANS};fill:{t['title']}}}"
        ".cur{animation:blink 1.1s steps(1) infinite}"
        "@keyframes blink{50%{opacity:0}}"
        "@media (prefers-reduced-motion:reduce){.cur{animation:none}}"
        "</style>",
        "<defs>",
        '<filter id="shadow" x="-20%" y="-20%" width="140%" height="150%" color-interpolation-filters="sRGB">'
        '<feGaussianBlur in="SourceAlpha" stdDeviation="10"/><feOffset dy="10"/>'
        f'<feComponentTransfer><feFuncA type="linear" slope="{t["shadow"]}"/></feComponentTransfer>'
        '<feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge></filter>',
        f'<linearGradient id="bar" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{t["bar_top"]}"/>'
        f'<stop offset="1" stop-color="{t["bar_bottom"]}"/></linearGradient>',
        f'<clipPath id="window"><rect {window}/></clipPath>',
        "</defs>",
        # the window: body, title bar, outline, the three buttons, the title
        f'<rect {window} fill="{t["body"]}" filter="url(#shadow)"/>',
        '<g clip-path="url(#window)">',
        f'<rect x="{x0}" y="{y0}" width="{num(win_w)}" height="{TITLEBAR}" fill="url(#bar)"/>',
        f'<rect x="{x0}" y="{y0 + TITLEBAR - 1}" width="{num(win_w)}" height="1" fill="{t["bar_line"]}"/>',
        "</g>",
        outline(0.5, *t["edge"]),
    ]
    if t["rim"]:
        out.append(outline(1.5, *t["rim"]))
    for i, (fill, ring) in enumerate((("#FF5F57", "#E0443E"), ("#FEBC2E", "#D89E24"), ("#28C840", "#1AAB29"))):
        out.append(f'<circle cx="{x0 + 20 + i * 20}" cy="{y0 + TITLEBAR / 2}" r="5.75" fill="{fill}" stroke="{ring}" stroke-width="0.5"/>')
    out.append(f'<text class="title" x="{num(x0 + win_w / 2)}" y="{y0 + 18.5}" text-anchor="middle">{escape(TITLE)}</text>')

    # The terminal contents. Every run of text is pinned to the character grid
    # and given its exact width, so it lines up in whatever monospace font the
    # viewer has (SF Mono, Menlo, Consolas, ...).
    out.append(f'<g class="t" transform="translate({num(x0 + PAD_X)} {y0 + TITLEBAR + PAD_TOP})">')
    for row, col, span, color in screen.blocks:
        x, y = num(col * CELL_W), row * CELL_H
        if color == "cursor":
            out.append(f'<rect class="cur" x="{x}" y="{y + 1}" width="{num(CELL_W)}" height="{CELL_H - 2}" fill="{t["cursor"]}"/>')
        else:
            out.append(f'<rect x="{x}" y="{y}" width="{num(span * CELL_W + 0.2)}" height="{CELL_H}" fill="{t["ansi"][color]}"/>')
    for row, col, string, style, fade in screen.text:
        attrs = f' class="{style}"' if style else ""
        if fade is not None:
            attrs += f' fill="{mix(*LOGO[theme], fade)}"'
        # logo rows split at every space; other lines only where two or more spaces meet
        for run in re.finditer(r"\S+" if fade is not None else r"\S+(?: \S+)*", string):
            out.append(
                f'<text{attrs} x="{num((col + run.start()) * CELL_W)}" y="{row * CELL_H + BASELINE}" '
                f'textLength="{num(len(run.group()) * CELL_W)}">{escape(run.group())}</text>'
            )
    out += ["</g>", "</svg>"]
    return "\n".join(out) + "\n"


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    force, offline = "--force" in sys.argv, "--offline" in sys.argv
    saved = json.loads(STATS_FILE.read_text()) if STATS_FILE.exists() else {}
    stats = saved.get("stats", {})
    if not offline:
        stats = fetch_stats(stats)
    missing = [name for name in ("repos", "followers", "created", "commits") if name not in stats]
    if missing:
        print(f"error: no data for {', '.join(missing)} and nothing saved in stats.json to fall back on")
        return 1

    now = datetime.now(timezone.utc).astimezone(ZoneInfo(TIMEZONE))
    values = placeholder_values(stats, now.date())
    # Rebuild only when a value, this script or the logo changed, so the daily
    # run doesn't commit a new "Last login" stamp for nothing.
    recipe = json.dumps(values, sort_keys=True).encode() + Path(__file__).read_bytes() + ART_FILE.read_bytes()
    built = hashlib.sha1(recipe).hexdigest()
    targets = {theme: ROOT / f"{theme}.svg" for theme in THEMES}
    if not force and saved.get("built") == built and all(path.exists() for path in targets.values()):
        print("nothing changed")
        return 0

    screen = compose(values, now)
    lines = [line.strip() for line in fill_in(INFO, values).strip().splitlines() if line.strip()]
    description = f"{USER}@{HOST}. " + "; ".join(re.sub(r"\s{2,}", ", ", line) for line in lines)
    for theme, path in targets.items():
        path.write_text(render(screen, theme, description), encoding="utf-8")
    STATS_FILE.write_text(json.dumps({"stats": stats, "built": built}, indent=2) + "\n")
    print("rebuilt " + ", ".join(path.name for path in targets.values()))
    for name, value in values.items():
        print(f"  {name}: {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
