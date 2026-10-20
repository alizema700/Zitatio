"""Prüfbericht als eigenständige HTML-Datei und als JSON."""

from __future__ import annotations

import base64
import csv
import datetime as dt
import hashlib
import html
import io
import json
from dataclasses import dataclass, field
from importlib import resources

from . import __version__
from .dataroom import DataRoom
from .facts import KIND_LABELS
from .verify import Finding, Status

SYMBOLS = {
    Status.GEPRUEFT: "✓",
    Status.ABWEICHUNG: "✗",
    Status.WIDERSPRUCH: "≠",
    Status.FALSCHE_FUNDSTELLE: "↷",
    Status.QUELLE_FEHLT: "✗",
    Status.OHNE_BELEG: "!",
    Status.UNGEPRUEFT: "?",
}
ORDER = [Status.ABWEICHUNG, Status.QUELLE_FEHLT, Status.WIDERSPRUCH, Status.FALSCHE_FUNDSTELLE, Status.OHNE_BELEG,
         Status.UNGEPRUEFT, Status.GEPRUEFT]


@dataclass
class Run:
    report_name: str
    report_sha256: str
    room: DataRoom
    findings: list[Finding]
    model: str | None = None
    created: dt.datetime | None = None
    conflicts: list = field(default_factory=list)  # crosscheck.Conflict
    addbacks: list = field(default_factory=list)  # derive.AddbackCheck
    gaps: list = field(default_factory=list)  # gaps.Gap
    contracts: list = field(default_factory=list)  # clauses.ContractEntry
    flags: list = field(default_factory=list)  # swiss.Flag
    internal: list = field(default_factory=list)  # consistency.ReportConflict
    netdebt: object | None = None  # netdebt.NetDebt
    valuation: object | None = None  # valuation.Valuation
    terms: list = field(default_factory=list)  # terms.Terms
    closing: list = field(default_factory=list)  # terms.ClosingItem
    revenue: tuple | None = None  # (Jahr, Umsatz) aus der neuesten Jahresrechnung
    diff: object | None = None  # versions.VersionDiff
    decisions: dict = field(default_factory=dict)  # Aussagenummer -> übernommener Entscheid

    def __post_init__(self):
        self.created = self.created or dt.datetime.now().astimezone()

    def counts(self) -> dict[Status, int]:
        return {s: sum(f.status is s for f in self.findings) for s in ORDER}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


CSV_COLUMNS = ["Nr", "Abschnitt", "Aussage", "Fundstellen", "Status", "Methode", "Begründung", "Belege",
               "Entscheid", "Notiz", "Prüfer"]


def _rows(run: Run) -> list[list]:
    return [
        [
            f.claim.number,
            f.claim.section,
            f.claim.clean_text,
            ", ".join(c.label for c in f.claim.citations),
            f.status.label,
            f.method,
            " ".join(f.reasons),
            " | ".join(f"{e.doc_label}, S. {e.page}: {e.before}{e.match}{e.after}" for e in f.evidence),
            *_decision(run, f),
        ]
        for f in run.findings
    ]


def _decision(run: Run, f: Finding) -> list[str]:
    d = run.decisions.get(f.claim.number) or {}
    labels = {"ok": "Zugestimmt", "nein": "Widersprochen"}
    return [labels.get(d.get("v", ""), ""), d.get("n", ""), d.get("p", "")]


def to_csv(run: Run) -> str:
    """Eine Zeile pro Aussage; Semikolon und BOM, damit Excel in der Schweiz es direkt öffnet.

    Die Spalten Entscheid, Notiz und Prüfer sind für die menschliche Durchsicht da;
    der HTML-Prüfbericht füllt sie beim Export aus.
    """
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";", lineterminator="\r\n")
    writer.writerow(CSV_COLUMNS)
    writer.writerows(_rows(run))
    return "\ufeff" + out.getvalue()


def to_json(run: Run) -> str:
    return json.dumps(
        {
            "zitatio_version": __version__,
            "erstellt": run.created.isoformat(timespec="seconds"),
            "bericht": {"name": run.report_name, "sha256": run.report_sha256},
            "pruefmodell": run.model,
            "datenraum": [
                {"index": d.index, "name": d.name, "seiten": len(d.pages), "sha256": d.sha256}
                for d in run.room.documents
            ],
            "hinweise": run.room.warnings,
            "zusammenfassung": {s.value: n for s, n in run.counts().items()},
            "aussagen": [
                {
                    "nr": f.claim.number,
                    "abschnitt": f.claim.section,
                    "aussage": f.claim.text,
                    "fundstellen": [c.label for c in f.claim.citations],
                    "werte": [
                        {"art": x.kind, "text": x.text, "normalisiert": x.display()}
                        for x in f.claim.facts
                    ],
                    "status": f.status.value,
                    "methode": f.method,
                    "begruendung": f.reasons,
                    "belege": [
                        {"dokument": e.doc_label, "seite": e.page,
                         "ausschnitt": e.before + e.match + e.after}
                        for e in f.evidence
                    ],
                }
                for f in run.findings
            ],
            "widersprueche": [
                {
                    "groesse": c.title,
                    "werte": [
                        {"dokument": x.doc.label, "seite": x.page, "zeile": x.cell.label, "wert": x.cell.fact.display()}
                        for x in c.sightings
                    ],
                }
                for c in run.conflicts
            ],
            "bereinigungen": [
                {
                    "abschnitt": c.section,
                    "ebitda_aussage": c.base.claim.number,
                    "bereinigungen": [{"aussage": f.claim.number, "betrag": str(v), "status": f.status.value} for f, v in c.items],
                    "nachgerechnet": str(c.expected),
                    "bericht": str(c.stated),
                    "stimmt": c.ok,
                }
                for c in run.addbacks
            ],
            "widersprueche_im_bericht": [
                {"groesse": c.title, "werte": c.values, "aussagen": [f.claim.number for f in c.findings]}
                for c in run.internal
            ],
            "versionsvergleich": None if run.diff is None else {
                "vorversion": run.diff.old_name,
                "zusammenfassung": run.diff.summary(),
                "aenderungen": [
                    {"aussage": c.new.claim.number, "art": c.kind, "vorher": c.old.claim.clean_text if c.old else None,
                     "status_vorher": c.old.status.value if c.old else None, "status": c.new.status.value,
                     "ergebnis": c.outcome}
                    for c in run.diff.changes if c.kind != "unverändert" or c.outcome
                ],
                "gestrichen": [{"text": f.claim.clean_text, "status_vorher": f.status.value} for f in run.diff.removed],
            },
            "schweiz": [
                {"stufe": fl.level, "bereich": fl.area, "titel": fl.title, "text": fl.text,
                 "belege": [{"dokument": e.doc_label, "seite": e.page, "text": e.match} for e in fl.evidence]}
                for fl in run.flags
            ],
            "nettoverschuldung": None if run.netdebt is None else {
                "jahr": run.netdebt.year, "nettoverschuldung": str(run.netdebt.net_debt),
                "inkl_schuldenaehnlich": str(run.netdebt.adjusted),
                "posten": [{"posten": i.label, "betrag": str(i.amount), "art": i.kind, "hinweis": i.note,
                            "belege": [{"dokument": e.doc_label, "seite": e.page, "text": e.match} for e in i.evidence]}
                           for i in run.netdebt.items],
                "covenant": None if run.netdebt.covenant is None else {
                    "grenze": str(run.netdebt.covenant.limit), "ist": str(run.netdebt.covenant.ratio),
                    "eingehalten": run.netdebt.covenant.ok},
            },
            "preisbruecke": None if run.valuation is None else {
                "multiple": str(run.valuation.multiple), "ebitda_bereinigt": str(run.valuation.ebitda),
                "unternehmenswert": str(run.valuation.ev),
                "equity_value": None if run.valuation.equity is None else str(run.valuation.equity),
                "equity_value_nach_befunden": None if run.valuation.checked_equity is None
                else str(run.valuation.checked_equity),
                "wirkungen": [{"posten": i.label, "betrag": str(i.amount), "grundlage": i.basis}
                              for i in run.valuation.impacts],
                "risiken": [{"posten": i.label, "betrag": str(i.amount), "grundlage": i.basis}
                            for i in run.valuation.risks],
            },
            "fragenliste": [{"nr": q.number, "bereich": q.area, "prioritaet": q.priority, "frage": q.text,
                             "bezug": q.reference} for q in _questions(run)],
            "closing_liste": [
                {"dokument": i.terms.doc.label, "titel": i.terms.doc.title, "art": i.kind, "text": i.text,
                 "volumen": str(i.terms.volume) if i.terms.volume else None,
                 "belege": [{"seite": e.page, "text": e.match} for e in i.evidence]}
                for i in run.closing
            ],
            "vertragsregister": [
                {"dokument": e.doc.label, "titel": e.doc.title,
                 **_terms_json(run, e),
                 "klauseln": [{"art": c.kind, "vorhanden": c.present, "seite": c.page, "satz": c.sentence}
                              for c in e.clauses]}
                for e in run.contracts if e.clauses
            ],
            "unterlagen": [
                {"bereich": g.area, "unterlage": g.name, "vorhanden": g.present,
                 "dokumente": [d.label for d in g.documents], "hinweis": g.note}
                for g in run.gaps
            ],
        },
        ensure_ascii=False,
        indent=2,
    )


