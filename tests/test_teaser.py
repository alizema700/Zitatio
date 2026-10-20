from pathlib import Path

from zitatio.dataroom import DataRoom
from zitatio.teaser import anonymity_leaks, codename, teaser, to_markdown

ROOM = Path(__file__).parent.parent / "beispiele" / "gross" / "datenraum"


def test_teaser_reads_figures_with_sources_and_stays_anonymous():
    room = DataRoom.from_folder(ROOM)
    lines = {line.label: line for line in teaser(room)}
    assert lines["Region"].value == "Ostschweiz"
    assert lines["Geschäftsjahr 2025"].value.startswith("Umsatz CHF 31.9 Mio., EBITDA CHF 5.3 Mio. (17 % Marge)")
    assert lines["Geschäftsjahr 2025"].evidence[0].doc_label == "DR 2.3"
    assert lines["Mitarbeitende"].value == "rund 170 Vollzeitstellen"
    buyer = to_markdown(list(lines.values()), codename(room), with_sources=False)
    assert "DR 2.3" not in buyer and anonymity_leaks(buyer, room) == []
    check = to_markdown(list(lines.values()), codename(room), with_sources=True)
    assert "DR 2.3, S. 4" in check
    assert anonymity_leaks("Kurzprofil der Rheintal Medtech AG in Altstätten", room) == ["altstätten", "rheintal"]


def test_teaser_review_regressions():
    from zitatio.dataroom import Document

    def doc(index, title, text):
        return Document(f"{index} {title}.txt", index, title, "0" * 64, [text])

    room = DataRoom([
        doc("1.1", "Handelsregisterauszug", "Firma: Limmat Software AG\nSitz: Zürich ZH\n"
                                            "Eintragung im Handelsregister: 03.04.2011"),
        doc("2.1", "Jahresrechnung 2023", "Erfolgsrechnung 2023 (in CHF)\nNettoerlöse 150'000\nEBITDA -350'000\n"
                                          "Jahresverlust -420'000\nVollzeitstellen im Jahresdurchschnitt 2023: 48"),
        doc("2.2", "Jahresrechnung 2024", "Erfolgsrechnung 2024 (in CHF)\nNettoerlöse 2'000'000\nEBITDA (250'000)\n"
                                          "Vollzeitstellen im Jahresdurchschnitt 2024: 48"),
        doc("6.1", "Kreditvertrag", "Zahlungen erfolgen im Format ISO 20022. Der Kreditnehmer ist nach ISO 9001 zu "
                                    "zertifizieren."),
    ])
    lines = {line.label: line.value for line in teaser(room)}
    assert lines["Geschäftsjahr 2023"] == ("Umsatz CHF 0.2 Mio., EBITDA CHF -0.4 Mio. (-233 % Marge), "
                                          "Jahresverlust CHF 0.4 Mio.")
    assert "EBITDA CHF -0.2 Mio." in lines["Geschäftsjahr 2024"]
    assert "Zertifizierungen" not in lines and lines["Umsatzwachstum 2023–2024"] == "1233 % pro Jahr"
    assert lines["Mitarbeitende"] == "rund 50 Vollzeitstellen" and lines["Region"] == "Zürich"
    assert anonymity_leaks(to_markdown(teaser(room), "Projekt Alpha", False), room) == []
