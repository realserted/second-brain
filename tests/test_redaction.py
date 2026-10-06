import pytest

from second_brain.redaction import Redactor

ALL = ["ssn", "bank_account", "routing_number", "credit_card", "email", "phone"]


@pytest.mark.parametrize(
    "text, leaked, tag",
    [
        ("SSN: 123-45-6789", "123-45-6789", "[REDACTED_SSN]"),
        ("Card 4111 1111 1111 1111 on file", "4111 1111 1111 1111", "[REDACTED_CREDIT_CARD]"),
        ("Account number: 000123456789", "000123456789", "[REDACTED_BANK_ACCOUNT]"),
        ("Routing number: 021000021", "021000021", "[REDACTED_ROUTING_NUMBER]"),
        ("mail me at jo@example.com", "jo@example.com", "[REDACTED_EMAIL]"),
        ("call (206) 555-0142 today", "555-0142", "[REDACTED_PHONE]"),
    ],
)
def test_each_category_is_redacted(text, leaked, tag):
    result = Redactor(ALL).redact(text)
    assert leaked not in result.text
    assert tag in result.text


def test_label_is_kept_value_removed():
    out = Redactor(["bank_account"]).redact("Account number: 000123456789").text
    assert out == "Account number: [REDACTED_BANK_ACCOUNT]"


def test_non_luhn_digit_runs_are_kept():
    # A 16-digit policy-style number that fails Luhn must survive.
    text = "Reference 1234 5678 9012 3456"
    assert Redactor(["credit_card"]).redact(text).text == text


def test_invalid_ssn_ranges_are_ignored():
    assert Redactor(["ssn"]).redact("000-12-3456").text == "000-12-3456"


def test_disabled_categories_pass_through():
    assert Redactor(["ssn"]).redact("jo@example.com").text == "jo@example.com"


def test_counts_are_reported():
    result = Redactor(ALL).redact("123-45-6789 and 4111111111111111")
    assert result.counts == {"ssn": 1, "credit_card": 1}


def test_unknown_category_rejected():
    with pytest.raises(ValueError):
        Redactor(["passport"])
