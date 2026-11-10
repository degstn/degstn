#!/usr/bin/env python3
"""Build dark.svg and light.svg for the profile README.

The picture is a macOS Terminal window that has just run `neofetch`: the
ASCII logo from art.txt on the left, "Key: value" lines on the right. Some
of it is live: the GitHub numbers, the newest macOS build Apple has
published, and the "Last login" stamp, which is the moment of the build.

    python3 build.py            fetch fresh numbers and rebuild
    python3 build.py --offline  rebuild from the numbers saved in stats.json

Standard library only. .github/workflows/readme.yml runs it every hour and
publishes the two SVGs to the `output` branch, which is what README.md shows.
"""

from __future__ import annotations

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
TITLE = "degstn — -zsh — {cols}×{rows}"   # window title, the way Terminal writes it; the size is filled in
COMMAND = "neofetch"
TIMEZONE = "America/New_York"    # for the "Last login" stamp

# One "Key: value" per line. Two spaces start another pair on the same line.
# {placeholders} are filled in live:
#   {macos} {uptime} {languages} {repos} {stars} {commits} {followers} {last_push}
INFO = """
OS: {macos} arm64
Host: MacBook Pro (M5 Max)
Uptime: {uptime} on GitHub
Shell: zsh
School: Lehigh University
Major: Materials Science & Eng., IBE Honors
Minor: Physics
Work: Founder, Aremac
Languages: {languages}
Camera: Hasselblad X2D 100C, Canon R5
Fabrication: Fusion 360, SolidWorks
Web: degstn.com
Email: d@degstn.com
X: @aegstn
Instagram: @degstn, @ntsged
LinkedIn: in/degstn
Repos: {repos}  Commits: {commits}  Followers: {followers}
Last push: {last_push}
"""

PINNED_LANGUAGES = ["Swift"]     # always listed first; the rest come from your repos
MAX_LANGUAGES = 4
MACOS_FALLBACK = "macOS 27"      # shown only until Apple's release feed has been read once

# Key color per theme, and the two colors the logo fades between (top, bottom).
ACCENT = {"dark": "#FF6A2B", "light": "#CC3D00"}
LOGO = {"dark": ("#FF9A52", "#FF5A1F"), "light": ("#E0561A", "#B83200")}

# The logo is art.txt: any ASCII art works, one line per row.

# ── Look ─────────────────────────────────────────────────────────────────────
# Measured from a macOS 27 Terminal window (SF Mono 11 in 7 x 14 pt cells,
# 32 pt title bar, 14 pt window buttons) and scaled up by 1.2.

FONT_SIZE = 13.2
CELL_W = 8.4
CELL_H = 17
BASELINE = 12.5
COLS = 80                        # the window grows if a line needs more
ART_INDENT, ART_GAP = 2, 4       # columns left of the logo, and between logo and info

PAD_X, PAD_TOP, PAD_BOTTOM = 12, 8, 12
TITLEBAR = 38
RADIUS = 20
MARGIN_X, MARGIN_TOP, MARGIN_BOTTOM = 30, 16, 48   # room for the window shadow

MONO = 'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, "Liberation Mono", "DejaVu Sans Mono", monospace'
SANS = '-apple-system, BlinkMacSystemFont, "SF Pro Text", "Helvetica Neue", "Segoe UI", Arial, sans-serif'

# The three window buttons: main fill, the lighter bloom low in the glass, the dark rim at the sides.
BUTTONS = [("#EC776B", "#EC9A92", "#C0392B"), ("#F3C050", "#F9D86A", "#B8780E"), ("#7ECD4C", "#AEDD8C", "#2F7D1F")]
FOLDER_BLUES = ("#95D2F2", "#6BB3E1", "#64ADDC")   # front top, front bottom, back

