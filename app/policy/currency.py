"""Minor-unit handling for the amounts the engine reasons about.

Every amount on the wire is an integer count of the currency's *minor* unit.
For USD that is cents, but the exponent is not 2 everywhere: JPY has no minor
unit at all and BHD has three.  Treating `amount_cents` as hundredths
regardless of currency reports a JPY 10,000 payment as 100, which is a 100x
error in both the audit log and anything a human reads before approving.
"""

# ISO 4217 exponents that are not 2.  Everything else is assumed to be 2.
_ZERO_DECIMAL = frozenset(
    {"BIF", "CLP", "DJF", "GNF", "ISK", "JPY", "KMF", "KRW", "PYG",
     "RWF", "UGX", "UYI", "VND", "VUV", "XAF", "XOF", "XPF"}
)
_THREE_DECIMAL = frozenset({"BHD", "IQD", "JOD", "KWD", "LYD", "OMR", "TND"})


def minor_unit_exponent(currency: str) -> int:
    code = currency.strip().upper()
    if code in _ZERO_DECIMAL:
        return 0
    if code in _THREE_DECIMAL:
        return 3
    return 2


def to_major_units(amount_minor: int, currency: str) -> float:
    """Converts a minor-unit amount to major units for display and audit."""
    exponent = minor_unit_exponent(currency)
    if exponent == 0:
        return float(amount_minor)
    return round(amount_minor / (10 ** exponent), exponent)


def currencies_match(request_currency: str, agent_currency: str) -> bool:
    return request_currency.strip().upper() == agent_currency.strip().upper()
