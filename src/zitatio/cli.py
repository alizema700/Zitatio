"""Kommandozeile: zitatio pruefen BERICHT --datenraum ORDNER"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .dataroom import DataRoom
from .derive import _chf
from .pipeline import run_check
from .render import ORDER, SYMBOLS, to_csv, to_disclosure_csv, to_html, to_json
from .report import load_report
from .versions import read_decisions


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="zitatio", description="Prüft DD-Berichte gegen den Datenraum.")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("pruefen", help="Bericht gegen Datenraum prüfen")
    p.add_argument("bericht", type=Path, help="DD-Bericht (.docx, .pdf, .md oder .txt)")
    p.add_argument("--datenraum", "-d", type=Path, required=True, help="Ordner mit den Datenraum-Dokumenten")
    p.add_argument("--out", "-o", type=Path, default=Path("pruefbericht.html"), help="HTML-Prüfbericht")
    p.add_argument("--json", type=Path, help="zusätzlich als JSON speichern")
    p.add_argument("--csv", type=Path, help="zusätzlich als CSV für Excel speichern")
    p.add_argument("--offenlegung", type=Path,
                   help="Offenlegungskarte als CSV: jede Aussage mit Dokument, Seite und Prüfsumme (für W&I)")
    p.add_argument("--modell", action="store_true",
                   help="Prüfmodell aus ZITATIO_LLM_BASE_URL / ZITATIO_LLM_MODEL verwenden")
    p.add_argument("--vorher", type=Path, help="frühere Version des Berichts: zeigt behobene, offene und neue Befunde")
    p.add_argument("--entscheide", type=Path,
                   help="exportiertes Prüf-CSV der Vorversion: Entscheide für unveränderte Aussagen übernehmen")
    b = sub.add_parser("benchmark", help="Trefferquote mit künstlich eingebauten Fehlern messen")
    b.add_argument("--datenraum", "-d", type=Path, required=True, help="Ordner mit den Datenraum-Dokumenten")
    b.add_argument("--fehler", action="store_true", help="jeden falsch erkannten Fall ausgeben")
    args = parser.parse_args(argv)

    if args.command == "benchmark":
        return _benchmark(args)

    model = None
    if args.modell:
        from .llm import OpenAICompatibleVerifier

        model = OpenAICompatibleVerifier.from_env()
        if model is None:
            parser.error("--modell braucht ZITATIO_LLM_BASE_URL und ZITATIO_LLM_MODEL")

    room = DataRoom.from_folder(args.datenraum)
    text, data = load_report(args.bericht)
    previous = (args.vorher.name, load_report(args.vorher)[0]) if args.vorher else None
    decisions = read_decisions(args.entscheide) if args.entscheide else None
    run = run_check(args.bericht.name, text, data, room, model, model.description if model else None,
                    previous=previous, decisions=decisions)

    args.out.write_text(to_html(run), encoding="utf-8")
    if args.json:
        args.json.write_text(to_json(run), encoding="utf-8")
    if args.csv:
        args.csv.write_text(to_csv(run), encoding="utf-8")
    if args.offenlegung:
        args.offenlegung.write_text(to_disclosure_csv(run), encoding="utf-8")

    for f in run.findings:
        where = ", ".join(c.label for c in f.claim.citations) or "ohne Fundstelle"
        short = f.claim.clean_text if len(f.claim.clean_text) <= 70 else f.claim.clean_text[:68] + "…"
        print(f"{SYMBOLS[f.status]} {f.claim.number:02d}  {f.status.label:<18} {where:<16} {short}")
    counts = run.counts()
    print("\n" + " · ".join(f"{counts[s]} {s.label}" for s in ORDER if counts[s]))
    for c in run.conflicts:
        print(f"≠ Widerspruch im Datenraum: {c.describe()}")
    for c in run.addbacks:
        print(f"{'✓' if c.ok else '✗'} Bereinigtes EBITDA nachgerechnet: {c.summary}, Bericht {_chf(c.stated)}")
    if run.closing:
        from .terms import _n, revenue_at_risk

        coc = len({id(i.terms) for i in run.closing if i.kind == "kontrollwechsel"})
        ending = sum(i.kind == "laufzeit" for i in run.closing)
        print(f"Closing-Liste: {coc} Verträge mit Kontrollwechselklausel (CHF {_n(revenue_at_risk(run.closing))} "
              f"Volumen p.a.), {ending} Laufzeiten zu klären")
    if run.diff is not None:
        print(f"Gegenüber {run.diff.old_name}: {run.diff.summary()}")
    if run.decisions:
        print(f"{len(run.decisions)} Entscheide aus der Vorversion übernommen")
    missing = [g.name for g in run.gaps if not g.present]
    if missing:
        print(f"Fehlende Unterlagen: {', '.join(missing)}")
    for w in room.warnings:
        print(f"Hinweis: {w}", file=sys.stderr)
    print(f"Prüfbericht: {args.out}")
    return 0


def _benchmark(args) -> int:
    from .benchmark import run_benchmark

    result = run_benchmark(DataRoom.from_folder(args.datenraum))
    print(f"{'Fehlerart':<22}{'erkannt':>10}{'Fälle':>8}{'Quote':>9}")
    for kind, (ok, total) in result.by_kind().items():
        print(f"{kind:<22}{ok:>10}{total:>8}{ok / total:>9.0%}")
    print(f"{'gesamt':<22}{sum(c.ok for c in result.cases):>10}{len(result.cases):>8}{result.accuracy:>9.0%}")
    for (expected, actual), n in result.confusion().most_common():
        print(f"  {n}x erwartet {expected.label}, erhalten {actual.label}")
    if args.fehler:
        for c in result.cases:
            if not c.ok:
                print(f"- [{c.kind}] {c.actual.label}: {c.text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
