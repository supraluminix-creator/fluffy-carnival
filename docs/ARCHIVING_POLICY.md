# Archiving policy (core/social/ws only)

This repository prioritizes the core data collection and storage flows, social integrations (X/Grok) and WebSocket clients. Anything that is not required for collecting or storing data or for AI interactions is considered non-core and can be archived.

## Scope kept (core)
- pipeline, api, scheduler, integrations
- typings, schema, data, run, exports, tests, tools, docs
- scripts, prompts, logs
- Social integrations: X (Twitter) curated feed + retweeters, Grok signals
- WebSockets clients and supporting code

## Scope archived
- Top-level directories that are not part of the list above
- Demonstration or UI code (e.g., streamlit_app.py)
- UI/Dashboard/Frontend paths or PowerShell scripts outside operational scripts
- Notebooks/demo folders, or files with extensions: .ipynb, .pbix, .ppt, .pptx, .ps1 (outside tools/ operational scope)

## Safety
- Nothing is deleted. Content is moved to `archive-YYYYMMDD_HHMMSS/` at repo root, and zipped. A report is generated.
- Placeholders and examples are preserved (e.g., `.env.example`, `.env.local.example`, `secrets.example.env`).

## How to use
- Scan only (no changes):
  ```powershell
  .\.venv\Scripts\python.exe tools\archive_repo.py --scan-only
  ```
- Archive and report:
  ```powershell
  .\.venv\Scripts\python.exe tools\archive_repo.py --run
  ```

## Notes
- The tool is conservative: only non-core content is archived based on explicit rules.
- If new non-core categories emerge, update `tools/archive_repo.py` (KEEP_TOP_DIRS/keywords) accordingly.
