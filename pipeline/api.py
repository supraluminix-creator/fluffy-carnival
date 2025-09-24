from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query
from typing import List

from .schemas import Report
from . import db_adapter


app = FastAPI(title="Crypto-AI Pipeline API", version="0.1.0")


@app.get("/api/report/latest", response_model=Report)
def get_latest():
    r = db_adapter.get_latest_report()
    if not r:
        raise HTTPException(status_code=404, detail="No report available")
    return r


@app.get("/api/report/history", response_model=List[Report])
def get_history(interval: str = Query(default="1h", pattern=r"^(15m|1h|4h|1d|1w|1m|1y)$")):
    return db_adapter.get_report_history(interval)


@app.get("/api/quant")
def get_quant():
    r = db_adapter.get_latest_report()
    if not r or not r.quant:
        raise HTTPException(status_code=404, detail="No quant report available")
    return r.quant


@app.get("/api/onchain")
def get_onchain():
    r = db_adapter.get_latest_report()
    # On-chain pourrait être dans technical ou une autre section dédiée selon implémentation finale
    if not r or not r.technical:
        raise HTTPException(status_code=404, detail="No on-chain/technical section available")
    return r.technical


@app.get("/api/fundamental")
def get_fundamental():
    r = db_adapter.get_latest_report()
    if not r or not r.fundamental:
        raise HTTPException(status_code=404, detail="No fundamental report available")
    return r.fundamental
