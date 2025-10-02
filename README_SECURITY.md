# Sécurité & Supply Chain

## SBOM (Software Bill of Materials)
Un SBOM CycloneDX minimal est générable localement et en CI pour inventorier les dépendances Python effectives.

### Génération manuelle
```
python -m pipeline.tools.generate_sbom
```
Fichiers produits par défaut dans `sbom/`:
- `sbom.json` (CycloneDX JSON)
- `sbom.xml` (si SBOM_FORMATS inclut XML)

### Variables d'environnement
| Var | Défaut | Description |
|-----|--------|-------------|
| `SBOM_OUTPUT_DIR` | `sbom` | Répertoire de sortie. |
| `SBOM_FORMATS` | `JSON` | Liste séparée par virgule (`JSON`, `XML`). |

### Contenu SBOM
Le script construit la liste des distributions installées (importlib.metadata) avec:
- name, version, purl (`pkg:pypi/<name>@<version>`) 
- hash heuristique SHA-256 (concat contenu `.py`) – indicatif, pas une signature officielle
- dependencies: noms référencés via `Requires-Dist` (pas de graphe hiérarchique complet)

Limitations actuelles:
- Pas de licences consolidées
- Pas de relations explicites parent → child (liste plate avec champ `dependencies` par composant)
- Hash non reproductible si fichiers `.py` exclus ou wheel binaire (fallback: absence de champ)

### Intégration CI (exemple GitHub Actions)
```yaml
name: sbom
on: [push]
jobs:
  build-sbom:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install -r requirements.txt
      - run: python -m pipeline.tools.generate_sbom
      - uses: actions/upload-artifact@v4
        with:
          name: sbom
          path: sbom/
```

### Usage futur
- Diff entre deux commits pour détecter ajout/suppression dépendance.
- Entrée potentielle pour un scanner vulnérabilités (Trivy, osv-scanner).
- Extraction licences / compliance.
- Génération CycloneDX complète (dependency graph, hashes standardisés).

## Principes additionnels (roadmap)
- Scan Semgrep baseline faible bruit.
- Protection secrets (pré-commit + push protection).
- Documentation `RUNBOOK_INCIDENTS.md` pour scénarios critiques.
