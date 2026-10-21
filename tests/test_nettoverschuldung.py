"""Nettoverschuldung, schuldenähnliche Posten und Covenant."""

from zitatio.dataroom import DataRoom
from zitatio.pipeline import run_check
from zitatio.verify import Status

DOCS = {
    "2.1 Jahresrechnung 2025.txt": ("Muster AG - Jahresrechnung 2025\nErfolgsrechnung 2025 (in CHF)\nNettoerlös 20'000'000\n"
                                    "EBITDA 2'000'000\n\nBilanz per 31.12.2025 (in CHF)\nFlüssige Mittel 1'000'000\n"
                                    "Verzinsliche Verbindlichkeiten 7'000'000\nAktienkapital 500'000\nEigenkapital 4'000'000\n"
                                    "Verbindlichkeiten gegenüber Vorsorgeeinrichtungen: CHF 50'000.\n"),
    "6.1 Kreditvertrag Bank.txt": "Kreditvertrag\nCovenant: Die Nettoverschuldung darf das 2.5-fache des EBITDA nicht übersteigen.",
    "6.2 Leasingvertrag Maschinen.txt": ("Leasingvertrag\nLaufzeit: 24 Monate ab 01.01.2025.\n"
                                         "Die monatliche Leasingrate beträgt CHF 10'000.\n"),
    "10.1 Klage Kunde AG.txt": "Klage\nDie Klägerin fordert Schadenersatz von CHF 800'000.",
}
REPORT = ("Die Nettoverschuldung per 31.12.2025 beträgt CHF 6.0 Mio. [DR 2.1, S. 1].\n\n"
          "Der Covenant zur Nettoverschuldung wird eingehalten [DR 6.1, S. 1].")


def test_net_debt_bridge_and_covenant_breach():
    room = DataRoom()
    for name, text in DOCS.items():
        room.add(name, text.encode())
    run = run_check("b.md", REPORT, REPORT.encode(), room)
    nd = run.netdebt
    assert nd.net_debt == 6000000 and nd.covenant.ratio == 3 and not nd.covenant.ok
    labels = {i.label: i.amount for i in nd.items}
    assert labels["Leasing DR 6.2 (geschätzt)"] == 120000  # 12 Raten 2026
    assert labels["Verbindlichkeiten gegenüber Vorsorgeeinrichtungen"] == 50000
    assert labels["Klage DR 10.1"] == 800000 and nd.adjusted == 6170000
    assert [f.status for f in run.findings] == [Status.GEPRUEFT, Status.ABWEICHUNG]
    assert any(f.area == "Covenant" and f.level == "warnung" for f in run.flags)
