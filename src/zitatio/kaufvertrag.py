"""Den Entwurf des Kaufvertrags gegen Datenraum und Bewertung prüfen.

- Kaufgegenstand: Verkauft die Verkäuferin mehr Aktien, als ihr laut Aktienbuch gehören?
- Vinkulierung: Verlangen die Statuten die Zustimmung des Verwaltungsrats zur Übertragung (Art. 685a OR), muss
  der Vertrag sie als Vollzugsbedingung vorsehen.
- Kaufpreis: Liegt der Preis im Entwurf über dem Equity Value, der nach den Befunden übrig bleibt?
- Locked Box: Gibt es zum Stichtag eine Bilanz im Datenraum?
"""

from __future__ import annotations

import re
from decimal import Decimal

from .dataroom import DataRoom
from .facts import AMOUNT, DATE, extract_facts, format_value
from .swiss import _HOLDER, HINWEIS, OK, WARNUNG, Flag
from .verify import _evidence

_SOLD = re.compile(r"(?:verk(?:auft|äuft)|vend)\w*[^.]{0,120}?([\d'’]+)\s+(?:(?:Namen|Inhaber)?aktien|actions)",
                   re.IGNORECASE)
_SELLER = re.compile(r"(?:zwischen\s+|und\s+)?([A-ZÄÖÜ][^;()\n]{2,100}?)\s*\((?:nachfolgend\s+)?(?:die\s+|der\s+|le\s+|la\s+|l')?[„\"«]?\s?(?:Verkäufer(?:in)?|Vendeu(?:r|se)|Venderesse)",
                     re.IGNORECASE)
_SELLER_LABEL = re.compile(r"(?:Verkäufer(?:in)?|Vendeur):\s*([^,;\n(]{3,80})", re.IGNORECASE)
_PRICE = re.compile(r"(?:kaufpreis|prix d'achat|prix de vente)[^.]{0,60}?(?:beträgt|von|in höhe von|s'élève à|est de)\s+(CHF\s*[\d'’.]+(?:\s*(?:Mio\.?|Millionen))?)",
                    re.IGNORECASE)
_VINKULIERUNG = re.compile(r"vinkul|übertragung[^.]{0,60}(?:namenaktien|aktien)[^.]{0,60}zustimmung|"
                           r"transfert[^.]{0,80}(?:approbation|agrément) du conseil", re.IGNORECASE)
_CONSENT_IN_SPA = re.compile(r"zustimmung des verwaltungsrat|(?:approbation|agrément|consentement) du conseil|vinkul|685[ab]?\s*(?:ff\.?\s*)?OR|eintragung[^.]{0,40}aktienbuch",
                             re.IGNORECASE)
_LOCKED_BOX = re.compile(r"locked[- ]?box", re.IGNORECASE)


def _norm(name: str) -> str:
    return re.sub(r"[^a-zäöü0-9]", "", name.lower())


def _chf(value: Decimal) -> str:
    return format_value("betrag", ("CHF", value.quantize(Decimal(1))))


def _n(value: int) -> str:
    return f"{value:,}".replace(",", "'")


