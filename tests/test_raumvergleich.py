"""Zwei Stände des Datenraums vergleichen."""

from zitatio.dataroom import DataRoom
from zitatio.pipeline import run_check
from zitatio.raumvergleich import compare_rooms, describe
from zitatio.render import to_html


def _room(docs: dict) -> DataRoom:
    room = DataRoom()
    for name, text in docs.items():
        room.add(name, text.encode())
    return room


def test_changed_new_and_removed_documents():
    old = _room({"2.1 Jahresrechnung 2025.txt": "Der Umsatz 2025 beträgt CHF 10'000'000.\fAnhang",
                 "4.1 Mietvertrag.txt": "Miete", "5.1 Liefervertrag.txt": "Lieferung"})
    new = _room({"2.1 Jahresrechnung 2025.txt": "Der Umsatz 2025 beträgt CHF 12'000'000.\fAnhang",
                 "4.1 Mietvertrag.txt": "Miete", "6.1 Kreditvertrag.txt": "Kredit"})
    changes = compare_rooms(old, new)
    assert [(c.kind, c.label) for c in changes] == [("geändert", "DR 2.1"), ("neu", "DR 6.1"), ("entfernt", "DR 5.1")]
    assert changes[0].pages == [1] and changes[0].removed == ["CHF 10'000'000"] and changes[0].added == ["CHF 12'000'000"]
    assert "S. 1" in describe(changes[0])

    report = "Der Umsatz 2025 beträgt CHF 12 Mio. [DR 2.1, S. 1]. Die Miete ist geregelt [DR 4.1, S. 1]."
    run = run_check("b.md", report, report.encode(), new)
    run.room_changes = changes
    page = to_html(run)
    assert 'id="datenraum-neu"' in page and "1 Aussage des Berichts" in page and 'href="#a1"' in page
