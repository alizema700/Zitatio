# Zitatio

Prüfschicht für Due-Diligence-Berichte. Zitatio prüft jede Aussage eines DD-Berichts oder IC-Memos gegen den
Datenraum und markiert sie als **Geprüft**, **Abweichung**, **Widerspruch**, **Falsche Fundstelle**, **Quelle fehlt**,
**Ohne Beleg** oder **Ungeprüft**. Zu jedem Status gehören eine Begründung und die Belegstelle.

Dazu prüft Zitatio den Datenraum selbst: Nennen zwei Dokumente für dieselbe Grösse verschiedene Werte, steht das als
Widerspruch im Prüfbericht. EBITDA-Bereinigungen und abgeleitete Werte (Wachstum, Margen, Summen) werden nachgerechnet,
fehlende Standardunterlagen gelistet, und eine Offenlegungskarte hält fest, welche Aussage auf welcher Seite steht.

Stand: Prototyp 0.1. Er prüft Werte (Beträge, Daten, Prozente, Fristen, UIDs) deterministisch. Ein Prüfmodell
für den Sinn einer Aussage kann optional über eine OpenAI-kompatible Schnittstelle angeschlossen werden.

## Schnellstart

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[web,dev]"

# Kommandozeile (HTML, dazu optional JSON, CSV für Excel und die Offenlegungskarte für W&I)
zitatio pruefen beispiele/alpenblick/dd-bericht.md -d beispiele/alpenblick/datenraum -o pruefbericht.html \
  --csv pruefbericht.csv --offenlegung offenlegungskarte.csv

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

## Benchmark

`zitatio benchmark` baut aus jeder Zeile des Datenraums mit einem prüfbaren Wert eine korrekt belegte Aussage und
dazu Varianten mit genau einem Fehler: Zahlendreher oder falscher Wert, falsche Seite, fehlendes Dokument, fehlende
Fundstelle, sowie korrekte Werte in anderer Schreibweise, korrekt gerundete und falsch gerundete Beträge. Ausgegeben wird die Trefferquote pro Fehlerart.

Das prüft die Regeln gegen bekannte Fehlerarten. Für eine Aussage über echte Berichte braucht es zusätzlich einen
Benchmark mit anonymisierten, von Menschen geschriebenen DD-Berichten.

### Grosser Testfall

`beispiele/gross` ist näher an einem echten Deal: 41 Dokumente mit 268 Seiten (PDF und Excel) und ein DD-Bericht
mit 220 Aussagen, von denen nur 14 absichtlich falsch sind. Dazu enthält der Datenraum drei Widersprüche, wie sie bei
falschen Angaben des Verkäufers vorkommen. `wahrheit.json` hält fest, welche Aussage richtig ist,
`widersprueche.json`, welche Grössen im Datenraum widersprüchlich sind.

```bash
python beispiele/gross/erzeugen.py    # Datenraum und Bericht neu erzeugen (fester Zufall)
python beispiele/gross/auswerten.py   # Zitatio laufen lassen und gegen die Wahrheit vergleichen
```

Ergebnis ohne Prüfmodell (siehe `beispiele/gross/ergebnis.txt`): 13 von 14 Fehlern gefunden, kein Fehlalarm bei 206
richtigen Aussagen, alle 3 Widersprüche im Datenraum gefunden und keiner zu viel, Laufzeit rund 1 Sekunde. Gefunden
werden auch Vorjahresspalte, EBIT statt Jahresgewinn, ein erfundenes Zitat und eine Bereinigung ohne Beleg.
Wachstum, Marge und zwei Summen werden nachgerechnet und sind geprüft. Verpasst wird eine falsch beschriebene
Vertragsklausel; dafür braucht es das Prüfmodell. 59 richtige Aussagen ohne Zahlen bleiben „Ungeprüft“ und müssen
gelesen werden.

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

Ergebnis (33 Antworten, 30 Berichte mit 4'850 Seiten, Prüfzeit rund 12 Sekunden):

| Art der Antwort | richtig bestätigt | falscher Wert erkannt | falsche Seite erkannt |
|---|---|---|---|
| direkt abgelesen (14) | 14 | 12 | 14 |
| berechnet, z. B. Marge, Durchschnitt, Free Cashflow (19) | 0, davon 18 „Ungeprüft“ | 1 | 1 |

Direkt abgelesene Werte prüft Zitatio auch in US-Tabellen mit „(in millions)“ zuverlässig. Zwei falsche Summen bleiben
„Ungeprüft“, weil das Wort „total“ sie als abgeleitet markiert. Berechnete Kennzahlen kann Zitatio in diesen Berichten
noch nicht nachrechnen und meldet sie ehrlich als „Ungeprüft“. Es gibt einen Fehlalarm, weil der generierte Satz eine
Quote als Abschreibung beschreibt.

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
- In US-Berichten, die jede Zahl auf eine eigene Zeile setzen, fehlen Zeilenbeschriftungen. Kennzahlen wie Margen
  oder Durchschnitte werden dort deshalb noch nicht nachgerechnet.
- Steht derselbe Wert auf einer anderen Seite, meldet Zitatio „Falsche Fundstelle“ nur, wenn ein Wort der Aussage
  kurz davor steht und das Dokument zur Aussage passt. Sonst bleibt es bei „Abweichung“.
- Zefix- und SHAB-Abgleich folgen; dafür braucht es Zugangsdaten zur Zefix-REST-Schnittstelle.
