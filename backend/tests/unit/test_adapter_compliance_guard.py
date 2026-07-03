"""Static compliance guard over adapter source (spec acceptance 23/24).

This is a grep-style, network-free structural check asserting that NO source
adapter ever *targets* a LinkedIn/Facebook login, profile, or authenticated
endpoint. It complements the per-adapter respx tests (which prove behaviour at
runtime) by proving the property statically across the real ``app.adapters``
tree — so a newly added adapter cannot silently introduce a forbidden URL.

Rules enforced (over REAL adapter source; the ``mock/`` tree is excluded because
its ``linkedin.com``/``facebook.com`` strings are *synthetic demo output data*
assigned to result fields, never fetched by any HTTP client):

- No adapter code contains ``linkedin.com`` at all (LinkedIn is an official
  connector stub; scraping/login is never wired, no HTTP client imported).
- No adapter code targets a Facebook login/authenticated/profile/group/messenger
  endpoint, nor a Graph ``/me`` user-node read. The only permitted Facebook hosts
  are the official Graph API reading a PAGE node (``graph.facebook.com/…/{page}``)
  and PUBLIC ``facebook.com`` Page URLs discovered/normalised via SERP (never
  fetched as HTML).
- No adapter automates any login/oauth authorize flow against these hosts.

Crucially, the scan keeps URL *string literals* visible (a URL passed to
``httpx.get(...)`` IS a target and must be caught) and only blanks genuine
docstrings and ``#`` comments, which legitimately *describe* forbidden endpoints
in order to forbid them. A negative-control test proves the guard is not vacuous.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ADAPTERS_DIR = Path(__file__).resolve().parents[2] / "app" / "adapters"
REPO_ROOT = ADAPTERS_DIR.parents[1]

# Directories whose string URLs are demo OUTPUT data (never network targets).
_EXCLUDED_DIRS = {"mock", "__pycache__"}

# Forbidden substrings that must never appear in real adapter code. Case-insensitive.
_FORBIDDEN_PATTERNS: tuple[tuple[str, str], ...] = (
    ("linkedin.com", "any linkedin.com URL (no official connector is wired)"),
    ("facebook.com/login", "facebook login endpoint"),
    ("facebook.com/profile.php", "facebook personal-profile endpoint"),
    ("facebook.com/people/", "facebook personal-profile endpoint"),
    ("facebook.com/groups/", "facebook group endpoint"),
    ("facebook.com/messages/", "facebook messenger endpoint"),
    ("graph.facebook.com/v19.0/me", "facebook graph /me user-node read"),
    ("/oauth/authorize", "an automated oauth/login authorize flow"),
)


def _docstring_ranges(tree: ast.AST) -> list[tuple[int, int]]:
    """Line ranges of genuine docstrings (module/class/func first string stmt)."""
    ranges: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list) or not body:
            continue
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            end = getattr(first, "end_lineno", first.lineno) or first.lineno
            ranges.append((first.lineno, end))
    return ranges


def _code_lines(path: Path) -> list[tuple[int, str]]:
    """Return (lineno, source) for scannable lines.

    Only genuine docstrings and ``#`` comments are removed. URL string literals
    that are passed to code (e.g. request targets) remain visible so the guard
    catches them.
    """
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(path))
    doc_ranges = _docstring_ranges(tree)

    def _in_docstring(lineno: int) -> bool:
        return any(start <= lineno <= stop for start, stop in doc_ranges)

    out: list[tuple[int, str]] = []
    for i, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if _in_docstring(i):
            continue
        code = re.split(r"\s#", raw, maxsplit=1)[0]  # drop trailing inline comment
        out.append((i, code))
    return out


def _real_adapter_files() -> list[Path]:
    files = [p for p in sorted(ADAPTERS_DIR.rglob("*.py")) if not (_EXCLUDED_DIRS & set(p.parts))]
    assert files, "no real adapter source files found"
    # Sanity: the source adapters we care about are in the set.
    names = {p.name for p in files}
    for expected in ("facebook_signals.py", "linkedin.py", "serp_jobs.py"):
        assert expected in names, f"expected adapter {expected} not scanned"
    return files


def _scan(path: Path) -> list[str]:
    hits: list[str] = []
    for lineno, code in _code_lines(path):
        low = code.lower()
        for needle, why in _FORBIDDEN_PATTERNS:
            if needle in low:
                try:
                    rel: Path | str = path.relative_to(REPO_ROOT)
                except ValueError:
                    rel = path
                hits.append(f"{rel}:{lineno} targets {why!r}: {code.strip()}")
    return hits


def test_no_real_adapter_targets_forbidden_social_endpoint() -> None:
    """AC 23/24: no real adapter code targets a login/profile/authenticated social URL."""
    violations: list[str] = []
    for path in _real_adapter_files():
        violations.extend(_scan(path))
    assert not violations, (
        "forbidden social endpoint(s) targeted in real adapter code:\n" + "\n".join(violations)
    )


def test_guard_is_not_vacuous_negative_control(tmp_path: Path) -> None:
    """A synthetic adapter that fetches a linkedin login URL MUST be flagged."""
    evil = tmp_path / "evil_adapter.py"
    evil.write_text(
        '"""A docstring may mention linkedin.com/login — that is allowed."""\n'
        "import httpx\n"
        "async def scrape():\n"
        '    return await httpx.AsyncClient().get("https://www.linkedin.com/login")\n'
    )
    hits = _scan(evil)
    assert hits, "negative control failed: guard did not catch a real forbidden target"
    assert any("linkedin.com" in h for h in hits)


def test_linkedin_adapter_has_no_http_client_and_no_url() -> None:
    """The LinkedIn stub imports no HTTP client and contains no linkedin.com URL."""
    path = ADAPTERS_DIR / "sources" / "linkedin.py"
    for _lineno, code in _code_lines(path):
        low = code.lower()
        assert "linkedin.com" not in low
        assert "httpx" not in low
        assert "aiohttp" not in low
        assert "requests" not in low


def test_facebook_only_uses_graph_page_and_serp_hosts() -> None:
    """Facebook adapter's only network hosts are Graph page-node + SERP web search."""
    from app.adapters.sources import facebook_signals as fb

    assert fb.GRAPH_API_BASE == "https://graph.facebook.com/v19.0"
    assert fb.SERPAPI_SEARCH_URL.startswith("https://serpapi.com/")
    # PAGE_FIELDS must be low-sensitivity public business fields — nothing about
    # people, followers, insights, or posts.
    for banned in ("followers", "insights", "posts", "friends", "likes"):
        assert banned not in fb.PAGE_FIELDS


@pytest.mark.parametrize(
    "url",
    [
        "https://facebook.com/profile.php?id=123",
        "https://www.facebook.com/people/John-Doe/100",
        "https://facebook.com/groups/somegroup",
        "https://m.facebook.com/messages/thread/1",
        "https://facebook.com/events/999",
        "https://facebook.com/story.php?story_fbid=1",
        "https://www.linkedin.com/in/jane",
    ],
)
def test_facebook_page_normaliser_rejects_non_public_page_urls(url: str) -> None:
    """The page-URL normaliser drops personal profiles/groups/messenger/etc."""
    from app.adapters.sources.facebook_signals import facebook_page_from_url

    assert facebook_page_from_url(url) is None
