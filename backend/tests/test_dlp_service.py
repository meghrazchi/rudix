import pytest

from app.domains.documents.services.dlp_service import DlpFinding, DlpScanResult, scan_text_for_dlp


def test_scan_empty_text_returns_allow() -> None:
    result = scan_text_for_dlp("", enabled=True, action="warn", min_findings=3)
    assert result.action == "allow"
    assert result.skipped is True


def test_scan_disabled_returns_allow() -> None:
    text = "SSN: 123-45-6789 CC: 4111-1111-1111-1111"
    result = scan_text_for_dlp(text, enabled=False, action="quarantine", min_findings=1)
    assert result.action == "allow"
    assert result.skipped is True


def test_scan_clean_text_returns_allow() -> None:
    text = "This is a completely clean document about machine learning algorithms."
    result = scan_text_for_dlp(text, enabled=True, action="warn", min_findings=3)
    assert result.action == "allow"
    assert result.total_findings == 0


def test_scan_detects_ssn() -> None:
    # 9XX-prefix SSNs are excluded by the pattern (reserved range); use valid ranges.
    text = "Employee SSN: 123-45-6789 and another 234-56-7890 and 345-67-8901 are here."
    result = scan_text_for_dlp(text, enabled=True, action="warn", min_findings=1)
    ssn_finding = next((f for f in result.findings if f.category == "ssn"), None)
    assert ssn_finding is not None
    assert ssn_finding.count >= 3


def test_scan_detects_credit_card() -> None:
    text = (
        "Payment cards: 4111-1111-1111-1111, 5500 0000 0000 0004, and 4000000000000002 "
        "are stored here."
    )
    result = scan_text_for_dlp(text, enabled=True, action="quarantine", min_findings=1)
    cc_finding = next((f for f in result.findings if f.category == "credit_card"), None)
    assert cc_finding is not None
    assert cc_finding.count >= 3


def test_scan_detects_phone_number() -> None:
    text = "Contact: (555) 123-4567, 555-987-6543, and +1 800-555-0199 for support."
    result = scan_text_for_dlp(text, enabled=True, action="warn", min_findings=1)
    phone_finding = next((f for f in result.findings if f.category == "phone_number"), None)
    assert phone_finding is not None
    assert phone_finding.count >= 3


def test_scan_below_min_findings_returns_allow() -> None:
    text = "Call us at (555) 123-4567 for more information."
    result = scan_text_for_dlp(text, enabled=True, action="quarantine", min_findings=5)
    assert result.action == "allow"
    assert result.total_findings < 5


def test_scan_above_min_findings_applies_action_warn() -> None:
    text = (
        "SSN 123-45-6789, CC 4111-1111-1111-1111, phone (555) 123-4567, "
        "another 987-65-4321 here."
    )
    result = scan_text_for_dlp(text, enabled=True, action="warn", min_findings=3)
    assert result.action == "warn"
    assert result.total_findings >= 3


def test_scan_above_min_findings_applies_action_quarantine() -> None:
    text = (
        "SSN 123-45-6789, CC 4111-1111-1111-1111, phone (555) 123-4567, "
        "another SSN 987-65-4321."
    )
    result = scan_text_for_dlp(text, enabled=True, action="quarantine", min_findings=3)
    assert result.action == "quarantine"


def test_scan_above_min_findings_applies_action_reject() -> None:
    text = (
        "SSN 123-45-6789, CC 4111-1111-1111-1111, phone (555) 123-4567, "
        "another SSN 987-65-4321."
    )
    result = scan_text_for_dlp(text, enabled=True, action="reject", min_findings=3)
    assert result.action == "reject"


def test_scan_findings_contain_counts_not_values() -> None:
    text = "SSN: 123-45-6789, 555-12-3456, 987-65-4321."
    result = scan_text_for_dlp(text, enabled=True, action="warn", min_findings=1)
    for finding in result.findings:
        assert isinstance(finding.category, str)
        assert isinstance(finding.count, int)
        assert finding.count > 0


def test_scan_to_dict_structure() -> None:
    text = "SSN: 123-45-6789, 555-12-3456, 987-65-4321 CC: 4111-1111-1111-1111."
    result = scan_text_for_dlp(text, enabled=True, action="warn", min_findings=1)
    d = result.to_dict()
    assert "action" in d
    assert "total_findings" in d
    assert "findings" in d
    assert isinstance(d["findings"], list)
    for entry in d["findings"]:
        assert "category" in entry
        assert "count" in entry


def test_scan_filters_example_email_domains() -> None:
    text = "Contact example@example.com or test@test.com — these are documentation examples."
    result = scan_text_for_dlp(text, enabled=True, action="warn", min_findings=1)
    email_finding = next((f for f in result.findings if f.category == "email_address"), None)
    assert email_finding is None or email_finding.count == 0


def test_scan_counts_real_emails() -> None:
    text = (
        "Email alice@acme.org, bob@widget.io, carol@startup.ai, and dana@bigcorp.com "
        "for onboarding."
    )
    result = scan_text_for_dlp(text, enabled=True, action="warn", min_findings=1)
    email_finding = next((f for f in result.findings if f.category == "email_address"), None)
    assert email_finding is not None
    assert email_finding.count >= 4
