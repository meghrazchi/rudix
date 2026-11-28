"""Edge proxy Caddyfile structure for staging and production compose (0.8.0, R08-01).

``caddy validate`` runs in CI (job ``deploy-config``, step "Validate Caddyfile"); Caddy is not
installed on development machines, so these tests check the Caddyfile text: sites, upstreams,
the body limit, log redaction, forwarded-header trust, and that every snippet import has both
variants on disk.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from app.core.settings.storage import StorageSettings

_REPO = Path(__file__).resolve().parents[2]
_EDGE = _REPO / "deploy" / "compose" / "edge"
_CADDYFILE = _EDGE / "Caddyfile"
_CI = _REPO / ".github" / "workflows" / "ci.yml"
_IMPORT_VARIANTS = {
    "tls_{$EDGE_TLS_MODE:acme}": ("tls_acme", "tls_files"),
    "noindex_{$EDGE_NOINDEX:false}": ("noindex_true", "noindex_false"),
    "matomo_{$EDGE_MATOMO:off}": ("matomo_off", "matomo_on"),
}


def _code(path: Path) -> str:
    """File text without comment lines or trailing comments."""
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = re.sub(r"(^|\s)#.*$", "", line).rstrip()
        if stripped.strip():
            lines.append(stripped)
    return "\n".join(lines)


def _block(text: str, header: str) -> str:
    """The body of the first block whose opening line is ``header {``."""
    start = text.index(header + " {")
    depth = 0
    # Count braces from the block's own opening brace, past any placeholder in the header.
    for index in range(start + len(header) + 1, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    raise AssertionError(f"unterminated block {header}")


@pytest.fixture(scope="module")
def caddyfile() -> str:
    return _code(_CADDYFILE)


def test_sites_route_to_compose_services(caddyfile: str) -> None:
    app = _block(caddyfile, "{$RUDIX_APP_HOST}")
    assert "dynamic a frontend 3000" in app
    api = _block(caddyfile, "{$RUDIX_API_HOST}")
    mcp = _block(api, "handle /mcp*")
    assert "dynamic a mcp {$MCP_HTTP_PORT:8010}" in mcp
    assert "dynamic a api 8000" in api.replace(mcp, "")
    matomo = _code(_EDGE / "matomo_on")
    assert "{$RUDIX_MATOMO_HOST} {" in matomo
    assert "reverse_proxy matomo:80" in matomo


def test_scaled_upstreams_balance_and_stream(caddyfile: str) -> None:
    options = _block(caddyfile, "(upstream_options)")
    for directive in (
        "lb_policy least_conn",
        "fail_duration",
        "max_fails",
        "unhealthy_status 502 503 504",
        "flush_interval -1",
        "stream_timeout",
        "stream_close_delay",
    ):
        assert directive in options, directive
    # Each proxied site uses the shared options and resolves replicas dynamically.
    assert caddyfile.count("import upstream_options") == 3
    assert caddyfile.count("dynamic a ") == 3


def test_body_limit_matches_the_documented_upload_coupling(caddyfile: str) -> None:
    api = _block(caddyfile, "{$RUDIX_API_HOST}")
    match = re.search(r"max_size \{\$EDGE_MAX_REQUEST_BODY:(\d+)MB\}", api)
    assert match, "request_body max_size must come from EDGE_MAX_REQUEST_BODY"
    edge_limit_mb = int(match.group(1))
    upload_limit_mb = StorageSettings.model_fields["max_upload_size_mb"].default
    assert edge_limit_mb == upload_limit_mb + 1 == 26
    for name in ("staging", "production"):
        compose = yaml.safe_load(
            (_REPO / "deploy" / "compose" / f"docker-compose.{name}.yml").read_text()
        )
        env = compose["services"]["edge"]["environment"]
        assert env["EDGE_MAX_REQUEST_BODY"] == "${EDGE_MAX_REQUEST_BODY:-26MB}"


def test_access_log_drops_query_strings_and_credentials(caddyfile: str) -> None:
    log = _block(caddyfile, "(access_log)")
    assert "output stdout" in log
    assert "request>uri regexp [?].* ?redacted" in log
    for header in ("Authorization", "Proxy-Authorization", "Cookie", "X-Api-Key"):
        assert f"request>headers>{header} delete" in log, header
    assert "resp_headers>Set-Cookie delete" in log
    sites = [_block(caddyfile, "{$RUDIX_APP_HOST}"), _block(caddyfile, "{$RUDIX_API_HOST}")]
    assert all("import access_log" in site for site in sites)
    assert "import access_log" in _code(_EDGE / "matomo_on")


def test_regexp_strips_the_query_from_a_uri() -> None:
    # The pattern Caddy applies (Go RE2 and Python agree on this subset).
    pattern = re.compile(r"[?].*")
    assert pattern.sub("?redacted", "/api/v1/share/abc?token=secret&x=1") == (
        "/api/v1/share/abc?redacted"
    )
    assert pattern.sub("?redacted", "/api/v1/health") == "/api/v1/health"


def test_client_forwarded_headers_are_not_trusted() -> None:
    for path in sorted(_EDGE.iterdir()):
        code = _code(path)
        assert "trusted_proxies" not in code, path.name
        assert "client_ip_headers" not in code, path.name
        assert "header_up X-Forwarded" not in code, path.name


def test_every_import_has_both_variants_on_disk(caddyfile: str) -> None:
    for token, variants in _IMPORT_VARIANTS.items():
        assert f"import {token}" in caddyfile, token
        for variant in variants:
            assert (_EDGE / variant).is_file(), variant
    assert caddyfile.count("import tls_{$EDGE_TLS_MODE:acme}") == 2
    assert caddyfile.count("import noindex_{$EDGE_NOINDEX:false}") == 2
    assert caddyfile.strip().endswith("import matomo_{$EDGE_MATOMO:off}")
    assert "import tls_{$EDGE_TLS_MODE:acme}" in _code(_EDGE / "matomo_on")
    # Off variants hold no directive, so an empty optional host never reaches the parser.
    assert _code(_EDGE / "matomo_off") == ""
    assert _code(_EDGE / "noindex_false") == ""


def test_snippet_contents() -> None:
    assert _code(_EDGE / "tls_acme") == "tls {$EDGE_ACME_EMAIL}"
    assert _code(_EDGE / "tls_files") == "tls /etc/caddy/certs/cert.pem /etc/caddy/certs/key.pem"
    assert _code(_EDGE / "noindex_true") == 'header X-Robots-Tag "noindex, nofollow"'
    gitignore = (_REPO / ".gitignore").read_text(encoding="utf-8")
    assert "deploy/compose/edge/certs/" in gitignore.splitlines()


def test_edge_does_not_duplicate_app_security_headers() -> None:
    # The frontend (config/security-headers.mjs) and the API (security_headers.py) set HSTS,
    # CSP, and the frame and content-type headers; the edge adds only X-Robots-Tag.
    for path in sorted(_EDGE.iterdir()):
        headers = re.findall(r"^\s*header\s+(\S+)", _code(path), flags=re.MULTILINE)
        assert set(headers) <= {"X-Robots-Tag"}, path.name
    frontend = (_REPO / "frontend" / "config" / "security-headers.mjs").read_text()
    assert "Strict-Transport-Security" in frontend
    backend = (_REPO / "backend" / "app" / "core" / "security_headers.py").read_text()
    assert "strict-transport-security" in backend


def test_ci_validates_every_caddyfile_variant() -> None:
    workflow = yaml.safe_load(_CI.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["deploy-config"]["steps"]
    names = [step.get("name") for step in steps]
    assert names.index("Validate Caddyfile") == names.index("Check compose files") + 1
    script = steps[names.index("Validate Caddyfile")]["run"]
    assert "for tls_mode in acme files" in script
    assert "for noindex in true false" in script
    assert "for matomo in off on" in script
    assert re.search(r"caddy:2\.\d+ caddy validate --config /etc/caddy/Caddyfile", script)
    assert "--adapter caddyfile" in script
