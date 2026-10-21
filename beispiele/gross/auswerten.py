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
    spa = ("spa-entwurf.md", (HERE / "spa-entwurf.md").read_text(encoding="utf-8"))
    run = run_check("dd-bericht.md", text, data, room, spa=spa)
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
    follow_ups = [(f, t) for f, t in correct if f.status in FLAGGED and t["hinweis"].startswith("folgt aus")]
    false_alarms = [(f, t) for f, t in correct if f.status in FLAGGED and (f, t) not in follow_ups]
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
    for f, t in follow_ups:
        print(f"  Folgehinweis, kein Fehlalarm ({t['hinweis']}): {f.status.label}: {f.claim.clean_text}")

    planted = json.loads((HERE / "widersprueche.json").read_text(encoding="utf-8"))
    titles = [c.title for c in run.conflicts]
    hits = [p for p in planted if p["groesse"] in titles]
    print(f"\nWidersprüche im Datenraum gefunden: {len(hits)} von {len(planted)} eingebauten, "
          f"{len(titles) - len(hits)} weitere gemeldet")
    for c in run.conflicts:
        mark = "eingebaut" if c.title in [p["groesse"] for p in planted] else "zusätzlich"
        print(f"  {mark:<10} {c.describe()}")
    for f, _ in rows:
        if f.status is Status.WIDERSPRUCH:
            print(f"  betrifft Aussage {f.claim.number}: {f.claim.clean_text}")

    expected = json.loads((HERE / "warnsignale.json").read_text(encoding="utf-8"))
    warnings = [w for w in run.flags if w.level == "warnung"]
    seen = {(w.area, d) for w in warnings for d in w.docs}
    hit = [e for e in expected if (e["art"], e["dokument"]) in seen]
    extra = [w for w in warnings if not any((w.area, d) in {(e["art"], e["dokument"]) for e in expected} for d in w.docs)]
    print(f"\nSchweizer Warnsignale gefunden: {len(hit)} von {len(expected)} eingebauten, {len(extra)} weitere gemeldet")
    for w in run.flags:
        print(f"  {w.level:<8} {w.area}: {w.title}")

    ok = sum(f.status is Status.GEPRUEFT for f, _ in correct)
    open_ = sum(f.status is Status.UNGEPRUEFT for f, _ in correct)
    other = len(correct) - ok - open_ - len(false_alarms) - len(follow_ups)
    print(f"\nRichtige Aussagen: {ok} geprüft, {open_} ungeprüft (keine prüfbaren Werte), "
          f"{other} mit Widerspruch im Datenraum, {len(follow_ups)} Folgehinweis, {len(false_alarms)} Fehlalarme")
    without_citations(room, truth)
    if details:
        for f, t in rows:
            print(f"{f.claim.number:03d} {f.status.label:<18} {'OK ' if t['richtig'] else 'ERR'} {f.claim.clean_text}")
            for r in f.reasons:
                print(f"      {r}")


# Fehler, die nur die Fundstelle betreffen: ohne Fundstellen ist die Aussage richtig
CITATION_ERRORS = {"falsche Seite", "falsches Dokument", "falscher Q&A-Eintrag"}


def without_citations(room: DataRoom, truth: dict) -> None:
    """Derselbe Bericht ohne jede Fundstelle, wie ein Information Memorandum: Zitatio sucht die Belege selbst."""
    import re

    from zitatio.report import parse_report

    def strip(text: str) -> str:
        return re.sub(r"\s*\[(?:DR|Q&A)[^\]]*\]", "", text).strip()

    by_text = {}
    for t in truth.values():
        claims = parse_report(strip(t["aussage"]))
        if claims:
            by_text[claims[0].clean_text] = t
    text, _ = load_report(HERE / "dd-bericht.md")
    plain = strip(text)
    run = run_check("ohne-fundstellen.md", plain, plain.encode(), room)
    rows = [(f, by_text[f.claim.clean_text]) for f in run.findings if f.claim.clean_text in by_text]
    wrong = [(f, t) for f, t in rows if not t["richtig"] and t["fehler"] not in CITATION_ERRORS]
    right = [(f, t) for f, t in rows if t["richtig"] or t["fehler"] in CITATION_ERRORS]
    located = sum(f.status is Status.GEPRUEFT for f, _ in right)
    wrong_ok = [t["fehler"] for f, t in wrong if f.status is Status.GEPRUEFT]
    deviations = sum(f.status is Status.ABWEICHUNG for f, _ in wrong)
    print(f"\nOhne Fundstellen (wie ein Information Memorandum): {len(rows)} Aussagen mit Werten")
    print(f"  richtige Aussagen im Datenraum belegt: {located} von {len(right)}")
    print(f"  falsche Werte als geprüft durchgelassen: {len(wrong_ok)} von {len(wrong)} "
          f"({deviations} als Abweichung erkannt, {len(wrong) - deviations - len(wrong_ok)} ohne Beleg)")
    for e in wrong_ok:
        print(f"    durchgelassen: {e}")


if __name__ == "__main__":
    main("--details" in sys.argv)
