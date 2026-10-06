import pytest

from second_brain.chunking import chunk_text


def test_short_text_is_one_chunk():
    assert chunk_text("Hello world.", size=100, overlap=10) == ["Hello world."]


def test_chunks_respect_size():
    text = "\n\n".join(f"Paragraph {i}. " + "word " * 40 for i in range(10))
    chunks = chunk_text(text, size=300, overlap=50)
    assert len(chunks) > 1
    assert all(len(c) <= 300 for c in chunks)


def test_long_paragraph_is_split_on_sentences():
    para = " ".join(f"Sentence number {i} is here." for i in range(60))
    chunks = chunk_text(para, size=200, overlap=0)
    assert all(len(c) <= 200 for c in chunks)
    assert "Sentence number 59 is here." in chunks[-1]


def test_overlap_carries_context_forward():
    text = "\n\n".join(["alpha " * 13, "beta " * 15, "gamma " * 13])
    chunks = chunk_text(text, size=200, overlap=60)
    assert len(chunks) == 2
    assert "beta" in chunks[0] and "beta" in chunks[1] and "gamma" in chunks[1]


def test_no_content_is_lost():
    words = [f"w{i}" for i in range(500)]
    text = "\n\n".join(" ".join(words[i:i + 25]) for i in range(0, 500, 25))
    joined = " ".join(chunk_text(text, size=250, overlap=40))
    assert all(w in joined for w in words)


def test_overlap_must_be_smaller_than_size():
    with pytest.raises(ValueError):
        chunk_text("x", size=10, overlap=10)
