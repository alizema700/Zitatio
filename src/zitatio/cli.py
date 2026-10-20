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
    p.add_argument("--excel", type=Path, help="Excel-Mappe mit Aussagen, EBITDA-Brücke, Nettoverschuldung und "
                   "Closing-Liste, Rechnungen als Formeln")
    p.add_argument("--memo", type=Path, help="eine Seite fürs IC-Memo als Markdown oder Word (.docx): das Wichtigste und offene Befunde")
    p.add_argument("--fragen", type=Path, help="Fragenliste an den Verkäufer als Markdown, für den Q&A-Prozess")
    p.add_argument("--spa", type=Path, help="Entwurf des Kaufvertrags: Garantien mit den Befunden abgleichen")
    p.add_argument("--klauseln", type=Path, help="Klauselvorschläge für den Kaufvertrag (.md oder .docx)")
    p.add_argument("--kaeuferfragen", type=Path, help="Fragen der Käufer (.xlsx/.md): Antwortentwürfe im Bericht")
    p.add_argument("--datenraum-vorher", type=Path, help="früherer Export des Datenraums: was ist neu oder geändert")
    p.add_argument("--kalender", type=Path, help="Fristen (Vertragsenden, Kündigungstage, Ablaufdaten) als .ics")
    p.add_argument("--vorher", type=Path, help="frühere Version des Berichts: zeigt behobene, offene und neue Befunde")
    p.add_argument("--entscheide", type=Path,
                   help="exportiertes Prüf-CSV der Vorversion: Entscheide für unveränderte Aussagen übernehmen")
    r = sub.add_parser("redflags", help="Red-Flag-Bericht aus dem Datenraum allein, ohne DD-Bericht")
    r.add_argument("--datenraum", "-d", type=Path, required=True, help="Ordner mit den Datenraum-Dokumenten")
    r.add_argument("--out", "-o", type=Path, default=Path("red-flags.html"), help="HTML-Bericht")
    r.add_argument("--excel", type=Path, help="Excel-Mappe mit Nettoverschuldung, Closing-Liste und Fragenliste")
    r.add_argument("--fragen", type=Path, help="Fragenliste an den Verkäufer als Markdown")
    r.add_argument("--spa", type=Path, help="Entwurf des Kaufvertrags: Garantien mit den Befunden abgleichen")
    r.add_argument("--klauseln", type=Path, help="Klauselvorschläge für den Kaufvertrag (.md oder .docx)")
    r.add_argument("--kaeuferfragen", type=Path, help="Fragen der Käufer (.xlsx/.md): Antwortentwürfe im Bericht")
    r.add_argument("--datenraum-vorher", type=Path, help="früherer Export des Datenraums: was ist neu oder geändert")
    r.add_argument("--kalender", type=Path, help="Fristen als Kalenderdatei (.ics)")
    r.add_argument("--json", type=Path, help="zusätzlich als JSON speichern")
    b = sub.add_parser("benchmark", help="Trefferquote mit künstlich eingebauten Fehlern messen")
    b.add_argument("--datenraum", "-d", type=Path, required=True, help="Ordner mit den Datenraum-Dokumenten")
    b.add_argument("--fehler", action="store_true", help="jeden falsch erkannten Fall ausgeben")
    a = sub.add_parser("antworten", help="Antwortentwürfe mit Fundstelle für eine Fragenliste der Käufer")
    a.add_argument("fragen", type=Path, help="Fragen als .txt, .md oder .xlsx (Spalte \"Frage\")")
    a.add_argument("-d", "--datenraum", type=Path, required=True, help="Ordner mit den Datenraum-Dokumenten")
    a.add_argument("-o", "--out", type=Path, default=Path("antworten.md"), help="Antwortentwürfe als Markdown")
    args = parser.parse_args(argv)

    if args.command == "benchmark":
        return _benchmark(args)
    if args.command == "redflags":
        return _redflags(args)
    if args.command == "antworten":
        return _answers(args)

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
    spa = (args.spa.name, load_report(args.spa)[0]) if args.spa else None
    run = run_check(args.bericht.name, text, data, room, model, model.description if model else None,
                    previous=previous, decisions=decisions, spa=spa)
    _attach_extras(args, run)

    args.out.write_text(to_html(run), encoding="utf-8")
    if args.json:
        args.json.write_text(to_json(run), encoding="utf-8")
    if args.csv:
        args.csv.write_text(to_csv(run), encoding="utf-8")
    if args.excel:
        from .excel import to_xlsx

        args.excel.write_bytes(to_xlsx(run))
    if args.memo:
        from .summary import to_markdown

        if args.memo.suffix.lower() == ".docx":
            from .word import markdown_to_docx

            args.memo.write_bytes(markdown_to_docx(to_markdown(run)))
        else:
            args.memo.write_text(to_markdown(run), encoding="utf-8")
    if args.fragen:
        from .questions import request_list
        from .questions import to_markdown as questions_markdown

        args.fragen.write_text(questions_markdown(request_list(run)), encoding="utf-8")
    if args.kalender:
        _write_calendar(args.kalender, run)
    if args.klauseln:
        _write_clauses(args.klauseln, run)
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


