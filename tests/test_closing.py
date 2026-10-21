"""Laufzeiten, Kündigungsfristen und Closing-Liste aus den Verträgen."""

import datetime as dt

from zitatio.clauses import contract_register
from zitatio.dataroom import DataRoom
from zitatio.terms import closing_list, revenue_at_risk

CONTRACTS = {
    "5.1 Liefervertrag Alpha AG.txt": ("Liefervertrag\nDer Vertrag tritt am 01.01.2022 in Kraft und endet am 31.12.2029.\n"
                                      "Das geschätzte jährliche Bestellvolumen beträgt CHF 2'000'000.\n"
                                      "Bei einem Kontrollwechsel kann die Kundin den Vertrag fristlos kündigen.\n"
                                      "Jede Partei kann mit einer Frist von 6 Monaten kündigen."),
    "5.2 Liefervertrag Beta AG.txt": ("Liefervertrag\nDer Vertrag tritt am 01.07.2021 in Kraft und endet am 30.06.2026.\n"
                                     "Ein Kontrollwechsel berührt den Bestand dieses Vertrags nicht."),
    "6.2 Leasingvertrag.txt": "Leasingvertrag\nLaufzeit: 60 Monate ab 01.04.2024.",
}


def test_terms_and_closing_list():
    room = DataRoom()
    for name, text in CONTRACTS.items():
        room.add(name, text.encode())
    terms, items = closing_list(contract_register(room), today=dt.date(2026, 10, 20))
    alpha, beta, leasing = terms
    assert (alpha.start, alpha.end, alpha.notice, alpha.volume) == (dt.date(2022, 1, 1), dt.date(2029, 12, 31),
                                                                      (6, "Monate"), 2000000)
    assert leasing.end == dt.date(2029, 3, 31)
    assert [(i.kind, i.terms.doc.label) for i in items] == [("kontrollwechsel", "DR 5.1"), ("laufzeit", "DR 5.2")]
    assert "Abgelaufen am 30.06.2026" in items[1].text
    assert revenue_at_risk(items) == 2000000


def test_earliest_exit_and_profile():
    from zitatio.terms import exit_profile
    room = DataRoom()
    room.add("5.1 Liefervertrag Alpha AG.txt", (
        "Liefervertrag\nDer Vertrag tritt am 01.01.2022 in Kraft und endet am 31.12.2029.\n"
        "Das geschätzte jährliche Bestellvolumen beträgt CHF 2'000'000.\n"
        "Jede Partei kann den Vertrag mit einer Frist von 3 Monaten auf das Ende eines Kalenderjahres kündigen.").encode())
    room.add("4.1 Mietvertrag Halle.txt", (
        "Mietvertrag\nDas Mietverhältnis beginnt am 01.01.2021 und ist fest abgeschlossen bis 31.12.2031.\n"
        "Nach Ablauf der festen Dauer kann das Mietverhältnis mit einer Frist von 12 Monaten gekündigt werden.").encode())
    today = dt.date(2026, 10, 20)
    terms, _ = closing_list(contract_register(room), today=today)
    lease, supply = terms
    assert supply.earliest_exit(today) == dt.date(2027, 12, 31) and supply.notice_text() == "3 Monate auf Jahresende"
    assert lease.after_fixed and lease.earliest_exit(today) == dt.date(2031, 12, 31)
    assert [(y, v) for y, v, _ in exit_profile(terms, today)] == [(2027, 2000000)]
