# Sprint du 2025-10-08 — Quick wins, pas de pytest pendant le sprint

Objectif: Avancer rapidement sur l’outillage d’injection (bookmarklet) et la validation manuelle de l’API LLM DeepSeek, sans lancer la suite de tests complète pendant le sprint (trop long). Les tests seront exécutés en fin de sprint.

Contenu du sprint:
- Bookmarklet `inject_prompt.js`
  - Ajout d’annotations JSDoc (lisibilité/maintenance)
  - Quick wins: nouveaux drapeaux `/clear` (vider le champ) et `/unique` (éviter les doublons)
  - Documentation enrichie (`bookmarklets/readme.md` déjà détaillé)
- Outillage exécution API (Windows):
  - `scripts/run_uvicorn.ps1`: lance l’API (chargement `.env.local`, auto-port, reload en option)
  - `scripts/smoke_llm_api.ps1`: smoke HTTP simple pour `/api/llm/status`, `/api/llm/generate`, `/api/llm/stream`
  - `scripts/smoke_llm_inprocess.ps1`: smoke in-process rapide (TestClient), sans serveur uvicorn
  - `scripts/build_bookmarklet.ps1`: génère le bookmarklet (compact/auto-pack/mapping/clipboard)

Exécution rapide (Windows PowerShell):

```powershell
# 1) Démarrer l’API en local
./scripts/run_uvicorn.ps1 -AutoPort

# 2) Vérifier l’API LLM (X-API-KEY pris depuis $env:API_WRITE_KEY)
./scripts/smoke_llm_api.ps1 -Base "http://127.0.0.1:8000"

# Variante in-process (sans serveur):
./scripts/smoke_llm_inprocess.ps1

# 3) Générer le bookmarklet et copier dans le presse-papiers
& .\.venv\Scripts\python.exe tools\build_bookmarklet.py --clip --auto-pack --compact --use-mapping
# ou via le helper PowerShell
./scripts/build_bookmarklet.ps1 -Compact -AutoPack -UseMapping -Clip -Page "bookmarklets/bookmarklet.html"
```

Notes:
- Le smoke PowerShell ne lit pas le SSE en flux continu (limitation `Invoke-WebRequest`), il valide le 200 et un contenu initial.
- Pour un test plus robuste, utilisez `tools/smoke_api_inprocess.py` (in-process TestClient) ou `tools/sse_client.py` en Python.
- DeepSeek peut être forcé via `API_LLM_ONLY=deepseek`; renseignez `DEEPSEEK_API_KEY` dans `.env.local`.

Fin de sprint:
- Exécuter lint + pytest via les tâches VS Code fournies (déjà vertes à la date du jour).