def check_spa(spa_name: str, spa_text: str, room: DataRoom, valuation=None) -> list[Flag]:
    flags: list[Flag] = []
    flat = re.sub(r"\s+", " ", spa_text)
    sellers = [m.group(1).strip() for m in _SELLER.finditer(flat)] + [m.group(1).strip() for m in _SELLER_LABEL.finditer(flat)]
    sold = _SOLD.search(flat)
    book = next((d for d in room.documents if d.index and re.search(r"aktienbuch|aktionärsverzeichnis|registre des actions",
                                                                    d.title, re.I)), None)

    if sellers and sold and book:
        count = int(re.sub(r"['’]", "", sold.group(1)))
        holdings = {}
        for p, text in enumerate(book.pages, 1):
            for m in _HOLDER.finditer(text):
                holdings[_norm(m.group(1))] = (int(re.sub(r"['’]", "", m.group(2))), m.group(1).strip(), p, m)
        # "Rohner Beteiligungen AG, Altstätten" ist im Aktienbuch "Rohner Beteiligungen AG"
        mine = {k for k in holdings if any(k in _norm(s) for s in sellers)}
        own = [holdings[k] for k in mine]
        held = sum(h[0] for h in own)
        ev = [_evidence(book, p, m.start(), m.end()) for _, _, p, m in own]
        names = ", ".join(dict.fromkeys(h[1] for h in own)) or ", ".join(dict.fromkeys(sellers))
        if held < count:
            others = [f"{name} ({_n(n)} Aktien)" for k, (n, name, _, _) in holdings.items() if k not in mine]
            flags.append(Flag(
                WARNUNG, "Kaufvertrag", f"Verkauft werden {_n(count)} Aktien, die Verkäuferin hält {_n(held)}",
                f"Laut {spa_name} verkauft {names} {_n(count)} Namenaktien; im Aktienbuch ({book.label}) stehen auf sie "
                f"{_n(held)}." + (f" Die übrigen gehören {', '.join(others)}." if others else "")
                + " Für diese Aktien braucht es eigene Kaufverträge oder ein Mitverkaufsrecht (Drag-along) aus einem "
                "Aktionärbindungsvertrag; sonst erwirbt die Käuferin nicht, was der Vertrag beschreibt.",
                ev, [book.index]))
        else:
            flags.append(Flag(OK, "Kaufvertrag", "Verkaufte Aktien gehören der Verkäuferin",
                              f"{names} hält laut Aktienbuch {_n(held)} Aktien ({book.label}).", ev))

    statutes = next((d for d in room.documents if d.index and re.search(r"statuten|statuts|statuto", d.title, re.I)), None)
    if statutes:
        for p, text in enumerate(statutes.pages, 1):
            m = _VINKULIERUNG.search(text)
            if m:
                ev = [_evidence(statutes, p, m.start(), m.end())]
                if _CONSENT_IN_SPA.search(flat):
                    flags.append(Flag(OK, "Kaufvertrag", "Vinkulierung im Vertrag geregelt",
                                      f"Die Statuten ({statutes.label}) vinkulieren die Namenaktien; der Entwurf regelt die "
                                      "Zustimmung des Verwaltungsrats.", ev))
                else:
                    flags.append(Flag(
                        WARNUNG, "Kaufvertrag", "Zustimmung des Verwaltungsrats zur Übertragung fehlt im Vertrag",
                        f"Die Statuten ({statutes.label}, S. {p}) vinkulieren die Namenaktien. Ohne Zustimmung des "
                        "Verwaltungsrats bleiben die Aktionärsrechte bei der Verkäuferin (Art. 685c OR). Als "
                        "Vollzugsbedingung aufnehmen, mit Eintrag der Käuferin ins Aktienbuch.", ev, [statutes.index]))
                break

    price = _PRICE.search(flat)
    if price and valuation is not None and valuation.checked_equity:
        value = next((f.value[1] for f in extract_facts(price.group(1)) if f.kind == AMOUNT), None)
        checked = valuation.checked_equity
        if value and value > checked * Decimal("1.01"):
            flags.append(Flag(
                WARNUNG, "Kaufvertrag", f"Kaufpreis {_chf(value)} über dem geprüften Equity Value {_chf(checked)}",
                f"{spa_name} nennt einen Kaufpreis von {_chf(value)}. Nach den Befunden bleibt ein Equity Value von "
                f"{_chf(checked)} (Preisbrücke): {_chf(value - checked)} mehr. Preis anpassen oder die Posten aus der "
                "Preisbrücke in der Kaufpreisformel abziehen.", [], ["SPA"]))
        elif value:
            flags.append(Flag(OK, "Kaufvertrag", f"Kaufpreis {_chf(value)} durch den geprüften Equity Value gedeckt",
                              f"Geprüfter Equity Value {_chf(checked)}."))

    if _LOCKED_BOX.search(flat):
        box = next((f.value for m in re.finditer(r"[^.]*locked[- ]?box[^.]*\.", flat, re.I)
                    for f in extract_facts(m.group(0)) if f.kind == DATE), None)
        if box:
            stamp = f"{box:%d.%m.%Y}"
            has_balance = any(re.search(rf"bilanz per {re.escape(stamp)}|bilan au {re.escape(stamp)}", t, re.I)
                              for d in room.documents if d.index for t in d.pages)
            if not has_balance:
                flags.append(Flag(HINWEIS, "Kaufvertrag", f"Keine Bilanz per Locked-Box-Stichtag {stamp}",
                                  "Der Preis beruht auf der Bilanz zum Stichtag. Im Datenraum liegt keine Bilanz mit "
                                  "diesem Datum; sie gehört als Locked-Box-Bilanz ins SPA."))
    return flags
