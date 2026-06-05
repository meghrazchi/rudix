from __future__ import annotations

import base64
import hashlib
import urllib.request
import urllib.error
from datetime import UTC, datetime
from uuid import UUID, uuid4
from xml.etree import ElementTree

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.org_sso_config import OrgSSOConfig


_SAML_NS = "urn:oasis:names:tc:SAML:2.0:metadata"
_DS_NS = "http://www.w3.org/2000/09/xmldsig#"

_MAX_METADATA_BYTES = 512 * 1024  # 512 KB
_FETCH_TIMEOUT_SECONDS = 8


def _sp_entity_id_for_org(organization_id: str) -> str:
    return f"{str(settings.api_base_url).rstrip('/')}/auth/sso/{organization_id}/metadata"


def _sp_acs_url_for_org(organization_id: str) -> str:
    return f"{str(settings.api_base_url).rstrip('/')}{settings.api_prefix}/auth/sso/{organization_id}/callback"


def _parse_saml_metadata(xml_bytes: bytes) -> dict:
    """Extract SSO URL, entity ID, and signing cert from IdP SAML metadata XML."""
    try:
        root = ElementTree.fromstring(xml_bytes)  # noqa: S314
    except ElementTree.ParseError as exc:
        raise ValueError(f"Invalid XML in IdP metadata: {exc}") from exc

    tag = root.tag
    entity_id: str | None = None
    sso_url: str | None = None
    certificate: str | None = None

    if "EntityDescriptor" in tag:
        entity_id = root.get("entityID")

    ns = {
        "md": _SAML_NS,
        "ds": _DS_NS,
    }

    sso_elem = root.find(".//md:IDPSSODescriptor/md:SingleSignOnService", ns)
    if sso_elem is None:
        sso_elem = root.find(".//{%s}SingleSignOnService" % _SAML_NS)
    if sso_elem is not None:
        sso_url = sso_elem.get("Location")

    cert_elem = root.find(".//ds:X509Certificate", ns)
    if cert_elem is None:
        cert_elem = root.find(".//{%s}X509Certificate" % _DS_NS)
    if cert_elem is not None and cert_elem.text:
        certificate = cert_elem.text.strip()

    return {
        "entity_id": entity_id,
        "sso_url": sso_url,
        "certificate": certificate,
    }


def _fetch_metadata_url(url: str) -> bytes:
    """Fetch IdP metadata XML from a URL. Raises ValueError on failure."""
    req = urllib.request.Request(url, headers={"User-Agent": "Rudix-SSO/1.0"})  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT_SECONDS) as resp:  # noqa: S310
            content_bytes = resp.read(_MAX_METADATA_BYTES + 1)
    except urllib.error.URLError as exc:
        raise ValueError(f"Could not reach IdP metadata URL: {exc.reason}") from exc
    except Exception as exc:
        raise ValueError(f"Failed to fetch IdP metadata: {exc}") from exc

    if len(content_bytes) > _MAX_METADATA_BYTES:
        raise ValueError("IdP metadata response exceeds maximum allowed size")
    return content_bytes


def _build_authn_request(sp_entity_id: str, idp_sso_url: str, relay_state: str) -> str:
    """Build a minimal SAML AuthnRequest and return as a redirect URL."""
    request_id = "_" + uuid4().hex
    issue_instant = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    authn_xml = (
        f'<samlp:AuthnRequest'
        f' xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol"'
        f' xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion"'
        f' ID="{request_id}"'
        f' Version="2.0"'
        f' IssueInstant="{issue_instant}"'
        f' Destination="{idp_sso_url}"'
        f' AssertionConsumerServiceBinding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST">'
        f'<saml:Issuer>{sp_entity_id}</saml:Issuer>'
        f'</samlp:AuthnRequest>'
    )
    encoded = base64.b64encode(authn_xml.encode("utf-8")).decode("utf-8")
    import urllib.parse
    params = urllib.parse.urlencode({
        "SAMLRequest": encoded,
        "RelayState": relay_state,
    })
    return f"{idp_sso_url}?{params}"