DISCLOSURE_COLUMNS = ["Nr", "Aussage", "Status", "Dokument", "Titel", "Datei", "SHA-256 Dokument", "Seite",
                      "Textstelle", "Geprüft am"]


def to_disclosure_csv(run: Run) -> str:
    """Offenlegungskarte: welche Aussage auf welcher Seite welches Dokuments steht.

    Eine Zeile pro Beleg, mit Prüfsumme des Dokuments und Zeitpunkt der Prüfung. So lässt
    sich später zeigen, was im Datenraum offengelegt war (W&I-Underwriting, Schadenfall).
    """
    docs = {d.label: d for d in run.room.documents}
    stamp = run.created.isoformat(timespec="seconds")
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";", lineterminator="\r\n")
    writer.writerow(DISCLOSURE_COLUMNS)
    for f in run.findings:
        if not f.evidence:
            writer.writerow([f.claim.number, f.claim.clean_text, f.status.label, "", "", "", "", "", "", stamp])
        for e in f.evidence:
            d = docs.get(e.doc_label)
            writer.writerow([f.claim.number, f.claim.clean_text, f.status.label, e.doc_label, d.title if d else "",
                             e.doc_name, d.sha256 if d else "", e.page, e.before + e.match + e.after, stamp])
    return "\ufeff" + out.getvalue()


def logo_svg() -> str:
    svg = resources.files("zitatio").joinpath("assets/zitatio-logo.svg").read_text()
    return (
        svg.replace('fill="#15202B"', 'style="fill:var(--ink)"')
        .replace('fill="#1E7A50"', 'style="fill:var(--green)"')
        .replace("<svg ", '<svg class="logo" role="img" aria-label="Zitatio" ', 1)
    )


def _font_faces() -> str:
    """Hausschrift als Data-URI, damit der Prüfbericht als einzelne Datei offline gleich aussieht."""
    faces = []
    for family, weight, name in (("Familjen Grotesk", 400, "familjen-grotesk-latin-400-normal"),
                                 ("Familjen Grotesk", 700, "familjen-grotesk-latin-700-normal"),
                                 ("Familjen Grotesk", 500, "familjen-grotesk-latin-500-normal")):
        data = resources.files("zitatio").joinpath(f"assets/fonts/{name}.woff2").read_bytes()
        faces.append(
            '@font-face {{ font-family:"%s"; font-weight:%d; font-display:swap; '
            'src:url(data:font/woff2;base64,%s) format("woff2"); }}' % (family, weight, base64.b64encode(data).decode())
        )
    return "\n".join(faces).replace("{{", "{").replace("}}", "}")


def _highlight(finding: Finding) -> str:
    """Aussage mit markierten Werten (ohne Fundstellenklammern)."""
    clean = finding.claim.clean_text
    out, pos = [], 0
    for fact in finding.claim.facts:
        out.append(html.escape(clean[pos : fact.start]))
        out.append(
            f'<mark title="{KIND_LABELS[fact.kind]}: {html.escape(fact.display())}">'
            f"{html.escape(clean[fact.start : fact.end])}</mark>"
        )
        pos = fact.end
    out.append(html.escape(clean[pos:]))
    return "".join(out)


def _protocol_line(f: Finding) -> str:
    short = f.claim.clean_text
    if len(short) > 78:
        short = short[:76].rstrip() + "…"
    where = ", ".join(c.label for c in f.claim.citations) or "ohne Fundstelle"
    return (
        f'<a class="pl s-{f.status.value}" href="#a{f.claim.number}">'
        f'<span class="sym">{SYMBOLS[f.status]}</span>'
        f'<span class="nr">{f.claim.number:02d}</span>'
        f'<span class="txt">{html.escape(short)}</span>'
        f'<span class="where">{html.escape(where)}</span>'
        f'<span class="st">{f.status.label}</span></a>'
    )


def _card(f: Finding, run: Run | None = None) -> str:
    reasons = "".join(f"<li>{html.escape(r)}</li>" for r in f.reasons)
    evidence = "".join(
        f'<figure class="ev"><figcaption>{html.escape(e.doc_label)}, S. {e.page}'
        f' <span class="file">{html.escape(e.doc_name)}</span></figcaption>'
        f"<blockquote>{html.escape(e.before)}<mark>{html.escape(e.match)}</mark>"
        f"{html.escape(e.after)}</blockquote></figure>"
        for e in f.evidence
    )
    where = ", ".join(c.label for c in f.claim.citations) or "keine"
    section = f'<span class="sec">{html.escape(f.claim.section)}</span>' if f.claim.section else ""
    change = run.diff.of(f) if run is not None and run.diff is not None else None
    before = ""
    if change is not None and change.kind != "unverändert":
        section += f'<span class="tag">{change.kind}</span>'
    if change is not None and change.kind == "geändert":
        before = f'<p class="cite diff">Vorher ({html.escape(change.old.status.label)}): {_diff_html(change)}</p>'
    return f"""
<article class="card s-{f.status.value}" id="a{f.claim.number}" data-status="{f.status.value}">
  <header><span class="badge">{SYMBOLS[f.status]} {f.status.label}</span>
  <span class="num">Aussage {f.claim.number}</span>{section}
  <span class="method">{html.escape(f.method)}</span></header>
  <p class="claim">{_highlight(f)}</p>
  {before}<p class="cite">Fundstelle: {html.escape(where)}</p>
  <ul class="reasons">{reasons}</ul>
  {evidence}
  <div class="decide" data-nr="{f.claim.number}">
    <span class="q">Ihr Entscheid</span>
    <button type="button" data-d="ok">Zustimmen</button>
    <button type="button" data-d="nein">Widersprechen</button>
    <input type="text" placeholder="Notiz, z. B. korrigiert in Version 2" aria-label="Notiz zu Aussage {f.claim.number}">
  </div>
</article>"""


