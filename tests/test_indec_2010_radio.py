from __future__ import annotations

from argentina_geography.sources.indec_2010_radio_probe import load_config


def test_indec_2010_source_registry_has_complete_province_set() -> None:
    config = load_config()
    rows = config["source_files"]
    assert len(rows) == 24
    assert len({row["province_code"] for row in rows}) == 24
    assert {row["province_code"] for row in rows} == {
        "02", "06", "10", "14", "18", "22", "26", "30", "34", "38", "42", "46",
        "50", "54", "58", "62", "66", "70", "74", "78", "82", "86", "90", "94",
    }
    assert all(row["download_url"].startswith("https://www.indec.gob.ar/") for row in rows)
