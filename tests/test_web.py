import json
from pathlib import Path

from fastapi.testclient import TestClient

from zitatio.web import app

EXAMPLE = Path(__file__).resolve().parents[1] / "beispiele" / "alpenblick"
client = TestClient(app)


def test_index_and_example():
    page = client.get("/").text
    assert "Kein Satz ohne Beleg" in page
    assert "{graph}" not in page and "\"aussagen\"" in page
    assert "Prüfprotokoll" in client.get("/beispiel").text


def test_hero_shows_real_findings_from_large_test():
    page = client.get("/").text
    assert "{hero}" not in page
    data = json.loads(page.split('id="hero-data">', 1)[1].split("</script>", 1)[0])
    assert data["seiten"] > 200 and len(data["dokumente"]) > 30
    labels = {b["label"] for b in data["befunde"]}
    assert {"Geprüft", "Abweichung", "Widerspruch", "Falsche Fundstelle"} <= labels
    for b in data["befunde"]:
        assert b["belege"] and all(0 <= e["seite"] < data["seiten"] for e in b["belege"])


def test_upload():
    files = [("bericht", ("dd-bericht.md", (EXAMPLE / "dd-bericht.md").read_bytes()))]
    for pdf in sorted((EXAMPLE / "datenraum").glob("*.pdf")):
        files.append(("datenraum", (f"datenraum/{pdf.name}", pdf.read_bytes(), "application/pdf")))
    response = client.post("/pruefen", files=files)
    assert response.status_code == 200
    assert "Quelle fehlt" in response.text


def test_upload_with_previous_version():
    report = (EXAMPLE / "dd-bericht.md").read_bytes()
    files = [("bericht", ("v2.md", report)), ("vorher", ("v1.md", report))]
    for pdf in sorted((EXAMPLE / "datenraum").glob("*.pdf")):
        files.append(("datenraum", (pdf.name, pdf.read_bytes(), "application/pdf")))
    response = client.post("/pruefen", files=files)
    assert response.status_code == 200
    assert "Änderungen gegenüber der Vorversion" in response.text and "0 geändert, 0 neu" in response.text
