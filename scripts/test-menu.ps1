Import-Module (Join-Path $PSScriptRoot "..\modules\CryptoPipelineMenu.psm1") -Force

Write-Host "Testing Crypto Pipeline menu registration..."
Register-CryptoPipelineMenu
Write-Host "Done."
