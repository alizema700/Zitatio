"""Kommandozeile: zitatio pruefen BERICHT --datenraum ORDNER"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .dataroom import DataRoom
from .pipeline import run_check
from .render import ORDER, SYMBOLS, to_csv, to_html, to_json
from .report import load_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="zitatio", description="Prüft DD-Berichte gegen den Datenraum.")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("pruefen", help="Bericht gegen Datenraum prüfen")
    p.add_argument("bericht", type=Path, help="DD-Bericht (.docx, .pdf, .md oder .txt)")
    p.add_argument("--datenraum", "-d", type=Path, required=True, help="Ordner mit den Datenraum-Dokumenten")
    p.add_argument("--out", "-o", type=Path, default=Path("pruefbericht.html"), help="HTML-Prüfbericht")
    p.add_argument("--json", type=Path, help="zusätzlich als JSON speichern")
    p.add_argument("--csv", type=Path, help="zusätzlich als CSV für Excel speichern")
    p.add_argument("--modell", action="store_true",
                   help="Prüfmodell aus ZITATIO_LLM_BASE_URL / ZITATIO_LLM_MODEL verwenden")
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
    run = run_check(args.bericht.name, text, data, room, model, model.description if model else None)

    args.out.write_text(to_html(run), encoding="utf-8")
    if args.json:
        args.json.write_text(to_json(run), encoding="utf-8")
    if args.csv:
        args.csv.write_text(to_csv(run), encoding="utf-8")

    for f in run.findings:
        where = ", ".join(c.label for c in f.claim.citations) or "ohne Fundstelle"
        short = f.claim.clean_text if len(f.claim.clean_text) <= 70 else f.claim.clean_text[:68] + "…"
        print(f"{SYMBOLS[f.status]} {f.claim.number:02d}  {f.status.label:<18} {where:<16} {short}")
    counts = run.counts()
    print("\n" + " · ".join(f"{counts[s]} {s.label}" for s in ORDER if counts[s]))
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
