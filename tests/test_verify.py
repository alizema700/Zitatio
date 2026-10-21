from pathlib import Path

import pytest

from zitatio.dataroom import DataRoom
from zitatio.pipeline import run_check
from zitatio.render import to_html, to_json
from zitatio.report import parse_report
from zitatio.verify import Status, Verdict, verify

EXAMPLE = Path(__file__).resolve().parents[1] / "beispiele" / "alpenblick"

EXPECTED = [
    Status.GEPRUEFT,  # UID korrekt
    Status.GEPRUEFT,  # Aktienkapital
    Status.ABWEICHUNG,  # UID mit falscher Prüfziffer
    Status.ABWEICHUNG,  # Nettoerlös vertauscht
    Status.OHNE_BELEG,  # Nettoverschuldung ohne Fundstelle
    Status.FALSCHE_FUNDSTELLE,  # Mietverpflichtungen auf S. 2
    Status.FALSCHE_FUNDSTELLE,  # Mietzins auf S. 2
    Status.GEPRUEFT,  # feste Dauer
    Status.ABWEICHUNG,  # Kündigungsfrist 18 statt 12 Monate
    Status.GEPRUEFT,  # Laufzeit Rahmenvertrag
    Status.ABWEICHUNG,  # Kontrollwechsel übersehen: Klauselsuche findet ihn
    Status.QUELLE_FEHLT,  # DR 4.2 existiert nicht
    Status.GEPRUEFT,  # Darlehen
    Status.QUELLE_FEHLT,  # S. 4 existiert nicht
    Status.GEPRUEFT,  # Businessplan: CHF 19.81 Mio. aus 19'812 TCHF in Excel
    Status.ABWEICHUNG,  # Businessplan: EBITDA 3.1 statt 2.87 Mio.
    Status.WIDERSPRUCH,  # EBITDA stimmt mit der Jahresrechnung, das Management Reporting nennt einen anderen Wert
    Status.GEPRUEFT,  # Bereinigung mit Beleg
    Status.OHNE_BELEG,  # Bereinigung ohne Beleg
    Status.ABWEICHUNG,  # bereinigtes EBITDA: Summe geht nicht auf
]


@pytest.fixture(scope="module")
def room():
    return DataRoom.from_folder(EXAMPLE / "datenraum")


@pytest.fixture(scope="module")
def claims():
    return parse_report((EXAMPLE / "dd-bericht.md").read_text())


def test_example_statuses(room):
    data = (EXAMPLE / "dd-bericht.md").read_bytes()
    run = run_check("dd-bericht.md", data.decode(), data, room)
    assert [f.status for f in run.findings] == EXPECTED


def test_deviation_names_closest_value_first(room, claims):
    finding = verify([claims[3]], room)[0]
    assert "Für Umsatz 2025 nennt die Fundstelle CHF 18'450'000" in finding.reasons[0]


def test_wrong_page_points_to_right_page(room, claims):
    finding = verify([claims[6]], room)[0]
    assert finding.evidence[0].page == 2
    assert "DR 3.2.1, S. 2" in finding.reasons[0]


def test_model_contradiction_with_verified_quote(room, claims):
    def model(claim, passages):
        return Verdict("WIDERSPRUCH", "ist die Kundin berechtigt, diesen Vertrag mit einer Frist von drei Monaten zu kündigen",
                       "Ziff. 14 regelt den Kontrollwechsel.")

    finding = verify([claims[10]], room, model)[0]
    assert finding.status is Status.ABWEICHUNG
    assert finding.method == "Modell"
    assert "drei Monaten" in finding.evidence[0].match


def test_model_answer_with_invented_quote_is_discarded(room, claims):
    def model(claim, passages):
        return Verdict("GESTUETZT", "Der Vertrag enthält keine Kontrollwechselklausel.", "")

    finding = verify([claims[10]], room, model)[0]
    assert finding.status is Status.UNGEPRUEFT
    assert any("verworfen" in r for r in finding.reasons)


def test_model_failure_keeps_rule_result(room, claims):
    def model(claim, passages):
        raise ConnectionError

    assert verify([claims[1]], room, model)[0].status is Status.GEPRUEFT


def test_renderers(room):
    report = EXAMPLE / "dd-bericht.md"
    data = report.read_bytes()
    run = run_check(report.name, data.decode(), data, room)
    page = to_html(run)
    assert "Prüfprotokoll" in page and "Falsche Fundstelle" in page
    assert '"status": "abweichung"' in to_json(run)
