#!/usr/bin/env python3
"""Generate assets/stats.svg (terminal-style GitHub stats card).

- Dengan GH_TOKEN  : pakai GitHub REST API (bytes per bahasa, stars, PR, issues).
- Tanpa token/limit: fallback scraping halaman publik github.com.
Kontribusi + streak selalu diambil dari grafik kontribusi publik.
"""
import os, re, sys, json, html, datetime as dt, urllib.request, urllib.error
from collections import Counter

USER = os.environ.get("GH_USER") or os.environ.get("GITHUB_REPOSITORY_OWNER") or "JohannesMRS"
TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "stats.svg")
UA = {"User-Agent": "profile-stats-generator"}


def http(url, api=False):
    h = dict(UA)
    if api:
        h["Accept"] = "application/vnd.github+json"
        if TOKEN:
            h["Authorization"] = f"Bearer {TOKEN}"
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def api(path):
    return json.loads(http("https://api.github.com" + path, api=True))


def text_of(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip()


# ---------------------------------------------------------------- data
def get_profile_and_langs():
    info = {"repos": None, "stars": None, "followers": None, "prs": None, "issues": None, "created": None}
    langs = Counter()
    try:  # ---- API mode
        u = api(f"/users/{USER}")
        info.update(repos=u["public_repos"], followers=u["followers"], created=u["created_at"][:4])
        repos, page = [], 1
        while True:
            chunk = api(f"/users/{USER}/repos?per_page=100&type=owner&page={page}")
            repos += chunk
            if len(chunk) < 100:
                break
            page += 1
        info["stars"] = sum(r["stargazers_count"] for r in repos)
        for r in repos:
            if r.get("fork"):
                continue
            for k, v in api(f"/repos/{USER}/{r['name']}/languages").items():
                langs[k] += v
        try:
            info["prs"] = api(f"/search/issues?q=author:{USER}+type:pr&per_page=1")["total_count"]
            info["issues"] = api(f"/search/issues?q=author:{USER}+type:issue&per_page=1")["total_count"]
        except Exception:
            pass
        if langs:
            return info, langs
    except Exception as e:
        print("API mode failed, fallback to scraping:", e, file=sys.stderr)

    # ---- scraping fallback
    p = http(f"https://github.com/{USER}")
    m = re.search(r'text-bold color-fg-default">\s*([\d.,k]+)\s*</span>\s*followers', p)
    if m: info["followers"] = m.group(1)
    page, stars, n_repos = 1, 0, 0
    while page <= 5:
        r = http(f"https://github.com/{USER}?tab=repositories&page={page}")
        for k in re.findall(r'itemprop="programmingLanguage">([^<]*)', r):
            langs[k.strip()] += 1
        for blk in re.findall(r'/stargazers">(.*?)</a>', r, re.S):
            d = re.sub(r"[^\d]", "", text_of(blk))
            stars += int(d) if d else 0
        n_repos += r.count('itemprop="name codeRepository"')
        if 'rel="next"' not in r:
            break
        page += 1
    info["repos"], info["stars"] = n_repos, stars
    return info, langs


def get_contributions(created_year):
    today = dt.date.today()
    first = int(created_year) if created_year else today.year - 4
    days = {}
    for y in range(first, today.year + 1):
        to = today.isoformat() if y == today.year else f"{y}-12-31"
        try:
            h = http(f"https://github.com/users/{USER}/contributions?from={y}-01-01&to={to}")
        except Exception as e:
            print("contrib fetch failed", y, e, file=sys.stderr)
            continue
        tips = {}
        for fid, body in re.findall(r'<tool-tip[^>]*for="([^"]+)"[^>]*>([^<]*)', h):
            m = re.match(r"\s*(\d+) contribution", body)
            tips[fid] = int(m.group(1)) if m else 0
        for td in re.findall(r"<td[^>]*data-date[^>]*>", h):
            d = re.search(r'data-date="([^"]+)"', td).group(1)
            i = re.search(r'id="([^"]+)"', td).group(1)
            lv = int(re.search(r'data-level="(\d)"', td).group(1))
            if dt.date.fromisoformat(d) <= today + dt.timedelta(days=1):  # toleransi zona waktu
                days[d] = (tips.get(i, 0), lv)
    return days


def streaks(days):
    ds = sorted(days)
    total = sum(days[d][0] for d in ds)
    longest = run = 0
    prev = None
    for d in ds:
        dd = dt.date.fromisoformat(d)
        if days[d][0] > 0:
            run = run + 1 if prev and (dd - prev).days == 1 else 1
            longest = max(longest, run)
            prev = dd
        else:
            run, prev = 0, None
    # current: berakhir di hari aktif terakhir, hanya valid jika hari ini / kemarin
    active = [d for d in ds if days[d][0] > 0]
    cur = 0
    if active:
        last = dt.date.fromisoformat(active[-1])
        if (dt.date.today() - last).days <= 1:
            while days.get(last.isoformat(), (0, 0))[0] > 0:
                cur += 1
                last -= dt.timedelta(days=1)
    return cur, longest, total


# ---------------------------------------------------------------- svg
FONT = "'Fira Code','JetBrains Mono','SF Mono',Consolas,'DejaVu Sans Mono',monospace"
LANG_COL = {"JavaScript": "#F7DF1E", "Go": "#00ADD8", "PHP": "#8892BF", "Python": "#4B8BBE", "HTML": "#E34F26",
            "CSS": "#1572B6", "TypeScript": "#3178C6", "Blade": "#F7523F", "Shell": "#89E051", "Vue": "#41B883",
            "Dart": "#00B4AB", "EJS": "#A91E50", "Jupyter Notebook": "#DA5B0B", "C": "#8b949e", "Java": "#B07219"}
HEAT = ["#161d27", "#0e4a5c", "#087a96", "#00a3cc", "#38e1ff"]
esc = lambda s: html.escape(str(s), quote=False)


def render(info, langs, days):
    cur, longest, total = streaks(days)
    CW = 9.6
    clips, body = [], []
    t = 0.5

    def cmd(i, text, y):
        nonlocal t
        n = len(text)
        dur = round(n * 0.05, 2)
        vals = ";".join(str(round(k * CW, 1)) for k in range(n + 1))
        clips.append(f'<clipPath id="k{i}"><rect x="100" y="{y-22}" width="0" height="30"><animate attributeName="width" values="{vals}" dur="{dur}s" begin="{t}s" calcMode="discrete" fill="freeze"/></rect></clipPath>')
        body.append(f'<text x="76" y="{y}" fill="#00ADD8" font-size="16" opacity="0"><animate attributeName="opacity" to="1" dur="0.01s" begin="{t}s" fill="freeze"/>$</text>')
        body.append(f'<text x="100" y="{y}" fill="#e6edf3" font-size="16" clip-path="url(#k{i})">{esc(text)}</text>')
        t = round(t + dur + 0.2, 2)
        return t

    def fade(content, begin):
        return f'<g opacity="0"><animate attributeName="opacity" from="0" to="1" dur="0.5s" begin="{begin}s" fill="freeze"/>{content}</g>'

    # --- section 1: stats
    t1 = cmd(0, f"gh stats --user {USER}", 125)
    fmt = lambda v: "–" if v is None else (f"{v:,}" if isinstance(v, int) else str(v))
    items = [("repos", info["repos"]), ("stars", info["stars"]), ("followers", info["followers"]),
             ("contributions", total), ("pull_requests", info["prs"]), ("issues", info["issues"])]
    g = []
    for k, (lab, val) in enumerate(items):
        x = 100 + (k % 3) * 245
        y = 156 + (k // 3) * 26
        g.append(f'<text x="{x}" y="{y}" font-size="14" fill="#8b949e">{lab}:</text><text x="{x + len(lab)*8.4 + 16}" y="{y}" font-size="14" font-weight="700" fill="#00ADD8">{esc(fmt(val))}</text>')
    body.append(fade("".join(g), t1))

    # --- section 2: languages
    t2 = cmd(1, "gh langs --top 6", 244)
    tot = sum(langs.values()) or 1
    top = langs.most_common(6)
    top_pct = (top[0][1] / tot * 100) if top else 1
    g = []
    for k, (name, v) in enumerate(top):
        y = 276 + k * 25
        pct = v / tot * 100
        w = max(6, 460 * pct / top_pct)
        col = LANG_COL.get(name, "#8b949e")
        g.append(f'<text x="100" y="{y}" font-size="13" fill="#c9d1d9">{esc(name)}</text>')
        g.append(f'<rect x="250" y="{y-10}" width="460" height="10" rx="5" fill="#161d27"/>')
        g.append(f'<rect x="250" y="{y-10}" width="0" height="10" rx="5" fill="{col}"><animate attributeName="width" from="0" to="{w:.1f}" dur="0.9s" begin="{t2 + k*0.12:.2f}s" fill="freeze"/></rect>')
        g.append(f'<text x="725" y="{y}" font-size="13" fill="#8b949e">{pct:.1f}%</text>')
    body.append(f'<g>{"".join(g)}</g>')
    t3 = cmd(2, "gh streak", 446)
    t3 = round(max(t3, t2 + 1.2), 2)

    # --- section 3: streak + heatmap
    big = []
    for k, (num, lab) in enumerate([(cur, "current streak"), (longest, "longest streak"), (total, "contributions")]):
        x = 100 + k * 135
        big.append(f'<text x="{x}" y="506" font-size="34" font-weight="700" fill="{"#38e1ff" if k == 0 else "#e6edf3"}">{num:,}</text><text x="{x}" y="528" font-size="12" fill="#8b949e">{lab}</text>')
    body.append(fade("".join(big), t3))
    ds = sorted(days)
    weeks = 26
    last = dt.date.fromisoformat(ds[-1])
    start = last - dt.timedelta(days=(last.weekday() + 1) % 7 + 7 * (weeks - 1))  # sunday-aligned
    cells = []
    for w in range(weeks):
        for d in range(7):
            day = start + dt.timedelta(days=w * 7 + d)
            if day > last:
                continue
            c, lv = days.get(day.isoformat(), (0, 0))
            cells.append(f'<rect x="{495 + w*13}" y="{462 + d*13}" width="10" height="10" rx="2.5" fill="{HEAT[lv]}"/>')
    body.append(fade("".join(cells), t3 + 0.2))
    t4 = round(t3 + 1.0, 2)
    body.append(f'<text x="76" y="560" font-size="16" fill="#00ADD8" opacity="0"><animate attributeName="opacity" to="1" dur="0.01s" begin="{t4}s" fill="freeze"/>$</text>')
    body.append(f'<rect x="98" y="545" width="9" height="19" fill="#e6edf3" opacity="0"><animate attributeName="opacity" values="0;1;1;0;0" keyTimes="0;0.01;0.5;0.51;1" dur="1.1s" begin="{t4}s" repeatCount="indefinite"/></rect>')
    upd = dt.date.today().isoformat()
    body.append(f'<text x="828" y="571" font-size="10" fill="#4b5563" text-anchor="end">updated {upd}</text>')

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="900" height="620" viewBox="0 0 900 620" font-family="{FONT}">
<defs>
  <pattern id="grid" width="30" height="30" patternUnits="userSpaceOnUse"><path d="M30 0H0V30" fill="none" stroke="#111923" stroke-width="1"/></pattern>
  <filter id="blur" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="55"/></filter>
  <linearGradient id="bar" x1="0" x2="1"><stop offset="0" stop-color="#00ADD8"/><stop offset="1" stop-color="#a855f7"/></linearGradient>
  {''.join(clips)}
</defs>
<rect width="900" height="620" rx="22" fill="#0a0e14"/>
<rect width="900" height="620" rx="22" fill="url(#grid)"/>
<circle cx="780" cy="90" r="120" fill="#00ADD8" opacity="0.2" filter="url(#blur)"><animate attributeName="cy" values="90;160;90" dur="9s" repeatCount="indefinite"/></circle>
<circle cx="110" cy="540" r="120" fill="#a855f7" opacity="0.18" filter="url(#blur)"><animate attributeName="cx" values="110;210;110" dur="11s" repeatCount="indefinite"/></circle>
<rect x="50" y="40" width="800" height="540" rx="14" fill="#0d1117" stroke="#263241"/>
<rect x="50" y="40" width="800" height="38" rx="14" fill="#111821"/><rect x="50" y="64" width="800" height="14" fill="#111821"/>
<line x1="50" y1="78" x2="850" y2="78" stroke="#263241"/>
<circle cx="78" cy="59" r="6" fill="#ff5f56"/><circle cx="98" cy="59" r="6" fill="#ffbd2e"/><circle cx="118" cy="59" r="6" fill="#27c93f"/>
<text x="450" y="64" fill="#6e7681" font-size="12" text-anchor="middle">{esc(USER)}@github: ~/stats</text>
<rect x="50" y="576" width="800" height="3" fill="url(#bar)" opacity="0.9"/>
{''.join(body)}
</svg>'''


def main():
    info, langs = get_profile_and_langs()
    days = get_contributions(info["created"])
    if not days:
        sys.exit("no contribution data")
    svg = render(info, langs, days)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(svg)
    print("ok ->", os.path.abspath(OUT))


if __name__ == "__main__":
    main()
