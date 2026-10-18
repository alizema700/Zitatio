import datetime as dt
from decimal import Decimal

import pytest

from zitatio.facts import AMOUNT, extract_facts, parse_number, uid_is_valid


def values(text, kind=None):
    return [f.value for f in extract_facts(text) if kind is None or f.kind == kind]


@pytest.mark.parametrize(
    "text",
    ["CHF 3'500'000", "CHF 3’500’000", "CHF 3.5 Mio.", "3,5 Mio. CHF", "TCHF 3'500",
     "Fr. 3 500 000.–", "CHF 3,500,000", "CHF 3.500.000,00", "3.5 Millionen CHF"],
)
def test_amount_spellings_normalize_to_same_value(text):
    assert values(text, AMOUNT) == [("CHF", Decimal(3_500_000))]


def test_parse_number_decimal_vs_thousands():
    assert parse_number("12.50") == Decimal("12.50")
    assert parse_number("1.250") == Decimal(1250)
    assert parse_number("1,25", scaled=True) == Decimal("1.25")


def test_dates_durations_percent():
    facts = extract_facts("Fest bis 31. Dezember 2029, danach zwölf Monaten Frist, Zins 2,4 %, fällig 31.03.2030.")
    assert [f.kind for f in facts] == ["datum", "frist", "prozent", "datum"]
    assert facts[0].value == dt.date(2029, 12, 31)
    assert facts[1].value == (12, "Monate")
    assert facts[2].value == Decimal("2.4")


def test_invalid_dates_are_ignored():
    assert values("am 31.02.2025") == []


def test_uid_checksum():
    assert uid_is_valid("CHE-411.872.905")
    assert not uid_is_valid("CHE-411.827.905")
    assert values("UID CHE-411.872.905") == ["CHE-411.872.905"]