def _diff_html(change) -> str:
    from .versions import word_diff

    tags = {"=": "{}", "-": "<del>{}</del>", "+": "<ins>{}</ins>"}
    return "".join(tags[k].format(html.escape(t)) for k, t in word_diff(change.old.claim.text, change.new.claim.text))


def _versions_html(run: Run) -> str:
    diff = run.diff
    if diff is None:
        return ""
    rows = []
    rank = {"neuer Befund": 0, "offen": 1, "behoben": 2}
    for c in sorted(diff.changes, key=lambda c: rank.get(c.outcome, 3)):
        if c.kind == "unverändert" and c.outcome != "offen":
            continue
        was = f'<span class="pill s-{c.old.status.value}">{c.old.status.label}</span>' if c.old else "–"
        text = _diff_html(c) if c.kind == "geändert" else html.escape(c.new.claim.clean_text)
        rows.append(f'<tr><td>{_pill(c.new)}</td><td>{c.kind}</td><td class="diff">{text}</td>'
                    f'<td>{was}</td><td>{html.escape(c.outcome)}</td></tr>')
    for f in diff.removed:
        rows.append(f'<tr><td>–</td><td>gestrichen</td><td class="diff"><del>{html.escape(f.claim.clean_text)}</del></td>'
                    f'<td><span class="pill s-{f.status.value}">{f.status.label}</span></td>'
                    f'<td>{"behoben" if f.status.value not in ("geprueft", "ungeprueft") else ""}</td></tr>')
    kept = len(run.decisions)
    carried = f" {kept} Entscheide aus der Vorversion übernommen." if kept else ""
    table = (f'<div class="tablebox"><table><thead><tr><th>Aussage</th><th>Änderung</th><th>Text</th>'
             f'<th>Vorher</th><th>Ergebnis</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>') if rows else ""
    return (f'<h2 id="versionen">Änderungen gegenüber der Vorversion</h2><p class="lead">Vorversion {html.escape(diff.old_name)}. '
            f"{html.escape(diff.summary())}{carried} Unveränderte Aussagen ohne offenen Befund sind ausgeblendet.</p>"
            + table)


def _xlsx(run: Run) -> bytes:
    from .excel import to_xlsx

    return to_xlsx(run)


def _keypoints_html(run: Run) -> str:
    from .summary import key_points

    points = key_points(run)
    if not points:
        return ""
    cls = {"kritisch": "abweichung", "klären": "ohne_beleg", "info": "ungeprueft"}
    items = "".join(
        f'<li class="s-{cls[p.level]}"><a href="{p.href}"><span class="badge">{p.level.capitalize()}</span>'
        f'<b>{html.escape(p.title)}</b></a><p>{html.escape(p.text)}</p></li>'
        for p in points[:10])
    return f'<section class="keys"><p class="kicker">Das Wichtigste für das Investment Committee</p><ul>{items}</ul></section>'


def _pill(f: Finding) -> str:
    return f'<a class="pill s-{f.status.value}" href="#a{f.claim.number}">Aussage {f.claim.number} · {f.status.label}</a>'


def _conflicts_html(run: Run) -> str:
    if not run.conflicts:
        return ""
    affected = {}
    for f in run.findings:
        for c in run.conflicts:
            if any(x.key in set(f.hits) for x in c.sightings):
                affected.setdefault(id(c), []).append(f)
    cards = []
    for c in run.conflicts:
        rows = "".join(
            f"<tr><td>{html.escape(x.doc.label)}, S. {x.page}</td><td class=\"opt\">{html.escape(x.doc.title)}</td>"
            f"<td>{html.escape(x.cell.label)}</td><td class=\"num\">{html.escape(x.cell.fact.display())}</td></tr>"
            for x in c.sightings
        )
        pills = "".join(_pill(f) for f in affected.get(id(c), []))
        cards.append(
            f'<article class="card s-widerspruch"><header><span class="badge">≠ Widerspruch</span>'
            f'<span class="num">{html.escape(c.title)}</span></header>'
            f'<div class="tablebox flat"><table><thead><tr><th>Fundstelle</th><th class="opt">Dokument</th><th>Zeile</th>'
            f'<th class="num">Wert</th></tr></thead><tbody>{rows}</tbody></table></div>'
            + (f'<p class="pills">Im Bericht: {pills}</p>' if pills else "")
            + "</article>"
        )
    n = len(run.conflicts)
    return (f'<h2 id="widersprueche">Widersprüche im Datenraum</h2><p class="lead">Bei {n} {"Grössen" if n > 1 else "Grösse"} nennen '
            "die Dokumente unterschiedliche Werte. Das betrifft die Unterlagen des Verkäufers selbst: "
            "Welcher Wert stimmt, muss geklärt werden, bevor der Bericht ihn übernimmt.</p>" + "".join(cards))


def _addbacks_html(run: Run) -> str:
    if not run.addbacks:
        return ""
    from .derive import _chf

    out = []
    for c in run.addbacks:
        base = next(x for x in c.base.claim.facts if x.kind == "betrag")
        def row(label: str, f: Finding | None, value: str, cls: str = "") -> str:
            pill = _pill(f) if f else ""
            return (f'<tr class="{cls}"><td>{html.escape(label)}<span class="m">{pill}</span></td>'
                    f'<td class="opt">{pill}</td><td class="num">{value}</td></tr>')

        rows = [row("Ausgewiesenes EBITDA", c.base, _chf(base.value[1]))]
        for f, v in c.items:
            amount = next(x for x in f.claim.facts if x.kind == "betrag")
            text = (f.claim.clean_text[: amount.start] + f.claim.clean_text[amount.end :]).strip(" :,.")
            text = text if len(text) < 80 else text[:78] + "…"
            rows.append(row(text, f, f"{'−' if v < 0 else '+'} {_chf(abs(v))}"))
        rows.append(row("Nachgerechnet", None, _chf(c.expected), "sum"))
        rows.append(row("Bericht nennt", c.total, _chf(c.stated), "sum"))
        verdict = ("Die Rechnung geht auf." if c.ok else "Die Rechnung geht nicht auf.")
        if c.unsupported:
            k = len(c.unsupported)
            verdict += f" {k} von {len(c.items)} Bereinigungen {'hat' if k == 1 else 'haben'} keinen Beleg im Datenraum."
        share = c.share
        if share is not None:
            verdict += f" Die Bereinigungen machen {share.quantize(1)} % des bereinigten EBITDA aus."
        status = "geprueft" if c.ok and not c.unsupported else ("abweichung" if not c.ok else "ohne_beleg")
        out.append(f'<article class="card s-{status}"><header><span class="badge">{"✓" if status == "geprueft" else "!"} '
                   f'{html.escape(verdict.split(".")[0])}</span><span class="num">{html.escape(c.section)}</span></header>'
                   f'<div class="tablebox flat"><table><tbody>{"".join(rows)}</tbody></table></div>'
                   f'<p class="cite">{html.escape(verdict)}</p></article>')
    return ('<h2 id="bereinigungen">EBITDA-Bereinigungen nachgerechnet</h2><p class="lead">Jede Bereinigung braucht eine Fundstelle, '
            "und die Summe muss aufgehen.</p>" + "".join(out))


