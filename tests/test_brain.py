import shutil

import pytest

from second_brain import SecondBrain
from second_brain.embeddings import HashEmbedder
from second_brain.store import IndexMismatchError

from conftest import DOCS


def _copy_docs(brain):
    shutil.copytree(DOCS, brain.settings.docs_dir, dirs_exist_ok=True)


def test_ingest_indexes_every_document(brain):
    _copy_docs(brain)
    report = brain.ingest()
    assert len(report.added) == 7
    assert {d["source"] for d in brain.list_documents()} >= {
        "leases/apartment-lease.md",
        "insurance/auto-policy.pdf",
    }


def test_reingest_is_incremental(brain):
    _copy_docs(brain)
    brain.ingest()
    report = brain.ingest()
    assert report.added == [] and report.updated == [] and len(report.unchanged) == 7


def test_changed_file_is_reindexed(brain):
    _copy_docs(brain)
    brain.ingest()
    gym = brain.settings.docs_dir / "memberships" / "gym.md"
    gym.write_text(gym.read_text() + "\n\nThe sauna closes at 9pm.")
    report = brain.ingest()
    assert report.updated == ["memberships/gym.md"]
    assert any("sauna" in h.text for h in brain.search("when does the sauna close"))


def test_deleted_file_is_pruned(brain):
    _copy_docs(brain)
    brain.ingest()
    (brain.settings.docs_dir / "notes" / "2026-goals.md").unlink()
    report = brain.ingest()
    assert report.removed == ["notes/2026-goals.md"]
    assert brain.get_document("notes/2026-goals.md") is None


def test_pii_never_reaches_the_index(brain):
    _copy_docs(brain)
    report = brain.ingest()
    stored = brain.store.all_text()
    for raw in ["123-45-6789", "4111 1111 1111 1111", "000123456789", "021000021"]:
        assert raw not in stored
    assert report.redactions["ssn"] == 1
    assert report.redactions["credit_card"] == 1


def test_search_finds_the_right_document(brain):
    _copy_docs(brain)
    brain.ingest()
    hits = brain.search("collision deductible")
    assert hits and hits[0].source == "insurance/auto-policy.pdf"


def test_off_topic_query_returns_nothing(brain):
    _copy_docs(brain)
    brain.ingest()
    assert brain.search("dentist appointment") == []


def test_embedder_mismatch_is_refused(settings):
    settings.docs_dir.mkdir()
    SecondBrain(settings, embedder=HashEmbedder(dim=384)).close()
    with pytest.raises(IndexMismatchError):
        SecondBrain(settings, embedder=HashEmbedder(dim=128))
