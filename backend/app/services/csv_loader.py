"""Read uploaded survey CSV files: a mandatory `verbatim` column, an optional `id` column."""

import csv
import io

VERBATIM_COLUMN = "verbatim"
DELIMITERS = ",;\t"
MAX_ROWS = 2_000
SNIFF_BYTES = 4_096


class CsvError(ValueError):
    """The file cannot be used as an analysis input; the message is shown to the user."""


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        # Excel on Windows (French locale) exports cp1252 by default.
        return data.decode("cp1252")


def load_verbatims(data: bytes) -> list[str]:
    """Return the verbatim texts in file order."""
    text = _decode(data)
    if not text.strip():
        raise CsvError("Le fichier CSV est vide.")
    try:
        dialect: type[csv.Dialect] | csv.Dialect = csv.Sniffer().sniff(
            text[:SNIFF_BYTES], delimiters=DELIMITERS
        )
    except csv.Error:
        dialect = csv.excel

    reader = csv.reader(io.StringIO(text), dialect)
    header = [name.strip().lower() for name in next(reader)]
    if VERBATIM_COLUMN not in header:
        raise CsvError(f"Colonne « {VERBATIM_COLUMN} » introuvable (colonnes lues : {header}).")
    column = header.index(VERBATIM_COLUMN)

    texts = [row[column] if column < len(row) else "" for row in reader if row]
    if not texts:
        raise CsvError("Le fichier CSV ne contient aucune ligne de données.")
    if len(texts) > MAX_ROWS:
        raise CsvError(f"Trop de lignes : {len(texts)} (maximum {MAX_ROWS}).")
    return texts
