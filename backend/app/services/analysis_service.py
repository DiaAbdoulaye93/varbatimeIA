"""Analysis lifecycle: creation (with result cache), background run, persistence."""

import hashlib
import json
import logging
from collections.abc import Callable, Sequence

from sqlalchemy import Engine
from sqlmodel import Session, col, select

from app.config import PROMPT_VERSION, Settings
from app.models import (
    ACTIVE_STATUSES,
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_PROCESSING,
    Analysis,
    LlmCall,
    Theme,
    Verbatim,
    VerbatimTheme,
    utcnow,
)
from app.pipeline.check import InputRejected
from app.pipeline.llm_client import LlmClient, LlmError, LlmUsage
from app.pipeline.pipeline import run_pipeline
from app.pipeline.preprocess import normalize
from app.schemas import PipelineResult

logger = logging.getLogger(__name__)

LlmClientFactory = Callable[[Settings], LlmClient]

INTERRUPTED_ERROR = "Analyse interrompue par un redémarrage du serveur."
INTERNAL_ERROR = "Erreur interne pendant l'analyse."


def content_hash(texts: Sequence[str], context: str) -> str:
    """Cache key: normalized verbatims + context + prompt version (IMPLEMENTATION.md §2.6)."""
    payload = json.dumps(
        {
            "texts": [normalize(t) for t in texts],
            "context": normalize(context),
            "prompt_version": PROMPT_VERSION,
        },
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def create_or_reuse(
    session: Session,
    *,
    name: str,
    context: str,
    texts: Sequence[str],
    source_filename: str | None = None,
    source_format: str | None = None,
    source_column: str | None = None,
) -> tuple[Analysis, bool]:
    """Return (analysis, reused). A done or running identical analysis is reused."""
    key = content_hash(texts, context)
    existing = session.exec(
        select(Analysis)
        .where(Analysis.content_hash == key)
        .where(col(Analysis.status).in_([STATUS_DONE, *ACTIVE_STATUSES]))
        .order_by(col(Analysis.created_at).desc())
    ).first()
    if existing is not None:
        logger.info("reusing analysis %s (same content hash)", existing.id)
        return existing, True
    analysis = Analysis(
        name=name,
        context=context,
        source_filename=source_filename,
        source_format=source_format,
        source_column=source_column,
        content_hash=key,
        total_verbatims=len(texts),
    )
    session.add(analysis)
    session.commit()
    session.refresh(analysis)
    return analysis, False


def fail_interrupted(engine: Engine) -> None:
    """Background tasks do not survive a restart: close the analyses they left running."""
    with Session(engine) as session:
        stale = session.exec(
            select(Analysis).where(col(Analysis.status).in_(ACTIVE_STATUSES))
        ).all()
        for analysis in stale:
            analysis.status, analysis.error = STATUS_FAILED, INTERRUPTED_ERROR
            analysis.finished_at = utcnow()
            session.add(analysis)
        session.commit()
    if stale:
        logger.warning("%d interrupted analyses marked as failed", len(stale))


def _update(engine: Engine, analysis_id: str, **fields: object) -> None:
    with Session(engine) as session:
        analysis = session.get_one(Analysis, analysis_id)
        for key, value in fields.items():
            setattr(analysis, key, value)
        session.add(analysis)
        session.commit()


def _llm_calls(analysis_id: str, usage: Sequence[LlmUsage]) -> list[LlmCall]:
    return [
        LlmCall(
            analysis_id=analysis_id,
            step=u.step,
            model=u.model,
            input_tokens=u.input_tokens,
            cache_creation_tokens=u.cache_creation_tokens,
            cache_read_tokens=u.cache_read_tokens,
            output_tokens=u.output_tokens,
            duration_ms=u.duration_ms,
        )
        for u in usage
    ]


def _persist_result(
    engine: Engine, analysis_id: str, result: PipelineResult, usage: Sequence[LlmUsage]
) -> None:
    with Session(engine) as session:
        verbatims = [
            Verbatim(
                analysis_id=analysis_id,
                idx=v.idx,
                text=v.text,
                text_norm=v.text_norm,
                sentiment=v.sentiment,
                themes_raw=v.themes_raw,
                key_phrase=v.key_phrase,
                skipped_reason=v.skipped_reason,
            )
            for v in result.verbatims
        ]
        themes = [
            Theme(
                analysis_id=analysis_id,
                rank=t.id,
                label=t.label,
                description=t.description,
                raw_labels=t.raw_labels,
                count=t.count,
                sentiment_breakdown=dict(t.sentiment_breakdown),
                representative_idx=t.representative_idx,
            )
            for t in result.themes
        ]
        session.add_all(verbatims + themes)
        session.flush()  # assigns primary keys

        theme_pk = {t.rank: t.id for t in themes}
        session.add_all(
            VerbatimTheme(verbatim_id=row.id, theme_id=theme_pk[rank])
            for row, v in zip(verbatims, result.verbatims, strict=True)
            for rank in v.theme_ids
            if row.id is not None and theme_pk.get(rank) is not None
        )
        session.add_all(_llm_calls(analysis_id, usage))

        analysis = session.get_one(Analysis, analysis_id)
        analysis.status, analysis.progress, analysis.current_step = STATUS_DONE, 100, "done"
        analysis.stats = result.stats.model_dump()
        analysis.synthesis_md = result.synthesis_md
        analysis.duration_ms = result.duration_ms
        analysis.finished_at = utcnow()
        session.add(analysis)
        session.commit()


def run_analysis(
    engine: Engine,
    analysis_id: str,
    texts: Sequence[str],
    settings: Settings,
    client_factory: LlmClientFactory,
) -> None:
    """Background task: run the pipeline and store the outcome, success or failure."""
    client: LlmClient | None = None
    try:
        with Session(engine) as session:
            context = session.get_one(Analysis, analysis_id).context
        _update(engine, analysis_id, status=STATUS_PROCESSING, progress=0)
        client = client_factory(settings)
        result = run_pipeline(
            client,
            settings,
            texts,
            context,
            on_progress=lambda step, progress, info: _update(
                engine,
                analysis_id,
                current_step=step,
                progress=progress,
                progress_info=info.model_dump(exclude_none=True),
            ),
        )
        _persist_result(engine, analysis_id, result, client.usage)
        logger.info("analysis %s done in %d ms", analysis_id, result.duration_ms)
    except Exception as exc:  # a background task has nobody to raise to
        logger.exception("analysis %s failed", analysis_id)
        # Messages written for the user: model errors and file rejections.
        message = str(exc) if isinstance(exc, (LlmError, InputRejected)) else INTERNAL_ERROR
        with Session(engine) as session:
            session.add_all(_llm_calls(analysis_id, client.usage if client else []))
            analysis = session.get_one(Analysis, analysis_id)
            analysis.status, analysis.error = STATUS_FAILED, message
            analysis.finished_at = utcnow()
            session.add(analysis)
            session.commit()
