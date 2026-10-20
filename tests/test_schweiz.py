"""Schweizer Prüfungen: Zeichnungsberechtigung, Kapitalschutz, gesetzliche Sätze."""

import datetime as dt

from zitatio.dataroom import DataRoom
from zitatio.pipeline import run_check
from zitatio.report import parse_report
from zitatio.swiss import apply_rates, check_capital, check_signatures, swiss_flags
from zitatio.verify import Status, verify

HR = """Handelsregister des Kantons Zürich - Auszug
Firma: Muster AG
Aktienkapital: CHF 100'000, eingeteilt in 100 Namenaktien zu CHF 1'000, vollständig liberiert.
Huber, Anna, von Zürich, in Zürich, Präsidentin des Verwaltungsrates, mit Einzelunterschrift
Meier, Dr. Paul, von Bern, in Zürich, Geschäftsführer, mit Kollektivunterschrift zu zweien
Frei, Lea, von Basel, in Zürich, mit Kollektivprokura zu zweien
Graf, Urs, von Chur, in Chur, Mitglied des Verwaltungsrates, ohne Zeichnungsberechtigung
"""


def _room(**docs) -> DataRoom:
    room = DataRoom()
    room.add("1.1 Handelsregisterauszug.txt", HR.encode())
    for name, text in docs.items():
        room.add(name, text.encode())
    return room


def _warned(room: DataRoom) -> set[str]:
    return {d for f in check_signatures(room) if f.level == "warnung" for d in f.docs}


def test_signatures_are_checked_against_the_commercial_register():
    room = _room(**{
        "4.1 Mietvertrag.txt": "Mietvertrag\nFür die Muster AG: Anna Huber, Präsidentin",
        "4.2 Liefervertrag.txt": "Liefervertrag\nFür die Muster AG: Dr. Paul Meier, CEO; Lea Frei, Prokuristin",
        "4.3 Kreditvertrag.txt": "Kreditvertrag\nFür die Muster AG: Dr. Paul Meier, CEO",
        "4.4 Leasingvertrag.txt": "Leasingvertrag\nFür die Muster AG: Urs Graf, Verwaltungsrat",
        "4.5 Lizenzvertrag.txt": "Lizenz\nFür die Muster AG: Hans Meier, Einkauf",
        "4.6 NDA.txt": "NDA\nFür die Lieferantin AG: Max Muster",
    })
    assert _warned(room) == {"4.3", "4.4", "4.5"}


def test_capital_loss_and_over_indebtedness():
    balance = "Muster AG - Jahresrechnung 2025\nBilanz per 31.12.2025 (in CHF)\nAktienkapital 100'000\n" \
              "Gesetzliche Gewinnreserve 20'000\nEigenkapital {}\n"
    for equity, expected in (("80'000", "ok"), ("50'000", "warnung"), ("-10'000", "warnung")):
        room = _room(**{"2.1 Jahresrechnung 2025.txt": balance.format(equity)})
        flag, = check_capital(room)
        assert flag.level == expected, equity
    flag, = check_capital(_room(**{"2.1 Jahresrechnung 2025.txt": balance.format("-10'000")}))
    assert "Überschuldung" in flag.title and "725b" in flag.text


def test_statutory_rates_are_checked_against_the_law():
    text = ("Seit 2024 beträgt der MWST-Normalsatz 8.1 %.\n\nDer MWST-Normalsatz beträgt 7.7 %.\n\n"
            "Der MWST-Normalsatz 2022 lag bei 7.7 %.\n\nAuf Dividenden fällt eine Verrechnungssteuer von 35 % an.")
    findings = verify(parse_report(text), DataRoom())
    apply_rates(findings, today=dt.date(2026, 1, 1))
    assert [f.status for f in findings] == [Status.GEPRUEFT, Status.ABWEICHUNG, Status.GEPRUEFT, Status.GEPRUEFT]
    assert "8.1 %" in findings[1].reasons[0] and "MWSTG" in findings[1].reasons[0]


def test_sentence_ending_with_percent_sign_is_split():
    claims = parse_report("Die Marge beträgt 8.1 %. Der Umsatz wuchs um 3 %.")
    assert len(claims) == 2


def test_report_shows_swiss_section():
    room = _room(**{"4.3 Kreditvertrag.txt": "Kreditvertrag\nFür die Muster AG: Dr. Paul Meier, CEO"})
    run = run_check("b.md", "Text.", b"Text.", room)
    assert any(f.level == "warnung" for f in run.flags)
    from zitatio.render import to_html
    assert "Schweizer Prüfungen" in to_html(run) and swiss_flags(room)
