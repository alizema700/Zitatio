# Zitatio

Prüfschicht für Due-Diligence-Berichte. Zitatio prüft jede Aussage eines DD-Berichts oder IC-Memos gegen den
Datenraum und markiert sie als **Geprüft**, **Abweichung**, **Widerspruch**, **Falsche Fundstelle**, **Quelle fehlt**,
**Ohne Beleg** oder **Ungeprüft**. Zu jedem Status gehören eine Begründung und die Belegstelle.

Dazu prüft Zitatio den Datenraum selbst: Nennen zwei Dokumente für dieselbe Grösse verschiedene Werte, steht das als
Widerspruch im Prüfbericht. EBITDA-Bereinigungen und abgeleitete Werte (Wachstum, Margen, Summen) werden nachgerechnet,
fehlende Standardunterlagen gelistet, und eine Offenlegungskarte hält fest, welche Aussage auf welcher Seite steht.

Für Schweizer Deals kommen Prüfungen hinzu, die über „steht es auf der Seite?“ hinausgehen: Zeichnungsberechtigung
gegen das Handelsregister, Kapitalschutz nach Art. 725a/b OR, Revisionspflicht, gesetzliche Steuer- und Beitragssätze,
WEKO-Schwelle, Vertragsregister mit Closing-Liste, Nettoverschuldung mit Covenant und Themen aus den VR-Protokollen,
die der Bericht verschweigt. Datenräume aus der Romandie und dem Tessin (Französisch, Italienisch) und englische
Berichte und Unterlagen werden gelesen.
Oben im Prüfbericht steht auf einer Seite, was das Investment Committee wissen muss.

Stand: Prototyp 0.1. Er prüft Werte (Beträge, Daten, Prozente, Fristen, UIDs) deterministisch. Ein Prüfmodell
für den Sinn einer Aussage kann optional über eine OpenAI-kompatible Schnittstelle angeschlossen werden.

## Schnellstart

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[web,dev]"

# Kommandozeile (HTML, dazu optional JSON, CSV für Excel und die Offenlegungskarte für W&I)
zitatio pruefen beispiele/alpenblick/dd-bericht.md -d beispiele/alpenblick/datenraum -o pruefbericht.html \
  --csv pruefbericht.csv --offenlegung offenlegungskarte.csv

# Zweiter Entwurf: behobene, offene und neue Befunde, Entscheide aus dem CSV übernehmen, eine Seite fürs IC-Memo
zitatio pruefen beispiele/gross/dd-bericht-v2.md -d beispiele/gross/datenraum --vorher beispiele/gross/dd-bericht.md \
  --entscheide pruefbericht.csv --memo ic-memo.md --excel pruefung.xlsx --fragen fragen.md \
  --spa beispiele/gross/spa-entwurf.md --memo ic-memo.docx --klauseln klauseln.docx --kalender fristen.ics

# Red-Flag-Bericht aus dem Datenraum allein, mit Fragenliste und Garantien
zitatio redflags -d beispiele/gross/datenraum -o red-flags.html --fragen fragen.md --spa beispiele/gross/spa-entwurf.md

# Verkäuferseite: Antwortentwürfe mit Fundstelle für die Fragen der Käufer
zitatio antworten kaeuferfragen.xlsx -d beispiele/gross/datenraum -o antworten.md

# Benchmark mit künstlich eingebauten Fehlern
zitatio benchmark -d beispiele/alpenblick/datenraum

# Weboberfläche auf http://127.0.0.1:8000
uvicorn zitatio.web:app --reload

