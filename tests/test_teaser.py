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
