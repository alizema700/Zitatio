"""Test mit echten Jahresberichten: FinanceBench (Patronus AI, CC BY-NC 4.0).

FinanceBench hat 150 Fragen zu US-Jahres- und Quartalsberichten (10-K, 10-Q). Zu jeder Antwort
steht die Seite, auf der der Beleg steht. Daraus baut das Skript einen DD-Bericht, in dem jede
Antwort als Aussage mit Fundstelle steht, in drei Varianten:

- richtig: Wert und Seite wie in FinanceBench
- falscher Wert: Wert um 8 % verändert, Seite richtig
- falsche Seite: Wert richtig, zitiert ist eine Seite ohne den Wert

Die PDFs bleiben ausserhalb des Repos (Lizenz nur für nicht-kommerzielle Nutzung):

    git clone --depth 1 https://github.com/patronus-ai/financebench /tmp/financebench
    python scripts/financebench_test.py /tmp/financebench --out /tmp/fb-test
"""

from __future__ import annotations

import argparse
import json
import pickle
import re
import sys
import time
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

from zitatio.dataroom import DataRoom
from zitatio.pipeline import run_check
from zitatio.verify import Status

_AMOUNT_ANSWER = re.compile(r"^\$(-?[\d,]+(?:\.\d+)?)$")
_PERCENT_ANSWER = re.compile(r"^(-?\d+(?:\.\d+)?)%$")


def _value(row: dict) -> tuple[str, Decimal, str] | None:
    """('betrag'|'prozent', Wert, Einheit) aus der FinanceBench-Antwort, sonst None."""
    answer, question = row["answer"].strip(), row["question"]
    if m := _PERCENT_ANSWER.match(answer):
        return "prozent", Decimal(m.group(1)), "%"
    if m := _AMOUNT_ANSWER.match(answer):
        value = Decimal(m.group(1).replace(",", ""))
        if re.search(r"USD\s+billions|in\s+billions", question, re.I):
            return "betrag", value, "Mrd."
        if re.search(r"USD\s+millions|in\s+millions|in USD million", question, re.I):
            return "betrag", value, "Mio."
    return None


def _fmt(kind: str, value: Decimal, unit: str) -> str:
    if kind == "prozent":
        return f"{value} %"
    text = f"{value.normalize():f}"
    whole, _, frac = text.partition(".")
    grouped = f"{int(whole):,}".replace(",", "'")
    return f"USD {grouped}{'.' + frac if frac else ''} {unit}"


def _wrong(kind: str, value: Decimal) -> Decimal:
    """8 % daneben, mit derselben Anzahl Nachkommastellen; 0 wird zu 1."""
    exp = value.as_tuple().exponent if value != value.to_integral() else 0
    step = Decimal(1).scaleb(exp)
    wrong = (value * Decimal("1.08")).quantize(step) if value else Decimal(1)
    return wrong if wrong != value else value + step


def _period(question: str) -> str:
    years = re.findall(r"FY\s?(\d{4})", question)
    if years:
        return "im Geschäftsjahr " + " bis ".join(dict.fromkeys(years))
    q = re.search(r"(Q[1-4])\s*(?:of\s*)?(?:FY)?\s*(\d{4})", question)
    return f"im {q.group(1)} {q.group(2)}" if q else ""


def _metric(question: str) -> str:
    m = re.search(r"what (?:is|was) (?:the )?(.+?)(?:\?| for | of | \()", question, re.I)
    text = m.group(1) if m else "die gefragte Kennzahl"
    text = re.sub(r"\b(?:FY\s?\d{4}(?:\s*-\s*FY\s?\d{4})?|year end|unadjusted)\b", "", text, flags=re.I)
    return re.sub(r"\s+", " ", text).strip(" ,'") or "die gefragte Kennzahl"


def _pages_without(doc_pages: list[str], value_digits: str, avoid: set[int]) -> int:
    """Eine Seite, auf der die Ziffernfolge nicht vorkommt (für die falsche Fundstelle)."""
    for page in range(2, len(doc_pages) + 1):
        if page in avoid:
            continue
        if value_digits not in re.sub(r"[^\d]", "", doc_pages[page - 1]):
            return page
    return 1