def _terms_json(run: Run, entry) -> dict:
    t = next((t for t in run.terms if t.entry is entry), None)
    if t is None:
        return {}
    return {"beginn": t.start.isoformat() if t.start else None, "ende": t.end.isoformat() if t.end else None,
            "kuendigungsfrist": t.notice_text() or None, "volumen": str(t.volume) if t.volume else None}


def _valuation_html(run: Run) -> str:
    v = run.valuation
    if v is None:
        return ""

    def chf(x) -> str:
        return ("− " if x < 0 else "") + f"CHF {abs(x):,.0f}".replace(",", "'")

    def row(label, value, where="", cls="", href="") -> str:
        label = f'<a href="{href}">{html.escape(label)}</a>' if href else html.escape(label)
        return (f'<tr class="{cls}"><td>{label}</td><td class="opt">{html.escape(where)}</td>'
                f'<td class="num">{value}</td></tr>')

    rows = [row("Bereinigtes EBITDA laut Bericht", chf(v.ebitda)),
            row("Multiple", f"{v.multiple}x", v.multiple_text if len(v.multiple_text) <= 90
                else v.multiple_text[:89].rsplit(" ", 1)[0] + " …"),
            row("Unternehmenswert", chf(v.ev), cls="sum")]
    if v.equity is not None:
        rows += [row(f"Nettoverschuldung laut Bilanz {v.year}", chf(-v.net_debt), href="#nettoverschuldung"),
                 row("Equity Value laut Rechnung", chf(v.equity), cls="sum")]
        for i in v.impacts:
            rows.append(row(i.label, chf(i.amount), i.basis, href=i.href))
        if v.impacts:
            delta = v.checked_equity - v.equity
            share = f" ({delta / v.equity * 100:.1f} %)" if v.equity else ""
            rows.append(row("Equity Value nach Befunden", chf(v.checked_equity) + html.escape(share), cls="sum"))
        if v.risks:
            rows.append('<tr><td colspan="3" class="where">Risiken daneben, nicht in der Summe: im SPA mit '
                        "Freistellung oder Rückbehalt regeln</td></tr>")
            rows += [row(i.label, chf(i.amount), i.basis, href=i.href) for i in v.risks]
    return ('<h2 id="preis">Preisbrücke</h2><p class="lead">Was die Befunde für den Kaufpreis bedeuten: '
            "Unternehmenswert aus Multiple und bereinigtem EBITDA des Berichts, minus Nettoverschuldung aus der Bilanz. "
            "Eine Bereinigung ohne Beleg fällt mal das Multiple weg, schuldenähnliche Posten Franken für Franken.</p>"
            '<div class="tablebox"><table><thead><tr><th>Posten</th><th class="opt">Grundlage</th><th>Betrag</th>'
            f'</tr></thead><tbody>{"".join(rows)}</tbody></table></div>')


def _netdebt_html(run: Run) -> str:
    from .netdebt import AEHNLICH, EVENTUAL, FINANZ

    nd = run.netdebt
    if nd is None or not nd.items:
        return ""

    def chf(v) -> str:
        return ("− " if v < 0 else "") + f"CHF {abs(v):,.0f}".replace(",", "'")

    def row(i) -> str:
        where = ", ".join(f"{e.doc_label}, S. {e.page}" for e in i.evidence)
        note = f' <span class="where">{html.escape(i.note)}</span>' if i.note else ""
        return (f"<tr><td>{html.escape(i.label)}{note}</td><td class=\"opt\">{html.escape(where)}</td>"
                f'<td class="num">{chf(i.amount)}</td></tr>')

    rows = [row(i) for i in nd.items if i.kind == FINANZ]
    rows.append(f'<tr class="sum"><td>Nettoverschuldung laut Bilanz {nd.year}</td><td class="opt"></td>'
                f'<td class="num">{chf(nd.net_debt)}</td></tr>')
    similar = [i for i in nd.items if i.kind == AEHNLICH]
    if similar:
        rows += [row(i) for i in similar]
        rows.append(f'<tr class="sum"><td>Inklusive schuldenähnlicher Posten</td><td class="opt"></td>'
                    f'<td class="num">{chf(nd.adjusted)}</td></tr>')
    contingent = [i for i in nd.items if i.kind == EVENTUAL]
    if contingent:
        rows.append('<tr><td colspan="3" class="where">Eventualverbindlichkeiten, nicht in der Summe: '
                    "im SPA mit Freistellung oder Rückbehalt regeln</td></tr>")
        rows += [row(i) for i in contingent]
    covenant = ""
    if nd.covenant:
        c = nd.covenant
        covenant = (f" Covenant im Kreditvertrag: höchstens {c.limit}x EBITDA, nachgerechnet {c.ratio}x "
                    f"({'eingehalten' if c.ok else 'verletzt'}).")
    return (f'<h2 id="nettoverschuldung">Nettoverschuldung</h2><p class="lead">Vom Unternehmenswert zum Preis der Aktien: '
            f"Finanzschulden und flüssige Mittel aus der Bilanz, dazu schuldenähnliche Posten aus dem Datenraum, "
            f"über die im SPA verhandelt wird.{html.escape(covenant)}</p>"
            f'<div class="tablebox"><table><thead><tr><th>Posten</th><th class="opt">Fundstelle</th><th>Betrag</th>'
            f'</tr></thead><tbody>{"".join(rows)}</tbody></table></div>')


def _closing_html(run: Run) -> str:
    from .terms import _n, revenue_at_risk

    if not run.closing:
        return ""
    by_doc: dict[int, list] = {}
    for i in run.closing:
        by_doc.setdefault(id(i.terms), []).append(i)
    rows = []
    for items in by_doc.values():
        t = items[0].terms
        todo = "".join(f'<p class="todo"><span class="pill s-{"abweichung" if i.kind == "kontrollwechsel" else "ohne_beleg"}">'
                       f'{"Kontrollwechsel" if i.kind == "kontrollwechsel" else "Laufzeit"}</span> {html.escape(i.text)}</p>'
                       for i in items)
        volume = f"CHF {_n(t.volume)}" if t.volume else "–"
        rows.append(f'<tr><td class="nw">{html.escape(t.doc.label)}</td><td class="opt">{html.escape(t.doc.title)}</td>'
                    f'<td>{todo}</td><td class="num">{volume}</td></tr>')
    coc = {id(i.terms) for i in run.closing if i.kind == "kontrollwechsel"}
    risk = revenue_at_risk(run.closing)
    lead = f"{len(coc)} Verträge mit Kontrollwechselklausel"
    if risk:
        lead += f", zusammen CHF {_n(risk)} jährliches Volumen"
        if run.revenue:
            lead += f" ({risk / run.revenue[1] * 100:.0f} % des Umsatzes {run.revenue[0]})"
    ending = sum(1 for i in run.closing if i.kind == "laufzeit")
    lead += f". {ending} Verträge sind abgelaufen oder enden in den nächsten 18 Monaten." if ending else "."
    return (f'<h2 id="closing">Closing-Liste</h2><p class="lead">{html.escape(lead)} Was vor Signing und Closing mit den '
            "Gegenparteien zu klären ist, mit Seite im Vertrag.</p>"
            '<div class="tablebox"><table><thead><tr><th>Index</th><th class="opt">Vertrag</th><th>Zu klären</th>'
            f'<th>Volumen p.a.</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>' + _exit_html(run))


def _questions(run: Run):
    from .questions import request_list

    return request_list(run)


