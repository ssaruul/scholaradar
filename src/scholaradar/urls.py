from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_PREFIXES = ("utm_", "mc_", "pk_", "piwik_", "hsa_")
TRACKING_PARAMS = {"fbclid", "gclid", "dclid", "msclkid", "yclid", "igshid", "ref", "ref_src", "source", "spm", "_ga", "_gl", "mkt_tok"}
DEFAULT_PORTS = {"http": "80", "https": "443"}


def canonicalize(url: str) -> str:
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower() or "http"
    host = parts.hostname.lower() if parts.hostname else ""
    if host.startswith("www."):
        host = host[4:]
    port = f":{parts.port}" if parts.port and str(parts.port) != DEFAULT_PORTS.get(scheme) else ""
    scheme = "https" if scheme == "http" else scheme
    path = parts.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    query_pairs = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key not in TRACKING_PARAMS and not key.lower().startswith(TRACKING_PREFIXES)
    ]
    query = urlencode(sorted(query_pairs), doseq=True)
    return urlunsplit((scheme, f"{host}{port}", path, query, ""))


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def is_http(url: str) -> bool:
    return urlsplit(url).scheme in {"http", "https"}
