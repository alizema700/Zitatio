"""Datenräume aus der Romandie und dem Tessin: französische und italienische Dokumente."""

import datetime as dt

from zitatio.clauses import contract_register
from zitatio.consistency import check_income_statements
from zitatio.dataroom import DataRoom
from zitatio.pipeline import run_check
from zitatio.swiss import check_capital, check_signatures, signatories
from zitatio.terms import closing_list
from zitatio.verify import Status

DOCS = {
    "1.1 Extrait du registre du commerce.txt": (
        "Extrait du registre du commerce du canton de Vaud\nRaison sociale: Léman Précision SA\n"
        "Capital-actions: CHF 500'000, divisé en 500 actions nominatives de CHF 1'000.\n"
        "Dubois, Claire, de Genève, à Lausanne, présidente du conseil d'administration, avec signature individuelle\n"
        "Rochat, Marc, de Vevey, à Montreux, directeur, avec signature collective à deux\n"
        "Favre, Luc, de Nyon, à Morges, sans droit de signature\n"),
    "2.1 Comptes annuels 2025.txt": (
        "Léman Précision SA - Comptes annuels 2025\nCompte de résultat 2025 (en CHF)\n"
        "Chiffre d'affaires net 12 400 000\nCharges de matériel 4 100 000\nCharges de personnel 5 200 000\n"
        "Autres charges d'exploitation 1 300 000\nEBITDA 2 000 000\n\n"
        "Bilan au 31.12.2025 (en CHF)\nCapital-actions 500 000\nRéserve légale issue du bénéfice 100 000\n"
        "Total fonds propres 200 000\n"),
    "5.1 Contrat de livraison Hôpital du Léman SA.txt": (
        "Contrat de livraison\nLe contrat entre en vigueur le 1er janvier 2022 et prend fin le 31 décembre 2026.\n"
        "Le volume annuel estimé s'élève à CHF 3,2 millions.\n"
        "En cas de changement de contrôle du fournisseur, le client peut résilier le contrat avec effet immédiat.\n"
        "Chaque partie peut résilier le contrat moyennant un préavis de six mois.\n"
        "Pour la Léman Précision SA: Marc Rochat, directeur\n"),
    "5.2 Contratto di fornitura Ticino Med SA.txt": (
        "Contratto di fornitura\nIl contratto entra in vigore il 1° luglio 2023 e scade il 30 giugno 2029.\n"
        "Un cambiamento di controllo non pregiudica la validità del presente contratto.\n"
        "Per la Léman Précision SA: Luc Favre, responsabile acquisti\n"),
}


def _room() -> DataRoom:
    room = DataRoom()
    for name, text in DOCS.items():
        room.add(name, text.encode())
    return room


def test_french_commercial_register_and_signatures():
    room = _room()
    kinds = {s.name: s.kind for s in signatories(room)}
    assert kinds == {"Claire Dubois": "signature individuelle", "Marc Rochat": "signature collective à deux",
                     "Luc Favre": "sans droit de signature"}
    warned = {d for f in check_signatures(room) if f.level == "warnung" for d in f.docs}
    assert warned == {"5.1", "5.2"}  # Rochat allein, Favre ohne Zeichnungsrecht


def test_french_financials_capital_and_footing():
    room = _room()
    flag, = check_capital(room)
    assert flag.level == "warnung"  # 200'000 < Hälfte von 600'000
    footing = check_income_statements(room)
    assert len(footing) == 1 and "200'000" in footing[0].text  # 12.4 - 4.1 - 5.2 - 1.3 = 1.8 Mio., nicht 2.0


def test_clauses_and_terms_in_french_and_italian():
    register = contract_register(_room())
    by_label = {e.doc.label: e for e in register}
    assert by_label["DR 5.1"].has("kontrollwechsel") is True
    assert by_label["DR 5.2"].has("kontrollwechsel") is False
    terms, items = closing_list(register, today=dt.date(2026, 10, 20))
    t = next(t for t in terms if t.doc.label == "DR 5.1")
    assert (t.start, t.end, t.notice, t.volume) == (dt.date(2022, 1, 1), dt.date(2026, 12, 31), (6, "Monate"), 3200000)
    t2 = next(t for t in terms if t.doc.label == "DR 5.2")
    assert (t2.start, t2.end) == (dt.date(2023, 7, 1), dt.date(2029, 6, 30))
    assert {(i.kind, i.terms.doc.label) for i in items} == {("kontrollwechsel", "DR 5.1"), ("laufzeit", "DR 5.1")}


def test_german_report_against_french_documents():
    report = ("Der Umsatz 2025 beträgt CHF 12.4 Mio. [DR 2.1, S. 1].\n\n"
              "Der Personalaufwand 2025 beträgt CHF 5.9 Mio. [DR 2.1, S. 1].\n\n"
              "Der Liefervertrag mit dem Hôpital du Léman enthält keine Kontrollwechselklausel [DR 5.1, S. 1].\n\n"
              "Der Vertrag endet am 31. Dezember 2026 [DR 5.1, S. 1].")
    run = run_check("bericht.md", report, report.encode(), _room())
    assert [f.status for f in run.findings] == [Status.GEPRUEFT, Status.ABWEICHUNG, Status.ABWEICHUNG, Status.GEPRUEFT]


def test_english_report_against_german_data_room():
    """Berichte von Schweizer Deal-Teams sind oft englisch, der Datenraum deutsch."""
    room = DataRoom()
    room.add("2.1 Jahresrechnung 2025.txt", ("Jahresrechnung 2025\nErfolgsrechnung 2025 (in CHF)\n"
                                              "Nettoerlös 18'540'000\nEBITDA 2'310'000\n").encode())
    room.add("3.1 Mietvertrag Werk.txt", ("Mietvertrag\nDer Vertrag ist fest abgeschlossen bis 31.12.2029.\n"
                                          "Danach gilt eine Kündigungsfrist von 12 Monaten.\n"
                                          "Bei einem Kontrollwechsel kann die Vermieterin den Vertrag kündigen.\n").encode())
    report = ("Net revenue for 2025 amounts to CHF 18.54 million [DR 2.1, p. 1].\n\n"
              "EBITDA in 2025 was CHF 2.31m [DR 2.1, p. 1].\n\n"
              "EBITDA in 2025 was CHF 2.6 million [DR 2.1, p. 1].\n\n"
              "The lease has a fixed term until 31 December 2029 [DR 3.1, p. 1].\n\n"
              "Thereafter a notice period of 18 months applies [DR 3.1, p. 1].\n\n"
              "The lease contains no change of control clause [DR 3.1, p. 1].")
    run = run_check("report.md", report, report.encode(), room)
    assert [f.status for f in run.findings] == [Status.GEPRUEFT, Status.GEPRUEFT, Status.ABWEICHUNG,
                                                Status.GEPRUEFT, Status.ABWEICHUNG, Status.ABWEICHUNG]


def test_english_data_room_metrics_and_dates():
    from zitatio.facts import extract_facts
    from zitatio.tables import metrics_in

    assert [m[0] for m in metrics_in("Net revenues; Cost of revenues; Net income; Cash and cash equivalents")] == [
        "umsatz", "jahresgewinn", "fluessige_mittel"]
    facts = extract_facts("Signed on March 3, 2025 for USD 1.2bn with a term of five years.")
    assert [(f.kind, f.value) for f in facts] == [("datum", dt.date(2025, 3, 3)), ("betrag", ("USD", 1200000000)),
                                                   ("frist", (5, "Jahre"))]