def _questions_html(run: Run) -> str:
    questions = _questions(run)
    if not questions:
        return ""
    rows = "".join(f'<tr><td class="nw">{q.number}</td><td class="opt">{html.escape(q.area)}</td>'
                   f'<td><span class="pill s-{"abweichung" if q.priority == "hoch" else "ohne_beleg"}">{q.priority}</span></td>'
                   f'<td>{html.escape(q.text)}</td><td class="opt">{html.escape(q.reference)}</td></tr>' for q in questions)
    high = sum(1 for q in questions if q.priority == "hoch")
    return (f'<h2 id="fragen">Fragenliste an den Verkäufer</h2><p class="lead">{len(questions)} Fragen, davon {high} mit '
            "hoher Priorität, aus den Befunden oben. Nur was der Verkäufer klären kann; als Tabelle auch in der "
            "Excel-Mappe und mit <code>--fragen</code> als Markdown.</p>"
            '<div class="tablebox"><table><thead><tr><th>Nr</th><th class="opt">Bereich</th><th>Priorität</th>'
            f'<th>Frage</th><th class="opt">Bezug</th></tr></thead><tbody>{rows}</tbody></table></div>')


def _exit_html(run: Run) -> str:
    from .terms import _n, exit_profile

    profile = exit_profile(run.terms, run.created.date())
    if not profile:
        return ""
    rows = []
    for year, volume, terms in profile:
        share = f"{volume / run.revenue[1] * 100:.0f} %" if run.revenue and run.revenue[1] else "–"
        names = ", ".join(f'<span title="{html.escape(t.doc.title)}">{html.escape(t.doc.label)}</span>' for t in terms)
        rows.append(f'<tr><td>bis Ende {year}</td><td class="num">CHF {_n(volume)}</td><td class="num">{share}</td>'
                    f"<td>{names}</td></tr>")
    return ('<p class="lead" style="margin-top:22px">Frühester ordentlicher Ausstieg der Kunden: Wird heute gekündigt, '
            "kann so viel Jahresvolumen bis zu diesem Datum wegfallen (Laufzeit, Kündigungsfrist und -termin aus dem "
            "Vertrag).</p>"
            '<div class="tablebox"><table><thead><tr><th>Frühestens weg</th><th>Volumen p.a.</th><th>Anteil Umsatz</th>'
            f'<th>Verträge</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>')


def _contracts_html(run: Run) -> str:
    from .clauses import KINDS, LABELS

    entries = [e for e in run.contracts if e.clauses]
    if not entries:
        return ""
    kinds = [k for k, *_ in KINDS if any(c.kind == k for e in entries for c in e.clauses)]
    rows = []
    for e in entries:
        cells = []
        for k in kinds:
            state = e.has(k)
            found = [c for c in e.clauses if c.kind == k and c.present is bool(state)]
            if state:
                c = found[0]
                cells.append(f'<td><span class="pill s-ohne_beleg" title="{html.escape(c.sentence)}">ja</span> '
                             f'<span class="where">S. {c.page}</span></td>')
            elif state is False:
                cells.append(f'<td><span class="where" title="{html.escape(found[0].sentence)}">ausgeschlossen</span></td>')
            else:
                cells.append('<td><span class="where">–</span></td>')
        t = next((t for t in run.terms if t.entry is e), None)
        end = f"{t.end:%d.%m.%Y}" if t and t.end else "–"
        notice = t.notice_text() if t and t.notice else "–"
        rows.append(f"<tr><td>{html.escape(e.doc.label)}</td><td class=\"opt\">{html.escape(e.doc.title)}</td>"
                    f"<td>{end}</td><td>{notice}</td>{''.join(cells)}</tr>")
    coc = [e for e in entries if e.has("kontrollwechsel")]
    lead = (f"{len(coc)} von {len(entries)} Verträgen erlauben der Gegenpartei bei einem Kontrollwechsel die Kündigung "
            "oder verlangen ihre Zustimmung: " + ", ".join(e.doc.label for e in coc) + "." if coc
            else f"Keiner der {len(entries)} Verträge enthält eine Kontrollwechselklausel.")
    head = "".join(f"<th>{html.escape(LABELS[k])}</th>" for k in kinds)
    return (f'<h2 id="vertraege">Vertragsregister</h2><p class="lead">{html.escape(lead)} Gefunden per Wortsuche mit Seite; '
            "der Satz erscheint beim Darüberfahren.</p>"
            f'<div class="tablebox"><table><thead><tr><th>Index</th><th class="opt">Dokument</th><th>Ende</th><th>Kündigung</th>{head}</tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')


def _internal_html(run: Run) -> str:
    if not run.internal:
        return ""
    cards = []
    for c in run.internal:
        rows = "".join(
            f'<tr><td>{_pill(f)}</td>'
            f'<td>{html.escape(f.claim.clean_text)}</td></tr>' for f in c.findings)
        cards.append(
            f'<article class="card s-widerspruch"><header><span class="badge">≠ im Bericht</span>'
            f'<span class="num">{html.escape(c.title)}: {html.escape(" vs. ".join(c.values))}</span></header>'
            f'<div class="tablebox flat"><table><thead><tr><th>Aussage</th><th>Text</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></div></article>')
    return ('<h2 id="bericht-widersprueche">Widersprüche im Bericht</h2><p class="lead">Der Bericht nennt für dieselbe Grösse und Periode '
            "an verschiedenen Stellen verschiedene Werte. Gerundete Schreibweisen zählen als gleich.</p>" + "".join(cards))


def _flags_html(run: Run) -> str:
    if not run.flags:
        return ""
    style = {"warnung": ("abweichung", "!"), "hinweis": ("ohne_beleg", "i"), "ok": ("geprueft", "✓")}
    cards = []
    for fl in run.flags:
        cls, sym = style[fl.level]
        quotes = "".join(
            f'<blockquote><span class="where">{html.escape(e.doc_label)}, S. {e.page}</span> '
            f'{html.escape(e.before)}<mark>{html.escape(e.match)}</mark>{html.escape(e.after)}</blockquote>'
            for e in fl.evidence[:2]
        ) if fl.level != "ok" else ""
        cards.append(f'<article class="card s-{cls}"><header><span class="badge">{sym} {html.escape(fl.area)}</span>'
                     f'<span class="num">{html.escape(fl.title)}</span></header>'
                     f'<p class="cite">{html.escape(fl.text)}</p>{quotes}</article>')
    n = sum(f.level == "warnung" for f in run.flags)
    lead = f"{n} Warnsignal{'e' if n != 1 else ''}. " if n else "Keine Warnsignale. "
    return (f'<h2 id="pruefungen">Prüfungen im Datenraum</h2><p class="lead">{lead}Erfolgsrechnungen nachgerechnet, '
            "Zeichnungsberechtigung gegen das Handelsregister, Kapitalschutz (Art. 725a OR), Revisionspflicht "
            "(Art. 727 OR), Vorsorge, Aktienbuch, Fusionskontrolle (Art. 9 KG), Covenants und Themen aus den "
            "Protokollen, die der Bericht nicht erwähnt.</p>" + "".join(cards))


