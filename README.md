# Zitatio

Prüfschicht für Due-Diligence-Berichte. Zitatio prüft jede Aussage eines DD-Berichts oder IC-Memos gegen den
Datenraum und markiert sie als **Geprüft**, **Abweichung**, **Falsche Fundstelle**, **Quelle fehlt**,
**Ohne Beleg** oder **Ungeprüft**. Zu jedem Status gehören eine Begründung und die Belegstelle.

Stand: Prototyp 0.1. Er prüft Werte (Beträge, Daten, Prozente, Fristen, UIDs) deterministisch. Ein Prüfmodell
für den Sinn einer Aussage kann optional über eine OpenAI-kompatible Schnittstelle angeschlossen werden.

## Schnellstart

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[web,dev]"

# Kommandozeile (HTML, dazu optional JSON und CSV für Excel)
zitatio pruefen beispiele/alpenblick/dd-bericht.md -d beispiele/alpenblick/datenraum -o pruefbericht.html --csv pruefbericht.csv

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
| Abweichung | Ein Wert fehlt an der Fundstelle (die nächstliegenden Werte dort werden genannt), die UID-Prüfziffer ist falsch, oder das Prüfmodell widerspricht. |
| Falsche Fundstelle | Die Werte stehen im Datenraum, aber auf einer anderen Seite oder in einem anderen Dokument. |
| Quelle fehlt | Das zitierte Dokument oder die zitierte Seite gibt es nicht. |
| Ohne Beleg | Die Aussage enthält Werte, aber keine Fundstelle. Ein passender Beleg wird vorgeschlagen, wenn es einen gibt. |
| Ungeprüft | Die Fundstelle existiert, aber die Aussage hat keine prüfbaren Werte. Die ähnlichste Textstelle wird als Lesehilfe gezeigt. |

Zwei Fälle aus dem DD-Alltag zählen als übereinstimmend und werden in der Begründung ausgewiesen:

- **Gerundete Werte:** „CHF 18.45 Mio.“ stimmt mit CHF 18'450'312 überein, weil die Schreibweise auf 10'000 genau
  ist, aber nur bei höchstens 1 % Abstand. „CHF 3 Mio.“ für CHF 3'400'000 bleibt eine Abweichung. Prozente runden
  nur, wenn die Aussage Nachkommastellen hat: „12.4 %“ passt zu 12.38 %, „2 %“ nicht zu 2.4 %.
- **Tabellen ohne Währung:** Nennt eine Seite genau eine Einheit im Kopf („in CHF“, „in TCHF“, „in Mio. CHF“),
  gelten Zahlen ohne Währung auf dieser Seite in dieser Einheit. Jahreszahlen und kleine Nummern werden ignoriert.
  Stehen zwei Einheiten auf einer Seite, wird nichts angenommen.

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

`beispiele/gross` ist näher an einem echten Deal: 40 Dokumente mit 264 Seiten (PDF und Excel) und ein DD-Bericht
mit 212 Aussagen, von denen nur 12 absichtlich falsch sind. `wahrheit.json` hält fest, welche Aussage richtig ist.

```bash
python beispiele/gross/erzeugen.py    # Datenraum und Bericht neu erzeugen (fester Zufall)
python beispiele/gross/auswerten.py   # Zitatio laufen lassen und gegen die Wahrheit vergleichen
```

Ergebnis ohne Prüfmodell (siehe `beispiele/gross/ergebnis.txt`): 9 von 12 Fehlern gefunden, 5 Fehlalarme bei 200
richtigen Aussagen, Laufzeit rund 1 Sekunde. Die Fehlalarme sind alle berechnete Werte (Wachstum, Marge, Summen),
die so nicht an der Fundstelle stehen. Verpasst werden Fehler, bei denen der Wert auf der Seite steht, aber etwas
anderes bedeutet (Vorjahresspalte, EBIT statt Jahresgewinn), und eine falsch beschriebene Vertragsklausel. Dafür
braucht es das Prüfmodell. 58 richtige Aussagen ohne Zahlen bleiben „Ungeprüft“ und müssen gelesen werden.

Die Aussagen im Bericht sind generiert und lehnen sich eng an die Formulierungen im Datenraum an. Echte Berichte
umschreiben freier; die Zahlen hier sind deshalb eher eine obere Grenze.

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
  verify.py    Prüfkern: Status, Begründung, Belegstellen; optionales Prüfmodell
  llm.py       OpenAI-kompatibler Client für das Prüfmodell
  render.py    Prüfbericht als HTML, JSON und CSV
  cli.py       Kommandozeile
  web.py       Lokale Weboberfläche (FastAPI)
beispiele/alpenblick/  Fiktiver Datenraum mit DD-Bericht und absichtlich eingebauten Fehlern
```

## Grenzen des Prototyps

- „Geprüft“ ohne Prüfmodell heisst, dass die Werte auf der Seite stehen, nicht dass sie dort dasselbe bedeuten.
- Gescannte PDFs ohne Textebene werden erkannt und gemeldet, aber noch nicht per OCR gelesen.
- Excel-Tabellen werden als Text gelesen; ob eine Zahl zur richtigen Zeile oder zum richtigen Jahr gehört, prüft
  erst das Prüfmodell.
- Zefix- und SHAB-Abgleich folgen; dafür braucht es Zugangsdaten zur Zefix-REST-Schnittstelle.
