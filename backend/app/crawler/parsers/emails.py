"""Email extraction: plain regex, mailto links, obfuscation decoding, and the
Cloudflare ``data-cfemail`` XOR scheme (spec §8 "name [at] domain [dot] com",
§9 email-obfuscation decoding + mailto parsing).

The obfuscation decoder normalizes the common human-readable disguises
(``[at]`` / ``(at)`` / `` at `` / ``[dot]`` / `` dot `` / ``&#64;``) back into a
real address BEFORE the standard regex runs, so ``jane [at] acme [dot] com``
and ``jane&#64;acme.com`` are both recovered. Cloudflare's email protection
hides the address in a hex ``data-cfemail`` attribute XOR-encoded against its
first byte; ``decode_cfemail`` reverses it.
"""

from __future__ import annotations

import re
from html import unescape

__all__ = [
    "EMAIL_RE",
    "decode_cfemail",
    "deobfuscate",
    "extract_emails",
]

# Deliberately conservative: a local-part, @, a dotted domain with a 2+ char TLD.
EMAIL_RE = re.compile(
    r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}",
)

# Ordered obfuscation rewrites. Longer/space-padded variants first so that
# " at " does not clobber "[at]" mid-rewrite. Case-insensitive.
_AT_PATTERNS = [
    re.compile(r"\s*[\[\(\{]\s*at\s*[\]\)\}]\s*", re.IGNORECASE),  # [at] (at) {at}
    re.compile(r"\s+at\s+", re.IGNORECASE),  # bare " at "
]
_DOT_PATTERNS = [
    re.compile(r"\s*[\[\(\{]\s*dot\s*[\]\)\}]\s*", re.IGNORECASE),  # [dot] (dot)
    re.compile(r"\s+dot\s+", re.IGNORECASE),  # bare " dot "
]


def deobfuscate(text: str) -> str:
    """Rewrite human-obfuscated ``at``/``dot`` disguises to ``@``/``.``.

    Also resolves HTML entities (``&#64;`` -> ``@``, ``&#46;`` -> ``.``) so the
    downstream regex sees a normal address. Non-destructive elsewhere.
    """
    if not text:
        return ""
    text = unescape(text)
    for pat in _AT_PATTERNS:
        text = pat.sub("@", text)
    for pat in _DOT_PATTERNS:
        text = pat.sub(".", text)
    return text


def decode_cfemail(hex_str: str) -> str | None:
    """Decode a Cloudflare ``data-cfemail`` hex string to a plain address.

    The first byte is the XOR key; each subsequent byte XORed with it yields an
    ASCII character. Returns None on malformed input.
    """
    hex_str = (hex_str or "").strip()
    if len(hex_str) < 4 or len(hex_str) % 2 != 0:
        return None
    try:
        data = bytes.fromhex(hex_str)
    except ValueError:
        return None
    key = data[0]
    try:
        decoded = "".join(chr(b ^ key) for b in data[1:])
    except ValueError:  # pragma: no cover - chr can't fail for 0..255
        return None
    return decoded if "@" in decoded else None


def _normalize(email: str) -> str:
    return email.strip().strip(".").lower()


# File extensions that ``EMAIL_RE`` mis-reads as a domain when a retina/asset name
# like ``logo@2x.png`` or ``hero@3x.jpg`` appears in the HTML — an image path, not
# a person.
_ASSET_TLDS = frozenset(
    {
        "png", "jpg", "jpeg", "gif", "svg", "webp", "bmp", "ico", "avif",
        "css", "js", "mjs", "json", "map", "xml", "woff", "woff2", "ttf",
        "eot", "otf", "mp4", "webm", "mp3", "wav", "pdf", "zip",
    }
)
# Domains that only ever appear as copy-paste placeholders in templates/boilerplate.
_PLACEHOLDER_DOMAINS = frozenset(
    {
        "example.com", "example.org", "example.net", "email.com", "domain.com",
        "yourdomain.com", "yourcompany.com", "mycompany.com", "company.com",
        "yoursite.com", "mysite.com", "website.com", "test.com", "sentry.io",
    }
)


def _is_asset_or_placeholder(email: str) -> bool:
    """True for image/asset filenames (``logo@2x.png``) and template placeholders
    (``you@example.com``) that the address regex would otherwise accept."""
    domain = email.rsplit("@", 1)[-1] if "@" in email else ""
    if not domain:
        return True
    tld = domain.rsplit(".", 1)[-1]
    if tld in _ASSET_TLDS:
        return True
    if domain in _PLACEHOLDER_DOMAINS:
        return True
    return False


def extract_emails(*, text: str = "", html: str = "", soup=None) -> list[str]:
    """Return de-duplicated, lower-cased emails from text/HTML/soup.

    Sources merged, in priority order:
    1. ``mailto:`` hrefs (highest signal),
    2. Cloudflare ``data-cfemail`` / ``.__cf_email__`` protected spans,
    3. de-obfuscated visible text (``[at]``/``[dot]``/entities),
    4. raw regex over the visible text.
    """
    found: list[str] = []
    seen: set[str] = set()

    def _add(candidate: str | None) -> None:
        if not candidate:
            return
        for match in EMAIL_RE.findall(candidate):
            norm = _normalize(match)
            if norm and norm not in seen and not _is_asset_or_placeholder(norm):
                seen.add(norm)
                found.append(norm)

    if soup is not None:
        # mailto: links
        for a in soup.select("a[href^=mailto], a[href^=MAILTO]"):
            href = a.get("href", "")
            addr = href.split(":", 1)[1] if ":" in href else ""
            addr = addr.split("?", 1)[0]  # drop ?subject=...
            _add(deobfuscate(addr))
        # Cloudflare protected emails: <a data-cfemail="..."> or <span class=__cf_email__>
        for el in soup.select("[data-cfemail]"):
            decoded = decode_cfemail(el.get("data-cfemail", ""))
            _add(decoded)

    if html:
        # Catch cfemail even when soup wasn't passed (defensive).
        for m in re.findall(r'data-cfemail="([0-9a-fA-F]+)"', html):
            _add(decode_cfemail(m))

    if text:
        _add(deobfuscate(text))
        _add(text)  # raw pass for already-clean addresses

    return found
