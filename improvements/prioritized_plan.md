# Prioritized Improvements Plan (Prod‑Safe)

This plan follows the methodology: Analyse → Solution → Delta → Tests → Rollback. Each item is a small, reviewable PR.

## 1) Boot banner + YAML validation

- Priority: Critical
- Description: Emit a single startup summary and validate `scheduler/jobs.yaml` (unknown keys, duplicate ids, bad `every` values).
- Impact: Eliminates config ambiguity; faster MTTR.
- Deliverables:
  - Code: `main.py` (boot banner), `scheduler/runner.py` or a new `scheduler/validate.py` for schema checks
  - Tests: unit tests for validation (good/bad samples), snapshot test for boot banner
  - Docs: README update documenting validation and banner
- PR Checklist: Analyse (config risks) → Solution (schema + banner) → Delta (small diff) → Tests (good/bad YAML) → Rollback (feature flag: `VALIDATE_JOBS=0`)
- Acceptance Criteria:
  - Bad YAML (dup id, unknown key) fails with clear error
  - Boot banner shows: run_id, config_path, enabled jobs, jitter, METRICS_PORT, HEALTH_PORT, RUN_JOBS_AT_START

## 2) Export schema guard (pydantic) + golden tests

- Priority: High
- Description: Define `ExportRow` with `schema_version`; validate before CSV write; provide golden fixture tests.
- Impact: Prevents silent data contract drift.
- Deliverables:
  - Code: `pipeline/exporter.py` (+ `models/export.py`)
  - Tests: `tests/test_export_schema.py` with valid/invalid rows; golden CSV consistency check
  - Docs: README (schema fields + version), CHANGELOG entry on version bump
- PR Checklist: Analyse (drift risk) → Solution (model+validate) → Delta → Tests (golden) → Rollback (flag `STRICT_EXPORT_SCHEMA=0`)
- Acceptance Criteria:
  - Invalid export raises and logs clear error
  - Golden file test passes; schema_version included in output

## 3) Unified HTTP client policy

- Priority: High
- Description: Provide a single helper (httpx/requests) with default timeout, retry/backoff, headers, and metrics labels; refactor collectors gradually behind a flag.
- Impact: Reduces intermittent failures; consistent telemetry.
- Deliverables:
  - Code: `pipeline/http_client.py` + per-collector opt-in
  - Tests: unit tests for retry/backoff and timeout behavior using httpx_mock
  - Docs: coding guide for collectors
- PR Checklist: Analyse → Solution (client wrapper) → Delta → Tests → Rollback (per collector feature flag)
- Acceptance Criteria:
  - Client enforces timeouts and retries; emits per‑collector metrics; at least 1–2 collectors migrated.

## 4) CI hardening (linters, security, coverage)

- Priority: High
- Description: Add ruff/black/isort, pip‑audit/safety, and coverage gates.
- Impact: Catches regressions early; consistent code quality.
- Deliverables:
  - Code: `.github/workflows/ci.yml` updates; config files (pyproject/ruff/black)
  - Tests: not applicable beyond current suite
  - Docs: CONTRIBUTING.md snippet
- PR Checklist: Analyse → Solution (CI steps) → Delta → Tests (CI green) → Rollback (step toggles)
- Acceptance Criteria:
  - CI fails on lint/security issues; coverage report produced; artifacts uploaded on failure.

## 5) DB health + indexes

- Priority: Medium
- Description: Add SQLite health checks in /health; create targeted indexes if missing.
- Impact: Better runtime insight and performance on hot paths.
- Deliverables:
  - Code: `pipeline/storage/sqlite_adapter.py` for ensure_indexes; `main.py` health enhancement
  - Tests: smoke test ensuring /health reports DB ok; migration idempotency
  - Docs: schema/index doc note
- PR Checklist: Analyse → Solution → Delta → Tests → Rollback
- Acceptance Criteria:
  - /health includes db_ok:true and schema version; indexes created idempotently.

## 6) Metrics tuning & docs

- Priority: Medium
- Description: Adjust histogram buckets per job family; add README metrics dictionary.
- Impact: More actionable latency/error insights.
- Deliverables:
  - Code: `scheduler/runner.py` buckets map
  - Docs: README “Metrics reference”
  - Tests: optional smoke assertions on metric exposure
- PR Checklist: Analyse → Solution → Delta → Tests → Rollback
- Acceptance Criteria:
  - Buckets applied; doc present; metrics scrape unaffected.# 🎯 **Plan d'Amélioration Priorisé - Crypto Monitor**

