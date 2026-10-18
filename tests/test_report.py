from zitatio.report import parse_citations, parse_report, split_sentences


def test_citation_formats():
    labels = [c.label for c in parse_citations("x [DR 3.2.1, S. 4] y (VDR 2.1 p. 3-4) z [Datenraum 5.3; DR 1.1, Seite 2]")]
    assert labels == ["DR 3.2.1, S. 4", "DR 2.1, S. 3–4", "DR 5.3", "DR 1.1, S. 2"]


def test_sentence_split_respects_abbreviations_and_dates():
    text = ("Der Zins beträgt ca. 2 % gem. Art. 3 Abs. 2 [DR 5.3, S. 1]. Fällig am 31. März 2030 ist "
            "das Darlehen über CHF 3.5 Mio. [DR 5.3]. Die Nettoverschuldung beträgt CHF 4.2 Mio. Danach folgt Text.")
    assert len(split_sentences(text)) == 4


def test_claims_keep_citation_and_strip_it_from_clean_text():
    claims = parse_report("# Finanzen\n\nDer Umsatz beträgt CHF 1 Mio. [DR 2.1, S. 1].\n\nReiner Fliesstext ohne Werte.")
    assert len(claims) == 1
    claim = claims[0]
    assert claim.section == "Finanzen"
    assert claim.clean_text == "Der Umsatz beträgt CHF 1 Mio."
    assert [c.label for c in claim.citations] == ["DR 2.1, S. 1"]
