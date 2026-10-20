"""Versionsvergleich zweier Berichtsentwürfe und Übernahme der Entscheide."""

from zitatio.dataroom import DataRoom
from zitatio.pipeline import run_check
from zitatio.render import to_csv, to_html
from zitatio.versions import read_decisions, word_diff

ROOM = {"2.1 Jahresrechnung 2025.txt": "Erfolgsrechnung 2025 (in CHF)\nUmsatz 2025 12'400'000\nEBITDA 2025 2'100'000\n"}
V1 = ("Der Umsatz 2025 beträgt CHF 12.4 Mio. [DR 2.1, S. 1].\n\nDas EBITDA 2025 beträgt CHF 2.4 Mio. [DR 2.1, S. 1].\n\n"
      "Der Markt wächst stark.\n\nDie Marge ist hoch [DR 2.1, S. 1].")
V2 = ("Der Umsatz 2025 beträgt CHF 12.4 Mio. [DR 2.1, S. 1].\n\nDas EBITDA 2025 beträgt CHF 2.1 Mio. [DR 2.1, S. 1].\n\n"
      "Der Markt wächst stark.\n\nDas EBITDA 2025 lag bei CHF 2.7 Mio. [DR 2.1, S. 1].")


def _room() -> DataRoom:
    room = DataRoom()
    for name, text in ROOM.items():
        room.add(name, text.encode())
    return room


def test_fixed_open_new_and_removed_findings():
    run = run_check("v2.md", V2, V2.encode(), _room(), previous=("v1.md", V1))
    kinds = [c.kind for c in run.diff.changes]
    assert kinds == ["unverändert", "geändert", "neu"]  # "Der Markt wächst stark." ist keine prüfbare Aussage
    assert run.diff.changes[1].outcome == "behoben" and run.diff.changes[2].outcome == "neuer Befund"
    assert [f.claim.clean_text for f in run.diff.removed] == ["Die Marge ist hoch."]
    assert "Änderungen gegenüber der Vorversion" in to_html(run) and "<del>2.4 </del>" in to_html(run)


def test_decisions_carry_over_only_for_unchanged_sentences(tmp_path):
    first = run_check("v1.md", V1, V1.encode(), _room())
    lines = to_csv(first).lstrip("﻿").splitlines()
    lines[1] = lines[1].rstrip(";") + ";Zugestimmt;passt;Ali"
    lines[2] = lines[2].rstrip(";") + ";Widersprochen;falsch;Ali"
    path = tmp_path / "v1.csv"
    path.write_text("﻿" + "\r\n".join(lines) + "\r\n", encoding="utf-8")
    run = run_check("v2.md", V2, V2.encode(), _room(), previous=("v1.md", V1), decisions=read_decisions(path))
    assert run.decisions == {1: {"v": "ok", "n": "passt", "p": "Ali"}}
    assert "Zugestimmt;passt;Ali" in to_csv(run)


def test_word_diff():
    assert word_diff("CHF 2.4 Mio.", "CHF 2.1 Mio.") == [("=", "CHF "), ("-", "2.4 "), ("+", "2.1 "), ("=", "Mio.")]
