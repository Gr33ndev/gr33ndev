"""Render a GitHub stats card (light + dark SVG) with a readme-stats style rank.

Data comes from the GitHub GraphQL API (public data, any token works; the
Actions GITHUB_TOKEN is enough). Commits are the last 12 months and include
private contributions if "Private contributions" is enabled on the profile.

The rank uses the same formula as anuraghazra/github-readme-stats
(src/calculateRank.js): weighted CDFs of commits, PRs, issues, reviews,
stars and followers mapped to S, A+ ... C.
"""

import json
import os
import urllib.request
from pathlib import Path

USER = "gr33ndev"
OUT = Path(__file__).resolve().parent.parent / "assets"

QUERY = """
query($login: String!) {
  user(login: $login) {
    name
    followers { totalCount }
    pullRequests { totalCount }
    issues { totalCount }
    contributionsCollection {
      totalCommitContributions
      restrictedContributionsCount
      totalPullRequestReviewContributions
    }
    repositories(ownerAffiliations: OWNER, isFork: false, first: 100,
                 orderBy: {field: STARGAZERS, direction: DESC}) {
      totalCount
      nodes { stargazerCount }
    }
  }
}
"""


def fetch_stats() -> dict:
    token = os.environ["GITHUB_TOKEN"]
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": QUERY, "variables": {"login": USER}}).encode(),
        headers={"Authorization": f"Bearer {token}", "User-Agent": f"{USER}-readme"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.load(resp)
    if payload.get("errors"):
        raise RuntimeError(payload["errors"])
    u = payload["data"]["user"]
    cc = u["contributionsCollection"]
    return {
        "commits": cc["totalCommitContributions"] + cc["restrictedContributionsCount"],
        "prs": u["pullRequests"]["totalCount"],
        "issues": u["issues"]["totalCount"],
        "reviews": cc["totalPullRequestReviewContributions"],
        "stars": sum(r["stargazerCount"] for r in u["repositories"]["nodes"]),
        "repos": u["repositories"]["totalCount"],
        "followers": u["followers"]["totalCount"],
    }


def rank(s: dict) -> tuple[str, float]:
    """Port of github-readme-stats calculateRank (all_commits = false)."""
    exp_cdf = lambda x: 1 - 2 ** -x
    log_cdf = lambda x: x / (1 + x)
    parts = [  # (weight, cdf value)
        (2, exp_cdf(s["commits"] / 250)),
        (3, exp_cdf(s["prs"] / 50)),
        (1, exp_cdf(s["issues"] / 25)),
        (1, exp_cdf(s["reviews"] / 2)),
        (4, log_cdf(s["stars"] / 50)),
        (1, log_cdf(s["followers"] / 10)),
    ]
    total = sum(w for w, _ in parts)
    pct = (1 - sum(w * v for w, v in parts) / total) * 100
    thresholds = [1, 12.5, 25, 37.5, 50, 62.5, 75, 87.5, 100]
    levels = ["S", "A+", "A", "A-", "B+", "B", "B-", "C+", "C"]
    level = next(l for t, l in zip(thresholds, levels) if pct <= t)
    return level, pct


THEMES = {
    "light": {"bg": "#ffffff", "border": "#d0d7de", "title": "#1a7f37", "text": "#1f2328",
              "muted": "#656d76", "track": "#d8f0de", "ring": "#1a7f37"},
    "dark": {"bg": "#0d1117", "border": "#30363d", "title": "#3fb950", "text": "#e6edf3",
             "muted": "#8b949e", "track": "#1b3a24", "ring": "#3fb950"},
}


def render(s: dict, theme: str) -> str:
    c = THEMES[theme]
    level, pct = rank(s)
    rows = [
        ("Commits (last year)", s["commits"]),
        ("Pull requests", s["prs"]),
        ("Issues", s["issues"]),
        ("Stars earned", s["stars"]),
        ("Public repos", s["repos"]),
    ]
    row_svg = "\n".join(
        f'<text x="25" y="{78 + i * 25}" class="label">{label}</text>'
        f'<text x="235" y="{78 + i * 25}" class="value" text-anchor="end">{value:,}</text>'
        for i, (label, value) in enumerate(rows)
    )
    # Ring fills with how far up the ranking you are (top 1% = full ring).
    r, circ = 40, 2 * 3.14159 * 40
    filled = circ * (1 - pct / 100)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="420" height="200" viewBox="0 0 420 200" role="img" aria-label="GitHub stats for {USER}: rank {level}">
<style>
  .title {{ font: 600 18px 'Segoe UI', Ubuntu, Sans-Serif; fill: {c['title']}; }}
  .label {{ font: 400 14px 'Segoe UI', Ubuntu, Sans-Serif; fill: {c['muted']}; }}
  .value {{ font: 600 14px 'Segoe UI', Ubuntu, Sans-Serif; fill: {c['text']}; }}
  .rank  {{ font: 700 26px 'Segoe UI', Ubuntu, Sans-Serif; fill: {c['text']}; }}
  .sub   {{ font: 400 11px 'Segoe UI', Ubuntu, Sans-Serif; fill: {c['muted']}; }}
</style>
<rect x="0.5" y="0.5" width="419" height="199" rx="6" fill="{c['bg']}" stroke="{c['border']}"/>
<text x="25" y="38" class="title">gr33ndev on GitHub</text>
{row_svg}
<g transform="translate(330 105)">
  <circle r="{r}" fill="none" stroke="{c['track']}" stroke-width="7"/>
  <circle r="{r}" fill="none" stroke="{c['ring']}" stroke-width="7" stroke-linecap="round"
          stroke-dasharray="{filled:.1f} {circ:.1f}" transform="rotate(-90)"/>
  <text y="9" class="rank" text-anchor="middle">{level}</text>
  <text y="{r + 24}" class="sub" text-anchor="middle">top {max(pct, 0.1):.0f}%</text>
</g>
</svg>
"""


def main(stats: dict | None = None) -> None:
    stats = stats or fetch_stats()
    OUT.mkdir(exist_ok=True)
    for theme in THEMES:
        (OUT / f"stats-{theme}.svg").write_text(render(stats, theme), encoding="utf-8")
    level, pct = rank(stats)
    print(f"stats card: rank {level} (top {pct:.1f}%) {stats}")


if __name__ == "__main__":
    main()
