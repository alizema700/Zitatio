"""Grosser Testfall: 268 Seiten, 220 Aussagen, 14 eingebaute Fehler, 3 Widersprüche im Datenraum (beispiele/gross)."""

import json
from pathlib import Path

import pytest

from zitatio.dataroom import DataRoom
from zitatio.pipeline import run_check
from zitatio.report import load_report
from zitatio.verify import Status

CASE = Path(__file__).resolve().parents[1] / "beispiele" / "gross"
FLAGGED = {Status.ABWEICHUNG, Status.FALSCHE_FUNDSTELLE, Status.QUELLE_FEHLT, Status.OHNE_BELEG}


@pytest.fixture(scope="module")
def run():
    room = DataRoom.from_folder(CASE / "datenraum")
    text, data = load_report(CASE / "dd-bericht.md")
    spa = ("spa-entwurf.md", (CASE / "spa-entwurf.md").read_text(encoding="utf-8"))
    return run_check("dd-bericht.md", text, data, room, spa=spa)


def test_large_case_finds_rule_detectable_errors_without_false_alarms(run):
    truth = {t["aussage"]: t for t in json.loads((CASE / "wahrheit.json").read_text(encoding="utf-8"))}
    assert len(run.findings) == len(truth)
    rows = [(f, truth[f.claim.text.strip()]) for f in run.findings]
    for f, t in rows:
        if not t["richtig"] and t["regeln_koennen_es_sehen"]:
            assert f.status in FLAGGED, t["fehler"]
    false_alarms = [f for f, t in rows if t["richtig"] and f.status in FLAGGED and not t["hinweis"].startswith("folgt aus")]
    assert false_alarms == []


def test_large_case_finds_every_planted_contradiction_and_nothing_else(run):
    planted = {c["groesse"] for c in json.loads((CASE / "widersprueche.json").read_text(encoding="utf-8"))}
    assert {c.title for c in run.conflicts} == planted


def test_large_case_recomputes_derived_values(run):
    derived = [f for f in run.findings if f.method == "Nachgerechnet"]
    assert len(derived) >= 4
    assert all(f.status in (Status.GEPRUEFT, Status.OHNE_BELEG) for f in derived)


def test_large_case_without_citations_finds_sources_itself():
    import re

    room = DataRoom.from_folder(CASE / "datenraum")
    text, _ = load_report(CASE / "dd-bericht.md")
    plain = re.sub(r"\s*\[(?:DR|Q&A)[^\]]*\]", "", text)
    run = run_check("im.md", plain, plain.encode(), room)
    truth = {re.sub(r"\s*\[(?:DR|Q&A)[^\]]*\]", "", t["aussage"]).strip(): t
             for t in json.loads((CASE / "wahrheit.json").read_text(encoding="utf-8"))}
    rows = [(f, truth[f.claim.text.strip()]) for f in run.findings if f.claim.text.strip() in truth]
    value_errors = [f for f, t in rows if not t["richtig"] and t["fehler"] not in
                    {"falsche Seite", "falsches Dokument", "falscher Q&A-Eintrag"}]
    assert value_errors and all(f.status is not Status.GEPRUEFT for f in value_errors)
    located = [f for f, t in rows if t["richtig"] and f.status is Status.GEPRUEFT]
    assert len(located) >= 110
    assert sum(f.method == "Belegsuche" and bool(f.evidence) for f in located) >= 100