## **🚦 Matrice de Priorisation**

| Amélioration | Impact | Effort | Risque | Priorité | Sprint |
|--------------|--------|--------|--------|----------|--------|
| **Scheduler centralisé** | 🔴 Critique | 🟡 Moyen | 🟢 Faible | **P0** | Sprint 1 |
| **Health endpoints** | 🔴 Critique | 🟢 Faible | 🟢 Faible | **P0** | Sprint 1 |
| **Parallel collectors** | 🟡 Élevé | 🟢 Faible | 🟢 Faible | **P0** | Sprint 1 |
| **Tests BaseCollector** | 🟡 Élevé | 🟡 Moyen | 🟢 Faible | **P1** | Sprint 1 |
| **GitHub Secrets CI** | 🟡 Élevé | 🟢 Faible | 🟢 Faible | **P1** | Sprint 1 |
| **Docker containerization** | 🟡 Élevé | 🟡 Moyen | 🟡 Moyen | **P1** | Sprint 2 |
| **PostgreSQL migration** | 🟡 Élevé | 🔴 Élevé | 🟡 Moyen | **P2** | Sprint 3 |
| **Grafana dashboards** | 🟡 Élevé | 🟡 Moyen | 🟢 Faible | **P2** | Sprint 3 |
| **Circuit breaker** | 🟢 Moyen | 🟡 Moyen | 🟢 Faible | **P3** | Sprint 4 |
| **Distributed tracing** | 🟢 Moyen | 🔴 Élevé | 🟡 Moyen | **P4** | Sprint 5 |

---

## **🏆 QUICK WINS (Effort < 1h, Impact immédiat)**

### **1. Health Endpoints FastAPI (15 min)**
```python
# Ajout dans main.py
from fastapi import FastAPI
app = FastAPI()

@app.get("/health")
async def health_check():
    return {"status": "healthy", "collectors": get_collectors_status()}

@app.get("/metrics")  
async def prometheus_metrics():
    return Response(generate_latest(), media_type="text/plain")
```
**Impact** : Monitoring externe possible immédiatement
**Effort** : 15 min
**Risque** : Aucun

### **2. Parallel Collectors (30 min)**
```python
# Modification main.py
async def run_all_collectors():
    collectors = [market, defillama, onchain, derivatives, sentiment]
    results = await asyncio.gather(*[c.collect() for c in collectors], 
                                   return_exceptions=True)
```
**Impact** : 5x réduction temps total collecte
**Effort** : 30 min  
**Risque** : Faible (testing requis)

### **3. Scheduler avec Jitter (45 min)**
```python
# Nouveau scheduler.py
import asyncio
import random
from apscheduler import AsyncIOScheduler

class CryptoScheduler:
    def add_collector(self, collector, interval, jitter_pct=10):
        jitter = interval * (jitter_pct / 100)
        actual_interval = interval + random.uniform(-jitter, jitter)
        scheduler.add_job(collector.collect, 'interval', seconds=actual_interval)
```
**Impact** : Respect quotas API + évitement rate limits
**Effort** : 45 min
**Risque** : Faible

---

## **🎯 SPRINT 1 - Stabilisation Core (Semaine 1)**

### **Objectifs**
✅ Éliminer les points de défaillance critique  
✅ Ajouter observabilité de base  
✅ Tests de régression  

### **User Stories**

#### **US1.1 - Scheduler Centralisé** 
**En tant que** DevOps  
**Je veux** un scheduler centralisé avec jitter  
**Pour que** les quotas API soient respectés automatiquement  

**Acceptance Criteria:**
- [ ] Scheduler avec APScheduler AsyncIO
- [ ] Jitter 10% sur tous les intervalles  
- [ ] Configuration via environment variables
- [ ] Graceful shutdown sur SIGTERM
- [ ] Tests unitaires scheduler

**Effort:** 4h | **Priorité:** P0

#### **US1.2 - Endpoints Observabilité**
**En tant que** SRE  
**Je veux** des endpoints `/health` et `/metrics`  
**Pour que** je puisse monitorer le service externalement  

**Acceptance Criteria:**
- [ ] FastAPI avec endpoints santé
- [ ] `/health` retourne status + collectors
- [ ] `/metrics` expose Prometheus format
- [ ] Démarrage sur port configurable
- [ ] Tests endpoints avec httpx

**Effort:** 2h | **Priorité:** P0

