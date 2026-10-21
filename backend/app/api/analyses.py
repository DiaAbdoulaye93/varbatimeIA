"""Routes /api/analyses (IMPLEMENTATION.md §4)."""

from collections import defaultdict
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Query, UploadFile, status
from sqlmodel import Session, col, func, select

from app.api.deps import EngineDep, LlmClientFactoryDep, SessionDep, SettingsDep
from app.config import PRICING
from app.models import Analysis, LlmCall, Theme, Verbatim, VerbatimTheme
from app.schemas import (
    AnalysisCreated,
    AnalysisDetail,
    AnalysisSummary,
    RepresentativeVerbatim,
    Sentiment,
    StepUsage,
    ThemeOut,
    UsageOut,
    VerbatimOut,
    VerbatimPage,
)
from app.services.analysis_service import create_or_reuse, run_analysis
from app.services.csv_loader import CsvError, load_verbatims

router = APIRouter(prefix="/api/analyses", tags=["analyses"])

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
LIST_LIMIT = 100
STEP_ORDER = ("extract", "cluster", "synthesize")


def _get_analysis(session: Session, analysis_id: str) -> Analysis:
    analysis = session.get(Analysis, analysis_id)
    if analysis is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Analyse introuvable.")
    return analysis


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=AnalysisCreated)
def create_analysis(
    background_tasks: BackgroundTasks,
    session: SessionDep,
    engine: EngineDep,
    settings: SettingsDep,
    client_factory: LlmClientFactoryDep,
    file: Annotated[UploadFile, File(description="CSV with a `verbatim` column")],
    context: Annotated[str, Form()] = "",
    name: Annotated[str | None, Form()] = None,
) -> AnalysisCreated:
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE, "Fichier trop volumineux (5 Mo max)."
        )
    try:
        texts = load_verbatims(data)
    except CsvError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    label = (name or "").strip() or Path(file.filename or "analyse").stem
    analysis, reused = create_or_reuse(session, name=label, context=context.strip(), texts=texts)
    if not reused:
        background_tasks.add_task(
            run_analysis, engine, analysis.id, texts, settings, client_factory
        )
    return AnalysisCreated(id=analysis.id, status=analysis.status, cached=reused)


@router.get("", response_model=list[AnalysisSummary])
def list_analyses(session: SessionDep) -> list[Analysis]:
    query = select(Analysis).order_by(col(Analysis.created_at).desc()).limit(LIST_LIMIT)
    return list(session.exec(query).all())


@router.get("/{analysis_id}", response_model=AnalysisDetail)
def get_analysis(analysis_id: str, session: SessionDep) -> Analysis:
    return _get_analysis(session, analysis_id)


@router.get("/{analysis_id}/themes", response_model=list[ThemeOut])
def get_themes(analysis_id: str, session: SessionDep) -> list[ThemeOut]:
    analysis = _get_analysis(session, analysis_id)
    themes = session.exec(
        select(Theme).where(Theme.analysis_id == analysis_id).order_by(col(Theme.rank))
    ).all()
    wanted = {idx for t in themes for idx in t.representative_idx}
    texts = {
        v.idx: v.text_norm
        for v in session.exec(
            select(Verbatim)
            .where(Verbatim.analysis_id == analysis_id)
            .where(col(Verbatim.idx).in_(wanted))
        ).all()
    }
    n_used = (analysis.stats or {}).get("n_used") or 0
    return [
        ThemeOut(
            id=t.id or 0,
            rank=t.rank,
            label=t.label,
            description=t.description,
            count=t.count,
            pct=round(100 * t.count / n_used) if n_used else 0,
            sentiment_breakdown=t.sentiment_breakdown,  # type: ignore[arg-type]
            raw_labels=t.raw_labels,
            representatives=[
                RepresentativeVerbatim(idx=i, text=texts[i])
                for i in t.representative_idx
                if i in texts
            ],
        )
        for t in themes
    ]


@router.get("/{analysis_id}/verbatims", response_model=VerbatimPage)
def get_verbatims(
    analysis_id: str,
    session: SessionDep,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
    sentiment: Sentiment | None = None,
    theme_id: int | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    include_skipped: bool = False,
) -> VerbatimPage:
    _get_analysis(session, analysis_id)
    query = select(Verbatim).where(Verbatim.analysis_id == analysis_id)
    if not include_skipped:
        query = query.where(col(Verbatim.skipped_reason).is_(None))
    if sentiment is not None:
        query = query.where(Verbatim.sentiment == sentiment)
    if theme_id is not None:
        query = query.join(VerbatimTheme, col(VerbatimTheme.verbatim_id) == col(Verbatim.id)).where(
            VerbatimTheme.theme_id == theme_id
        )
    if q:
        query = query.where(col(Verbatim.text).ilike(f"%{q}%"))

    total = session.exec(select(func.count()).select_from(query.subquery())).one()
    rows = session.exec(
        query.order_by(col(Verbatim.idx)).offset((page - 1) * size).limit(size)
    ).all()

    themes_by_verbatim: dict[int, list[int]] = defaultdict(list)
    ids = [v.id for v in rows if v.id is not None]
    links = session.exec(
        select(VerbatimTheme)
        .where(col(VerbatimTheme.verbatim_id).in_(ids))
        .order_by(col(VerbatimTheme.theme_id))
    ).all()
    for link in links:
        themes_by_verbatim[link.verbatim_id].append(link.theme_id)

    items = [
        VerbatimOut(
            idx=v.idx,
            text=v.text,
            sentiment=v.sentiment,  # type: ignore[arg-type]
            themes_raw=v.themes_raw,
            key_phrase=v.key_phrase,
            skipped_reason=v.skipped_reason,
            theme_ids=themes_by_verbatim.get(v.id or 0, []),
        )
        for v in rows
    ]
    return VerbatimPage(items=items, total=total, page=page, size=size)


def _cost(call: LlmCall) -> float | None:
    price = PRICING.get(call.model)
    if price is None:
        return None
    return price.cost(
        call.input_tokens, call.cache_creation_tokens, call.cache_read_tokens, call.output_tokens
    )


def _sum_usage(step: str, calls: list[LlmCall]) -> StepUsage:
    costs = [_cost(c) for c in calls]
    return StepUsage(
        step=step,
        calls=len(calls),
        models=sorted({c.model for c in calls}),
        input_tokens=sum(c.input_tokens for c in calls),
        cache_creation_tokens=sum(c.cache_creation_tokens for c in calls),
        cache_read_tokens=sum(c.cache_read_tokens for c in calls),
        output_tokens=sum(c.output_tokens for c in calls),
        duration_ms=sum(c.duration_ms for c in calls),
        cost_usd=None if None in costs else round(sum(c for c in costs if c is not None), 6),
    )


@router.get("/{analysis_id}/usage", response_model=UsageOut)
def get_usage(analysis_id: str, session: SessionDep) -> UsageOut:
    analysis = _get_analysis(session, analysis_id)
    calls = list(
        session.exec(
            select(LlmCall).where(LlmCall.analysis_id == analysis_id).order_by(col(LlmCall.id))
        ).all()
    )
    by_step: dict[str, list[LlmCall]] = defaultdict(list)
    for call in calls:
        by_step[call.step].append(call)
    order = sorted(
        by_step, key=lambda s: STEP_ORDER.index(s) if s in STEP_ORDER else len(STEP_ORDER)
    )
    return UsageOut(
        steps=[_sum_usage(step, by_step[step]) for step in order],
        total=_sum_usage("total", calls),
        analysis_duration_ms=analysis.duration_ms,
    )
