"""Klauselvorschläge für den Kaufvertrag aus den Befunden.

Was der Käufer verlangen kann, steht bei jeder Garantie (spa.py). Hier wird daraus ein Entwurf in der Sprache
eines Schweizer Aktienkaufvertrags: Vollzugsbedingungen für die Zustimmungen zum Kontrollwechsel, spezifische
Freistellungen für bekannte Risiken, Abzüge in der Kaufpreisformel, die Klausel zur indirekten Teilliquidation
und die Liste der Unterlagen, die vor dem Signing fehlen. Ein Entwurf für die Anwältin oder den Anwalt, kein
fertiger Vertragstext.

Spezifische Freistellungen gelten in der Praxis unabhängig von der Offenlegung und ausserhalb von Freibetrag und
Haftungshöchstbetrag; sonst nützen sie bei einem bekannten Risiko nichts (Kenntnis des Käufers, Art. 200 OR).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .spa import BEDINGUNG, FREISTELLUNG, KLAEREN, NACHREICHEN, PREIS, TEILLIQUIDATION, collect_issues

_STREITWERT = re.compile(r"Streitwert (CHF [\d'’]+)")


@dataclass
class Draft:
    group: str  # Überschrift im Entwurf
    number: str  # vorgeschlagene Ziffer, "" wenn keine
    heading: str
    text: str
    basis: list[str] = field(default_factory=list)  # Befunde, aus denen der Vorschlag folgt


def _subject(title: str) -> str:
    """Befundtitel als Sachverhalt im Vertragstext."""
    title = re.sub(r"^(?:MWST|Protokolle|Leakage|Covenant|Vorsorge|Kapitalschutz): ", "", title)
    return title.rstrip(".")


_QUOTE = re.compile(r"«([^»]+)»")
_MINUTES_REF = re.compile(r"\((DR [\d.]+, S\. \d+)\)")


def _heading(issue) -> str:
    if m := re.match(r"Klage (DR [\d.]+)", issue.title):
        return f"Verfahren {m.group(1)}"
    return re.split(r" \(DR | im Bericht|: CHF", _subject(issue.title))[0][:60]


def _merge_minutes(issues: list, titles: dict) -> list:
    """Ein Protokolleintrag zum selben Verfahren wie eine Klage im Datenraum braucht keine eigene Freistellung."""
    def names(issue) -> set[str]:
        refs = re.findall(r"DR [\d.]+", issue.title)
        return {w for r in refs for w in re.findall(r"[A-ZÄÖÜ][a-zäöü]{4,}", titles.get(r, "")) if w != "Klage"}

    others = [(i, names(i)) for i in issues if not _MINUTES_REF.search(i.title)]
    out = []
    for i in issues:
        quote = _QUOTE.search(i.text) if _MINUTES_REF.search(i.title) else None
        if quote and any(n and any(w in quote.group(1) for w in n) for _, n in others):
            continue
        out.append(i)
    return out


def _next_number(spa_text: str, chapter: str) -> callable:
    taken = [int(m.group(1)) for m in re.finditer(rf"^\s*{chapter}\.(\d+)\b", spa_text or "", re.MULTILINE)]
    counter = iter(range(max(taken, default=0) + 1, 1000))
    return lambda: f"{chapter}.{next(counter)}" if spa_text else ""


def _issues(run) -> list[tuple]:
    """(Issue, gedeckt durch Ziffer) ohne Doppel; mit SPA aus dem Abgleich, sonst aus allen Befunden."""
    seen, out = set(), []
    if run.warranties:
        for w in run.warranties:
            for i in w.issues:
                if i.title not in seen:
                    seen.add(i.title)
                    out.append((i, w.covered_by.get(id(i))))
    else:
        for i in collect_issues(run):
            if i.title not in seen:
                seen.add(i.title)
                out.append((i, None))
    return out


def drafts(run) -> list[Draft]:
    spa_text = getattr(run, "spa_text", "") or ""
    issues = _issues(run)
    out: list[Draft] = []

    cond = _next_number(spa_text, "4")
    consent = [i for i, _ in issues if i.action == BEDINGUNG and i.title.startswith("Vinkulierung")]
    coc = [i for i, _ in issues if i.action == BEDINGUNG and not i.title.startswith("Vinkulierung")]
    if coc:
        names = [re.sub(r"^Kontrollwechselklausel ", "", i.title) for i in coc]
        listing = "; ".join(f"({chr(97 + n)}) {name}" for n, name in enumerate(names))
        out.append(Draft("Vollzugsbedingungen", cond(), "Zustimmungen zum Kontrollwechsel",
                         "Die Pflicht der Käuferin zum Vollzug steht unter der Bedingung, dass die Gegenparteien der "
                         "folgenden Verträge schriftlich auf ihr Kündigungsrecht aus dem Kontrollwechsel verzichtet "
                         f"oder dem Kontrollwechsel zugestimmt haben: {listing}. Die Käuferin kann auf diese Bedingung "
                         "ganz oder teilweise verzichten.", [i.title for i in coc]))

    if consent:
        out.append(Draft("Vollzugsbedingungen", cond(), "Zustimmung des Verwaltungsrats",
                         "Der Verwaltungsrat der Gesellschaft hat der Übertragung der Aktien auf die Käuferin zugestimmt "
                         "und die Käuferin als Aktionärin mit Stimmrecht ins Aktienbuch eingetragen (Art. 685a ff. OR). "
                         "Die Verkäuferin stellt sicher, dass der Verwaltungsrat vor dem Vollzug darüber beschliesst.",
                         [i.title for i in consent]))

    number = _next_number(spa_text, "6")
    open_ = [i for i, covered in issues if i.action == FREISTELLUNG and not covered]
    titles = {d.label: d.title for d in run.room.documents if d.index}
    for i in _merge_minutes(open_, titles):
        subject = _subject(i.title)
        quote = _QUOTE.search(i.text)
        where = _MINUTES_REF.search(i.title)
        if quote and where:
            subject = f"«{quote.group(1).rstrip('.')}» ({where.group(1)})"
        elif m := re.match(r"Klage (DR [\d.]+), Streitwert (CHF [\d'’]+)", i.title):
            subject = f"der Klage gemäss {m.group(1)} ({titles.get(m.group(1), 'Klage')}, Streitwert {m.group(2)})"
        costs = "Steuern, Zinsen und Bussen" if "steuern" in i.topics else "Anwalts- und Verfahrenskosten"
        text = (f"Die Verkäuferin stellt die Käuferin und die Gesellschaft von allen Verlusten und Kosten "
                f"(einschliesslich {costs}) frei, die aus oder im Zusammenhang mit folgendem Sachverhalt entstehen: "
                f"{subject}. Diese Freistellung gilt unabhängig von einer Offenlegung oder Kenntnis der Käuferin und "
                "ohne Anrechnung an Freibetrag und Haftungshöchstbetrag.")
        amount = _STREITWERT.search(i.title)
        if amount:
            text += (f" Zur Sicherung werden vom Kaufpreis {amount.group(1)} bis zum rechtskräftigen Abschluss des "
                     "Verfahrens auf ein Sperrkonto (Escrow) bezahlt.")
        heading = _heading(i)
        out.append(Draft("Spezifische Freistellungen", number(), heading, text, [i.title]))

    debt = [i for i, _ in issues if i.action == PREIS and not i.title.startswith("Kaufpreis")]
    if debt:
        listing = "; ".join(i.title for i in debt)
        out.append(Draft("Kaufpreis", "", "Schuldenähnliche Posten",
                         "Als Finanzverbindlichkeiten im Sinne der Nettofinanzverbindlichkeiten gelten zusätzlich: "
                         f"{listing}. Sie werden vom Unternehmenswert abgezogen.", [i.title for i in debt]))

    if any(i.action == TEILLIQUIDATION for i, _ in issues):
        basis = [i.title for i, _ in issues if i.action == TEILLIQUIDATION]
        out.append(Draft("Steuern", number(), "Indirekte Teilliquidation",
                         "Die Käuferin verpflichtet sich, während fünf Jahren nach dem Vollzugstag keine Ausschüttung "
                         "von Substanz der Gesellschaft vorzunehmen oder zu veranlassen, die im Zeitpunkt des Verkaufs "
                         "bereits vorhanden und handelsrechtlich ausschüttungsfähig war (Art. 20a Abs. 1 lit. a DBG). "
                         "Verletzt sie diese Pflicht, stellt sie die Verkäufer von den daraus entstehenden Einkommens"
                         "steuern frei. Die Gesellschaft gilt nicht als Partei dieser Verpflichtung.", basis))

    missing = [re.sub(r"^(?:Verweise: )?(DR [\d.]+): (.+?) fehlt im Datenraum$", r"\2 zu \1",
                      i.title.removeprefix("Fehlt im Datenraum: ")) for i, _ in issues if i.action == NACHREICHEN]
    if missing:
        out.append(Draft("Vor dem Signing", "", "Nachzureichende Unterlagen",
                         "Die Verkäuferin stellt vor der Unterzeichnung folgende Unterlagen in den Datenraum: "
                         + "; ".join(missing) + ".", missing))

    clarify = [i for i, _ in issues if i.action == KLAEREN]
    if clarify:
        out.append(Draft("Offenlegung", "", "Garantien präzisieren",
                         "Zu klären und je nach Antwort in der betroffenen Garantie zu präzisieren oder ausdrücklich "
                         "von der Offenlegung auszunehmen: " + "; ".join(i.title for i in clarify) + ".",
                         [i.title for i in clarify]))
    return out


def to_markdown(items: list[Draft], spa_name: str | None = None) -> str:
    head = f"Klauselvorschläge zu {spa_name}" if spa_name else "Klauselvorschläge für den Kaufvertrag"
    lines = [f"# {head}", "", "_Entwurf aus den Befunden von Zitatio. Juristisch zu prüfen, kein fertiger Vertragstext._"]
    group = None
    for d in items:
        if d.group != group:
            group = d.group
            lines += ["", f"## {group}"]
        lines += ["", f"**{(d.number + ' ') if d.number else ''}{d.heading}**", "", d.text]
    return "\n".join(lines) + "\n"


def to_docx(items: list[Draft], spa_name: str | None = None) -> bytes:
    """Dieselben Vorschläge als Word-Datei, zum Einfügen in den Vertragsentwurf."""
    import io
    import zipfile
    from xml.sax.saxutils import escape

    def para(text: str, style: str | None = None, bold: bool = False, italic: bool = False) -> str:
        ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
        rpr = "<w:rPr>" + ("<w:b/>" if bold else "") + ("<w:i/>" if italic else "") + "</w:rPr>"
        return f'<w:p>{ppr}<w:r>{rpr}<w:t xml:space="preserve">{escape(text)}</w:t></w:r></w:p>'

    head = f"Klauselvorschläge zu {spa_name}" if spa_name else "Klauselvorschläge für den Kaufvertrag"
    body = [para(head, "Heading1"),
            para("Entwurf aus den Befunden von Zitatio. Juristisch zu prüfen, kein fertiger Vertragstext.", italic=True)]
    group = None
    for d in items:
        if d.group != group:
            group = d.group
            body.append(para(group, "Heading2"))
        body.append(para(f"{(d.number + ' ') if d.number else ''}{d.heading}", bold=True))
        body.append(para(d.text))
    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    document = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {ns}><w:body>{"".join(body)}'
                '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1417" w:right="1417" w:bottom="1134" '
                'w:left="1417" w:header="708" w:footer="708" w:gutter="0"/></w:sectPr></w:body></w:document>')

    def style(sid: str, name: str, size: int, bold: bool) -> str:
        return (f'<w:style w:type="paragraph" w:styleId="{sid}"><w:name w:val="{name}"/><w:basedOn w:val="Normal"/>'
                f'<w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:spacing w:before="240" w:after="120"/>'
                f'<w:outlineLvl w:val="{0 if sid == "Heading1" else 1}"/></w:pPr>'
                f'<w:rPr>{"<w:b/>" if bold else ""}<w:sz w:val="{size}"/></w:rPr></w:style>')

    styles = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:styles {ns}>'
              '<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/><w:sz w:val="22"/>'
              '<w:lang w:val="de-CH"/></w:rPr></w:rPrDefault><w:pPrDefault><w:pPr><w:spacing w:after="120"/></w:pPr>'
              '</w:pPrDefault></w:docDefaults>'
              '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>'
              + style("Heading1", "heading 1", 32, True) + style("Heading2", "heading 2", 26, True) + "</w:styles>")
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    files = {
        "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>',
        "_rels/.rels": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'<Relationship Id="rId1" Type="{rel}/officeDocument" Target="word/document.xml"/></Relationships>',
        "word/_rels/document.xml.rels": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'<Relationship Id="rId1" Type="{rel}/styles" Target="styles.xml"/></Relationships>',
        "word/document.xml": document,
        "word/styles.xml": styles,
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in files.items():
            z.writestr(name, content)
    return buf.getvalue()
