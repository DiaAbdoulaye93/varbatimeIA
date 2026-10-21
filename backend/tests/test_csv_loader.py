"""CSV upload parsing."""

import pytest

from app.services.csv_loader import MAX_ROWS, CsvError, load_verbatims
from tests.test_preprocess import INPUT_CSV


def test_reads_the_demo_csv() -> None:
    texts = load_verbatims(INPUT_CSV.read_bytes())
    assert len(texts) == 223
    assert texts[0].startswith("Le réseau coupe")


def test_semicolon_bom_and_extra_columns() -> None:
    data = "﻿Id;Note;Verbatim\n1;3;Très bien, merci\n2;1;\n".encode()
    assert load_verbatims(data) == ["Très bien, merci", ""]


def test_cp1252_fallback() -> None:
    data = "verbatim\nréseau coupé\n".encode("cp1252")
    assert load_verbatims(data) == ["réseau coupé"]


def test_multiline_quoted_verbatims() -> None:
    assert load_verbatims(b'verbatim\n"ligne 1\nligne 2"\n') == ["ligne 1\nligne 2"]


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"", "vide"),
        (b"id,texte\n1,abc\n", "introuvable"),
        (b"verbatim\n", "aucune ligne"),
        (("verbatim\n" + "x\n" * (MAX_ROWS + 1)).encode(), "Trop de lignes"),
    ],
)
def test_rejects_unusable_files(data: bytes, message: str) -> None:
    with pytest.raises(CsvError, match=message):
        load_verbatims(data)
