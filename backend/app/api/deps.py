"""FastAPI dependencies. The engine and LLM client factory live on app.state (see main.py)."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import Engine
from sqlmodel import Session

from app.config import Settings, get_settings
from app.services.analysis_service import LlmClientFactory


def get_db_engine(request: Request) -> Engine:
    return request.app.state.engine


def get_session(engine: Annotated[Engine, Depends(get_db_engine)]) -> Iterator[Session]:
    with Session(engine) as session:
        yield session


def get_llm_client_factory(request: Request) -> LlmClientFactory:
    return request.app.state.llm_client_factory


EngineDep = Annotated[Engine, Depends(get_db_engine)]
SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
LlmClientFactoryDep = Annotated[LlmClientFactory, Depends(get_llm_client_factory)]