def _gaps_html(run: Run) -> str:
    if not run.gaps:
        return ""
    rows = []
    for g in run.gaps:
        if g.present:
            docs = ", ".join(d.label for d in g.documents[:4]) + (" …" if len(g.documents) > 4 else "")
            state = f'<span class="pill s-geprueft">vorhanden</span> <span class="where">{html.escape(docs)}</span>'
            if g.note:
                state += f' <span class="warn">{html.escape(g.note)}</span>'
        else:
            state = '<span class="pill s-ohne_beleg">fehlt</span>'
        rows.append(f"<tr><td>{html.escape(g.area)}</td><td>{html.escape(g.name)}</td><td>{state}</td></tr>")
    missing = sum(not g.present for g in run.gaps)
    lead = (f"{missing} von {len(run.gaps)} üblichen Unterlagen fehlen im Datenraum." if missing
            else "Alle üblichen Unterlagen sind im Datenraum vorhanden.")
    return (f'<h2 id="unterlagen">Erwartete Unterlagen</h2><p class="lead">{lead} Die Liste ist allgemein; '
            "ob eine Unterlage für diesen Deal nötig ist, entscheidet das Team.</p>"
            f'<div class="tablebox"><table><thead><tr><th>Bereich</th><th>Unterlage</th><th>Im Datenraum</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')


def to_html(run: Run) -> str:
    counts = run.counts()
    total = len(run.findings)
    problems = total - counts[Status.GEPRUEFT] - counts[Status.UNGEPRUEFT]
    headline = (
        f"{problems} von {total} Aussagen brauchen eine Korrektur oder Klärung."
        if problems
        else f"Alle {total} prüfbaren Aussagen stimmen mit dem Datenraum überein."
    )
    chips = "".join(
        f'<button class="chip s-{s.value}" data-filter="{s.value}">'
        f'<b>{n}</b> {s.label}</button>'
        for s, n in counts.items()
        if n
    )
    protocol = "\n".join(_protocol_line(f) for f in run.findings)
    colors = {Status.GEPRUEFT: "var(--green)", Status.ABWEICHUNG: "var(--red)", Status.QUELLE_FEHLT: "var(--red)",
              Status.WIDERSPRUCH: "var(--amber)",
              Status.FALSCHE_FUNDSTELLE: "var(--amber)", Status.OHNE_BELEG: "var(--amber)", Status.UNGEPRUEFT: "var(--gray-bg)"}
    stops, acc = [], 0
    for st in [Status.GEPRUEFT] + [x for x in ORDER if x is not Status.GEPRUEFT]:
        if counts[st]:
            start, acc = acc, acc + counts[st]
            stops.append(f"{colors[st]} {start / total * 360:.1f}deg {acc / total * 360:.1f}deg")
    donut = ", ".join(stops) or "var(--gray-bg) 0deg 360deg"
    ok_share = f"{counts[Status.GEPRUEFT] / total:.0%}" if total else "–"
    cards = "\n".join(_card(f, run) for f in sorted(run.findings, key=lambda f: (ORDER.index(f.status), f.claim.number)))
    docs = "".join(
        f"<tr><td>{html.escape(d.label)}</td><td>{html.escape(d.title)}</td><td>{len(d.pages)}</td>"
        f'<td class="hash">{d.sha256[:16]}…</td></tr>'
        for d in run.room.documents
    )
    extra = _versions_html(run) + _flags_html(run) + _internal_html(run) + _conflicts_html(run) + _addbacks_html(run) + _valuation_html(run) + _netdebt_html(run) + _closing_html(run) + _contracts_html(run) + _questions_html(run)
    gaps = _gaps_html(run)
    warnings = "".join(f"<li>{html.escape(w)}</li>" for w in run.room.warnings)
    warnings_html = f'<ul class="warn">{warnings}</ul>' if warnings else ""
    model = html.escape(run.model) if run.model else "aus (nur Regeln)"
    stamp = run.created.strftime("%d.%m.%Y, %H:%M")
    return TEMPLATE.format(
        fonts=_font_faces(),
        donut=donut,
        keypoints=_keypoints_html(run),
        ok_share=ok_share.replace("%", "&nbsp;%"),
        csv=base64.b64encode(to_csv(run).encode("utf-8")).decode(),
        rows=json.dumps({"columns": CSV_COLUMNS, "rows": _rows(run),
                         "carried": {str(k): {"v": d.get("v", ""), "n": d.get("n", "")} for k, d in run.decisions.items()}},
                        ensure_ascii=False).replace("</", "<\\/"),
        key=html.escape(run.report_sha256 + "-" + run.created.isoformat(timespec="seconds")),
        csv_name=html.escape(run.report_name.rsplit(".", 1)[0] + "-pruefbericht.csv"),
        title=html.escape(run.report_name),
        logo=logo_svg(),
        report=html.escape(run.report_name),
        stamp=stamp,
        model=model,
        headline=headline,
        total=total,
        docs_count=len(run.room.documents),
        chips=chips,
        protocol=protocol,
        cards=cards,
        extra=extra,
        gaps=gaps,
        disclosure=base64.b64encode(to_disclosure_csv(run).encode("utf-8")).decode(),
        disclosure_name=html.escape(run.report_name.rsplit(".", 1)[0] + "-offenlegungskarte.csv"),
        xlsx=base64.b64encode(_xlsx(run)).decode(),
        xlsx_name=html.escape(run.report_name.rsplit(".", 1)[0] + "-pruefung.xlsx"),
        docs=docs,
        warnings=warnings_html,
        report_hash=run.report_sha256[:16],
        version=__version__,
    )


