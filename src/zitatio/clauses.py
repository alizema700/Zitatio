"""Vertragsregister: Welche Verträge enthalten Kontrollwechsel, Exklusivität, Konkurrenzverbot & Co.?

Käufer fragen bei jedem Deal dasselbe: Welche Verträge darf die Gegenseite beim Closing kündigen,
welche binden das Unternehmen exklusiv, wo drohen Strafen? Zitatio liest jede Klausel mit Seite und
Satz aus dem Datenraum und prüft Aussagen des Berichts dagegen ("enthält keine Change-of-Control-Klausel").

Die Erkennung arbeitet mit Wortmustern und einer Verneinungsregel, nicht mit einem Modell: Ein Satz wie
"Ein Kontrollwechsel berührt den Bestand dieses Vertrags nicht" zählt als ausdrücklich keine Klausel.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .dataroom import DataRoom, Document

# (Schlüssel, Bezeichnung, Muster, Bedeutung für den Deal)
KINDS: list[tuple[str, str, re.Pattern, str]] = [
    (key, label, re.compile(rx, re.IGNORECASE), why)
    for key, label, rx, why in [
        ("kontrollwechsel", "Kontrollwechsel",
         r"kontrollwechsel\w*|change[- ]of[- ]control|wechsel (?:der|in der) (?:kontrolle|beherrschung|mehrheit)"
         r"|übernahme der (?:aktien)?mehrheit|changement de contrôle|cambiamento di controllo|cambio di controllo",
         "Gegenpartei kann beim Closing kündigen oder zustimmen müssen"),
        ("exklusivitaet", "Exklusivität",
         r"\bexklusiv\w*|alleinvertrieb\w*|alleinbezug\w*|ausschliesslich\w* (?:bei|von|über) (?:der|dem)\b"
         r"|\bexclusivit[ée]\w*|\bà titre exclusif|\besclusiv\w*",
         "bindet das Unternehmen an eine Partei"),
        ("konkurrenzverbot", "Konkurrenzverbot",
         r"konkurrenzverbot\w*|wettbewerbsverbot\w*|non-?compete|abwerbeverbot\w*"
         r"|prohibition de concurrence|interdiction de concurrence|non-concurrence|divieto di concorrenza",
         "schränkt Geschäft oder Personen nach dem Deal ein"),
        ("konventionalstrafe", "Konventionalstrafe", r"konventionalstrafe\w*|vertragsstrafe\w*|pönale\w*|peine conventionnelle|pena convenzionale",
         "Zahlungsrisiko bei Verletzung"),
        ("abtretung", "Abtretung nur mit Zustimmung",
         r"(?:abtret\w*|übertrag\w*|cédé\w*|céder|cession|transf[ée]r\w*|ced\w*|cessione|trasfer\w*)[^.]{0,80}"
         r"(?:zustimmung|einwilligung|genehmigung|consentement|accord préalable|consenso)"
         r"|(?:zustimmung|einwilligung|consentement|consenso)[^.]{0,80}(?:abtret\w*|übertrag\w*|cession|céd\w*|cessione)",
         "Asset Deal oder Umstrukturierung braucht Zustimmung"),
        ("meistbeguenstigung", "Meistbegünstigung", r"meistbegünstig\w*|most[- ]favou?red|nation la plus favorisée|nazione più favorita", "begrenzt Preisgestaltung"),
        ("haftungsbegrenzung", "Haftungsbegrenzung", r"haftung\w*[^.]{0,60}(?:begrenzt|beschränkt|ausgeschlossen)"
         r"|responsabilité[^.]{0,60}(?:limitée|exclue)|responsabilità[^.]{0,60}(?:limitata|esclusa)",
         "Höhe des Risikos bei Schäden"),
        ("garantie", "Bürgschaft oder Garantie", r"\bbürgschaft\w*|\bgarantieerklärung\w*|patronatserklärung\w*|\bcautionnement\w*|lettre de patronage"
         r"|\bfideiussion\w*|lettera di patronage",
         "Eventualverbindlichkeit"),
    ]
]
LABELS = {key: label for key, label, _, _ in KINDS}
WHY = {key: why for key, _, _, why in KINDS}

_NEGATION = re.compile(r"\b(?:nicht|kein\w*|ohne|weder|pas|aucun\w*|sans|ni|non(?!-)|nessun\w*|senza|né)\b"
                       r"|berührt\b[^.]*\bnicht", re.IGNORECASE)
_SENTENCE = re.compile(r"[^.!?]+(?:[.!?]|$)")


@dataclass
class Clause:
    kind: str
    doc: Document
    page: int
    start: int
    end: int
    sentence: str
    present: bool  # False: der Satz schliesst die Klausel ausdrücklich aus

    @property
    def where(self) -> str:
        return f"{self.doc.label}, S. {self.page}"


@dataclass
class ContractEntry:
    doc: Document
    clauses: list[Clause] = field(default_factory=list)

    def has(self, kind: str) -> bool | None:
        """True: Klausel vorhanden, False: ausdrücklich ausgeschlossen, None: nichts dazu im Dokument."""
        found = [c for c in self.clauses if c.kind == kind]
        if any(c.present for c in found):
            return True
        return False if found else None


def _sentences(text: str):
    # Zeilenumbrüche aus dem PDF trennen keine Sätze; gleiche Länge, damit die Positionen stimmen.
    for m in _SENTENCE.finditer(text.replace("\n", " ")):
        s = re.sub(r"\s+", " ", m.group(0)).strip()
        if len(s) > 12:
            yield m.start(), m.end(), s


def find_clauses(doc: Document) -> list[Clause]:
    out = []
    for page_no, text in enumerate(doc.pages, 1):
        for start, end, sentence in _sentences(text):
            for key, _, rx, _ in KINDS:
                if rx.search(sentence):
                    out.append(Clause(key, doc, page_no, start, end, sentence, not _NEGATION.search(sentence)))
    return out


_CONTRACT_TITLE = re.compile(r"vertrag|vereinbarung|police|lizenz|agreement|reglement|statuten"
                             r"|contrat|convention|accord|bail|licence|contratto|accordo|polizza|licenza", re.IGNORECASE)


def contract_register(room: DataRoom) -> list[ContractEntry]:
    """Alle Verträge des Datenraums mit ihren Klauseln, in Datenraum-Reihenfolge."""
    entries = []
    for doc in room.documents:
        if doc.index is None:
            continue
        clauses = find_clauses(doc)
        if clauses or _CONTRACT_TITLE.search(doc.title):
            entries.append(ContractEntry(doc, clauses))
    return entries


# --- Aussagen des Berichts gegen das Register prüfen -------------------------------

_CLAIM_NEGATION = re.compile(r"\b(?:kein\w*|nicht|ohne|weder|pas|aucun\w*|sans|non(?!-)|nessun\w*|senza)\b", re.IGNORECASE)


def clause_claims(text: str) -> list[tuple[str, bool]]:
    """Welche Klauseln eine Aussage nennt und ob sie sie behauptet (True) oder verneint (False)."""
    out = []
    for key, _, rx, _ in KINDS:
        if rx.search(text):
            out.append((key, not _CLAIM_NEGATION.search(text)))
    return out


def apply_clauses(findings, room: DataRoom, register: list[ContractEntry]) -> None:
    """Aussagen über Klauseln gegen das Register prüfen. Ändert nur Geprüft und Ungeprüft."""
    from .verify import Status, _evidence

    by_doc = {id(e.doc): e for e in register}
    for f in findings:
        said = clause_claims(f.claim.clean_text)
        if not said or not f.claim.citations or f.status not in (Status.GEPRUEFT, Status.UNGEPRUEFT):
            continue
        cited = []
        for c in f.claim.citations:
            doc = room.get(c.index)
            if doc is None:
                continue
            pages = set(range(c.page_from, (c.page_to or c.page_from) + 1)) if c.page_from else set(range(1, len(doc.pages) + 1))
            cited.append((doc, pages))
        if not cited:
            continue
        problems, oks, wrong_page = [], [], []
        for kind, asserted in said:
            label = LABELS[kind]
            clauses = [c for doc, _ in cited for c in (by_doc.get(id(doc)) or ContractEntry(doc)).clauses if c.kind == kind]
            present = [c for c in clauses if c.present]
            on_page = [c for c in present if any(c.doc is d and c.page in pages for d, pages in cited)]
            excluded = [c for c in clauses if not c.present and any(c.doc is d and c.page in pages for d, pages in cited)]
            if asserted and on_page:
                oks.append((f"{label}-Klausel", on_page[0]))
            elif asserted and present:
                wrong_page.append((label, present[0]))
            elif asserted:
                note = f" Dort steht: «{excluded[0].sentence}»" if excluded else ""
                problems.append((f"Die Fundstelle enthält keine {label}-Klausel.{note}", excluded[0] if excluded else None))
            elif present:
                c = present[0]
                problems.append((f"{c.where} enthält eine {label}-Klausel: «{c.sentence}» "
                                 f"({WHY[kind]}).", c))
            elif excluded:
                oks.append((f"{label} ausdrücklich ausgeschlossen", excluded[0]))
        if not (problems or oks or wrong_page):
            continue
        f.method = "Klauselsuche" if f.method == "Regeln" else f.method
        for _, c in oks + wrong_page + problems:
            if c is not None:
                f.evidence.append(_evidence(c.doc, c.page, c.start, c.end))
        if problems:
            f.status = Status.ABWEICHUNG
            f.reasons = [text for text, _ in problems] + [r for r in f.reasons if "keine automatisch prüfbaren" not in r]
        elif wrong_page:
            f.status = Status.FALSCHE_FUNDSTELLE
            f.reasons = [f"Die {label}-Klausel steht nicht an der Fundstelle, sondern in {c.where}." for label, c in wrong_page]
        else:
            if f.status is Status.UNGEPRUEFT:
                f.status = Status.GEPRUEFT
                f.reasons = []
            f.reasons.append("Klausel an der Fundstelle gefunden: " + ", ".join(t for t, _ in oks) + ".")
