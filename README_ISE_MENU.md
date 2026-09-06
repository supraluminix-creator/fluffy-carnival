# PowerShell ISE Menu for Crypto Pipeline

The `CryptoPipelineMenu` module adds a persistent Add-ons menu to Windows PowerShell ISE so non-technical operators can launch the most common tasks without remembering commands.

## Installation

1. Ensure the repository virtual environment exists at `.venv` (run `python -m venv .venv` if needed).
2. Import the module once:
   ```powershell
   Import-Module (Join-Path $PWD "modules\CryptoPipelineMenu.psm1")
   ```
3. The module automatically appends an `Import-Module` line to `$PROFILE.CurrentUserCurrentHost`. Close and reopen PowerShell ISE to load the menu on start-up.

## Usage

- Open PowerShell ISE and verify the **Crypto Pipeline Tools** entry in the Add-ons menu.
- Keyboard shortcuts (avoiding conflicts automatically):
  - `Ctrl+Shift+M` – start scheduler mode (`main.py`).
  - *(menu only)* **Stop Scheduler** – terminates the tracked scheduler process if it was started from the menu.
  - `Ctrl+Shift+L` – run legacy batch (`main.py`).
  - `Ctrl+Shift+T` – execute `pytest -v -q --cov`.
  - `Ctrl+Shift+W` – launch whale insider monitor.
  - `Ctrl+Shift+B` – start Bybit WebSocket bridge.
  - `Ctrl+Shift+P` – run `cli_purge.py --dry-run`.
- Dynamic **Run [Name]** entries are created automatically for every `scripts/*.py` and `pipeline/collectors/*.py` file.
- Use the **Toolbar (preview)** entry to open the Windows Forms stub with quick action buttons.
- Long-running jobs (like the scheduler) stay active until you stop them. The menu tracks launched processes so you can stop them later without hunting for PIDs.

## Troubleshooting

- **Menu missing:** Re-import the module (`Import-Module modules/CryptoPipelineMenu.psm1 -Force`). Ensure PowerShell ISE is running (the module no-ops in non-ISE hosts).
- **Venv not detected:** Verify `.venv\Scripts\python.exe` exists. The module falls back to `venv\Scripts\python.exe` if needed.
- **Profile locked:** If `$PROFILE.CurrentUserCurrentHost` cannot be written, add the import line manually.
- **Error pop-ups:** The module shows friendly dialogs through `System.Windows.Forms.MessageBox` while also logging to the console.

## Toolbar Preview

The toolbar window is a proof-of-concept built with .NET WinForms. It opens a small dialog with buttons mapped to the same actions as the Add-ons menu. Extend it by editing `Show-CryptoPipelineToolbar` inside the module.

## Maintenance

- Update shortcuts or actions in `modules/CryptoPipelineMenu.psm1`.
- Add new scripts to `scripts/` or collectors to `pipeline/collectors/`; the menu refreshes on module import.
- Run the smoke script `scripts/test-menu.ps1` to validate menu registration in automation.