# Tests
pytest
```

## Konventionen

- **Datenraum:** Jeder Dateiname beginnt mit der Indexnummer, z. B. `3.2.1 Mietvertrag Werk Winterthur.pdf`
  (`03.02.01` gilt als dasselbe wie `3.2.1`). Unterstützt werden PDF (mit Textebene), Word (`.docx`, Seiten über
  manuelle Seitenumbrüche), Excel (`.xlsx`, jedes Tabellenblatt ist eine Seite), `.txt` und `.md`.
  Ein ZIP-Export des virtuellen Datenraums kann direkt angegeben werden (`-d datenraum.zip`), samt Unterordnern.
- **Bericht:** Word, PDF, Markdown oder Text. In Word werden Überschriften zu Abschnitten und Tabellenzeilen zu Aussagen.
- **Fundstellen im Bericht:** `[DR 3.2.1, S. 2]`, `(VDR 2.1 p. 3-4)` und `[Datenraum 5.3; DR 1.1, Seite 2]`.
  Ohne Seitenangabe wird das ganze Dokument durchsucht.
- **Q&A-Liste:** `[Q&A 17]` zitiert Eintrag 17 einer Q&A-Liste im Datenraum (Dateiname mit „Q&A“, „Fragenkatalog“
  o. ä.; eine Zeile pro Eintrag, die mit der Nummer beginnt). Jeder Eintrag ist eine eigene Quelle: ein Wert aus
  Eintrag 17 belegt nicht Eintrag 19.
- **Sprachen:** Bericht auf Deutsch oder Englisch, Datenraum auf Deutsch, Französisch, Italienisch oder Englisch
  (Daten wie „31 décembre 2031“ oder „December 31, 2029“, Beträge wie „1 200 000“, „12,4 millions“ oder „CHF 2.31m“,
  Fristen wie „18 months“, Kennzahlen, Klauseln, Handelsregister, Unterschriften). Der Prüfbericht ist deutsch.

## So wird geprüft

| Status | Bedeutung |
|---|---|
| Geprüft | Jeder Wert der Aussage steht auf der zitierten Seite, oder das Prüfmodell stützt die Aussage mit einem wörtlichen Zitat. |
| Abweichung | Ein Wert fehlt an der Fundstelle (der Tabellenwert der genannten Grösse oder die nächstliegenden Werte werden genannt), steht dort in der falschen Jahresspalte oder Zeile, ein wörtliches Zitat steht nicht im Datenraum, eine Rechnung geht nicht auf, die UID-Prüfziffer ist falsch, oder das Prüfmodell widerspricht. |
| Widerspruch | Der Wert steht an der Fundstelle, aber ein anderes Dokument im Datenraum nennt für dieselbe Grösse und Periode einen anderen Wert. |
| Falsche Fundstelle | Die Werte stehen im Datenraum, aber auf einer anderen Seite oder in einem anderen Dokument; oder die Aussage nennt eine Firma oder Dokumentart, die zu einem anderen Dokument gehört. |
| Quelle fehlt | Das zitierte Dokument oder die zitierte Seite gibt es nicht. |
| Ohne Beleg | Die Aussage enthält Werte, aber keine Fundstelle. Ein passender Beleg wird vorgeschlagen, wenn es einen gibt. |
| Ungeprüft | Die Fundstelle existiert, aber die Aussage hat keine prüfbaren Werte, oder sie nennt einen abgeleiteten Wert, der sich nicht nachrechnen lässt. Die ähnlichste Textstelle wird als Lesehilfe gezeigt. |

Zwei Fälle aus dem DD-Alltag zählen als übereinstimmend und werden in der Begründung ausgewiesen:

- **Gerundete Werte:** „CHF 18.45 Mio.“ stimmt mit CHF 18'450'312 überein, weil die Schreibweise auf 10'000 genau
  ist, aber nur bei höchstens 1 % Abstand. „CHF 3 Mio.“ für CHF 3'400'000 bleibt eine Abweichung. Prozente runden
  nur, wenn die Aussage Nachkommastellen hat: „12.4 %“ passt zu 12.38 %, „2 %“ nicht zu 2.4 %.
- **Tabellen ohne Währung:** Nennt eine Seite genau eine Einheit im Kopf („in CHF“, „in TCHF“, „in Mio. CHF“),
  gelten Zahlen ohne Währung auf dieser Seite in dieser Einheit. Jahreszahlen und kleine Nummern werden ignoriert.
  Stehen zwei Einheiten auf einer Seite, wird nichts angenommen.

### Zeilen, Spalten und Widersprüche

Zitatio liest Tabellen auf Datenraum-Seiten mit Zeile und Spalte: „Materialaufwand 11'041'327 9'824'405“ unter dem
Kopf „Erfolgsrechnung 2025 und 2024“ gehört zu Materialaufwand 2025 und 2024. Daraus folgen drei Prüfungen:

- **Jahresspalte:** „Materialaufwand 2025 CHF 9.82 Mio.“ ist eine Abweichung, wenn der Wert in der Spalte 2024 steht.
- **Zeile:** „Jahresgewinn CHF 3.88 Mio.“ ist eine Abweichung, wenn der Wert in der Zeile „Betriebsergebnis (EBIT)“ steht.
- **Widerspruch im Datenraum:** Dieselbe Grösse und Periode wird über alle Dokumente verglichen, z. B. die Vorjahresspalte
  mit dem Vorjahresabschluss, Management Accounts mit der Jahresrechnung oder das Aktienkapital in Handelsregister und
  Statuten. Rundungen („31'862“ TCHF zu CHF 31'862'415) zählen nicht als Widerspruch, Plan und Ist werden getrennt, und
  gemeldet wird nur, was mindestens zwei Dokumente unterschiedlich nennen.

Erkannt werden gängige Grössen (Umsatz/Nettoerlös, EBITDA, EBIT, Jahresgewinn, Material- und Personalaufwand,
Abschreibungen, Finanzaufwand, flüssige Mittel, Eigen- und Aktienkapital, Nettoverschuldung, verzinsliche
Verbindlichkeiten, Auftragsbestand, Investitionen, steuerbarer Reingewinn, bereinigtes EBITDA).

### Zitate und Dokumentbezug

Ein wörtliches Zitat im Bericht („…“, «…») muss wörtlich auf der zitierten Seite stehen; Auslassungen mit „[…]“ sind
erlaubt. Steht es nirgends im Datenraum, gilt es als verändert oder erfunden. Nennt eine Aussage eine Firma
(„Lakeside Dental SA“) oder eine Dokumentart („Mietvertrag“), die nur zu einem anderen Dokument passt, ist es eine
falsche Fundstelle.

### Nachrechnen

- **Abgeleitete Werte:** Wachstum und Margen werden aus den Tabellenwerten der zitierten Seite nachgerechnet, Summen
  („insgesamt“) aus belegten Beträgen früherer Aussagen im selben Abschnitt. Geht die Rechnung auf, ist die Aussage
  geprüft; geht sie nicht auf, ist es eine Abweichung mit Rechenweg; lässt sie sich nicht nachrechnen, bleibt sie ungeprüft.
- **EBITDA-Bereinigungen:** In einem Abschnitt zu Bereinigungen (Überschrift mit „Bereinigung“, „Addback“, „Quality of
  Earnings“ …) gilt: ausgewiesenes EBITDA plus Bereinigungen muss das bereinigte EBITDA ergeben, und jede Bereinigung
  braucht eine Fundstelle. Der Prüfbericht zeigt die Rechnung und den Anteil der Bereinigungen am bereinigten EBITDA.

### Lückenliste und Offenlegungskarte

Der Prüfbericht listet 20 übliche DD-Unterlagen (Handelsregister bis Bewilligungen) und zeigt, welche im Datenraum
fehlen. Die Offenlegungskarte (`--offenlegung` oder Link im HTML-Bericht) hat eine Zeile je Beleg: Aussage, Status,
Dokument, Seite, Textstelle, SHA-256 des Dokuments und Prüfzeitpunkt. Sie hilft beim W&I-Underwriting und im
Schadenfall zu zeigen, was offengelegt war.

### Grundsatz

Grundsatz: Im Zweifel nie „Geprüft“. Die Antwort eines Prüfmodells zählt nur, wenn sein Zitat wörtlich in der
Quelle steht; sonst wird sie verworfen. Ist das Modell nicht erreichbar, bleibt das Regelergebnis stehen.

Im HTML-Prüfbericht hält die prüfende Person zu jeder Aussage fest, ob sie Zitatio zustimmt oder widerspricht,
mit Notiz und Namen. Die Entscheide bleiben im Browser gespeichert und gehen mit „Protokoll exportieren“ ins CSV.

Der Prüfbericht enthält SHA-256-Hashes des Berichts und aller Datenraum-Dokumente, damit später nachvollziehbar
ist, was genau geprüft wurde.

## Schweizer Prüfungen und Deal-Themen

### Das Wichtigste für das Investment Committee

Oben im Prüfbericht stehen die Befunde nach Gewicht: zuerst, was Preis oder Closing betrifft (Abweichungen,
Warnsignale, Umsatz unter Kontrollwechselklauseln), dann, was vor dem Signing zu klären ist. Jeder Punkt verlinkt
seinen Abschnitt. `--memo ic-memo.md` schreibt dieselbe Seite mit den offenen Befunden als Markdown fürs IC-Memo, mit `--memo ic-memo.docx` als Word-Datei mit Tabelle.
`--excel` (und der Link „Excel-Mappe“ im Prüfbericht) liefert die Aussagen, die EBITDA-Brücke, die Nettoverschuldung
mit Covenant, die Closing-Liste und die Fragenliste als Excel-Mappe; die Rechnungen stehen dort als Formeln.

### Preisbrücke

Nennt der Bericht ein Multiple auf das bereinigte EBITDA („mit dem 7.5-fachen bereinigten EBITDA“), rechnet Zitatio
Unternehmenswert und Equity Value nach (minus Nettoverschuldung aus der Bilanz) und prüft die Aussagen dazu. Die
Preisbrücke zeigt, was die Befunde kosten: Eine Bereinigung ohne Beleg wirkt mal das Multiple, schuldenähnliche Posten
Franken für Franken; Klagen stehen als Risiko daneben. Im grossen Testfall sind das −CHF 1.8 Mio. (−4.4 %) auf den
Equity Value, plus CHF 1.45 Mio. Streitwert. Die Rechnung steht auch als Blatt „Preisbrücke“ mit Formeln in der
Excel-Mappe.

### Garantien im Kaufvertrag

Mit `--spa spa-entwurf.md` (oder dem Feld „Kaufvertrag“ beim Hochladen) liest Zitatio die nummerierten Garantien
des SPA-Entwurfs und ordnet jeder Garantie die Befunde zu, die sie berühren: Kontrollwechselklauseln und
Zeichnungsberechtigung zu „Wesentliche Verträge“, die angekündigte Steuerprüfung zu „Steuern“, die Klage zu
„Rechtsstreitigkeiten“, schuldenähnliche Posten zu „Finanzierung“ und „Vorsorge“. Zu jedem Befund steht, was der
Käufer verlangen kann (Freistellung, Closing-Bedingung, Nachreichen, Abzug im Kaufpreis), und ob eine Freistellung im
Entwurf ihn schon abdeckt. `beispiele/gross/spa-entwurf.md` ist ein fiktiver Entwurf dazu: 10 von 11 Garantien sind
berührt, die Steuerprüfung ist durch die Steuerfreistellung Ziff. 6.1 abgedeckt, die Klage nicht.

### Kaufvertrag gegen Datenraum

Mit `--spa` prüft Zitatio auch den Entwurf selbst: Verkauft die Verkäuferin mehr Aktien, als ihr laut Aktienbuch
gehören? Vinkulieren die Statuten die Namenaktien, ohne dass der Vertrag die Zustimmung des Verwaltungsrats als
Vollzugsbedingung vorsieht (Art. 685a ff. OR)? Liegt der Kaufpreis über dem Equity Value, der nach den Befunden
übrig bleibt? Gibt es eine Bilanz per Locked-Box-Stichtag? Im grossen Testfall verkauft die Rohner Beteiligungen AG
alle 12'000 Aktien, hält aber nur 7'200.

### Klauselvorschläge für den Kaufvertrag

Aus den Befunden schreibt Zitatio einen Entwurf in der Sprache eines Schweizer Aktienkaufvertrags: eine
Vollzugsbedingung für alle Zustimmungen zum Kontrollwechsel, spezifische Freistellungen für bekannte Risiken
(unabhängig von der Offenlegung, ausserhalb von Freibetrag und Haftungshöchstbetrag, bei einer Klage mit Sperrkonto
in Höhe des Streitwerts), schuldenähnliche Posten für die Kaufpreisformel, die Klausel zur indirekten
Teilliquidation, nachzureichende Unterlagen und Garantien, die präzisiert werden müssen. Was eine Freistellung im
SPA-Entwurf schon deckt, kommt nicht doppelt; neue Ziffern schliessen an die bestehenden an. Mit `--spa` steht der
Entwurf im Prüfbericht, mit `--klauseln vorschlaege.docx` als Word-Datei oder `.md`.

### Leakage nach dem Locked-Box-Stichtag

Nennt der SPA-Entwurf oder der Bericht einen Locked-Box-Stichtag, sucht Zitatio im Datenraum nach Dividenden,
Management Fees, Darlehen an Nahestehende, Boni für den Verkauf und anderen Zahlungen an die Verkäuferin mit einem
Datum nach dem Stichtag. Im grossen Testfall steht eine Management Fee von CHF 60'000 an die Holding der Aktionärin
in der Q&A-Liste; Zitatio meldet sie als Warnsignal und ordnet sie der Garantie „Keine Leakage“ zu.

### Red-Flag-Bericht ohne DD-Bericht

Vor dem ersten Entwurf gibt es nur den Datenraum. `zitatio redflags -d datenraum -o red-flags.html` (oder das
Hochladen ohne Bericht) prüft ihn allein: Warnsignale aus Handelsregister, Protokollen, Verträgen und Jahresrechnungen,
Widersprüche zwischen Dokumenten, Nettoverschuldung, Closing-Liste, Garantien (mit `--spa`) und die Fragenliste an
den Verkäufer. Im grossen Testfall: 7 Warnsignale und 25 Fragen, ohne eine Zeile Bericht.

### Belegsuche ohne Fundstellen

Ein Information Memorandum oder eine Management-Präsentation nennt Zahlen ohne Seite. Hat ein Dokument keine einzige
Fundstelle, sucht Zitatio die Belege selbst: Es ordnet alle Seiten des Datenraums nach Ähnlichkeit zur Aussage
(BM25, bei kurzen Sätzen mit dem Satz davor) und prüft die Werte auf den besten Seiten wie bei einer zitierten
Aussage. Was gefunden wird, ist „Geprüft“ mit der gefundenen Fundstelle; was nicht, bleibt „Ohne Beleg“. Nennt eine
passende Tabelle für dieselbe Grösse und dasselbe Jahr einen anderen Wert, ist es eine „Abweichung“. Im grossen
Testfall ohne Fundstellen: 122 von 155 richtigen Aussagen belegt, kein falscher Wert als geprüft durchgelassen, 5 von
11 falschen Werten als Abweichung erkannt (siehe `ergebnis.txt`). In einem Bericht mit Fundstellen bleibt eine Aussage
ohne Fundstelle „Ohne Beleg“, mit dem gefundenen Beleg als Hinweis.

### Fragenliste an den Verkäufer

Aus den Befunden, die nur der Verkäufer klären kann, macht Zitatio eine nummerierte Fragenliste mit Priorität und
Fundstelle: fehlende Unterlagen und Nachträge, Widersprüche zwischen Dokumenten, Warnsignale aus Protokollen und
Handelsregister, Zustimmungen zum Kontrollwechsel, auslaufende Verträge, Bereinigungen ohne Beleg und offene
Verfahren. Sie steht unten im Prüfbericht, im Blatt „Fragenliste“ der Excel-Mappe (mit Spalte für die Antwort) und
mit `--fragen fragen.md` als Markdown. Falsche Fundstellen im eigenen Bericht kommen nicht hinein.
Steht in der Q&A-Liste des Datenraums schon ein Eintrag zum Thema, nennt die Frage ihn („Q&A 5“).

### Antwortentwürfe für Käuferfragen

Für die Verkäuferseite: `zitatio antworten fragen.xlsx -d datenraum -o antworten.md` nimmt die Fragenliste der
Käufer (Excel mit Spalte „Frage“, Text oder Markdown) und sucht zu jeder Frage den Satz im Datenraum, der sie
beantwortet, mit Dokument und Seite. Gefragt wird nach einem Wert („wie hoch“, „wann“, „wie lange“), zählen nur
Sätze mit einem Wert dieser Art. Nennt der Datenraum für diesen Wert verschiedene Zahlen, steht das bei der Antwort.
Findet Zitatio nichts Tragfähiges, steht „Im Datenraum nicht gefunden“ statt einer erfundenen Antwort.

### Neuer Stand des Datenraums

`--datenraum-vorher alter-export/` vergleicht zwei Exporte nach Indexnummer und Prüfsumme: welche Dokumente neu,
entfernt oder ersetzt sind, auf welchen Seiten sich ein ersetztes Dokument geändert hat und welche Werte vorher und
nachher dastehen. Aussagen des Berichts, die eine geänderte Seite zitieren, sind verlinkt, damit nur sie neu gelesen
werden müssen.

### Fristenkalender

Vertragsenden, der letzte Tag für eine Kündigung auf das Vertragsende und Ablaufdaten von Zertifikaten und
Bewilligungen stehen im Prüfbericht unter „Fristen“ und mit `--kalender fristen.ics` als Kalenderdatei für Outlook
oder Google Kalender, mit Erinnerung 14 Tage vorher. Jeder Termin nennt die Fundstelle. Passt ein Kündigungstermin
(etwa „auf Jahresende“) nicht zum Vertragsende, rechnet Zitatio keinen Termin aus, statt einen zu erfinden.

### Prüfungen im Datenraum

| Prüfung | Was Zitatio tut |
|---|---|
| Zeichnungsberechtigung | Liest Einzel- und Kollektivunterschriften aus dem Handelsregisterauszug und prüft jeden Unterschriftenblock „Für die … AG“. Warnt, wenn jemand ohne Eintrag oder mit Kollektivunterschrift allein unterschreibt. |
| Kapitalschutz | Hälftiger Kapitalverlust und Überschuldung nach Art. 725a/b OR aus der neuesten Bilanz. |
| Revisionspflicht | Schwellen nach Art. 727 OR (Bilanzsumme, Umsatz, Vollzeitstellen) gegen die Revisionsart. |
| Vorsorge | Deckungsgrad der Pensionskasse unter 100 %. |
| Aktienbuch | Verbuchte Aktien gegen Handelsregister. |
| Fusionskontrolle | Umsatzschwelle Art. 9 KG; Lex Koller bei Grundeigentum. |
| Indirekte Teilliquidation | Halten natürliche Personen laut Aktienbuch zusammen mindestens 20 %, Hinweis auf Art. 20a Abs. 1 lit. a DBG mit den handelsrechtlich ausschüttbaren Reserven; im SPA-Abgleich als fehlende Steuerklausel. |
| Leakage und Verrechnungssteuer | Zahlungen an die Aktionärin nach dem Locked-Box-Stichtag, mit Hinweis auf 35 % Verrechnungssteuer bei geldwerten Leistungen. |
| MWST-Umsatzabstimmung | Summe der Ziffer 200 aller Quartalsabrechnungen gegen die Nettoerlöse der Jahresrechnung; Lücke über 1 % mit möglicher Nachsteuer (8.1 %), Verzugszins (Art. 87 MWSTG) und Verjährung (Art. 42 MWSTG). Steuer pro Quartal nachgerechnet, fehlende Quartale gemeldet. |
| Datenschutz im Datenraum | AHV-Nummern (mit Prüfziffer) und Gesundheitsdaten zu einzelnen Personen (Art. 5 lit. c DSG) pro Dokument; vor der Weitergabe schwärzen oder in einen Clean Room verschieben. |
| Arbeitsverträge | Konkurrenzverbot über drei Jahre (Art. 340a OR; fällt bei Kündigung ohne begründeten Anlass dahin, Art. 340c OR) als Hinweis; Ferien unter vier Wochen (Art. 329a OR, zwingend) als Warnsignal mit Freistellung. |
| Steuerbarer Gewinn | Steuerbarer Reingewinn der Veranlagung gegen den Jahresgewinn (Massgeblichkeit, Art. 58 DBG; Steuern sind abziehbar, Art. 59 DBG). Über 10 % höher: Aufrechnungen, Aufstellung verlangen; tiefer: Verlustvorträge prüfen. |
| Datenraum-Index | Liegt ein Index oder eine Dokumentenliste im Datenraum, meldet Zitatio jede aufgeführte Nummer ohne Dokument. |
| Sanktionen | Mit `--sanktionen liste.xml` (Gesamtliste des SECO, CSV oder ein Name pro Zeile) gleicht Zitatio Aktionäre, Zeichnungsberechtigte und Firmen im Datenraum ab, unabhängig von der Reihenfolge von Vor- und Nachname. Nichts wird aus dem Internet geladen. |
| Erfolgsrechnung nachgerechnet | Jede Spalte: EBITDA = Umsatz − Material − Personal − übriger Aufwand, EBIT, Jahresgewinn. Findet falsch übertragene Zeilen. |
| Monatsabschlüsse nachgerechnet | Summe der Monatsblätter gegen „kumuliert“ oder „Total“ in der Übersicht der Management Accounts. |
| Management Reporting gegen Jahresrechnung | Umsatz und EBITDA aus der Summe der Monatsblätter (TCHF erkannt) gegen die Jahresrechnung; über 5 % Abweichung: Überleitung verlangen. |
| Covenant | „Nettoverschuldung höchstens x-mal EBITDA“ aus dem Kreditvertrag, nachgerechnet aus der Bilanz. |
| Nachträge | Erwähnt ein Vertrag einen Nachtrag, eine Zusatzvereinbarung oder einen Side Letter, der nicht im Datenraum liegt, ist das ein Warnsignal: Werte aus dem Grundvertrag können überholt sein. |
| Protokolle | Steuerprüfung, Klage, Rückruf, Sanierung, Abgänge und weitere Themen aus VR- und GV-Protokollen; Warnung, wenn der Bericht das Thema nirgends anspricht. |

Gesetzliche Sätze im Bericht (MWST je nach Jahr, Verrechnungssteuer, Emissionsabgabe, AHV/IV/EO, BVG-Umwandlungssatz,
direkte Bundessteuer) werden gegen das Gesetz geprüft: Ein veralteter MWST-Satz von 7.7 % ist eine Abweichung.

### Verträge und Closing-Liste

Das Vertragsregister zeigt pro Vertrag Kontrollwechsel, Exklusivität, Konkurrenzverbot, Konventionalstrafe,
Abtretung mit Zustimmung, Meistbegünstigung, Haftungsbegrenzung und Garantien, jeweils mit Seite und Satz, dazu Ende
und Kündigungsfrist. Aussagen wie „enthält keine Change-of-Control-Klausel“ werden dagegen geprüft. Die Closing-Liste
nennt die Gegenparteien, die vor dem Closing zustimmen müssen, das jährliche Volumen daran (Anteil am Umsatz), und
Verträge, die abgelaufen sind oder in den nächsten 18 Monaten enden.

### Nettoverschuldung

Finanzschulden und flüssige Mittel aus der Bilanz, dazu schuldenähnliche Posten aus dem Datenraum (Leasing bis
Laufzeitende, Verbindlichkeiten gegenüber Vorsorgeeinrichtungen, beschlossene Dividenden) und Klagen als
Eventualverbindlichkeiten. Aussagen zur Nettoverschuldung und zum Covenant werden nachgerechnet.

### Widersprüche im Bericht und Versionsvergleich

Nennt der Bericht für dieselbe Grösse und Periode an zwei Stellen verschiedene Werte, steht das im Prüfbericht.
Mit `--vorher` vergleicht Zitatio zwei Entwürfe: welche Befunde behoben, offen oder neu sind, mit wortweisem
Unterschied. `--entscheide` übernimmt Zustimmen/Widersprechen und Notizen aus dem CSV der Vorversion für
unveränderte Aussagen. Das CSV hält die Prüfsumme jedes zitierten Dokuments fest: Hat der Verkäufer ein Dokument
inzwischen ersetzt, wird der Entscheid nicht übernommen, und die Aussage ist mit „Entscheid neu nötig“ markiert.
Beides geht auch im Upload-Formular der Weboberfläche.

## Benchmark

`zitatio benchmark` baut aus jeder Zeile des Datenraums mit einem prüfbaren Wert eine korrekt belegte Aussage und
dazu Varianten mit genau einem Fehler: Zahlendreher oder falscher Wert, falsche Seite, fehlendes Dokument, fehlende
Fundstelle, sowie korrekte Werte in anderer Schreibweise, korrekt gerundete und falsch gerundete Beträge. Ausgegeben wird die Trefferquote pro Fehlerart.

Das prüft die Regeln gegen bekannte Fehlerarten. Für eine Aussage über echte Berichte braucht es zusätzlich einen
Benchmark mit anonymisierten, von Menschen geschriebenen DD-Berichten.

### Grosser Testfall

`beispiele/gross` ist näher an einem echten Deal: 42 Dokumente mit 269 Seiten (PDF und Excel) und ein DD-Bericht
mit 229 Aussagen, von denen nur 16 absichtlich falsch sind. Dazu enthält der Datenraum drei Widersprüche, wie sie bei
falschen Angaben des Verkäufers vorkommen, und neun Warnsignale im Datenraum (eine falsch übertragene Zeile der Erfolgsrechnung, eine Übersicht der
Management Accounts, die nicht zur Summe der Monate passt,
zwei Unterschriften ohne Zeichnungsberechtigung, eine angekündigte Steuerprüfung im VR-Protokoll, ein fehlender
Nachtrag zum Mietvertrag, eine Zahlung an die Aktionärin nach dem Locked-Box-Stichtag, eine Lücke von
CHF 1.24 Mio. zwischen MWST-Abrechnungen und Jahresrechnung, AHV-Nummer und Gesundheitsdaten im Arbeitsvertrag).
`wahrheit.json` hält fest, welche Aussage richtig ist, `widersprueche.json` und `warnsignale.json`, was im Datenraum
eingebaut ist. `dd-bericht-v2.md` (aus `entwurf2.py`) ist ein zweiter Entwurf für den Versionsvergleich.

```bash
python beispiele/gross/erzeugen.py    # Datenraum und Bericht neu erzeugen (fester Zufall)
python beispiele/gross/auswerten.py   # Zitatio laufen lassen und gegen die Wahrheit vergleichen
```

Ergebnis ohne Prüfmodell (siehe `beispiele/gross/ergebnis.txt`): alle 16 Fehler gefunden, kein Fehlalarm bei 213
richtigen Aussagen, alle 3 Widersprüche im Datenraum und alle 12 Warnsignale gefunden (9 im Datenraum, 3 im SPA-Entwurf), keines zu viel, Laufzeit rund
1 Sekunde. Gefunden werden auch Vorjahresspalte, EBIT statt Jahresgewinn, ein erfundenes Zitat, ein falsch zitierter Q&A-Eintrag, eine Bereinigung
ohne Beleg, ein veralteter MWST-Satz und eine übersehene Kontrollwechselklausel. Wachstum, Marge, zwei Summen und
der Covenant werden nachgerechnet und sind geprüft. 45 richtige Aussagen ohne Zahlen bleiben „Ungeprüft“ und
müssen gelesen werden.

Die Aussagen im Bericht sind generiert und lehnen sich eng an die Formulierungen im Datenraum an. Echte Berichte
umschreiben freier; die Zahlen hier sind deshalb eher eine obere Grenze.

### Echte Jahresberichte: FinanceBench

[FinanceBench](https://github.com/patronus-ai/financebench) (Patronus AI, CC BY-NC 4.0) enthält 150 Fragen zu echten
US-Jahres- und Quartalsberichten. Zu jeder Antwort steht die Seite, auf der der Beleg steht. Das Skript macht aus jeder
Antwort mit Betrag oder Prozentwert einen Satz mit Fundstelle, in drei Varianten: richtig, mit um 8 % falschem Wert und
mit falscher Seite. Die PDFs bleiben wegen der Lizenz ausserhalb des Repos.

```bash
git clone --depth 1 https://github.com/patronus-ai/financebench /tmp/financebench
python scripts/financebench_test.py /tmp/financebench --out /tmp/fb-test
```

Ergebnis (33 Antworten, 30 Berichte mit 4'850 Seiten, Prüfzeit rund 18 Sekunden):

| Art der Antwort | richtig bestätigt | falscher Wert erkannt | falsche Seite erkannt |
|---|---|---|---|
| direkt abgelesen (14) | 14 | 12 | 14 |
| berechnet, z. B. Marge, Durchschnitt, Free Cashflow (19) | 0, davon 18 „Ungeprüft“ | 1 | 1 |

Direkt abgelesene Werte prüft Zitatio auch in US-Tabellen mit „(in millions)“ zuverlässig. Zwei falsche Summen bleiben
„Ungeprüft“, weil das Wort „total“ sie als abgeleitet markiert. Berechnete Kennzahlen kann Zitatio in diesen Berichten
noch nicht nachrechnen und meldet sie ehrlich als „Ungeprüft“. Es gibt einen Fehlalarm, weil der generierte Satz eine
Quote als Abschreibung beschreibt.

Derselbe Bericht ohne Fundstellen (Belegsuche über alle 4'850 Seiten, rund 5 Sekunden): 6 von 14 direkt abgelesenen
Werten findet Zitatio selbst, kein falscher Wert wird als geprüft durchgelassen. Die generierten Sätze sind hier
englisch-deutsche Mischformen wie „die gefragte Kennzahl“, die Suche hat also wenig Wörter, an denen sie sich
orientieren kann.

## Prüfmodell (optional)

```bash
export ZITATIO_LLM_BASE_URL=http://localhost:8000/v1   # vLLM, Ollama oder Infomaniak
export ZITATIO_LLM_MODEL=swiss-ai/Apertus-8B-Instruct-2509
export ZITATIO_LLM_API_KEY=...                         # falls nötig
zitatio pruefen bericht.md -d datenraum --modell
```

Ohne Prüfmodell verlässt kein Dokument den Rechner.

## Aufbau

```
src/zitatio/
  facts.py     Werte erkennen und normalisieren (CHF 3.5 Mio. = CHF 3'500'000), UID-Prüfziffer
  dataroom.py  Datenraum einlesen (Indexnummer, Seitentexte, Hashes)
  docx.py      Word-Dateien ohne Zusatzpaket lesen
  xlsx.py      Excel-Dateien ohne Zusatzpaket lesen (Zahlen so, wie Excel sie anzeigt)
  benchmark.py Trefferquote mit künstlich eingebauten Fehlern
  report.py    Bericht in Aussagen und Fundstellen zerlegen
  tables.py    Zeilen und Spalten: zu welcher Grösse und welchem Jahr ein Wert gehört
  verify.py    Prüfkern: Status, Begründung, Belegstellen, Zitate, Dokumentbezug; optionales Prüfmodell
  crosscheck.py Widersprüche zwischen Datenraum-Dokumenten
  derive.py    Abgeleitete Werte und EBITDA-Bereinigungen nachrechnen
  consistency.py Widersprüche im Bericht, Erfolgsrechnungen nachrechnen
  swiss.py     Handelsregister, Zeichnungsberechtigung, Art. 725/727 OR, Vorsorge, WEKO, Lex Koller, gesetzliche Sätze
  clauses.py   Vertragsregister: Klauseln mit Seite und Satz
  terms.py     Laufzeiten, Kündigungsfristen, Volumen, Closing-Liste
  netdebt.py   Nettoverschuldung, schuldenähnliche Posten, Covenant
  valuation.py Preisbrücke: Unternehmenswert, Equity Value, Preiswirkung der Befunde
  questions.py Fragenliste an den Verkäufer
  locate.py    Belegsuche ohne Fundstellen (BM25 über alle Seiten)
  spa.py       Garantien im SPA-Entwurf gegen die Befunde
  leakage.py   Zahlungen an die Verkäuferin nach dem Locked-Box-Stichtag
  minutes.py   Themen aus VR-Protokollen, die der Bericht nicht erwähnt
  references.py Erwähnte Nachträge und Side Letters, die im Datenraum fehlen
  versions.py  Versionsvergleich zweier Entwürfe, Entscheide übernehmen
  summary.py   Das Wichtigste fürs IC, Markdown fürs Memo
  excel.py     Excel-Mappe mit Formeln, ohne Zusatzpaket geschrieben
  gaps.py      Lückenliste der üblichen DD-Unterlagen
  llm.py       OpenAI-kompatibler Client für das Prüfmodell
  render.py    Prüfbericht als HTML, JSON, CSV und Offenlegungskarte
  cli.py       Kommandozeile
  web.py       Lokale Weboberfläche (FastAPI)