def _redflags(args) -> int:
    from .questions import request_list
    from .questions import to_markdown as questions_markdown

    room = DataRoom.from_folder(args.datenraum)
    spa = (args.spa.name, load_report(args.spa)[0]) if args.spa else None
    run = run_check(args.datenraum.resolve().name, "", b"", room, spa=spa)
    _attach_extras(args, run)
    args.out.write_text(to_html(run), encoding="utf-8")
    if args.json:
        args.json.write_text(to_json(run), encoding="utf-8")
    if args.excel:
        from .excel import to_xlsx

        args.excel.write_bytes(to_xlsx(run))
    if args.kalender:
        _write_calendar(args.kalender, run)
    if args.klauseln:
        _write_clauses(args.klauseln, run)
    questions = request_list(run)
    if args.fragen:
        args.fragen.write_text(questions_markdown(questions), encoding="utf-8")
    for fl in run.flags:
        if fl.level == "warnung":
            print(f"! {fl.area}: {fl.title}")
    print(f"\n{sum(fl.level == 'warnung' for fl in run.flags)} Warnsignale, {len(questions)} Fragen an den Verkäufer")
    print(f"Red-Flag-Bericht: {args.out}")
    return 0


def _attach_extras(args, run) -> None:
    if args.datenraum_vorher:
        from .raumvergleich import compare_rooms

        run.room_changes = compare_rooms(DataRoom.from_folder(args.datenraum_vorher), run.room)
    if args.kaeuferfragen:
        from .antworten import answer, read_questions

        questions = read_questions(args.kaeuferfragen.read_bytes(), args.kaeuferfragen.suffix.lower())
        run.answers = answer(questions, run.room)


def _answers(args) -> int:
    from .antworten import answer, read_questions
    from .antworten import to_markdown as answers_markdown

    questions = read_questions(args.fragen.read_bytes(), args.fragen.suffix.lower())
    answers = answer(questions, DataRoom.from_folder(args.datenraum))
    args.out.write_text(answers_markdown(answers), encoding="utf-8")
    found = sum(1 for a in answers if a.text)
    print(f"{found} von {len(answers)} Fragen mit Antwortentwurf aus dem Datenraum: {args.out}")
    return 0


def _write_clauses(path: Path, run) -> None:
    from .markup import drafts, to_docx, to_markdown

    items = drafts(run)
    if path.suffix.lower() == ".docx":
        path.write_bytes(to_docx(items, run.spa_name))
    else:
        path.write_text(to_markdown(items, run.spa_name), encoding="utf-8")
    print(f"{len(items)} Klauselvorschläge: {path}")


def _write_calendar(path: Path, run) -> None:
    from .fristen import deadlines, to_ics

    items = deadlines(run)
    path.write_text(to_ics(items, run.report_name), encoding="utf-8", newline="")
    print(f"{len(items)} Fristen im Kalender: {path}")


if __name__ == "__main__":
    raise SystemExit(main())