TEMPLATE = """<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Prüfbericht · {title}</title>
<style>
{fonts}
:root {{
  --ink:#15202B; --ink-2:#4A5560; --ink-3:#7D8790; --page:#F7F8F6; --card:#FFFFFF;
  --line:rgba(21,32,43,.09); --line-2:rgba(21,32,43,.16);
  --green:#1E7A50; --green-bg:#DCEDE3; --red:#B42318; --red-bg:#F6E1DE;
  --amber:#9A5B00; --amber-bg:#F3E8D2; --gray:#5B6670; --gray-bg:#E7EAEC; --mark:#DCEDE3; --mark-claim:#ECE7DE;
  --mono: ui-monospace, "SF Mono", "JetBrains Mono", Menlo, Consolas, monospace;
  --sans: "Familjen Grotesk", ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  --display: "Familjen Grotesk", ui-sans-serif, system-ui, sans-serif;
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    --ink:#EEF2F0; --ink-2:#A9B4BD; --ink-3:#7D8A95; --page:#121A22; --card:#18222C;
    --line:rgba(238,242,240,.09); --line-2:rgba(238,242,240,.16);
    --green:#4CC38A; --green-bg:#16352A; --red:#F07A6E; --red-bg:#3A1F1E;
    --amber:#E8B04B; --amber-bg:#3A2E16; --gray:#A9B4BD; --gray-bg:#24303A; --mark:#1E4A36; --mark-claim:#2A3540;
  }}
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--page); color:var(--ink); font:15px/1.6 var(--sans); -webkit-font-smoothing:antialiased; }}
main {{ max-width:1040px; margin:0 auto; padding:36px 20px 80px; }}
.top {{ display:flex; align-items:center; justify-content:space-between; gap:16px; flex-wrap:wrap; }}
.logo {{ height:26px; width:auto; }}
.meta {{ font-size:13px; line-height:1.5; color:var(--ink-3); text-align:right; }}
.kicker {{ font-size:12px; font-weight:700; letter-spacing:.16em; text-transform:uppercase; color:var(--ink-2); margin:0 0 10px; }}
.summary {{ display:grid; grid-template-columns:minmax(0,1fr) auto; gap:32px; align-items:center; margin:64px 0 28px; }}
h1 {{ font:500 clamp(30px, 4.4vw, 48px)/1.08 var(--display); letter-spacing:-.035em; margin:0 0 12px; }}
.sub {{ color:var(--ink-2); margin:0; }}
.donut {{ width:132px; height:132px; border-radius:50%; background:conic-gradient({donut}); display:grid; place-items:center; }}
.donut span {{ width:96px; height:96px; border-radius:50%; background:var(--page); display:grid; place-items:center; text-align:center;
  font:500 24px/1 var(--display); }}
.donut small {{ display:block; font:12px var(--sans); color:var(--ink-3); margin-top:4px; }}
.chips {{ display:flex; flex-wrap:wrap; gap:8px; margin:0 0 18px; }}
.chip {{ font:500 13px var(--sans); border:0; background:var(--cbg); color:var(--c); border-radius:999px; padding:7px 14px; cursor:pointer; }}
.chip b {{ font-variant-numeric:tabular-nums; }}
.chip.on {{ box-shadow:0 0 0 2px var(--c); }}
.review {{ display:flex; flex-wrap:wrap; align-items:center; gap:10px 18px; background:var(--card); border-radius:20px;
  box-shadow:0 0 0 1px var(--line); padding:14px 20px; margin:0 0 18px; font-size:14px; }}
.review input {{ font:14px var(--sans); color:var(--ink); background:var(--page); border:1px solid var(--line-2); border-radius:999px; padding:7px 14px; min-width:0; }}
.review .bar {{ flex:1 1 160px; height:4px; background:var(--gray-bg); border-radius:2px; overflow:hidden; }}
.review .bar i {{ display:block; height:100%; width:0; background:var(--green); transition:width .2s; }}
.review a {{ background:var(--ink); color:var(--page); text-decoration:none; border-radius:999px; padding:9px 18px; font-weight:500; }}
.proto {{ background:var(--card); border-radius:24px; box-shadow:0 0 0 1px var(--line); padding:10px 0; overflow:hidden; }}
.proto .head {{ display:flex; justify-content:space-between; padding:10px 22px 12px; border-bottom:1px solid var(--line); }}
.proto .head .kicker {{ margin:0; }}
.proto .head span:last-child {{ font-size:13px; color:var(--ink-3); }}
.pl {{ display:grid; grid-template-columns:30px 1fr auto auto; gap:14px; align-items:center; padding:9px 22px; color:inherit; text-decoration:none;
  border-bottom:1px solid var(--line); font-size:14px; }}
.pl:last-child {{ border-bottom:0; }}
.pl:hover {{ background:var(--page); }}
.pl .sym {{ display:none; }}
.pl .nr {{ width:26px; height:26px; border-radius:50%; border:1px solid var(--c); color:var(--c); display:grid; place-items:center; font-size:11px; }}
.pl .txt {{ white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
.pl .where {{ color:var(--ink-3); font-size:13px; white-space:nowrap; }}
.pl .st {{ font-size:12px; font-weight:500; color:var(--c); background:var(--cbg); border-radius:999px; padding:3px 10px; white-space:nowrap; text-transform:none; }}
h2 {{ font:500 30px/1.2 var(--display); letter-spacing:-.025em; margin:64px 0 18px; }}
.card {{ background:var(--card); border-radius:24px; box-shadow:0 0 0 1px var(--line); padding:22px 24px; margin:0 0 14px; }}
.card header {{ display:flex; flex-wrap:wrap; align-items:center; gap:10px; font-size:13px; color:var(--ink-3); }}
.badge {{ font-weight:500; color:var(--c); background:var(--cbg); border-radius:999px; padding:4px 12px; }}
.method {{ margin-left:auto; }}
.sec {{ }}
.keys {{ background:var(--card); border-radius:24px; box-shadow:0 0 0 1px var(--line); padding:20px 24px 8px; margin:18px 0 0; }}
.keys ul {{ list-style:none; margin:10px 0 0; padding:0; }}
.keys li {{ padding:12px 0; border-top:1px solid var(--line); }}
.keys li a {{ display:flex; flex-wrap:wrap; gap:10px; align-items:center; color:inherit; text-decoration:none; }}
.keys li b {{ font-weight:500; }}
.keys li p {{ margin:6px 0 0; color:var(--ink-2); font-size:14px; }}
.todo {{ margin:4px 0; font-size:14px; }}
td.nw {{ white-space:nowrap; }}
.tag {{ font-size:12px; font-weight:500; color:var(--ink-2); box-shadow:0 0 0 1px var(--line); border-radius:999px; padding:3px 10px; }}
.diff del {{ color:var(--red); text-decoration:line-through; }}
.diff ins {{ color:var(--green); background:var(--green-bg); text-decoration:none; border-radius:4px; padding:0 2px; }}
.claim {{ font:400 19px/1.5 var(--display); margin:14px 0 6px; }}
.claim mark, blockquote mark {{ background:var(--mark); color:inherit; border-radius:4px; padding:0 3px; }}
.claim mark {{ background:var(--mark-claim); }}
.cite {{ font-size:13px; color:var(--ink-3); margin:0 0 10px; }}
.reasons {{ margin:0 0 10px; padding-left:18px; color:var(--ink-2); }}
.ev {{ margin:10px 0 0; }}
.ev figcaption {{ font-size:12px; color:var(--ink-3); }}
.ev .file {{ opacity:.8; }}
blockquote {{ margin:6px 0 0; padding:12px 16px; background:var(--page); border-radius:14px; font-size:14px; color:var(--ink-2); }}
.s-geprueft {{ --c:var(--green); --cbg:var(--green-bg); }}
.s-abweichung, .s-quelle_fehlt {{ --c:var(--red); --cbg:var(--red-bg); }}
.s-widerspruch, .s-falsche_fundstelle, .s-ohne_beleg {{ --c:var(--amber); --cbg:var(--amber-bg); }}
.s-ungeprueft {{ --c:var(--gray); --cbg:var(--gray-bg); }}
.tablebox {{ background:var(--card); border-radius:24px; box-shadow:0 0 0 1px var(--line); padding:6px 14px; overflow-x:auto; }}
table {{ width:100%; border-collapse:collapse; font-size:14px; }}
td, th {{ text-align:left; padding:10px 8px; border-bottom:1px solid var(--line); }}
tr:last-child td {{ border-bottom:0; }}
th {{ font-size:12px; font-weight:700; letter-spacing:.12em; text-transform:uppercase; color:var(--ink-3); }}
.hash {{ font:12px var(--mono); color:var(--ink-3); }}
.lead {{ color:var(--ink-2); margin:-6px 0 18px; max-width:720px; }}
.tablebox.flat {{ box-shadow:none; padding:0; margin-top:10px; border-radius:0; background:transparent; }}
td.num, th.num {{ text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }}
tr.sum td {{ font-weight:700; }}
.pill {{ display:inline-block; font-size:12px; font-weight:500; color:var(--c); background:var(--cbg); border-radius:999px;
  padding:2px 10px; text-decoration:none; white-space:nowrap; }}
.pills {{ display:flex; flex-wrap:wrap; gap:6px; align-items:center; font-size:13px; color:var(--ink-3); margin:12px 0 0; }}
.where {{ color:var(--ink-3); font-size:13px; }}
td .m {{ display:none; }}
@media (max-width:640px) {{
  .tablebox.flat .opt {{ display:none; }}
  td .m {{ display:block; margin-top:4px; }}
}}
.review a.ghost {{ background:transparent; color:var(--ink); box-shadow:inset 0 0 0 1px var(--line-2); }}
.warn {{ color:var(--amber); font-size:13px; }}
.note {{ font-size:13px; color:var(--ink-3); margin-top:40px; }}
.decide {{ display:flex; flex-wrap:wrap; align-items:center; gap:8px; margin-top:16px; padding-top:14px; border-top:1px solid var(--line); }}
.decide .q {{ font-size:13px; color:var(--ink-3); margin-right:4px; }}
.decide button {{ font:500 13px var(--sans); border:1px solid var(--line-2); background:transparent; color:var(--ink);
  border-radius:999px; padding:6px 16px; cursor:pointer; }}
.decide button.on[data-d=ok] {{ background:var(--green); border-color:var(--green); color:var(--card); }}
.decide button.on[data-d=nein] {{ background:var(--ink); border-color:var(--ink); color:var(--card); }}
.decide input {{ flex:1 1 200px; min-width:0; font:13px var(--sans); color:var(--ink); background:var(--page);
  border:1px solid var(--line-2); border-radius:999px; padding:7px 14px; }}
.card.done {{ opacity:.7; }}
@media (max-width:640px) {{
  .summary {{ grid-template-columns:minmax(0,1fr); margin-top:40px; }}
  .donut {{ width:104px; height:104px; }} .donut span {{ width:76px; height:76px; font-size:24px; }}
  .hash {{ display:none; }} .pl {{ grid-template-columns:30px 1fr auto; }} .pl .where {{ display:none; }}
}}
@media print {{ .chips, .review a, .decide button:not(.on) {{ display:none; }} .card {{ break-inside:avoid; }} }}
</style>
</head>
<body>
<main>
  <div class="top">{logo}
    <div class="meta">Prüfbericht · {stamp}<br>Prüfmodell: {model}</div>
  </div>
  <div class="summary">
    <div><p class="kicker">Prüfbericht</p><h1>{headline}</h1>
    <p class="sub">{report} · {total} Aussagen gegen {docs_count} Dokumente im Datenraum geprüft.</p></div>
    <div class="donut" aria-hidden="true"><span>{ok_share}<small>geprüft</small></span></div>
  </div>
  <div class="chips">{chips}</div>
  {keypoints}
  <div class="review" id="review">
    <label>Durchgesehen von <input type="text" id="reviewer" placeholder="Name" autocomplete="name"></label>
    <span id="progress">0 von {total} entschieden</span><span class="bar"><i id="bar"></i></span>
    <a id="export" href="data:text/csv;charset=utf-8;base64,{csv}" download="{csv_name}">Protokoll exportieren</a>
    <a class="ghost" href="data:text/csv;charset=utf-8;base64,{disclosure}" download="{disclosure_name}"
      title="Welche Aussage auf welcher Seite steht, mit Prüfsumme je Dokument: für W&amp;I-Underwriting">Offenlegungskarte</a>
    <a class="ghost" href="data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,{xlsx}"
      download="{xlsx_name}" title="Aussagen, EBITDA-Brücke, Nettoverschuldung und Closing-Liste mit Formeln">Excel-Mappe</a>
  </div>
  <section class="proto" aria-label="Prüfprotokoll">
    <div class="head"><p class="kicker">Prüfprotokoll</p><span>{report}</span></div>
    {protocol}
  </section>
  {extra}
  <h2>Aussagen im Detail</h2>
  {cards}
  <h2>Datenraum</h2>
  <div class="tablebox"><table><thead><tr><th>Index</th><th>Dokument</th><th>Seiten</th><th class="hash">SHA-256</th></tr></thead>
  <tbody>{docs}</tbody></table></div>
  {warnings}
  {gaps}
  <p class="note">„Geprüft“ heisst: Jeder Betrag, jedes Datum, jeder Prozentsatz, jede Frist und jede UID der Aussage
  steht auf der zitierten Seite. Den Sinn einer Aussage bestätigt nur das Prüfmodell, und nur mit einem Zitat,
  das wörtlich in der Quelle steht. Bericht SHA-256 {report_hash}… · Zitatio {version}</p>
</main>
<script type="application/json" id="rows">{rows}</script>
<script>
document.querySelectorAll('.chip').forEach(function (chip) {{
  chip.addEventListener('click', function () {{
    var on = !chip.classList.contains('on');
    document.querySelectorAll('.chip').forEach(function (c) {{ c.classList.remove('on'); }});
    if (on) chip.classList.add('on');
    document.querySelectorAll('.card').forEach(function (card) {{
      card.hidden = on && card.dataset.status !== chip.dataset.filter;
    }});
  }});
}});

// Menschliche Durchsicht: Entscheide bleiben in diesem Browser gespeichert und gehen ins CSV.
(function () {{
  var KEY = 'zitatio:{key}', data = JSON.parse(document.getElementById('rows').textContent);
  var state = {{ reviewer: '', d: {{}} }};
  try {{ state = JSON.parse(localStorage.getItem(KEY)) || state; }} catch (e) {{}}
  Object.keys(data.carried || {{}}).forEach(function (nr) {{ if (!state.d[nr]) state.d[nr] = data.carried[nr]; }});
  var who = document.getElementById('reviewer'), link = document.getElementById('export');
  function save() {{ try {{ localStorage.setItem(KEY, JSON.stringify(state)); }} catch (e) {{}} }}
  function cell(v) {{ v = String(v == null ? '' : v); return /[;"\\r\\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v; }}
  function refresh() {{
    var done = 0;
    document.querySelectorAll('.decide').forEach(function (box) {{
      var d = state.d[box.dataset.nr] || {{}};
      box.querySelectorAll('button').forEach(function (b) {{ b.classList.toggle('on', b.dataset.d === d.v); }});
      box.closest('.card').classList.toggle('done', !!d.v);
      if (d.v) done++;
    }});
    var total = data.rows.length;
    document.getElementById('progress').textContent = done + ' von ' + total + ' entschieden';
    document.getElementById('bar').style.width = (100 * done / total) + '%';
    var labels = {{ ok: 'Zugestimmt', nein: 'Widersprochen' }};
    var lines = [data.columns].concat(data.rows.map(function (r) {{
      var d = state.d[r[0]] || {{}};
      return r.slice(0, -3).concat([labels[d.v] || '', d.n || '', d.v || d.n ? state.reviewer : '']);
    }}));
    var csv = '\\ufeff' + lines.map(function (r) {{ return r.map(cell).join(';'); }}).join('\\r\\n') + '\\r\\n';
    link.href = 'data:text/csv;charset=utf-8,' + encodeURIComponent(csv);
  }}
  who.value = state.reviewer || '';
  who.addEventListener('input', function () {{ state.reviewer = who.value; save(); refresh(); }});
  document.querySelectorAll('.decide').forEach(function (box) {{
    var nr = box.dataset.nr, note = box.querySelector('input');
    note.value = (state.d[nr] || {{}}).n || '';
    box.querySelectorAll('button').forEach(function (b) {{
      b.addEventListener('click', function () {{
        var d = state.d[nr] = state.d[nr] || {{}};
        d.v = d.v === b.dataset.d ? '' : b.dataset.d;
        save(); refresh();
      }});
    }});
    note.addEventListener('input', function () {{ (state.d[nr] = state.d[nr] || {{}}).n = note.value; save(); refresh(); }});
  }});
  refresh();
}})();
</script>
</body>
</html>
"""
