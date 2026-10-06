from pathlib import Path

from second_brain import Settings


def test_wiki_dir_defaults_to_wiki(monkeypatch):
    monkeypatch.delenv("SECOND_BRAIN_WIKI", raising=False)
    assert Settings.from_env().wiki_dir == Path("wiki")


def test_wiki_dir_reads_env(monkeypatch, tmp_path):
    monkeypatch.setenv("SECOND_BRAIN_WIKI", str(tmp_path / "my-wiki"))
    assert Settings.from_env().wiki_dir == tmp_path / "my-wiki"
