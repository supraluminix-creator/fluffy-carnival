# Action Plan by Sprints / Atomic Tasks

This plan slices work into small, reviewable PRs with clear dependencies.

## Sprint 1 — Foundations & Guardrails

1. Boot banner + YAML validation
   - Files: `main.py`, `scheduler/runner.py` (or new `scheduler/validate.py`)
   - Tests: `tests/test_scheduler_config.py` (valid/invalid YAML cases)
   - Label: `feat: boot-banner+yaml-validation`
   - Dependencies: None
   - Quick win: Yes

2. Export schema guard (pydantic) + golden tests
   - Files: `pipeline/exporter.py`, `pipeline/models/export.py` (new)
   - Tests: `tests/test_export_schema.py`, golden fixtures under `tests/fixtures/`
   - Label: `feat: export-schema-guard`
   - Dependencies: None
   - Quick win: Yes

3. CI hardening (linters + security + coverage)
   - Files: `.github/workflows/ci.yml`, `pyproject.toml` or config files
   - Tests: CI should run and fail on violations
   - Label: `ci: lint-security-coverage`
   - Dependencies: None
   - Quick win: Yes

## Sprint 2 — Resilience & Consistency

4. Unified HTTP client wrapper
   - Files: `pipeline/http_client.py` (new), updates in 1–2 collectors
   - Tests: `tests/test_http_client.py` with httpx_mock/requests_mock
   - Label: `feat: http-client-wrapper`
   - Dependencies: S1

5. Metrics tuning & docs
   - Files: `scheduler/runner.py`, `README.md`
   - Tests: optional scrape assertions
   - Label: `obs: metrics-tuning`
   - Dependencies: None

6. DB health & indexes
   - Files: `pipeline/storage/sqlite_adapter.py`, `main.py`
   - Tests: `tests/test_health_db.py`
   - Label: `feat: db-health-indexes`
   - Dependencies: None

## Sprint 3 — Quality of Life & Ops

7. Troubleshooting guide & script flags
   - Files: `README.md`, `README_NEW_PRODSAFE.md`, `scripts/run_scheduler.ps1`
   - Tests: N/A
   - Label: `docs: troubleshooting+flags`
   - Dependencies: None

8. Extend tests coverage (health/metrics/export)
   - Files: `tests/` new cases for /health shape, /metrics readiness, exporter failures
   - Tests: as listed
   - Label: `test: coverage-extensions`
   - Dependencies: S1

## Acceptance & Rollback

- Each PR includes: analysis, solution, delta, tests, rollback plan (feature flags where applicable).
- Rollback: Flip the corresponding feature flag or revert files touched by the PR; ensure CI gates catch regressions.# 🚀 **Plan d'Action Opérationnel - Crypto Monitor**

## **🎯 Sprint 1 - Stabilisation Core (7 jours)**

### **🗓️ Planning détaillé**

| Jour | Task | Owner | Heures | Deliverable |
|------|------|-------|--------|-------------|
| **J1** | US1.1 Scheduler centralisé | Dev | 4h | `scheduler.py` fonctionnel |
| **J2** | US1.2 Health endpoints | Dev | 2h | FastAPI `/health` `/metrics` |
| **J2** | US1.3 Parallel collectors | Dev | 3h | `asyncio.gather()` implémenté |  
| **J3** | US1.4 Tests BaseCollector | Dev | 4h | Coverage >90% tests |
| **J3** | US1.5 GitHub Secrets | DevOps | 1h | CI/CD sécurisé |
| **J4-5** | Integration testing | QA | 4h | Validation end-to-end |
| **J6** | Documentation | Tech Writer | 2h | README + API docs |
| **J7** | Demo & review | Team | 1h | Sprint review |

**Total effort:** 21h | **Capacity:** 40h équipe

---

## **📋 TASK 1.1 - Scheduler Centralisé**

### **Checklist détaillée**

#### **Phase 1: Setup (30min)**
- [ ] Installer APScheduler : `pip install apscheduler`
- [ ] Créer `pipeline/scheduler.py`
- [ ] Ajouter imports nécessaires

