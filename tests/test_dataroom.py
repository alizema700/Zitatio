

def test_vdr_folders_number_the_documents(tmp_path):
    import io
    import zipfile

    from zitatio.dataroom import DataRoom

    files = {"01 Gesellschaft/01 Handelsregisterauszug.txt": "Firma: Muster AG",
             "01 Gesellschaft/1.2 Statuten.txt": "Statuten",
             "02 Finanzen/01 Jahresrechnung 2024.txt": "Jahresrechnung",
             "02 Finanzen/2025 Abschlüsse/03 Zwischenabschluss.txt": "Zwischenabschluss",
             "Diverses/Lageplan.txt": "Lageplan"}
    for name, text in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text, encoding="utf-8")
    room = DataRoom.from_folder(tmp_path)
    assert {d.index: d.title for d in room.documents} == {
        "1.1": "Handelsregisterauszug", "1.2": "Statuten", "2.1": "Jahresrechnung 2024",
        "2.3": "Zwischenabschluss", "0.1": "Lageplan"}
    assert any("DR 0.1" in w for w in room.warnings)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, text in files.items():
            z.writestr(name, text)
    zipped = DataRoom()
    zipped.add("export.zip", buf.getvalue())
    assert sorted(d.index for d in zipped.documents) == sorted(d.index for d in room.documents)


def test_gap_list_reads_the_first_line_of_unnamed_scans():
    from zitatio.dataroom import DataRoom
    from zitatio.gaps import check_gaps

    room = DataRoom()
    room.add("3.1 Scan_0012.txt", b"Auszug aus dem Handelsregister des Kantons Bern\nFirma: Muster AG")
    gaps = {g.name: g.present for g in check_gaps(room)}
    assert gaps["Handelsregisterauszug"] and not gaps["Statuten"]
