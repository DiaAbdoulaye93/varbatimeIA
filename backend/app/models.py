"""Database tables (README, Modèle de données)."""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, LargeBinary, Text
from sqlmodel import Field, SQLModel

STATUS_PENDING = "pending"
STATUS_PROCESSING = "processing"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
ACTIVE_STATUSES = (STATUS_PENDING, STATUS_PROCESSING)


def utcnow() -> datetime:
    return datetime.now(UTC)


class Analysis(SQLModel, table=True):
    __tablename__ = "analyses"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    name: str
    context: str = Field(sa_type=Text)
    source_filename: str | None = None
    source_format: str | None = None  # csv | tsv | txt | json | xlsx | docx
    source_column: str | None = None  # tabular files: the column that was read
    status: str = Field(default=STATUS_PENDING, index=True)
    progress: int = 0
    current_step: str = "preprocess"  # kept on failure: the step that failed
    progress_info: dict[str, Any] | None = Field(default=None, sa_type=JSON)
    error: str | None = Field(default=None, sa_type=Text)
    content_hash: str = Field(index=True)
    total_verbatims: int = 0
    stats: dict[str, Any] | None = Field(default=None, sa_type=JSON)
    synthesis_md: str | None = Field(default=None, sa_type=Text)
    duration_ms: int | None = None
    created_at: datetime = Field(default_factory=utcnow, sa_type=DateTime(timezone=True))
    finished_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))


class Verbatim(SQLModel, table=True):
    __tablename__ = "verbatims"

    id: int | None = Field(default=None, primary_key=True)
    analysis_id: str = Field(foreign_key="analyses.id", index=True, ondelete="CASCADE")
    idx: int  # 1-based position in the CSV
    text: str = Field(sa_type=Text)
    text_norm: str = Field(sa_type=Text)
    sentiment: str | None = Field(default=None, index=True)
    themes_raw: list[str] = Field(default_factory=list, sa_type=JSON)
    key_phrase: str | None = None
    skipped_reason: str | None = None


class Theme(SQLModel, table=True):
    __tablename__ = "themes"

    id: int | None = Field(default=None, primary_key=True)
    analysis_id: str = Field(foreign_key="analyses.id", index=True, ondelete="CASCADE")
    rank: int  # 1 = most mentioned
    label: str
    description: str = Field(sa_type=Text)
    raw_labels: list[str] = Field(default_factory=list, sa_type=JSON)
    count: int
    sentiment_breakdown: dict[str, int] = Field(default_factory=dict, sa_type=JSON)
    representative_idx: list[int] = Field(default_factory=list, sa_type=JSON)


class VerbatimTheme(SQLModel, table=True):
    __tablename__ = "verbatim_themes"

    verbatim_id: int = Field(foreign_key="verbatims.id", primary_key=True, ondelete="CASCADE")
    theme_id: int = Field(foreign_key="themes.id", primary_key=True, ondelete="CASCADE")


class LlmCall(SQLModel, table=True):
    __tablename__ = "llm_calls"

    id: int | None = Field(default=None, primary_key=True)
    analysis_id: str = Field(foreign_key="analyses.id", index=True, ondelete="CASCADE")
    step: str
    model: str
    input_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    output_tokens: int
    duration_ms: int
    created_at: datetime = Field(default_factory=utcnow, sa_type=DateTime(timezone=True))


class SourceFile(SQLModel, table=True):
    """The uploaded file, kept as is so it can be viewed or printed after the analysis."""

    __tablename__ = "source_files"

    analysis_id: str = Field(foreign_key="analyses.id", primary_key=True, ondelete="CASCADE")
    filename: str
    size: int
    data: bytes = Field(sa_type=LargeBinary)
