"""Per-network destination address normalization.

Lowercasing every address is correct for EVM chains, where addresses are
hex and case only carries an EIP-55 checksum, and wrong for Solana, whose
base58 addresses are case-sensitive: `Foo...` and `foo...` are different
accounts, so a case-folded denylist entry can be evaded by retyping the
address in another case.
"""

import re

EVM_NETWORKS = frozenset({"ethereum", "base", "polygon", "arbitrum"})
BASE58_NETWORKS = frozenset({"solana"})

_EVM_ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")
# base58 omits 0, O, I and l to avoid visual ambiguity.
_BASE58_ADDRESS = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")


def is_case_sensitive(network: str | None) -> bool:
    """Base58 networks encode distinct accounts in distinct cases; hex networks
    use case only as an EIP-55 checksum."""
    return (network or "").strip().lower() in BASE58_NETWORKS


def normalize_destination(address: str | None, network: str | None) -> str | None:
    """Returns the canonical form of ``address`` for ``network``, or ``None``
    for an empty address.

    EVM addresses are case-folded because their case is only a checksum.
    Anything on a base58 network keeps its case.  An address that matches
    neither shape is treated as an opaque account reference and only trimmed,
    so unknown or off-chain rails still reach the allow/deny lists."""
    raw = (address or "").strip()
    if not raw:
        return None

    if is_case_sensitive(network):
        return raw
    if (network or "").strip().lower() in EVM_NETWORKS or _EVM_ADDRESS.match(raw):
        return raw.lower()
    return raw


def destination_matches(address: str, entry: str, network: str | None) -> bool:
    """Compares a normalized address against a list entry.

    Case-sensitive on networks whose addresses are case-sensitive; anywhere
    else a case-insensitive comparison is used, which can only ever widen a
    denylist match, never narrow one."""
    normalized_entry = normalize_destination(entry, network) or ""
    if is_case_sensitive(network):
        return address == normalized_entry
    return address.casefold() == normalized_entry.casefold()