#### **Phase 2: Implementation (2h30)**
```python
# pipeline/scheduler.py
import asyncio
import random
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

class CryptoScheduler:
    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self.logger = logging.getLogger(__name__)
    
    def add_collector(self, collector, interval_seconds, jitter_percent=10):
        """Ajoute un collector avec jitter anti-rate-limit"""
        jitter = interval_seconds * (jitter_percent / 100)
        actual_interval = interval_seconds + random.uniform(-jitter, jitter)
        
        self.scheduler.add_job(
            func=collector.collect,
            trigger=IntervalTrigger(seconds=actual_interval),
            id=f"collector_{collector.name}",
            max_instances=1,
            coalesce=True
        )
        
    async def start(self):
        """Démarre le scheduler"""
        self.scheduler.start()
        self.logger.info("Scheduler started")
        
    async def shutdown(self):
        """Arrêt graceful"""
        self.scheduler.shutdown(wait=True)
        self.logger.info("Scheduler stopped")
```

#### **Phase 3: Configuration (30min)**
- [ ] Ajouter variables environnement dans `.env`
```bash
# Scheduler timing (seconds)
COLLECTOR_INTERVAL_MARKET=300
COLLECTOR_INTERVAL_DEFILLAMA=900
COLLECTOR_INTERVAL_ONCHAIN=1800
COLLECTOR_INTERVAL_DERIVATIVES=300
COLLECTOR_INTERVAL_SENTIMENT=3600
SCHEDULER_JITTER_PERCENT=10
```

#### **Phase 4: Integration main.py (30min)**
```python
# main.py update
from pipeline.scheduler import CryptoScheduler
import signal

async def main():
    scheduler = CryptoScheduler()
    
    # Setup collectors
    market_collector = MarketCollector()
    defillama_collector = DefiLlamaCollector()
    # ... autres collectors
    
    # Schedule avec jitter
    scheduler.add_collector(market_collector, 
                          int(os.getenv('COLLECTOR_INTERVAL_MARKET', 300)))
    scheduler.add_collector(defillama_collector,
                          int(os.getenv('COLLECTOR_INTERVAL_DEFILLAMA', 900)))
    
    # Graceful shutdown
    def signal_handler(signum, frame):
        asyncio.create_task(scheduler.shutdown())
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    await scheduler.start()
    # Keep running
    while True:
        await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(main())
```

**Validation:** Scheduler démarre, collectors s'exécutent avec jitter, graceful shutdown fonctionne

---

## **📋 TASK 1.2 - Health Endpoints**

### **Checklist détaillée**

#### **Phase 1: FastAPI Setup (30min)**
- [ ] Installer FastAPI : `pip install fastapi uvicorn`
- [ ] Créer `api/health.py`

#### **Phase 2: Endpoints Implementation (1h)**
```python
# api/health.py
from fastapi import FastAPI, Response
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
import time
import asyncio

app = FastAPI(title="Crypto Monitor API", version="1.0.0")

@app.get("/health")
async def health_check():
    """Health check endpoint pour load balancers"""
    collectors_status = await get_collectors_health()
    
    overall_status = "healthy" if all(
        c["status"] == "healthy" for c in collectors_status.values()
    ) else "degraded"
    
    return {
        "status": overall_status,
        "timestamp": time.time(),
        "collectors": collectors_status,
        "version": "1.0.0"
    }

@app.get("/metrics")
async def prometheus_metrics():
    """Prometheus metrics endpoint"""
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST
    )

@app.get("/status")
async def detailed_status():
    """Status détaillé pour debugging"""
    return {
        "uptime": get_uptime_seconds(),
        "last_collection_times": await get_last_collection_times(),
        "cache_stats": get_cache_statistics(),
        "memory_usage": get_memory_usage()
    }

async def get_collectors_health():
    """Vérifie la santé de chaque collector"""
    # Implementation à adapter selon collectors existants
    pass
```

#### **Phase 3: Integration main.py (30min)**
```python
# main.py - ajouter serveur API
import uvicorn
from api.health import app

async def run_api_server():
    """Démarre serveur FastAPI en background"""
    config = uvicorn.Config(app, host="0.0.0.0", port=8000, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()

async def main():
    # ... scheduler setup
    
    # Démarrer API en parallèle
    api_task = asyncio.create_task(run_api_server())
    scheduler_task = asyncio.create_task(run_scheduler())
    
    await asyncio.gather(api_task, scheduler_task)
```

**Validation:** `curl http://localhost:8000/health` retourne JSON status

---

## **📋 TASK 1.3 - Parallel Collectors**

### **Checklist détaillée**

