# Legacy Audit

Ce document recense les modules legacy supprimés ou en cours de dépréciation après la segmentation des métriques et la refonte export.

## Statuts
- Active: utilisée normalement.
- Deprecated: fonctionne encore mais émet un `DeprecationWarning`, remplacée par un nouvel API.
- Removed: retirée du codebase (remplacer usages immédiatement si encore référencés hors repo).

## Tableau
| Module | Statut | Remplacement / Note |
|--------|--------|----------------------|
| `pipeline/metrics.py` | Deprecated (stub) | Stub de ré-export + compat; segmentation sous `pipeline/metrics/` |
| `pipeline/db_metrics.py` | Deprecated (shim) | Redirige vers `pipeline.db_stats` avec `DeprecationWarning` |
| `pipeline/base_collector.py` | Deprecated (shim) | Redirige vers `pipeline.collectors.base_collector` |
| `pipeline/monitoring.py` | Deprecated | Migrer vers imports directs `from pipeline.metrics import ...` |
| `pipeline/exporter.py` | Deprecated | Utiliser `pipeline.export_utils.export_latest_and_timestamped` |

## Rationale suppressions
- Élimination des doublons réduit risque d'incohérences métriques et classes divergentes.
- Centralisation logique (ex: DB metrics) dans modules thématiques.
- Simplification surface publique: un seul point d'import stable `pipeline.metrics`.

## TODO potentiels (futurs)
- Introduire wrapper high-level pour exports (si besoin d'API objet) par-dessus `export_utils`.
- Ajouter script CI vérifiant absence ré-introduction modules supprimés.
- Fusion/clarification des jobs (`export_job.py`, `flush_jobs.py`) si encore présents mais non utilisés.

Dernière mise à jour: conversion de certains Removed en shims Deprecated (préservation compat externe).
