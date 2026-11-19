import logging

from config.storage import LenientManifestStaticFilesStorage


def test_a_file_missing_from_the_manifest_is_served_unhashed(tmp_path, caplog):
    storage = LenientManifestStaticFilesStorage(location=tmp_path, base_url="/static/")
    with caplog.at_level(logging.WARNING, logger="config.storage"):
        assert storage.url("css/missing.css") == "/static/css/missing.css"
    assert "css/missing.css" in caplog.text


def test_a_known_file_gets_its_hashed_name(tmp_path):
    storage = LenientManifestStaticFilesStorage(location=tmp_path, base_url="/static/")
    storage.hashed_files = {"css/app.css": "css/app.0123456789ab.css"}
    assert storage.url("css/app.css") == "/static/css/app.0123456789ab.css"
