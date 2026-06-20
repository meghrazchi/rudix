"""URL building and normalization utilities for the connector SDK."""

from __future__ import annotations

from urllib.parse import urlencode, urlparse, urlunparse


def normalize_url(url: str) -> str:
    """Strip trailing slashes and fragment from a URL; enforce https scheme where absent.

    Raises ValueError if the URL is not an HTTP/HTTPS URL after normalization.
    """
    url = url.strip()

    # urlparse needs a scheme to correctly split netloc from path.
    # Check for an explicit non-http/https scheme before adding the // prefix.
    parsed_raw = urlparse(url)
    if parsed_raw.scheme and parsed_raw.scheme not in {"http", "https"}:
        raise ValueError(f"URL must use http or https scheme, got: {parsed_raw.scheme!r}")

    # Prepend "//" so bare "host/path" forms (no scheme) are parsed correctly.
    if not parsed_raw.scheme:
        url = "//" + url

    parsed = urlparse(url)

    scheme = parsed.scheme or "https"
    path = parsed.path.rstrip("/") or "/"
    normalized = urlunparse((scheme, parsed.netloc, path, parsed.params, parsed.query, ""))
    return normalized


def build_url(base: str, *path_segments: str, **query_params: str | int | bool | None) -> str:
    """Join a base URL with path segments and append query parameters.

    None-valued query params are omitted. Bool values are serialized as lowercase strings.

    Example:
        build_url("https://api.example.com", "v2", "issues", page=1, status=None)
        → "https://api.example.com/v2/issues?page=1"
    """
    base = base.rstrip("/")
    for segment in path_segments:
        segment = str(segment).strip("/")
        if segment:
            base = f"{base}/{segment}"

    params: list[tuple[str, str]] = []
    for key, value in query_params.items():
        if value is None:
            continue
        if isinstance(value, bool):
            params.append((key, str(value).lower()))
        else:
            params.append((key, str(value)))

    if params:
        qs = urlencode(params)
        return f"{base}?{qs}"
    return base
