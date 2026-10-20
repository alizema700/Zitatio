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
