from __future__ import annotations


def normalize_domain(value: str) -> str:
    value = value.strip().lower().rstrip(".")
    if not value or "://" in value or "/" in value or any(char.isspace() for char in value):
        raise ValueError(f"invalid domain: {value!r}")
    try:
        return value.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError(f"invalid domain: {value!r}") from exc


def domain_allowed(host: str, allowed_domains: set[str]) -> bool:
    try:
        normalized_host = normalize_domain(host)
        normalized_allowed = {normalize_domain(domain) for domain in allowed_domains}
    except ValueError:
        return False
    return any(
        normalized_host == domain or normalized_host.endswith("." + domain)
        for domain in normalized_allowed
    )
