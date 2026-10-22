"""Read uploaded survey files: CSV/TSV, TXT, JSON, XLSX, DOCX and PDF.

The format is recognised from the file content (magic bytes), the extension only breaks
ties. Executables, scripts, markup and macro-enabled documents are refused, and nothing in
a file is ever executed: only its text is extracted. Messages are shown to the user (French).
"""

import csv
import io
import json
import re
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import PurePath
from typing import Any

from docx import Document
from openpyxl import load_workbook
from pypdf import PdfReader
from pypdf.errors import PdfReadError

MAX_ROWS = 2_000
MAX_PDF_PAGES = 200
MAX_UNZIPPED_BYTES = 50 * 1024 * 1024  # zip bomb guard for .xlsx / .docx
MAX_ZIP_ENTRIES = 2_000
SNIFF_CHARS = 4_096
DELIMITERS = ",;\t"

# Preferred column names, in priority order (compared lowercased, accents kept).
TEXT_COLUMNS = (
    "verbatim",
    "verbatims",
    "réponse",
    "reponse",
    "réponses",
    "reponses",
    "commentaire",
    "commentaires",
    "avis",
    "remarque",
    "remarques",
    "texte",
    "text",
    "comment",
    "comments",
    "feedback",
    "answer",
    "response",
)

# Never accepted, whatever the content looks like.
BLOCKED_EXTENSIONS = frozenset(
    {
        ".js", ".mjs", ".cjs", ".ts", ".html", ".htm", ".xhtml", ".svg", ".xml", ".php",
        ".py", ".rb", ".pl", ".sh", ".bash", ".bat", ".cmd", ".ps1", ".vbs", ".vbe", ".wsf",
        ".exe", ".dll", ".msi", ".com", ".scr", ".jar", ".apk", ".app", ".bin", ".iso",
        ".zip", ".rar", ".7z", ".gz", ".tar", ".xlsm", ".xltm", ".docm", ".dotm", ".pptm",
        ".hta", ".lnk", ".reg",
    }
)  # fmt: skip
SUPPORTED = "CSV, TSV, TXT, JSON, Excel (.xlsx), Word (.docx) ou PDF"

# Magic bytes of formats refused outright.
_DANGEROUS_SIGNATURES = (
    (b"MZ", "un programme Windows"),
    (b"\x7fELF", "un programme Linux"),
    (b"\xcf\xfa\xed\xfe", "un programme macOS"),
    (b"\xca\xfe\xba\xbe", "un programme compilé"),
    (b"#!", "un script"),
    (b"\xd0\xcf\x11\xe0", "un ancien document Office (.doc/.xls), qui peut contenir des macros"),
    (b"Rar!", "une archive"),
    (b"7z\xbc\xaf", "une archive"),
    (b"\x1f\x8b", "une archive"),
)
_MARKUP = re.compile(r"^\s*<(!doctype|html|svg|script|\?xml|head|body|iframe)", re.IGNORECASE)


class FileError(ValueError):
    """The file cannot be used as an analysis input; the message is shown to the user."""


@dataclass(frozen=True)
class LoadedFile:
    texts: list[str]
    source_format: str  # csv | tsv | txt | json | xlsx | docx | pdf
    source_column: str | None = None  # tabular formats: the column read


def load_verbatims(data: bytes, filename: str = "") -> LoadedFile:
    """Return the verbatim texts of an uploaded file, in file order."""
    extension = PurePath(filename).suffix.lower()
    if extension in BLOCKED_EXTENSIONS:
        raise FileError(
            f"Les fichiers {extension} ne sont pas acceptés. Formats acceptés : {SUPPORTED}."
        )
    if not data.strip():
        raise FileError("Le fichier est vide.")
    for signature, kind in _DANGEROUS_SIGNATURES:
        if data.startswith(signature):
            raise FileError(f"Ce fichier est {kind} : il n'est pas accepté.")

    if data.startswith(b"PK\x03\x04"):
        loaded = _load_office(data)
    elif data.startswith(b"%PDF-"):
        loaded = _load_pdf(data)
    else:
        loaded = _load_text(data, extension)

    texts = loaded.texts
    if not any(t.strip() for t in texts):
        raise FileError("Aucune réponse lisible n'a été trouvée dans ce fichier.")
    if len(texts) > MAX_ROWS:
        raise FileError(f"Trop de réponses : {len(texts)} (maximum {MAX_ROWS}).")
    return loaded


