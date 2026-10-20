"""Versionsvergleich: Was hat sich zwischen zwei Entwürfen des Berichts geändert?

Ein DD-Bericht geht durch mehrere Entwürfe. Beim zweiten Durchgang will niemand 200 Aussagen neu
durchsehen, sondern wissen: Welche Befunde sind behoben, welche noch offen, was ist neu dazugekommen?
Unveränderte Aussagen übernehmen die Entscheide der Vorversion (Zustimmen, Widersprechen, Notiz).
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from .verify import Finding, Status

OPEN = {Status.ABWEICHUNG, Status.FALSCHE_FUNDSTELLE, Status.QUELLE_FEHLT, Status.OHNE_BELEG, Status.WIDERSPRUCH}
UNCHANGED, CHANGED, NEW = "unverändert", "geändert", "neu"


@dataclass
class Change:
    kind: str  # unverändert, geändert, neu
    new: Finding
    old: Finding | None = None

    @property
    def outcome(self) -> str:
        """behoben, offen, neuer Befund oder leer."""
        was = self.old is not None and self.old.status in OPEN
        now = self.new.status in OPEN
        if was and not now:
            return "behoben"
        if was and now:
            return "offen"
        return "neuer Befund" if now else ""


@dataclass
class VersionDiff:
    old_name: str
    changes: list[Change]
    removed: list[Finding] = field(default_factory=list)

    def of(self, finding: Finding) -> Change | None:
        return next((c for c in self.changes if c.new is finding), None)

    def count(self, kind: str) -> int:
        return sum(c.kind == kind for c in self.changes)

    def outcomes(self) -> dict[str, int]:
        out = {"behoben": 0, "offen": 0, "neuer Befund": 0, "gestrichen": 0}
        for c in self.changes:
            if c.outcome:
                out[c.outcome] += 1
        out["gestrichen"] = sum(f.status in OPEN for f in self.removed)
        out["behoben"] += out["gestrichen"]
        return out

    def summary(self) -> str:
        o = self.outcomes()
        before = o["behoben"] + o["offen"]
        parts = [f"{self.count(CHANGED)} geändert, {self.count(NEW)} neu, {len(self.removed)} gestrichen."]
        if before:
            parts.append(f"Von {before} Befunden der Vorversion sind {o['behoben']} behoben und {o['offen']} offen.")
        if o["neuer Befund"]:
            parts.append(f"{o['neuer Befund']} neue{'r' if o['neuer Befund'] == 1 else ''} Befund"
                         f"{'e' if o['neuer Befund'] != 1 else ''}.")
        return " ".join(parts)


def _key(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def compare(old: list[Finding], new: list[Finding], old_name: str = "Vorversion") -> VersionDiff:
    """Ordnet jeder neuen Aussage die passende alte zu: gleicher Text, sonst ähnlichster Text."""
    by_text: dict[str, list[Finding]] = {}
    for f in old:
        by_text.setdefault(_key(f.claim.text), []).append(f)
    used: set[int] = set()
    changes: list[Change | None] = [None] * len(new)
    for i, f in enumerate(new):
        same = [o for o in by_text.get(_key(f.claim.text), []) if id(o) not in used]
        if same:
            used.add(id(same[0]))
            changes[i] = Change(UNCHANGED, f, same[0])
    # Geänderte Sätze: im gleichen Abschnitt und in der Nähe der alten Position suchen.
    position = {id(o): k for k, o in enumerate(old)}
    for i, f in enumerate(new):
        if changes[i] is not None:
            continue
        best, score = None, 0.0
        for o in old:
            if id(o) in used:
                continue
            ratio = SequenceMatcher(None, _key(o.claim.clean_text), _key(f.claim.clean_text)).ratio()
            ratio += 0.05 * (o.claim.section == f.claim.section)
            if ratio > score:
                best, score = o, ratio
        if best is not None and score >= 0.6:
            used.add(id(best))
            changes[i] = Change(CHANGED, f, best)
        else:
            changes[i] = Change(NEW, f)
    removed = sorted((o for o in old if id(o) not in used), key=lambda o: position[id(o)])
    return VersionDiff(old_name, changes, removed)  # type: ignore[arg-type]


def word_diff(old: str, new: str) -> list[tuple[str, str]]:
    """Wortweiser Unterschied als (Art, Text) mit Art in "=", "-", "+"."""
    a, b = re.findall(r"\S+\s*", old), re.findall(r"\S+\s*", new)
    out = []
    for op, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            out.append(("=", "".join(a[i1:i2])))
            continue
        if i2 > i1:
            out.append(("-", "".join(a[i1:i2])))
        if j2 > j1:
            out.append(("+", "".join(b[j1:j2])))
    return out


# --- Entscheide aus dem CSV der Vorversion übernehmen ----------------------------

_LABELS = {"Zugestimmt": "ok", "Widersprochen": "nein"}


def read_decisions(path: Path) -> dict[str, dict]:
    """Entscheide aus einem exportierten Prüf-CSV, nach Aussagetext."""
    return parse_decisions(path.read_text(encoding="utf-8-sig"))


def parse_decisions(text: str) -> dict[str, dict]:
    text = text.lstrip("\ufeff")
    out = {}
    for row in csv.DictReader(io.StringIO(text), delimiter=";"):
        verdict, note = _LABELS.get((row.get("Entscheid") or "").strip(), ""), (row.get("Notiz") or "").strip()
        if verdict or note:
            out[_key(row.get("Aussage") or "")] = {"v": verdict, "n": note, "p": (row.get("Prüfer") or "").strip()}
    return out


def carry_decisions(findings: list[Finding], decisions: dict[str, dict], diff: VersionDiff | None = None) -> dict:
    """Entscheide für unveränderte Aussagen, nach Aussagenummer. Geänderte Aussagen werden neu entschieden."""
    out = {}
    for f in findings:
        change = diff.of(f) if diff else None
        if change is not None and change.kind != UNCHANGED:
            continue
        d = decisions.get(_key(f.claim.clean_text))
        if d:
            out[f.claim.number] = d
    return out
