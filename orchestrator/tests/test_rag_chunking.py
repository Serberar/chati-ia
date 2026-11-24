import pytest

from chat.rag import _chunk_text, _sanitize_filename


def test_chunk_text_empty_returns_no_chunks():
    assert _chunk_text("") == []
    assert _chunk_text("   \n  ") == []


def test_chunk_text_short_text_single_chunk():
    text = "Esto es un texto corto."
    chunks = _chunk_text(text, size=900, overlap=150)
    assert len(chunks) == 1
    assert chunks[0] == text


def test_chunk_text_splits_long_text_respecting_sentences():
    text = " ".join(f"Esta es la frase numero {i}." for i in range(60))
    chunks = _chunk_text(text, size=200, overlap=50)
    assert len(chunks) > 1
    for c in chunks:
        assert c.rstrip().endswith(".")
        assert len(c) <= 200 + 60


def test_chunk_text_overlap_repeats_trailing_sentence():
    text = " ".join(f"Frase {i} de la lista." for i in range(30))
    chunks = _chunk_text(text, size=150, overlap=40)
    assert len(chunks) > 1
    first_words = set(chunks[0].split())
    second_words = set(chunks[1].split())
    assert first_words & second_words, "deberia haber solape entre chunks consecutivos"


def test_chunk_text_oversized_sentence_is_split_without_cutting_words():
    text = "palabra " * 500
    chunks = _chunk_text(text, size=200, overlap=50)
    assert len(chunks) > 1
    assert max(len(c) for c in chunks) <= 200 + 200 // 3 + 10
    assert all(w == "palabra" for c in chunks for w in c.split())


def test_chunk_text_normalizes_whitespace():
    text = "linea uno\n\n\nlinea   dos\tcon tabulador"
    chunks = _chunk_text(text)
    assert len(chunks) == 1
    assert "\n" not in chunks[0]
    assert "  " not in chunks[0]


def test_sanitize_filename_strips_path_traversal():
    assert _sanitize_filename("../../etc/passwd") == "passwd"
    assert _sanitize_filename("C:\\Windows\\System32\\evil.dll") == "evil.dll"
    assert _sanitize_filename("informe.pdf") == "informe.pdf"
    assert _sanitize_filename("nota.txt:oculto.pdf") == "nota.txt_oculto.pdf"
    assert _sanitize_filename('a<b>"c|d?.txt') == "a_b__c_d_.txt"


def test_sanitize_filename_rejects_empty_result():
    with pytest.raises(ValueError):
        _sanitize_filename("..")
    with pytest.raises(ValueError):
        _sanitize_filename("...")