#### **US1.3 - Parallel Collectors**
**En tant que** développeur  
**Je veux** que les collectors s'exécutent en parallèle  
**Pour que** la latence totale soit optimisée  

**Acceptance Criteria:**
- [ ] `asyncio.gather()` pour collectors batch
- [ ] Gestion exceptions individuelles
- [ ] Logging parallèle structuré  
- [ ] Métriques par collector maintenues
- [ ] Tests concurrence

**Effort:** 3h | **Priorité:** P0

#### **US1.4 - Tests BaseCollector**
**En tant que** développeur  
**Je veux** une suite de tests complète pour BaseCollector  
**Pour que** les régressions soient détectées  

**Acceptance Criteria:**
- [ ] Tests retry/backoff avec mocks
- [ ] Tests fallback main→backup
- [ ] Tests cache hit/miss
- [ ] Tests métriques Prometheus
- [ ] Coverage >90% BaseCollector

**Effort:** 4h | **Priorité:** P1

#### **US1.5 - Secrets CI/CD**
**En tant que** DevOps  
**Je veux** les API keys via GitHub Secrets  
**Pour que** la CI soit sécurisée  

**Acceptance Criteria:**
- [ ] Secrets configurés dans GitHub repo
- [ ] Variables d'environnement en CI
- [ ] Tests avec vraies APIs (optionnel)
- [ ] Documentation secrets setup
- [ ] Rotation keys process

**Effort:** 1h | **Priorité:** P1

### **Livrables Sprint 1**
- ✅ Scheduler fonctionnel avec jitter
- ✅ Endpoints `/health` et `/metrics` 
- ✅ Collectors parallélisés
- ✅ Tests BaseCollector >90% coverage
- ✅ CI/CD sécurisé avec GitHub Secrets
- ✅ Performance 5x amélioration latence

---

## **🔧 SPRINT 2 - Containerization & CI/CD (Semaine 2)**

### **Objectifs**
🐳 Containerisation Docker complète  
🚀 CI/CD pipeline robuste  
📊 Monitoring étendu  

### **User Stories**

#### **US2.1 - Docker Multi-stage**
**En tant que** DevOps  
**Je veux** un Dockerfile optimisé  
**Pour que** le déploiement soit reproductible  

**Acceptance Criteria:**
- [ ] Multi-stage build (build/runtime)
- [ ] Image Alpine <100MB
- [ ] Non-root user security
- [ ] Health check intégré
- [ ] docker-compose development

**Effort:** 4h | **Priorité:** P1

#### **US2.2 - CI/CD Advanced**
**En tant que** développeur  
**Je veux** une pipeline CI/CD complète  
**Pour que** le déploiement soit automatisé  

**Acceptance Criteria:**
- [ ] Lint (black, isort, mypy)
- [ ] Security scan (safety, bandit)
- [ ] Tests + coverage report
- [ ] Docker build + push
- [ ] Semantic versioning

**Effort:** 6h | **Priorité:** P1

#### **US2.3 - Configuration Management**
**En tant que** développeur  
**Je veux** une configuration centralisée  
**Pour que** les environments soient gérés facilement  

**Acceptance Criteria:**
- [ ] Pydantic Settings model
- [ ] Validation configuration startup
- [ ] Environment-specific configs
- [ ] Configuration hot-reload
- [ ] Documentation config

**Effort:** 3h | **Priorité:** P2

### **Livrables Sprint 2**
- ✅ Docker image optimisée production
- ✅ CI/CD pipeline complète  
- ✅ Configuration management robuste
- ✅ Documentation déploiement

---

## **🗄️ SPRINT 3 - Storage & Observability (Semaine 3)**

### **Objectifs**
🗄️ Migration PostgreSQL  
📊 Dashboards Grafana  
🔍 Observabilité avancée  

### **User Stories**

#### **US3.1 - PostgreSQL Migration**
**En tant que** Data Engineer  
**Je veux** migrer de SQLite vers PostgreSQL  
**Pour que** la scalabilité soit assurée  

**Acceptance Criteria:**
- [ ] Schema migration SQLite → PostgreSQL
- [ ] Connection pooling asyncpg
- [ ] Transactions ACID robustes
- [ ] Backup/restore automatisé
- [ ] Performance benchmarking

**Effort:** 8h | **Priorité:** P2

#### **US3.2 - Grafana Dashboards**
**En tant que** SRE  
**Je veux** des dashboards Grafana  
**Pour que** le monitoring soit visuel  