THEMES = {
    "light": {
        "body": "#FFFFFF", "bar_line": "#E5E5E5", "title": "#585858",
        "edge": ("#000000", 0.18), "rim": None, "shadow": 0.3, "glow": 0.2,
        "fg": "#000000", "cursor": "#929292",
        "ansi": ["#1C1C1E", "#FF3B30", "#34C759", "#FFCC00", "#007AFF", "#AF52DE", "#32ADE6", "#C7C7CC",
                 "#8E8E93", "#FF6259", "#5DD57C", "#FFD633", "#3395FF", "#BF75E5", "#5BBDEB", "#E5E5EA"],
    },
    "dark": {
        "body": "#1E1E1E", "bar_line": "#333333", "title": "#A6A6A6",
        "edge": ("#000000", 0.6), "rim": ("#FFFFFF", 0.14), "shadow": 0.55, "glow": 0.16,
        "fg": "#F5F5F5", "cursor": "#6E6E6E",
        "ansi": ["#3A3A3C", "#FF453A", "#30D158", "#FFD60A", "#0A84FF", "#BF5AF2", "#64D2FF", "#D1D1D6",
                 "#636366", "#FF6961", "#5EE07F", "#FFE04D", "#409CFF", "#DA8FFF", "#8FE0FF", "#F2F2F7"],
    },
}

ROOT = Path(__file__).resolve().parent
ART_FILE = ROOT / "art.txt"
STATS_FILE = ROOT / "stats.json"
API = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
APPLE_FEED = os.environ.get("APPLE_FEED_URL", "https://developer.apple.com/news/releases/rss/releases.rss")


# ── Live numbers ─────────────────────────────────────────────────────────────

def download(url: str, headers: dict | None = None) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": f"{LOGIN}-profile-readme", **(headers or {})})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def github(path: str):
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return json.loads(download(API + path, headers))


def version_key(version: str) -> tuple:
    return tuple(int(part) for part in version.split("."))


def newest_macos(feed: str) -> dict | None:
    """The highest macOS version in Apple's release feed, betas included.

    Titles look like "macOS 27.3 beta (26C5035r)", "macOS 27.3 beta 2 (...)",
    "macOS 27.3 RC (...)" or "macOS 27.2.1 (26B131)". The feed is newest
    first, so the first title with the highest version is its latest build.
    """
    title = re.compile(r"macOS(?: [A-Za-z][A-Za-z ]*?)? (\d+(?:\.\d+)*)(?: (beta|RC)(?: \d+)?)? \(([0-9A-Za-z]+)\)", re.I)
    best = None
    for text in re.findall(r"<title>(?:<!\[CDATA\[)?\s*(macOS[^<\]]*?)\s*(?:\]\]>)?</title>", feed):
        match = title.fullmatch(text)
        if match and (best is None or version_key(match[1]) > version_key(best["version"])):
            best = {"version": match[1], "stage": (match[2] or "").lower(), "build": match[3]}
    return best


