"""Grosser Testfall: 264 Seiten, 212 Aussagen, 12 eingebaute Fehler (beispiele/gross)."""

import json
from pathlib import Path

from zitatio.dataroom import DataRoom
from zitatio.pipeline import run_check
from zitatio.report import load_report
from zitatio.verify import Status

CASE = Path(__file__).resolve().parents[1] / "beispiele" / "gross"
FLAGGED = {Status.ABWEICHUNG, Status.FALSCHE_FUNDSTELLE, Status.QUELLE_FEHLT, Status.OHNE_BELEG}


def test_large_case_finds_rule_detectable_errors_with_few_false_alarms():
    room = DataRoom.from_folder(CASE / "datenraum")
    text, data = load_report(CASE / "dd-bericht.md")
    truth = {t["aussage"]: t for t in json.loads((CASE / "wahrheit.json").read_text(encoding="utf-8"))}
    findings = run_check("dd-bericht.md", text, data, room).findings
    assert len(findings) == len(truth)
    rows = [(f, truth[f.claim.text.strip()]) for f in findings]
    for f, t in rows:
        if not t["richtig"] and t["regeln_koennen_es_sehen"]:
            assert f.status in FLAGGED, t["fehler"]
    false_alarms = [f for f, t in rows if t["richtig"] and f.status in FLAGGED]
    assert len(false_alarms) <= 5
    assert all(truth[f.claim.text.strip()]["hinweis"] == "abgeleitet" for f in false_alarms)
