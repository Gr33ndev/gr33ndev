"""Refresh the generated blocks of README.md.

Blocks:
  TOOLS     the public repos you pushed to most recently (own repos, no forks,
            not archived), minus the ones in SKIP_REPOS. Description comes from
            the repo's "About" text, falling back to the hub's tools.json.
  CONTRIBS  recent pull requests to other people's public repos, via the GitHub
            search API; skips own repos and team projects (SKIP_OWNERS), and
            drops PRs that were closed without being merged.

If a source can't be fetched, that block is left as it is, so a flaky API
never wipes the README.

Usage: python scripts/update_readme.py
Env:   GITHUB_TOKEN (optional, raises the API rate limit; set in the workflow)
"""

import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

USER = "gr33ndev"
README = Path(__file__).resolve().parent.parent / "README.md"

RECENT_COUNT = 3
# Repos never listed under "Recently worked on" (case-insensitive):
# this profile repo, the hub, things featured elsewhere, and repos not to show.
SKIP_REPOS = {
    USER, f"{USER}.github.io", "contributions",
    "OpenAmpere",
    "RentClaim", "RailCast", "Vienna-Gyn-Finder",
}
TOOLS_SOURCE = f"https://{USER}.github.io/tools.json"  # fallback descriptions only

CONTRIB_REPOS = 5
# Own account plus team projects (not external open-source contributions).
SKIP_OWNERS = {USER, "Gamify-IT", "VadimSteshkov", "josezehentner"}


# ---------- helpers ----------

def api_headers() -> dict:
    headers = {"Accept": "application/vnd.github+json"}
    if token := os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    return headers


def fetch_json(url: str, headers: dict | None = None):
    req = urllib.request.Request(url, headers={"User-Agent": f"{USER}-readme", **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def replace_block(text: str, name: str, body: str) -> str:
    start, end = f"<!-- {name}:START -->", f"<!-- {name}:END -->"
    pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.S)
    return pattern.sub(lambda _: f"{start}\n{body}\n{end}", text)


def short(desc: str, limit: int = 90) -> str:
    """First sentence, cut at a word boundary if still too long; drops filler openers."""
    text = re.split(r"(?<=[.!?])\s", desc.strip())[0].rstrip(".")
    text = re.sub(r"^(A|An)\s+(stateless,\s*)?(client-side\s*)?(,\s*)?", "", text)
    text = text[0].upper() + text[1:] if text else text
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return text


# ---------- recently worked on ----------

def fetch_repos() -> list[dict]:
    url = f"https://api.github.com/users/{USER}/repos?" + urllib.parse.urlencode(
        {"type": "owner", "sort": "pushed", "direction": "desc", "per_page": 50}
    )
    return fetch_json(url, api_headers())


def fetch_tool_descs() -> dict[str, str]:
    """Map lower-case repo name -> description from the hub's tools.json."""
    try:
        tools = fetch_json(TOOLS_SOURCE)
    except Exception:
        return {}
    out = {}
    for t in tools:
        u = urlparse(t.get("url", ""))
        if u.netloc == f"{USER}.github.io" and (name := u.path.strip("/").split("/")[0]):
            out[name.lower()] = t.get("desc", "")
    return out


def live_link(repo: dict) -> str | None:
    if repo.get("homepage"):
        return repo["homepage"]
    if repo.get("has_pages"):
        return f"https://{USER}.github.io/{repo['name']}/"
    return None


def render_recent(repos: list[dict], tool_descs: dict[str, str]) -> str:
    skip = {s.lower() for s in SKIP_REPOS}
    picked = [
        r for r in repos  # API already sorts by last push, newest first
        if not r.get("fork") and not r.get("archived") and not r.get("private")
        and r["name"].lower() not in skip
    ][:RECENT_COUNT]
    lines = []
    for r in picked:
        desc = r.get("description") or tool_descs.get(r["name"].lower(), "")
        line = f"- **[{r['name']}]({r['html_url']})**"
        if desc:
            line += f": {short(desc)}"
        if live := live_link(r):
            line += f" · [live]({live})"
        lines.append(line)
    return "\n".join(lines)


# ---------- contributions ----------

def search_prs() -> list[dict]:
    excluded = " ".join(f"-user:{o}" for o in sorted(SKIP_OWNERS))
    q = f"is:pr is:public author:{USER} {excluded}"
    url = "https://api.github.com/search/issues?" + urllib.parse.urlencode(
        {"q": q, "sort": "created", "order": "desc", "per_page": 100}
    )
    return fetch_json(url, api_headers())["items"]


def render_contribs(items: list[dict]) -> str:
    """One line per repo, newest activity first: latest PR + count of the others."""
    repos: dict[str, list[dict]] = {}
    for pr in items:  # already sorted newest first
        repo = pr["repository_url"].split("/repos/", 1)[1]  # "owner/name"
        if repo.split("/")[0] in SKIP_OWNERS:
            continue
        merged = (pr.get("pull_request") or {}).get("merged_at")
        if pr["state"] == "closed" and not merged:
            continue  # closed without merge
        pr["_status"] = "merged" if merged else "open"
        repos.setdefault(repo, []).append(pr)

    lines = []
    for repo, prs in list(repos.items())[:CONTRIB_REPOS]:
        latest = prs[0]
        title = latest["title"].replace("[", "(").replace("]", ")")
        line = (
            f"- **[{repo}](https://github.com/{repo})**: "
            f"[{title}]({latest['html_url']}) ({latest['_status']})"
        )
        if len(prs) > 1:
            line += f" · [+{len(prs) - 1} more](https://github.com/{repo}/pulls?q=is%3Apr+author%3A{USER})"
        lines.append(line)
    if not lines:
        return ""  # no section at all rather than an empty one
    return (
        "#### Recent open-source contributions\n\n"
        + "\n".join(lines)
        + f"\n\nFull list: **[{USER}.github.io/contributions](https://{USER}.github.io/contributions)**"
    )


# ---------- main ----------

def main() -> None:
    text = README.read_text(encoding="utf-8")
    new = text

    try:
        new = replace_block(new, "TOOLS", render_recent(fetch_repos(), fetch_tool_descs()))
    except Exception as e:  # keep the old block
        print(f"recent repos: skipped ({e})")

    try:
        new = replace_block(new, "CONTRIBS", render_contribs(search_prs()))
    except Exception as e:  # keep the old block
        print(f"contributions: skipped ({e})")

    try:
        import stats_card
        stats_card.main()
    except Exception as e:  # keep the old card
        print(f"stats card: skipped ({e})")

    if new != text:
        README.write_text(new, encoding="utf-8")
        print("README updated")
    else:
        print("README unchanged")


if __name__ == "__main__":
    main()