#### **Phase 1: Refactor collectors (1h30)**
```python
# pipeline/orchestrator.py
import asyncio
import logging
from typing import List
from .collectors.base_collector import BaseCollector

class ParallelOrchestrator:
    def __init__(self, collectors: List[BaseCollector]):
        self.collectors = collectors
        self.logger = logging.getLogger(__name__)
    
    async def run_all_collectors(self):
        """Exécute tous les collectors en parallèle"""
        start_time = time.time()
        
        # Gather avec gestion exceptions
        results = await asyncio.gather(
            *[self._safe_collect(collector) for collector in self.collectors],
            return_exceptions=True
        )
        
        # Log résultats
        execution_time = time.time() - start_time
        success_count = sum(1 for r in results if not isinstance(r, Exception))
        
        self.logger.info(
            "Parallel collection completed",
            total_collectors=len(self.collectors),
            successful=success_count,
            execution_time=execution_time
        )
        
        return results
    
    async def _safe_collect(self, collector):
        """Wrapper pour gestion erreurs individuelles"""
        try:
            result = await collector.collect()
            self.logger.info(f"Collector {collector.name} succeeded")
            return result
        except Exception as e:
            self.logger.error(f"Collector {collector.name} failed: {e}")
            raise
```

#### **Phase 2: Update main collector calls (1h)**
- [ ] Modifier scheduler pour utiliser orchestrator
- [ ] Tester exécution parallèle vs séquentielle
- [ ] Valider métriques individuelles préservées

#### **Phase 3: Benchmark performance (30min)**
- [ ] Mesurer temps avant/après parallélisation
- [ ] Documenter amélioration performance

**Validation:** 5x réduction temps total, logs structurés maintenus

---

## **📋 TASK 1.4 - Tests BaseCollector**

### **Checklist détaillée**

#### **Phase 1: Test Infrastructure (1h)**
```python
# tests/test_base_collector.py
import pytest
import asyncio
from unittest.mock import AsyncMock, Mock, patch
from pipeline.collectors.base_collector import BaseCollector

class TestCollector(BaseCollector):
    """Collector de test concret"""
    def __init__(self):
        super().__init__(name="test")
    
    async def fetch_main(self):
        return {"data": "main"}
    
    async def fetch_backup(self):
        return {"data": "backup"}

@pytest.fixture
def test_collector():
    return TestCollector()

@pytest.fixture
def mock_cache():
    with patch('diskcache.Cache') as mock:
        yield mock

@pytest.mark.asyncio
class TestBaseCollector:
    async def test_fetch_main_success(self, test_collector, mock_cache):
        # Test fetch main réussi
        pass
    
    async def test_fetch_main_failure_fallback_backup(self, test_collector):
        # Test fallback main → backup
        pass
    
    async def test_retry_exponential_backoff(self, test_collector):
        # Test retry avec backoff
        pass
    
    async def test_cache_hit_miss(self, test_collector, mock_cache):
        # Test cache TTL
        pass
    
    async def test_prometheus_metrics_updated(self, test_collector):
        # Test métriques
        pass
```

#### **Phase 2: Tests exhaustifs (2h30)**
- [ ] 15 test cases couvrant tous les paths
- [ ] Mocks pour APIs externes
- [ ] Tests timeout et exceptions
- [ ] Tests métriques Prometheus

#### **Phase 3: Coverage validation (30min)**
- [ ] Installer pytest-cov : `pip install pytest-cov`
- [ ] Run `pytest --cov=pipeline.collectors.base_collector --cov-report=html`
- [ ] Valider >90% coverage

**Validation:** Coverage >90%, tous tests passent, CI verte

---

## **📋 TASK 1.5 - GitHub Secrets CI/CD**

### **Checklist détaillée**

#### **Phase 1: Secrets Configuration (30min)**
1. **GitHub Repository Settings → Secrets and variables → Actions**
2. **Ajouter secrets:**
   - `COINMARKETCAP_API_KEY`
   - `ETHERSCAN_API_KEY`  
   - `BYBIT_API_KEY` (si nécessaire)
   - `BYBIT_SECRET_KEY` (si nécessaire)

#### **Phase 2: CI Workflow Update (20min)**
```yaml
# .github/workflows/ci.yml update
name: CI
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    env:
      COINMARKETCAP_API_KEY: ${{ secrets.COINMARKETCAP_API_KEY }}
      ETHERSCAN_API_KEY: ${{ secrets.ETHERSCAN_API_KEY }}
    
    steps:
    - uses: actions/checkout@v3
    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.12'
    
    - name: Install dependencies
      run: |
        pip install -r requirements.txt
        pip install pytest pytest-cov
    
    - name: Run tests
      run: |
        pytest --cov=pipeline --cov-report=xml
    
    - name: Upload coverage
      uses: codecov/codecov-action@v3
      with:
        file: ./coverage.xml
```

