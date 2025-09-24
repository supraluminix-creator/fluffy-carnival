from __future__ import annotations

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class TechnicalSection(BaseModel):
    patterns: Optional[List[str]] = None
    levels: Optional[Dict[str, float]] = None
    momentum: Optional[Dict[str, Any]] = None


class QuantSection(BaseModel):
    volatility: Optional[Dict[str, Any]] = None
    correlations: Optional[Dict[str, float]] = None
    risk_ratios: Optional[Dict[str, float]] = None


class FundamentalSection(BaseModel):
    macro: Optional[str] = None
    regulation: Optional[str] = None
    adoption: Optional[str] = None


class SourceItem(BaseModel):
    title: str
    url: str
    date: Optional[str] = None


class ScriptItem(BaseModel):
    name: str
    language: str = Field(default="python")
    code: str


class SynthesisSection(BaseModel):
    summary: Optional[str] = None
    scenarios: Optional[List[str]] = None
    risks: Optional[List[str]] = None
    opportunities: Optional[List[str]] = None


class ReportMeta(BaseModel):
    asset: str = Field(default="BTC")
    run_id: str


class Report(BaseModel):
    meta: ReportMeta
    technical: Optional[TechnicalSection] = None
    quant: Optional[QuantSection] = None
    fundamental: Optional[FundamentalSection] = None
    sources: Optional[List[SourceItem]] = None
    scripts: Optional[List[ScriptItem]] = None
    synthesis: Optional[SynthesisSection] = None