def fetch_stats(previous: dict) -> dict:
    """Fresh numbers. Any source that fails keeps its previous value."""
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
        # Your own work only: no forks, and not this profile repo.
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

    def macos():
        found = newest_macos(download(APPLE_FEED).decode("utf-8", "replace"))
        known = stats.get("macos")
        # The feed only holds recent releases, so never step back to an older version.
        if found and not (known and version_key(known["version"]) > version_key(found["version"])):
            stats["macos"] = found

    for label, step in (("profile", profile), ("repositories", repositories), ("commit count", commits), ("macOS version", macos)):
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
        "macos": MACOS_FALLBACK,
        "uptime": uptime(date.fromisoformat(stats["created"]), today),
        "languages": ", ".join(languages[:MAX_LANGUAGES]),
        "repos": f"{stats['repos']:,}",
        "stars": f"{stats.get('stars', 0):,}",
        "commits": f"{stats['commits']:,}",
        "followers": f"{stats['followers']:,}",
        "last_push": "",
    }
    macos = stats.get("macos")
    if macos:
        stage = {"beta": " Beta", "rc": " RC"}.get(macos["stage"], "")
        values["macos"] = f"macOS {macos['version']}{stage} ({macos['build']})"
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
    title = TITLE.format(cols=cols, rows=screen.rows)

    def outline(inset, color, opacity):
        return (f'<rect x="{x0 + inset}" y="{y0 + inset}" width="{num(win_w - 2 * inset)}" height="{num(win_h - 2 * inset)}" '
                f'rx="{RADIUS - inset}" fill="none" stroke="{color}" stroke-opacity="{opacity}"/>')

    def gradient(name, top, bottom):
        return (f'<linearGradient id="{name}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{top}"/>'
                f'<stop offset="1" stop-color="{bottom}"/></linearGradient>')

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{num(width)}" height="{num(height)}" '
        f'viewBox="0 0 {num(width)} {num(height)}" role="img" aria-labelledby="title desc">',
        f'<title id="title">{escape(f"{USER}@{HOST}: a terminal window running {COMMAND}")}</title>',
        f'<desc id="desc">{escape(description)}</desc>',
        "<style>"
        f".t{{font:{FONT_SIZE}px {MONO};fill:{t['fg']};font-variant-ligatures:none}}"
        f".k{{fill:{ACCENT[theme]};font-weight:700}}"
        ".a{font-weight:700}"
        f".title{{font:700 15.5px {SANS};fill:{t['title']}}}"
        ".cur{animation:blink 1.1s steps(1) infinite}"
        "@keyframes blink{50%{opacity:0}}"
        "@media (prefers-reduced-motion:reduce){.cur{animation:none}}"
        "</style>",
        "<defs>",
        '<filter id="shadow" x="-20%" y="-20%" width="140%" height="150%" color-interpolation-filters="sRGB">'
        '<feGaussianBlur in="SourceAlpha" stdDeviation="13"/><feOffset dy="13"/>'
        f'<feComponentTransfer><feFuncA type="linear" slope="{t["shadow"]}"/></feComponentTransfer>'
        '<feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge></filter>',
        '<filter id="glow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="1.5"/></filter>',
        gradient("folder", *FOLDER_BLUES[:2]),
    ]
    for i, (fill, bloom, rim) in enumerate(BUTTONS):
        out.append(f'<radialGradient id="button{i}" cx="0.5" cy="0.92" r="0.8"><stop offset="0" stop-color="{bloom}"/>'
                   f'<stop offset="1" stop-color="{fill}"/></radialGradient>')
        out.append(f'<linearGradient id="rim{i}"><stop offset="0" stop-color="{rim}" stop-opacity="0.9"/>'
                   f'<stop offset="0.2" stop-color="{rim}" stop-opacity="0"/><stop offset="0.8" stop-color="{rim}" stop-opacity="0"/>'
                   f'<stop offset="1" stop-color="{rim}" stop-opacity="0.9"/></linearGradient>')
    out += [
        "</defs>",
        # the window: one surface for title bar and body, a hairline between them
        f'<rect x="{x0}" y="{y0}" width="{num(win_w)}" height="{num(win_h)}" rx="{RADIUS}" fill="{t["body"]}" filter="url(#shadow)"/>',
        f'<rect x="{x0}" y="{y0 + TITLEBAR - 1}" width="{num(win_w)}" height="1" fill="{t["bar_line"]}"/>',
        outline(0.5, *t["edge"]),
    ]
    if t["rim"]:
        out.append(outline(1.5, *t["rim"]))

    # window buttons: a soft glow underneath, glass with a bloom low down, a rim that darkens at the sides
    cy = y0 + 18.9
    for i, (fill, _, rim) in enumerate(BUTTONS):
        cx = num(x0 + 18.9 + i * 27.6)
        out.append(f'<circle cx="{cx}" cy="{cy + 1.2}" r="8.4" fill="{fill}" opacity="{t["glow"]}" filter="url(#glow)"/>')
        out.append(f'<circle cx="{cx}" cy="{cy}" r="8.1" fill="url(#button{i})" stroke="{rim}" stroke-opacity="0.28" stroke-width="0.6"/>')
        out.append(f'<circle cx="{cx}" cy="{cy}" r="8" fill="none" stroke="url(#rim{i})" stroke-width="0.9"/>')

    # folder glyph and title, left-aligned after the buttons
    fx, fy = x0 + 99.6, y0 + 11.6
    out.append(f'<rect x="{num(fx)}" y="{num(fy)}" width="7.6" height="6" rx="1.7" fill="{FOLDER_BLUES[2]}"/>')
    out.append(f'<rect x="{num(fx)}" y="{num(fy + 1.9)}" width="16.8" height="12.5" rx="2.2" fill="{FOLDER_BLUES[2]}"/>')
    out.append(f'<rect x="{num(fx)}" y="{num(fy + 3.7)}" width="16.8" height="10.7" rx="2.2" fill="url(#folder)"/>')
    out.append(f'<text class="title" x="{num(x0 + 123)}" y="{num(y0 + 25.2)}">{escape(title)}</text>')

    # The terminal contents. Every run of text is pinned to the character grid
    # and given its exact width, so it lines up in whatever monospace font the
    # viewer has (SF Mono, Menlo, Consolas, ...).
    out.append(f'<g class="t" transform="translate({num(x0 + PAD_X)} {y0 + TITLEBAR + PAD_TOP})">')
    for row, col, span, color in screen.blocks:
        x, y = num(col * CELL_W), row * CELL_H
        if color == "cursor":
            out.append(f'<rect class="cur" x="{x}" y="{y}" width="{num(CELL_W)}" height="{CELL_H}" fill="{t["cursor"]}"/>')
        else:
            out.append(f'<rect x="{x}" y="{y}" width="{num(span * CELL_W + 0.2)}" height="{CELL_H}" fill="{t["ansi"][color]}"/>')
    for row, col, string, style, fade in screen.text:
        attrs = f' class="{style}"' if style else ""
        if fade is not None:
            attrs += f' fill="{mix(*LOGO[theme], fade)}"'
        # logo rows split at every space; other lines only where two or more spaces meet
        for run in re.finditer(r"\S+" if fade is not None else r"\S+(?: \S+)*", string):
            out.append(
                f'<text{attrs} x="{num((col + run.start()) * CELL_W)}" y="{num(row * CELL_H + BASELINE)}" '
                f'textLength="{num(len(run.group()) * CELL_W)}">{escape(run.group())}</text>'
            )
    out += ["</g>", "</svg>"]
    return "\n".join(out) + "\n"


