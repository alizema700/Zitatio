"""Preisbrücke: Unternehmenswert, Equity Value und Preiswirkung der Befunde."""

from zitatio.dataroom import DataRoom
from zitatio.pipeline import run_check
from zitatio.render import to_html
from zitatio.summary import key_points
from zitatio.verify import Status

from test_nettoverschuldung import DOCS


def _run(report: str):
    room = DataRoom()
    for name, text in DOCS.items():
        room.add(name, text.encode())
    return run_check("b.md", report, report.encode(), room)


def test_enterprise_and_equity_value_are_recomputed():
    report = ("## Bewertung\n\nDie Bewertung erfolgt mit einem Multiple von 6.0x EBITDA.\n\n"
              "Der Unternehmenswert beträgt CHF 12.0 Mio.\n\n"
              "Nach Abzug der Nettoverschuldung ergibt sich ein Equity Value von CHF 7.0 Mio.")
    run = _run(report)
    v = run.valuation
    assert v.multiple == 6 and v.ev == 12000000 and v.equity == 6000000
    ev, equity = run.findings
    assert ev.status is Status.GEPRUEFT and ev.method == "Nachgerechnet"
    assert equity.status is Status.ABWEICHUNG and "CHF 6.00 Mio." in equity.reasons[0]
    # Schuldenähnliche Posten mindern den Preis Franken für Franken, die Klage steht daneben
    assert v.checked_equity == 6000000 - 50000 - 120000
    assert [i.label for i in v.risks] == ["Klage DR 10.1"]
    assert 'id="preis"' in to_html(run)
    assert any(p.title.startswith("Preiswirkung der Befunde") and p.href == "#preis" for p in key_points(run))


def test_no_bridge_without_multiple():
    assert _run("Der Unternehmenswert beträgt CHF 12.0 Mio.").valuation is None
