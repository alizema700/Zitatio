"""Fristenkalender: Vertragsenden, letzte Kündigungstermine und Ablaufdaten als Kalender.

Aus der Closing-Liste weiss Zitatio, wann Verträge enden und mit welcher Frist sie gekündigt werden. Für das
Deal-Team zählt der letzte Tag, an dem noch gekündigt oder neu verhandelt werden kann. Dazu kommen Zertifikate
und Bewilligungen mit Ablaufdatum. Alles geht als iCalendar-Datei (.ics) in Outlook oder Google Kalender.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

from .facts import DATE, extract_facts
from .terms import _add_months

_EXPIRY = re.compile(r"gültig bis|läuft am .{0,20}ab|valable jusqu|valido fino|valid until|expires on", re.IGNORECASE)
_SENTENCE = re.compile(r"(?:[^.!?]|[.!?](?=\d))+(?:[.!?]|$)")


@dataclass
class Deadline:
    date: dt.date
    title: str
    detail: str
    reference: str  # "DR 5.3, S. 2"


def _ref(ev) -> str:
    return f"{ev.doc_label}, S. {ev.page}"


def _on_term(end: dt.date, notice_to: str | None) -> bool:
    """Kündigung auf Jahres- oder Quartalsende passt nur, wenn das Vertragsende auf einen solchen Termin fällt."""
    last_of_month = (end + dt.timedelta(days=1)).day == 1
    if notice_to == "jahr":
        return (end.month, end.day) == (12, 31)
    if notice_to == "quartal":
        return last_of_month and end.month % 3 == 0
    if notice_to == "monat":
        return last_of_month
    return True


def deadlines(run, today: dt.date | None = None) -> list[Deadline]:
    today = today or run.created.date()
    out: list[Deadline] = []
    for t in run.terms or []:
        if not t.end or t.end < today:
            continue
        name = t.doc.title
        out.append(Deadline(t.end, f"Vertragsende: {name}", f"{t.doc.label} endet am {t.end:%d.%m.%Y}.",
                            _ref(t.evidence["ende"])))
        if t.notice and t.notice[1] in ("Monate", "Jahre") and _on_term(t.end, t.notice_to):
            months = t.notice[0] * (12 if t.notice[1] == "Jahre" else 1)
            last = _add_months(t.end + dt.timedelta(days=1), -months) - dt.timedelta(days=1)
            if last >= today:
                ev = t.evidence.get("kuendigung", t.evidence["ende"])
                out.append(Deadline(last, f"Letzter Kündigungstag: {name}",
                                    f"Kündigungsfrist {t.notice_text()}; um auf das Vertragsende am {t.end:%d.%m.%Y} "
                                    "zu kündigen oder neu zu verhandeln, muss die Kündigung bis zu diesem Tag eingetroffen sein.",
                                    _ref(ev)))
    seen = set()
    from .verify import _evidence

    for doc in run.room.documents:
        if doc.index is None:
            continue
        for p, text in enumerate(doc.pages, 1):
            flat = text.replace("\n", " ")
            for m in _SENTENCE.finditer(flat):
                hit = _EXPIRY.search(m.group(0))
                if not hit:
                    continue
                dates = [f for f in extract_facts(m.group(0)) if f.kind == DATE and f.start > hit.start()]
                if not dates or dates[0].value < today or (doc.index, dates[0].value) in seen:
                    continue
                seen.add((doc.index, dates[0].value))
                ev = _evidence(doc, p, m.start() + dates[0].start, m.start() + dates[0].end)
                sentence = re.sub(r"\s+", " ", m.group(0)).strip(" ;|")
                out.append(Deadline(dates[0].value, f"Läuft ab: {sentence if len(sentence) <= 70 else doc.title}",
                                    f"{sentence} ({doc.title})", _ref(ev)))
    # Vertragsenden aus Verträgen erscheinen schon oben
    contract_ends = {(d.reference.split(",")[0], d.date) for d in out if d.title.startswith("Vertragsende")}
    out = [d for d in out if not (d.title.startswith("Läuft ab") and (d.reference.split(",")[0], d.date) in contract_ends)]
    return sorted(out, key=lambda d: d.date)


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str) -> str:
    """Zeilen über 75 Byte umbrechen (RFC 5545)."""
    out, cur = [], ""
    for ch in line:
        if len((cur + ch).encode()) > 74:
            out.append(cur)
            cur = " " + ch
        else:
            cur += ch
    return "\r\n".join(out + [cur])


def to_ics(items: list[Deadline], name: str, stamp: dt.datetime | None = None) -> str:
    stamp = (stamp or dt.datetime.now(dt.timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Zitatio//Fristen//DE", "CALSCALE:GREGORIAN",
             f"X-WR-CALNAME:{_escape('Fristen ' + name)}"]
    for n, d in enumerate(items, 1):
        lines += ["BEGIN:VEVENT", f"UID:zitatio-{d.date:%Y%m%d}-{n}@zitatio", f"DTSTAMP:{stamp}",
                  f"DTSTART;VALUE=DATE:{d.date:%Y%m%d}",
                  f"DTEND;VALUE=DATE:{d.date + dt.timedelta(days=1):%Y%m%d}",
                  f"SUMMARY:{_escape(d.title)}", f"DESCRIPTION:{_escape(d.detail + ' (' + d.reference + ')')}",
                  "BEGIN:VALARM", "ACTION:DISPLAY", "TRIGGER:-P14D", f"DESCRIPTION:{_escape(d.title)}", "END:VALARM",
                  "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"
