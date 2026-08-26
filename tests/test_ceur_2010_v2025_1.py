from argentina_geography.sources.ceur_2010_v2025_1_probe import load_config


def test_ceur_2010_v2025_1_source_identity_is_pinned() -> None:
    config = load_config()
    assert config["authority_status"] == "curated_research"
    assert config["release"] == "V2025-1"
    assert config["file_name"] == "RADIOS_2010_V2025-1.zip"
    assert config["target_vintage"] == "2010"
    assert config["download_url"].endswith("RADIOS_2010_V2025-1.zip?isAllowed=y&sequence=14")
