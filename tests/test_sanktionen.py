"""Namen im Datenraum gegen eine Sanktionsliste."""

from pathlib import Path

from zitatio.dataroom import DataRoom
from zitatio.sanktionen import check_sanctions, read_list

GROSS = Path(__file__).resolve().parents[1] / "beispiele" / "gross"
SECO = """<?xml version="1.0" encoding="UTF-8"?>
<swiss-sanctions-list><target ssid="1"><individual><identity><name>
<name-part name-part-type="given-name"><value>Luca</value></name-part>
<name-part name-part-type="family-name"><value>Fässler</value></name-part>
</name></identity></individual></target>
<target ssid="2"><entity><identity><name><name-part><value>Nordlicht Medical GmbH</value></name-part></name>
</identity></entity></target>
<target ssid="3"><entity><identity><name><name-part><value>Rheintal</value></name-part></name></identity></entity></target>
</swiss-sanctions-list>""".encode()


def test_names_in_the_data_room_against_the_seco_list():
    names = read_list(SECO, ".xml")
    assert names == ["Luca Fässler", "Nordlicht Medical GmbH", "Rheintal"]
    flags = check_sanctions(DataRoom.from_folder(GROSS / "datenraum"), names, "SECO-Liste")
    titles = {f.title for f in flags}
    # Reihenfolge der Namen egal; ein einzelnes Wort ("Rheintal") trifft nicht
    assert titles == {"Luca Fässler steht auf der SECO-Liste", "Nordlicht Medical GmbH steht auf der SECO-Liste"}
    assert all(f.level == "warnung" and f.evidence for f in flags)


def test_csv_list_without_hits():
    names = read_list("Name;Land\nIvan Petrov;RU\nAcme Trading LLC;AE\n".encode(), ".csv")
    assert names == ["Ivan Petrov", "Acme Trading LLC"]
    flag, = check_sanctions(DataRoom.from_folder(GROSS / "datenraum"), names)
    assert flag.level == "ok"
