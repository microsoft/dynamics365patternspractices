from pathlib import Path

from app.fs_browser import list_directory, list_roots


def test_list_roots_includes_home():
    roots = list_roots()
    assert any(r["path"] == str(Path.home().resolve()) for r in roots)


def test_list_directory_home():
    listing = list_directory(str(Path.home()))
    assert listing["path"] == str(Path.home().resolve())
    assert isinstance(listing["entries"], list)


def test_list_directory_rejects_relative():
    try:
        list_directory("BPC Files")
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "absolute" in str(exc).lower()
