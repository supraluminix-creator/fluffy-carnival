Tests - Conventions & Stratégie
================================

Objectifs:
- Couvrir les chemins fonctionnels critiques (collectors, export, scheduler, métriques, santé).
- Limiter la dette de maintenance en évitant tests fragiles dépendants du réseau ou du timing réel.
- Normaliser l'usage de `# pragma: no cover`.

Politique de Mock Réseau
------------------------
1. Toute requête HTTP externe doit être mockée (httpx / websocket).
2. Les scénarios fallback (API principale échoue -> secondaire) sont testés au moins une fois par famille de collectors.
3. Pas de test end‑to‑end réseau live dans la CI (instabilité, flakiness).

Usage Accepté de `# pragma: no cover`
------------------------------------
Utiliser uniquement si l'une des conditions suivantes est vraie:
1. Branche hautement défensive (ex: double fallback rarissime, parse exotique) dont le test serait artificiel et peu robuste.
2. Code d'exécution manuelle (`if __name__ == "__main__":`).
3. Sections timing non déterministes (flush condition sur horloge, race volontairement tolérée).
4. Protocol / shim purement structurel (aucune logique).

À éviter:
- Masquer une logique testable facilement (validation entrées, transformation pure, helpers simples).

Organisation des Tests
----------------------
tests/
  test_* : tests unitaires rapides (collectors, export, métriques).
  utils/ : helpers de mocks (clients http asynchrones, réponses simulées).

Principes:
- Un test = un comportement principal (Given/When/Then implicite).
- Préférer Assert ciblés et lisibles vs. assertions multiples sur de gros objets.
- Temps d'exécution visé < 5s global.

Métriques & Observabilité
-------------------------
Pour les compteurs / histogrammes Prometheus:
1. Utiliser `._value.get()` pour assertions internes (OK en test isolé).
2. Pour tests de bout en bout, sérialiser via `generate_latest()` et matcher les lignes.

Scheduler & Long-Running
------------------------
Simuler la boucle principale en monkeypatchant `asyncio.sleep` pour déclencher un `KeyboardInterrupt` ou terminer rapidement.

Export & Fichiers
-----------------
Utiliser `tmp_path` pytest.
Tester chemins d'erreur (permission simulée, pas de données) + succès.

Ajouts Futurs Potentiels
------------------------
- Tests property-based (hypothesis) pour validateurs de normalisation.
- Tests contract pour formats d'enregistrement exportés (schéma JSON/CSV stable).
- Tests de performance ciblés (profil simple collectors). 

Maintenance
-----------
Avant d'ajouter un nouveau `pragma: no cover`, vérifier:
1. Le test serait-il réellement flaky ?
2. Une injection de dépendance ou refactor simple rendrait-il le test trivial ?
3. La valeur de la branche est-elle critique en production ? Si oui, mieux vaut un test robuste.

Historique Nettoyage P1
-----------------------
- Suppression ancien module `pipeline.monitoring` + tests associés.
- Ajout tests ciblés `logging_config`, `metrics init`, `exporter exceptions`.
- Retrait pragmas devenus superflus.

Contact / Revue
---------------
Toute proposition de suppression globale de tests doit être revue (code owner). Pull Request: inclure diff couverture (`coverage diff`).
