from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TechnicalSection(BaseModel):
    patterns: list[str] | None = None
    levels: dict[str, float] | None = None
    momentum: dict[str, Any] | None = None


class QuantSection(BaseModel):
    volatility: dict[str, Any] | None = None
    correlations: dict[str, float] | None = None
    risk_ratios: dict[str, float] | None = None


class FundamentalSection(BaseModel):
    macro: str | None = None
    regulation: str | None = None
    adoption: str | None = None


class SourceItem(BaseModel):
    title: str
    url: str
    date: str | None = None


class ScriptItem(BaseModel):
    name: str
    language: str = Field(default="python")
    code: str


class SynthesisSection(BaseModel):
    summary: str | None = None
    scenarios: list[str] | None = None
    risks: list[str] | None = None
    opportunities: list[str] | None = None


class ReportMeta(BaseModel):
    asset: str = Field(default="BTC")
    run_id: str


class Report(BaseModel):
    meta: ReportMeta
    technical: TechnicalSection | None = None
    quant: QuantSection | None = None
    fundamental: FundamentalSection | None = None
    sources: list[SourceItem] | None = None
    scripts: list[ScriptItem] | None = None
    synthesis: SynthesisSection | None = None


class HealthResponse(BaseModel):
    status: str
    version: str | None = None
    git_sha: str | None = None
    build_date: str | None = None
    started_at: str | None = None
    uptime_seconds: float | None = None


class HistoryMetaResponse(BaseModel):
    total: int
    page: int
    page_size: int
    has_next: bool
    items: list[Report]