def _extract_name_id_from_saml_response(xml_bytes: bytes) -> str | None:
    """Parse a SAML Response and extract the NameID."""
    try:
        root = ElementTree.fromstring(xml_bytes)  # noqa: S314
    except ElementTree.ParseError:
        return None

    # Try both SAML assertion namespaces
    for ns_uri in (
        "urn:oasis:names:tc:SAML:2.0:assertion",
        "urn:oasis:names:tc:SAML:1.0:assertion",
    ):
        elem = root.find(".//{%s}NameID" % ns_uri)
        if elem is not None and elem.text:
            return elem.text.strip()
    return None


def _extract_attributes_from_saml_response(xml_bytes: bytes) -> dict[str, str]:
    """Extract SAML attribute values as a flat name→value dict."""
    attrs: dict[str, str] = {}
    try:
        root = ElementTree.fromstring(xml_bytes)  # noqa: S314
    except ElementTree.ParseError:
        return attrs

    for ns_uri in (
        "urn:oasis:names:tc:SAML:2.0:assertion",
        "urn:oasis:names:tc:SAML:1.0:assertion",
    ):
        for attr_elem in root.findall(".//{%s}Attribute" % ns_uri):
            name = attr_elem.get("Name") or attr_elem.get("AttributeName") or ""
            value_elem = attr_elem.find("{%s}AttributeValue" % ns_uri)
            if name and value_elem is not None and value_elem.text:
                attrs[name] = value_elem.text.strip()
    return attrs


