"""One canonical vendor parser.

The blocklist matcher and the phishing heuristic used to parse the vendor
string separately — `urlparse` in one, a hand-rolled regex in the other — and
disagreed on the inputs that matter most: `https://delta.com@evil.com` is
`evil.com` to the first and `delta` to the second, so whether it was caught
depended on which rule happened to run.  Every rule now resolves the vendor
through `canonical_host`.
"""

import ipaddress
import re
from urllib.parse import urlsplit

_HOSTNAME = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)+$")
_MAX_LABEL_LENGTH = 30

# Brands agents commonly pay, used only for lookalike detection.  A vendor that
# *is* one of these is unaffected; one within a single edit of one is not.
_LOOKALIKE_BRANDS = frozenset(
    {"amazon.com", "apple.com", "coinbase.com", "delta.com", "github.com",
     "google.com", "microsoft.com", "openai.com", "paypal.com", "stripe.com"}
)


def canonical_host(value: str) -> str | None:
    """Resolves a vendor URL or name to its hostname, or ``None`` for free-text
    vendor names.  Userinfo (`user@host`) is discarded by the URL parser, so the
    host returned is the host the payment would actually reach."""
    raw = (value or "").strip().lower()
    if not raw:
        return None

    parsed = urlsplit(raw if "://" in raw else f"https://{raw}")
    try:
        host = (parsed.hostname or "").strip()
    except ValueError:
        return None
    if not host:
        return None
    if _is_ip_literal(host):
        return host
    return host if _HOSTNAME.match(host) else None


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return True


def _has_userinfo(value: str) -> bool:
    raw = (value or "").strip().lower()
    parsed = urlsplit(raw if "://" in raw else f"https://{raw}")
    return "@" in (parsed.netloc or "")


def _edit_distance_within_one(left: str, right: str) -> bool:
    if abs(len(left) - len(right)) > 1:
        return False
    if left == right:
        return False
    longer, shorter = (left, right) if len(left) >= len(right) else (right, left)
    i = j = 0
    edits = 0
    while i < len(longer) and j < len(shorter):
        if longer[i] == shorter[j]:
            i += 1
            j += 1
            continue
        edits += 1
        if edits > 1:
            return False
        i += 1
        if len(longer) == len(shorter):
            j += 1
    return True


def phishing_reason(vendor: str) -> str | None:
    """Returns the heuristic that flagged this vendor, or ``None``."""
    if _has_userinfo(vendor):
        return "VENDOR_URL_EMBEDS_USERINFO"
    if re.search(r"/:[a-zA-Z]", vendor or ""):
        return "VENDOR_URL_SUSPICIOUS_PATH"

    host = canonical_host(vendor)
    if host is None:
        return None
    if _is_ip_literal(host):
        return "VENDOR_HOST_IS_IP_LITERAL"

    labels = host.split(".")
    if any(label.startswith("xn--") for label in labels):
        return "VENDOR_HOST_PUNYCODE"
    if any(len(label) > _MAX_LABEL_LENGTH for label in labels):
        return "VENDOR_HOST_OVERLONG_LABEL"

    registrable = ".".join(labels[-2:])
    if registrable not in _LOOKALIKE_BRANDS:
        for brand in _LOOKALIKE_BRANDS:
            if _edit_distance_within_one(registrable, brand):
                return "VENDOR_HOST_BRAND_LOOKALIKE"
    return None


def vendor_allowlisted(allowed_vendors: list[str], vendor: str) -> bool:
    """Exact host or subdomain match against the agent's allowlist.  Free-text
    entries are compared as normalized strings so an allowlist can name a
    vendor that has no URL."""
    host = canonical_host(vendor)
    candidate = (vendor or "").strip().lower()
    for raw_entry in allowed_vendors:
        entry = (raw_entry or "").strip().lower()
        if not entry:
            continue
        entry_host = canonical_host(entry)
        if entry_host and host:
            if host == entry_host or host.endswith(f".{entry_host}"):
                return True
            continue
        if candidate == entry:
            return True
    return False