#### **Phase 3: Documentation (10min)**
- [ ] Update README.md avec instructions secrets
- [ ] Documenter rotation process

**Validation:** CI passe avec vraies API keys, secrets sécurisés

---

## **🔄 Workflow Quotidien Sprint 1**

### **Daily Standup (15min/jour)**
**Questions:**
1. Qu'est-ce que j'ai terminé hier ?
2. Sur quoi je travaille aujourd'hui ?
3. Y a-t-il des blockers ?

### **Code Review Process**
1. **Self-review** avant push
2. **Peer review** dans les 4h
3. **Tests automatiques** doivent passer
4. **Merge** après validation

### **Definition of Done**
- [ ] Code reviewé et approuvé
- [ ] Tests unitaires écrits et passent
- [ ] Documentation mise à jour
- [ ] Métriques validées
- [ ] Performance benchmarkée

---

## **📊 Métriques de Suivi Sprint 1**

### **Daily Tracking**

| Jour | Tasks Planned | Tasks Completed | Blockers | Notes |
|------|---------------|-----------------|----------|-------|
| J1 | Scheduler setup | ✅/❌ | None/List | Progress notes |
| J2 | Health endpoints + Parallel | ✅/❌ | None/List | Progress notes |
| J3 | Tests + Secrets | ✅/❌ | None/List | Progress notes |
| J4-5 | Integration testing | ✅/❌ | None/List | Progress notes |
| J6 | Documentation | ✅/❌ | None/List | Progress notes |
| J7 | Demo | ✅/❌ | None/List | Sprint review |

### **Quality Gates**

| Gate | Criteria | Status |
|------|----------|--------|
| **Code Quality** | No linting errors | ⏳ Pending |
| **Test Coverage** | >90% BaseCollector | ⏳ Pending |
| **Performance** | <3s total collection | ⏳ Pending |
| **Security** | No secrets in code | ⏳ Pending |
| **Documentation** | README updated | ⏳ Pending |

---

## **🚨 Risk Mitigation**

### **Risques identifiés**

| Risque | Probabilité | Impact | Mitigation |
|--------|-------------|--------|------------|
| **API rate limits** | Moyen | Élevé | Jitter + cache + fallback |
| **Performance regression** | Faible | Moyen | Benchmarking continu |
| **Tests flaky** | Moyen | Moyen | Mocks stables + retry |
| **CI/CD failure** | Faible | Élevé | Local testing first |

### **Contingency Plans**
- **Scheduler issues** → Fallback sur cron simple
- **FastAPI problems** → Health check minimal
- **Test failures** → Prioriser tests critiques
- **Time overrun** → Descope documentation

---

## **✅ Sprint 1 Success Criteria**

### **Must Have (P0)**
- [x] Scheduler centralisé fonctionnel avec jitter
- [x] Health endpoints `/health` et `/metrics`
- [x] Collectors parallélisés avec `asyncio.gather()`
- [x] Performance 3x amélioration minimum

### **Should Have (P1)**  
- [x] Tests BaseCollector >90% coverage
- [x] GitHub Secrets configuration
- [x] Documentation mise à jour
- [x] CI/CD pipeline sécurisé

### **Could Have (P2)**
- [ ] Benchmarking détaillé
- [ ] Métriques business
- [ ] Architecture Decision Records

**READY FOR SPRINT 2:** ✅ Tous les Must Have + Should Have complétés

---

## **🎯 Next Actions Immédiates**

### **🚀 START HERE:**
1. **Créer branche feature** : `git checkout -b feature/sprint-1-stabilization`
2. **Installer dépendances** : `pip install apscheduler fastapi uvicorn`
3. **Commencer TASK 1.1** : Créer `pipeline/scheduler.py`
4. **Setup tracking** : Daily standup 9h00

### **🛠️ Development Environment**
```bash
# Setup rapide
cd new_crypto_prodsafe
git checkout -b feature/sprint-1-stabilization
pip install apscheduler fastapi uvicorn pytest pytest-cov
mkdir -p api
touch pipeline/scheduler.py api/health.py
```

### **⏰ Timeline Reminder**
- **J1 EOD:** Scheduler fonctionnel 
- **J2 EOD:** Health endpoints + Parallel collectors
- **J3 EOD:** Tests + Secrets configuration
- **J7:** Sprint review & demo

**SPRINT 1 STARTS NOW** 🚀