# ── Main ─────────────────────────────────────────────────────────────────────

def load_stats() -> dict:
    try:
        saved = json.loads(STATS_FILE.read_text())
    except (OSError, ValueError):
        return {}
    return saved.get("stats", saved) if isinstance(saved, dict) else {}


def main() -> int:
    stats = load_stats()
    if "--offline" not in sys.argv:
        stats = fetch_stats(stats)
    missing = [name for name in ("repos", "followers", "created", "commits") if name not in stats]
    if missing:
        print(f"error: no data for {', '.join(missing)} and nothing saved in stats.json to fall back on")
        return 1

    now = datetime.now(timezone.utc).astimezone(ZoneInfo(TIMEZONE))
    values = placeholder_values(stats, now.date())
    screen = compose(values, now)
    lines = [line.strip() for line in fill_in(INFO, values).strip().splitlines() if line.strip()]
    description = f"{USER}@{HOST}. " + "; ".join(re.sub(r"\s{2,}", ", ", line) for line in lines)
    for theme in THEMES:
        (ROOT / f"{theme}.svg").write_text(render(screen, theme, description), encoding="utf-8")
    STATS_FILE.write_text(json.dumps(stats, indent=2) + "\n")
    print(f"built dark.svg and light.svg at {now:%Y-%m-%d %H:%M:%S %Z}")
    for name, value in values.items():
        print(f"  {name}: {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