class SSOService:
    async def get_config(
        self, db: AsyncSession, *, organization_id: UUID
    ) -> OrgSSOConfig | None:
        result = await db.execute(
            select(OrgSSOConfig).where(OrgSSOConfig.organization_id == organization_id)
        )
        return result.scalar_one_or_none()

    async def get_config_by_domain(
        self, db: AsyncSession, *, domain: str
    ) -> OrgSSOConfig | None:
        result = await db.execute(
            select(OrgSSOConfig).where(
                OrgSSOConfig.domain == domain.strip().lower(),
                OrgSSOConfig.enabled.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def get_config_by_org_id_str(
        self, db: AsyncSession, *, organization_id: str
    ) -> OrgSSOConfig | None:
        try:
            org_uuid = UUID(organization_id)
        except ValueError:
            return None
        return await self.get_config(db, organization_id=org_uuid)

    async def upsert_config(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        payload: dict,
        actor_id: UUID | None,
    ) -> OrgSSOConfig:
        existing = await self.get_config(db, organization_id=organization_id)
        org_id_str = str(organization_id)

        idp_metadata_xml: str | None = payload.get("idp_metadata_xml")
        idp_metadata_url: str | None = payload.get("idp_metadata_url")

        # Parse SAML metadata if provided
        idp_sso_url: str | None = payload.get("idp_sso_url")
        idp_entity_id: str | None = payload.get("idp_entity_id")
        idp_certificate: str | None = payload.get("idp_certificate")

        if idp_metadata_xml:
            try:
                parsed = _parse_saml_metadata(idp_metadata_xml.encode("utf-8"))
                idp_sso_url = idp_sso_url or parsed.get("sso_url")
                idp_entity_id = idp_entity_id or parsed.get("entity_id")
                idp_certificate = idp_certificate or parsed.get("certificate")
            except ValueError:
                pass

        if existing is None:
            config = OrgSSOConfig(
                organization_id=organization_id,
                sp_entity_id=_sp_entity_id_for_org(org_id_str),
                sp_acs_url=_sp_acs_url_for_org(org_id_str),
                created_by_id=actor_id,
            )
            db.add(config)
        else:
            config = existing

        config.sso_type = payload.get("sso_type", "saml")
        config.domain = payload["domain"].strip().lower()
        config.enabled = payload.get("enabled", False)
        config.idp_metadata_url = idp_metadata_url
        config.idp_metadata_xml = idp_metadata_xml
        config.idp_sso_url = idp_sso_url
        config.idp_entity_id = idp_entity_id
        config.idp_certificate = idp_certificate
        config.attribute_mapping = payload.get("attribute_mapping") or {}
        config.updated_by_id = actor_id

        await db.flush()
        await db.refresh(config)
        return config

    async def delete_config(
        self, db: AsyncSession, *, organization_id: UUID
    ) -> bool:
        config = await self.get_config(db, organization_id=organization_id)
        if config is None:
            return False
        await db.delete(config)
        await db.flush()
        return True

    async def test_connection(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        idp_metadata_url: str | None,
        idp_metadata_xml: str | None,
        idp_sso_url: str | None,
    ) -> dict:
        """Validate that the IdP configuration is reachable and parseable."""
        now = datetime.now(UTC)
        detail: str
        success: bool

        try:
            if idp_metadata_url:
                xml_bytes = _fetch_metadata_url(idp_metadata_url)
                _parse_saml_metadata(xml_bytes)
                detail = "IdP metadata URL is reachable and contains valid SAML metadata."
                success = True
            elif idp_metadata_xml:
                _parse_saml_metadata(idp_metadata_xml.encode("utf-8"))
                detail = "IdP metadata XML is valid and parseable."
                success = True
            elif idp_sso_url:
                # Minimal reachability: try a HEAD/GET to the SSO URL
                req = urllib.request.Request(  # noqa: S310
                    idp_sso_url, method="HEAD", headers={"User-Agent": "Rudix-SSO/1.0"}
                )
                try:
                    urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT_SECONDS)  # noqa: S310
                    detail = "IdP SSO URL is reachable."
                    success = True
                except urllib.error.HTTPError as http_err:
                    # IdPs often return 302/400 for bare SSO URLs — still reachable
                    if http_err.code < 500:
                        detail = f"IdP SSO URL responded with HTTP {http_err.code} (reachable)."
                        success = True
                    else:
                        detail = f"IdP SSO URL returned server error: HTTP {http_err.code}."
                        success = False
            else:
                detail = "No IdP metadata URL, XML, or SSO URL provided. Nothing to test."
                success = False
        except ValueError as exc:
            detail = str(exc)
            success = False
        except Exception as exc:
            detail = f"Unexpected error during connection test: {exc}"
            success = False

        # Persist test result on config if it exists
        config = await self.get_config(db, organization_id=organization_id)
        if config is not None:
            config.last_test_at = now
            config.last_test_result = "success" if success else "failure"
            config.last_test_error = None if success else detail
            await db.flush()

        return {
            "success": success,
            "result": "success" if success else "failure",
            "detail": detail,
            "checked_at": now,
        }

    def build_authn_redirect_url(
        self, config: OrgSSOConfig, *, relay_state: str
    ) -> str | None:
        """Return IdP redirect URL with SAMLRequest, or None if not configured."""
        if not config.idp_sso_url:
            return None
        return _build_authn_request(config.sp_entity_id, config.idp_sso_url, relay_state)

    def parse_saml_callback(
        self,
        *,
        saml_response_b64: str,
        config: OrgSSOConfig,
    ) -> dict:
        """
        Decode and parse a SAML Response POST.
        Returns {"name_id": str, "attributes": dict} or raises ValueError.
        In production, replace with python3-saml for full signature validation.
        """
        try:
            xml_bytes = base64.b64decode(saml_response_b64)
        except Exception as exc:
            raise ValueError("SAMLResponse is not valid base64") from exc

        name_id = _extract_name_id_from_saml_response(xml_bytes)
        if not name_id:
            raise ValueError("SAMLResponse does not contain a NameID")

        attributes = _extract_attributes_from_saml_response(xml_bytes)

        # Resolve email from NameID or attribute_mapping
        email: str | None = None
        mapping = config.attribute_mapping or {}
        email_attr = mapping.get("email", "email")
        for candidate in (email_attr, "email", "mail", "emailAddress",
                          "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress"):
            if candidate in attributes:
                email = attributes[candidate]
                break

        if not email:
            # Use NameID as email if it looks like one
            if "@" in name_id:
                email = name_id
            else:
                raise ValueError("Cannot determine user email from SAML response")

        display_name: str | None = None
        name_attr = mapping.get("display_name", "displayName")
        for candidate in (name_attr, "displayName", "cn", "name",
                          "http://schemas.microsoft.com/identity/claims/displayname"):
            if candidate in attributes:
                display_name = attributes[candidate]
                break

        return {
            "name_id": name_id,
            "email": email.strip().lower(),
            "display_name": display_name,
            "attributes": attributes,
        }
