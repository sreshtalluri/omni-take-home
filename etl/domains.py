def normalize_domain(domain: str) -> str:
    d = domain.strip().lower().rstrip(".")
    return d.removeprefix("www.")

def reverse_domain(domain: str) -> str:
    return ".".join(reversed(normalize_domain(domain).split(".")))
