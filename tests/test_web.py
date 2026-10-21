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


def test_upload_without_report_gives_red_flag_report():
    files = [("datenraum", (f"datenraum/{pdf.name}", pdf.read_bytes(), "application/pdf"))
             for pdf in sorted((EXAMPLE / "datenraum").glob("*.pdf"))]
    response = client.post("/pruefen", files=files)
    assert response.status_code == 200
    assert "Red-Flag-Bericht" in response.text and 'class="redflag"' in response.text


def test_buyer_questions_get_answer_drafts():
    files = [("datenraum", (pdf.name, pdf.read_bytes(), "application/pdf"))
             for pdf in sorted((EXAMPLE / "datenraum").glob("*.pdf"))]
    files.append(("kaeuferfragen", ("fragen.md", "1. Besitzt die Gesellschaft Kryptowährungen?\n".encode())))
    response = client.post("/pruefen", files=files)
    assert response.status_code == 200
    assert 'id="antworten"' in response.text and "Im Datenraum nicht gefunden" in response.text


def test_password_and_upload_limit(monkeypatch):
    import io
    import zipfile

    import zitatio.web as web
    from zitatio import dataroom

    monkeypatch.setenv("ZITATIO_PASSWORT", "geheim")
    assert client.get("/").status_code == 401 and client.get("/gesund").json()["status"] == "ok"
    assert client.get("/", auth=("pilot", "falsch")).status_code == 401
    page = client.get("/", auth=("pilot", "geheim"))
    assert page.status_code == 200 and page.headers["x-frame-options"] == "DENY"
    monkeypatch.delenv("ZITATIO_PASSWORT")

    monkeypatch.setattr(web, "MAX_UPLOAD", 1000)
    big = client.post("/pruefen", files=[("datenraum", ("1.1 Gross.txt", b"x" * 2000, "text/plain"))])
    assert big.status_code == 413

    monkeypatch.setattr(dataroom, "MAX_ZIP_BYTES", 10_000)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("1.1 Bombe.txt", "0" * 1_000_000)
    room = dataroom.DataRoom()
    room.add("export.zip", buf.getvalue())
    assert not room.documents and "übersprungen" in room.warnings[0]
