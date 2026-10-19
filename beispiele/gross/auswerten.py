"""Zitatio auf den grossen Testfall anwenden und gegen wahrheit.json auswerten.

Aufruf: python beispiele/gross/auswerten.py [--details]
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path

from zitatio.dataroom import DataRoom
from zitatio.pipeline import run_check
from zitatio.report import load_report
from zitatio.verify import Status

HERE = Path(__file__).parent
FLAGGED = {Status.ABWEICHUNG, Status.FALSCHE_FUNDSTELLE, Status.QUELLE_FEHLT, Status.OHNE_BELEG}


def main(details: bool) -> None:
    started = time.perf_counter()
    room = DataRoom.from_folder(HERE / "datenraum")
    text, data = load_report(HERE / "dd-bericht.md")
    run = run_check("dd-bericht.md", text, data, room)
    seconds = time.perf_counter() - started

    truth = {t["aussage"]: t for t in json.loads((HERE / "wahrheit.json").read_text(encoding="utf-8"))}
    rows = []
    for f in run.findings:
        t = truth.get(f.claim.text.strip())
        if t is None:
            raise SystemExit(f"Aussage nicht in wahrheit.json (falsch zerlegt?): {f.claim.text}")
        rows.append((f, t))
    assert len(rows) == len(truth), (len(rows), len(truth))

    errors = [(f, t) for f, t in rows if not t["richtig"]]
    correct = [(f, t) for f, t in rows if t["richtig"]]
    found = [(f, t) for f, t in errors if f.status in FLAGGED]
    false_alarms = [(f, t) for f, t in correct if f.status in FLAGGED]
    status = Counter(f.status.label for f, _ in rows)

    pages = sum(len(d.pages) for d in room.documents)
    print(f"Datenraum: {len(room.documents)} Dokumente, {pages} Seiten · Bericht: {len(rows)} Aussagen · "
          f"Laufzeit {seconds:.1f} s")
    print("Status: " + ", ".join(f"{n} {s}" for s, n in status.most_common()))
    print(f"\nEingebaute Fehler gefunden: {len(found)} von {len(errors)}")
    for f, t in errors:
        mark = "gefunden " if f.status in FLAGGED else "verpasst "
        print(f"  {mark} {t['fehler']:<36} -> {f.status.label}")
    print(f"\nFehlalarme bei richtigen Aussagen: {len(false_alarms)} von {len(correct)}")
    for f, t in false_alarms:
        why = f" ({t['hinweis']})" if t["hinweis"] else ""
        print(f"  {f.status.label}{why}: {f.claim.clean_text}")
    ok = sum(f.status is Status.GEPRUEFT for f, _ in correct)
    open_ = sum(f.status is Status.UNGEPRUEFT for f, _ in correct)
    print(f"\nRichtige Aussagen: {ok} geprüft, {open_} ungeprüft (keine prüfbaren Werte), {len(false_alarms)} Fehlalarme")
    if details:
        for f, t in rows:
            print(f"{f.claim.number:03d} {f.status.label:<18} {'OK ' if t['richtig'] else 'ERR'} {f.claim.clean_text}")
            for r in f.reasons:
                print(f"      {r}")


if __name__ == "__main__":
    main("--details" in sys.argv)