def build(fb: Path, out: Path) -> tuple[str, list[dict], DataRoom]:
    rows = [json.loads(line) for line in (fb / "data" / "financebench_open_source.jsonl").open()]
    items = [(row, v) for row in rows if (v := _value(row))]
    docs = sorted({row["doc_name"] for row, _ in items})
    index = {name: str(i + 1) for i, name in enumerate(docs)}

    room_dir = out / "datenraum"
    room_dir.mkdir(parents=True, exist_ok=True)
    for name in docs:
        link = room_dir / f"{index[name]} {name}.pdf"
        if not link.exists():
            link.symlink_to((fb / "pdfs" / f"{name}.pdf").resolve())
    started = time.perf_counter()
    cache = out / "datenraum.pickle"  # PDFs lesen dauert Minuten; Seitentexte für weitere Läufe merken
    room = pickle.loads(cache.read_bytes()) if cache.exists() else DataRoom.from_folder(room_dir)
    cache.write_bytes(pickle.dumps(room))
    print(f"Datenraum: {len(room.documents)} Dokumente, "
          f"{sum(len(d.pages) for d in room.documents)} Seiten, {time.perf_counter() - started:.0f} s gelesen")

    lines, truth = ["# FinanceBench als DD-Bericht", ""], []
    for row, (kind, value, unit) in items:
        doc = room.get(index[row["doc_name"]])
        pages = sorted({e["evidence_page_num"] + 1 for e in row["evidence"]})
        cite = "; ".join(f"DR {doc.index}, S. {p}" for p in pages)
        reasoning = row.get("question_reasoning") or ""
        extraction = reasoning.strip() == "Information extraction"
        subject = f"{row['company']}: {_metric(row['question'])} {_period(row['question'])}".strip()
        lines += [f"## {row['financebench_id']}", ""]
        variants = [("richtig", value, cite)]
        variants.append(("falscher Wert", _wrong(kind, value), cite))
        digits = re.sub(r"[^\d]", "", f"{value.normalize():f}").lstrip("0") or "0"
        other = _pages_without(doc.pages, digits, set(pages))
        variants.append(("falsche Seite", value, f"DR {doc.index}, S. {other}"))
        for variant, shown, where in variants:
            lines.append(f"{subject} beträgt {_fmt(kind, shown, unit)} [{where}].")
            lines.append("")
            truth.append({"id": row["financebench_id"], "variante": variant, "art": kind,
                          "direkt": extraction, "frage": row["question_type"]})
    report = "\n".join(lines)
    (out / "bericht.md").write_text(report, encoding="utf-8")
    (out / "wahrheit.json").write_text(json.dumps(truth, ensure_ascii=False, indent=1), encoding="utf-8")
    return report, truth, room


def evaluate(report: str, truth: list[dict], room: DataRoom, out: Path) -> str:
    started = time.perf_counter()
    run = run_check("bericht.md", report, report.encode(), room)
    seconds = time.perf_counter() - started
    findings = run.findings
    if len(findings) != len(truth):
        raise SystemExit(f"{len(findings)} Aussagen erkannt, {len(truth)} erwartet")

    table: dict[tuple[str, str], Counter] = defaultdict(Counter)
    detail = []
    for f, t in zip(findings, truth):
        group = "direkt abgelesen" if t["direkt"] else "berechnet"
        table[(group, t["variante"])][f.status.label] += 1
        detail.append({**t, "status": f.status.label, "aussage": f.claim.clean_text,
                       "grund": f.reasons[0] if f.reasons else ""})
    (out / "ergebnis.json").write_text(json.dumps(detail, ensure_ascii=False, indent=1), encoding="utf-8")

    good = {"richtig": {Status.GEPRUEFT.label},
            "falscher Wert": {Status.ABWEICHUNG.label, Status.WIDERSPRUCH.label},
            "falsche Seite": {Status.FALSCHE_FUNDSTELLE.label, Status.ABWEICHUNG.label}}
    lines = [f"FinanceBench: {len(truth) // 3} Antworten x 3 Varianten = {len(truth)} Aussagen, "
             f"Prüfzeit {seconds:.1f} s", ""]
    for (group, variant), counts in sorted(table.items()):
        n = sum(counts.values())
        hit = sum(c for s, c in counts.items() if s in good[variant])
        spread = ", ".join(f"{s} {c}" for s, c in counts.most_common())
        lines.append(f"{group:17} {variant:14} {hit:3}/{n:<3} richtig erkannt   ({spread})")
    return "\n".join(lines)


def evaluate_without_citations(report: str, truth: list[dict], room: DataRoom) -> str:
    """Derselbe Bericht ohne Fundstellen: Zitatio muss die Seite in allen Berichten selbst finden."""
    plain = re.sub(r"\s*\[DR [^\]]*\]", "", report)
    started = time.perf_counter()
    run = run_check("ohne-fundstellen.md", plain, plain.encode(), room)
    seconds = time.perf_counter() - started
    table: dict[tuple[str, str], Counter] = defaultdict(Counter)
    for f, t in zip(run.findings, truth):
        if t["variante"] == "falsche Seite":
            continue  # ohne Fundstelle dieselbe Aussage wie "richtig"
        group = "direkt abgelesen" if t["direkt"] else "berechnet"
        table[(group, t["variante"])][f.status.label] += 1
    good = {"richtig": {Status.GEPRUEFT.label},
            "falscher Wert": {Status.ABWEICHUNG.label, Status.WIDERSPRUCH.label, Status.OHNE_BELEG.label}}
    lines = ["", f"Ohne Fundstellen (Belegsuche über alle {sum(len(d.pages) for d in room.documents)} Seiten), "
             f"Prüfzeit {seconds:.1f} s", ""]
    for (group, variant), counts in sorted(table.items()):
        n = sum(counts.values())
        hit = sum(c for st, c in counts.items() if st in good[variant])
        spread = ", ".join(f"{st} {c}" for st, c in counts.most_common())
        lines.append(f"{group:17} {variant:14} {hit:3}/{n:<3} richtig erkannt   ({spread})")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("financebench", type=Path, help="Klon von github.com/patronus-ai/financebench")
    parser.add_argument("--out", type=Path, default=Path("financebench-test"))
    args = parser.parse_args()
    report, truth, room = build(args.financebench, args.out)
    summary = evaluate(report, truth, room, args.out) + evaluate_without_citations(report, truth, room)
    (args.out / "ergebnis.txt").write_text(summary + "\n", encoding="utf-8")
    print(summary)


if __name__ == "__main__":
    sys.exit(main())