# --- Plain text formats ---


def _decode(data: bytes) -> str:
    if b"\x00" in data[:SNIFF_CHARS]:
        raise FileError(
            f"Ce fichier n'est pas un fichier texte lisible. Formats acceptés : {SUPPORTED}."
        )
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        # Excel on Windows (French locale) exports cp1252 by default.
        return data.decode("cp1252")


def _load_text(data: bytes, extension: str) -> LoadedFile:
    text = _decode(data)
    if _MARKUP.match(text):
        raise FileError(
            "Les pages web et fichiers de balisage (HTML, SVG, XML) ne sont pas acceptés."
        )
    stripped = text.lstrip()
    if extension == ".json" or (extension not in (".csv", ".tsv", ".txt") and stripped[:1] in "[{"):
        return _load_json(text)
    if extension == ".txt":
        return LoadedFile(texts=_lines(text), source_format="txt")
    if extension in (".csv", ".tsv") or _looks_tabular(text):
        return _load_csv(text, "tsv" if extension == ".tsv" else "csv")
    return LoadedFile(texts=_lines(text), source_format="txt")


def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _looks_tabular(text: str) -> bool:
    try:
        dialect = csv.Sniffer().sniff(text[:SNIFF_CHARS], delimiters=DELIMITERS)
    except csv.Error:
        return False
    first = next(csv.reader(io.StringIO(text), dialect), [])
    return len(first) > 1 and any(_is_text_column_name(c) for c in first)


def _load_csv(text: str, fmt: str) -> LoadedFile:
    try:
        dialect: type[csv.Dialect] | csv.Dialect = csv.Sniffer().sniff(
            text[:SNIFF_CHARS], delimiters=DELIMITERS
        )
    except csv.Error:
        dialect = csv.excel
    rows = [row for row in csv.reader(io.StringIO(text), dialect) if row]
    return _from_table(rows, fmt)


def _load_json(text: str) -> LoadedFile:
    try:
        payload: Any = json.loads(text)
    except json.JSONDecodeError as exc:
        raise FileError(f"Fichier JSON invalide (ligne {exc.lineno}).") from exc
    if isinstance(payload, dict):
        # {"verbatims": [...]} or any single list value.
        lists = [v for v in payload.values() if isinstance(v, list)]
        if len(lists) != 1:
            raise FileError(
                "JSON attendu : une liste de réponses, ou un objet contenant une liste."
            )
        payload = lists[0]
    if not isinstance(payload, list):
        raise FileError("JSON attendu : une liste de réponses.")
    if all(isinstance(item, str) for item in payload):
        return LoadedFile(texts=[item.strip() for item in payload], source_format="json")
    if all(isinstance(item, dict) for item in payload):
        keys = list(dict.fromkeys(k for item in payload for k in item))
        rows = [keys] + [[_cell(item.get(k)) for k in keys] for item in payload]
        return _from_table(rows, "json")
    raise FileError("JSON attendu : une liste de textes ou une liste d'objets.")


# --- Tables (CSV, JSON objects, XLSX, DOCX tables) ---


def _cell(value: object) -> str:
    return "" if value is None else str(value).strip()


def _is_text_column_name(name: str) -> bool:
    return name.strip().lower() in TEXT_COLUMNS