beispiele/alpenblick/  Fiktiver Datenraum mit DD-Bericht und absichtlich eingebauten Fehlern
```

## Grenzen des Prototyps

- „Geprüft“ ohne Prüfmodell heisst, dass die Werte auf der Seite stehen, nicht dass sie dort dasselbe bedeuten.
- Gescannte PDFs ohne Textebene werden erkannt und gemeldet, aber noch nicht per OCR gelesen.
- Zeilen und Jahresspalten werden nur für die oben genannten Grössen erkannt, und nur, wenn der Tabellenkopf die Jahre
  in derselben Anzahl nennt wie die Zeile Werte hat. Sonst bleibt es bei der Prüfung „Wert steht auf der Seite“.
- Widersprüche werden nur für Tabellenzeilen mit bekannter Grösse und Periode gefunden, nicht in Fliesstext.
- Die Lückenliste erkennt Unterlagen am Dateinamen, nicht am Inhalt.
- Klauseln, Laufzeiten und Protokoll-Themen werden mit Wortmustern erkannt. Eine ungewöhnlich formulierte Klausel
  fehlt im Register; ein Thema in den Protokollen kann im Bericht mit anderen Worten behandelt sein.
- Schuldenähnliche Posten sind ein Vorschlag für die Verhandlung, keine abschliessende Liste. Leasing wird aus Rate,
  Laufzeitende und Restwert geschätzt.
- In US-Berichten, die jede Zahl auf eine eigene Zeile setzen, fehlen Zeilenbeschriftungen. Kennzahlen wie Margen
  oder Durchschnitte werden dort deshalb noch nicht nachgerechnet.
- Steht derselbe Wert auf einer anderen Seite, meldet Zitatio „Falsche Fundstelle“ nur, wenn ein Wort der Aussage
  kurz davor steht und das Dokument zur Aussage passt. Sonst bleibt es bei „Abweichung“.
- Zefix- und SHAB-Abgleich folgen; dafür braucht es Zugangsdaten zur Zefix-REST-Schnittstelle.