**Acceptance Criteria:**
- [ ] Dashboard collectors performance
- [ ] Dashboard API quotas/limits
- [ ] Dashboard erreurs/alertes
- [ ] Dashboard business metrics
- [ ] Templates export/import

**Effort:** 6h | **Priorité:** P2

#### **US3.3 - Alerting Rules**
**En tant que** SRE  
**Je veux** des alertes automatisées  
**Pour que** les incidents soient détectés rapidement  

**Acceptance Criteria:**
- [ ] AlertManager configuration
- [ ] Rules collectors down
- [ ] Rules quotas exceeded
- [ ] Rules performance degradation
- [ ] Notification Slack/email

**Effort:** 4h | **Priorité:** P2

### **Livrables Sprint 3**
- ✅ PostgreSQL production-ready
- ✅ Grafana dashboards complets
- ✅ Alerting automatisé
- ✅ Documentation monitoring

---

## **⚡ SPRINT 4 - Résilience Avancée (Semaine 4)**

### **Objectifs**
🛡️ Circuit breaker pattern  
🔄 Dead letter queues  
🎯 Performance optimization  

### **User Stories**

#### **US4.1 - Circuit Breaker**
**En tant que** développeur  
**Je veux** un circuit breaker par collector  
**Pour que** les cascading failures soient évitées  

**Acceptance Criteria:**
- [ ] Circuit breaker configurable (failure threshold)
- [ ] Half-open state pour recovery testing
- [ ] Métriques circuit state
- [ ] Fallback graceful sur circuit open
- [ ] Tests failure scenarios

**Effort:** 6h | **Priorité:** P3

#### **US4.2 - Performance Optimization**
**En tant que** développeur  
**Je veux** optimiser les performances critiques  
**Pour que** la latence soit minimisée  

**Acceptance Criteria:**
- [ ] Profiling collectors avec cProfile
- [ ] Optimisation requêtes database
- [ ] Connection pooling tuning
- [ ] Cache strategy optimization
- [ ] Load testing results

**Effort:** 8h | **Priorité:** P3

### **Livrables Sprint 4**
- ✅ Circuit breakers fonctionnels
- ✅ Performance optimisée 50%+
- ✅ Tests charge validés

---

## **🚀 SPRINT 5+ - Scalabilité (Semaines 5-8)**

### **Vision Long Terme**

#### **Infrastructure**
- Kubernetes deployment
- Horizontal Pod Autoscaling
- Service mesh (Istio)
- Distributed caching (Redis)

#### **Observability**
- OpenTelemetry tracing
- Distributed logging (ELK)
- Chaos engineering
- SLA/SLO monitoring

#### **Features**
- Real-time data streaming
- ML-based anomaly detection
- Multi-region deployment
- Data lake integration

---

## **📊 ROI & Métriques de Succès**

### **KPIs Techniques**

| Métrique | Baseline | Sprint 1 | Sprint 3 | Sprint 5 |
|----------|----------|----------|----------|----------|
| **Latence totale collecte** | ~15s séquentiel | ~3s parallèle | ~2s optimisé | ~1s scalé |
| **Disponibilité service** | 85% (local) | 95% (monitoring) | 99% (resilience) | 99.9% (distributed) |
| **Time to recovery** | Manual | 30min (alerts) | 5min (auto) | 1min (chaos) |
| **Coverage tests** | 40% | 80% | 90% | 95% |
| **Deployment time** | Manual 30min | Docker 5min | CI/CD 2min | K8s 30s |

### **KPIs Business**

| Métrique | Baseline | Target Sprint 3 | Impact |
|----------|----------|-----------------|--------|
| **Data freshness** | 15min avg | 5min avg | ⬆️ 3x amélioration |
| **API costs** | $200/mois | $150/mois | ⬇️ 25% réduction |
| **Incidents/mois** | 8 incidents | 2 incidents | ⬇️ 75% réduction |
| **Dev velocity** | 2 features/sprint | 4 features/sprint | ⬆️ 2x amélioration |

---

## **🎯 Recommandations Stratégiques**

### **1. Commencer par Sprint 1 complet**
Focus sur stabilisation avant features avancées

### **2. Mesurer chaque amélioration**
Métriques before/after pour valider ROI

### **3. Documentation continue**
Architecture decisions records (ADR) à chaque changement

### **4. Review sécurité**
Security review avant production deployment

### **5. Formation équipe**
Knowledge transfer sur patterns implémentés

**NEXT ACTION:** 🚀 Commencer US1.1 - Scheduler Centralisé