def _pick_column(header: Sequence[str], rows: Sequence[Sequence[str]]) -> int:
    names = [h.strip().lower() for h in header]
    for wanted in TEXT_COLUMNS:
        if wanted in names:
            return names.index(wanted)

    # No known name: the column with the most free text (long, mostly non-numeric values).
    def score(col: int) -> float:
        values = [r[col] for r in rows if col < len(r) and r[col].strip()]
        if not values:
            return 0.0
        textual = [v for v in values if not re.fullmatch(r"[\d\s.,:/%+-]+", v)]
        return (len(textual) / len(values)) * (sum(len(v) for v in textual) / max(len(textual), 1))

    best = max(range(len(header)), key=score)
    if score(best) == 0:
        raise FileError("Aucune colonne de texte libre n'a été trouvée dans ce tableau.")
    return best


def _from_table(rows: list[list[str]], fmt: str) -> LoadedFile:
    if not rows:
        raise FileError("Le tableau est vide.")
    header, body = rows[0], rows[1:]
    if len(header) == 1 and not _is_text_column_name(header[0]):
        # A single unnamed column: the first line is a response, not a header.
        return LoadedFile(texts=[r[0].strip() for r in rows if r], source_format=fmt)
    if not body:
        raise FileError("Le tableau ne contient aucune ligne de données.")
    col = _pick_column(header, body)
    texts = [row[col].strip() if col < len(row) else "" for row in body]
    return LoadedFile(texts=texts, source_format=fmt, source_column=header[col].strip())


# --- Office documents (zip containers) ---


def _open_zip(data: bytes) -> zipfile.ZipFile:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise FileError("Fichier Office illisible ou corrompu.") from exc
    entries = archive.infolist()
    if len(entries) > MAX_ZIP_ENTRIES or sum(e.file_size for e in entries) > MAX_UNZIPPED_BYTES:
        raise FileError("Fichier trop volumineux une fois décompressé : il n'est pas accepté.")
    if any(e.filename.lower().endswith("vbaproject.bin") for e in entries):
        raise FileError("Ce document contient des macros : il n'est pas accepté.")
    return archive


def _load_office(data: bytes) -> LoadedFile:
    names = set(_open_zip(data).namelist())
    if "xl/workbook.xml" in names:
        return _load_xlsx(data)
    if "word/document.xml" in names:
        return _load_docx(data)
    raise FileError(f"Archive non reconnue. Formats acceptés : {SUPPORTED}.")


def _load_xlsx(data: bytes) -> LoadedFile:
    workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        for sheet in workbook.worksheets:
            rows = [
                [_cell(v) for v in row]
                for row in sheet.iter_rows(values_only=True)
                if any(v is not None and str(v).strip() for v in row)
            ]
            if rows:
                return _from_table(rows, "xlsx")
    finally:
        workbook.close()
    raise FileError("Le classeur Excel est vide.")


def _load_docx(data: bytes) -> LoadedFile:
    document = Document(io.BytesIO(data))
    for table in document.tables:
        rows = [[cell.text.strip() for cell in row.cells] for row in table.rows]
        if len(rows) >= 2:
            return _from_table(rows, "docx")
    texts = [
        p.text.strip()
        for p in document.paragraphs
        if p.text.strip() and not (p.style is not None and _is_heading(p.style.name or ""))
    ]
    return LoadedFile(texts=texts, source_format="docx")


def _is_heading(style_name: str) -> bool:
    return style_name.lower().startswith(("heading", "titre", "title"))


# --- PDF ---


def _load_pdf(data: bytes) -> LoadedFile:
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise FileError("Ce PDF est protégé par un mot de passe : il n'est pas accepté.")
        if len(reader.pages) > MAX_PDF_PAGES:
            raise FileError(f"PDF trop long : {len(reader.pages)} pages (maximum {MAX_PDF_PAGES}).")
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    except PdfReadError as exc:
        raise FileError("PDF illisible ou corrompu.") from exc
    # Blank lines separate responses when present; otherwise one response per line.
    blocks = [" ".join(b.split()) for b in re.split(r"\n\s*\n", text) if b.strip()]
    texts = blocks if len(blocks) > 1 else _lines(text)
    if not texts:
        raise FileError("Aucun texte n'a pu être extrait de ce PDF (document scanné ?).")
    return LoadedFile(texts=texts, source_format="pdf")
