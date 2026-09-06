Set-StrictMode -Version Latest

if (-not (Get-Variable -Name 'CryptoPipelineModulePath' -Scope Script -ErrorAction SilentlyContinue)) {
    $script:CryptoPipelineModulePath = $null
}

if (-not $script:CryptoPipelineModulePath) {
    if ($PSCommandPath) {
        $script:CryptoPipelineModulePath = $PSCommandPath
    } elseif ($MyInvocation.MyCommand -and $MyInvocation.MyCommand.Path) {
        $script:CryptoPipelineModulePath = $MyInvocation.MyCommand.Path
    } elseif ($PSScriptRoot) {
        $script:CryptoPipelineModulePath = Join-Path -Path $PSScriptRoot -ChildPath "CryptoPipelineMenu.psm1"
    }
}

if (-not (Get-Variable -Name 'CryptoProcessRegistry' -Scope Script -ErrorAction SilentlyContinue)) {
    $script:CryptoProcessRegistry = @{}
}

if (-not (Get-Variable -Name 'LLMBookmarkletsCache' -Scope Script -ErrorAction SilentlyContinue)) {
    $script:LLMBookmarkletsCache = $null
}

if (-not (Get-Variable -Name 'LLMRoleUrls' -Scope Script -ErrorAction SilentlyContinue)) {
    $script:LLMRoleUrls = @{
        grok = "https://grok.x.ai/?q="
        deepseek = "https://platform.deepseek.com/chat?q="
        claude = "https://claude.ai/chats?q="
        perplexity = "https://www.perplexity.ai/search?q="
        mistral = "https://chat.mistral.ai/chat?q="
    }
}

<#
 CryptoPipelineMenu.psm1 - PowerShell ISE helpers for the crypto monitoring pipeline.
 Provides one-click launchers for common tasks and a prototype toolbar.
#>

function Show-MenuError {
    param(
        [Parameter(Mandatory)] [string] $Message,
        [string] $Title = "Crypto Pipeline"
    )
    Write-Error $Message
    try {
        Add-Type -AssemblyName System.Windows.Forms -ErrorAction Stop | Out-Null
        [System.Windows.Forms.MessageBox]::Show($Message, $Title, 'OK', 'Error') | Out-Null
    } catch {
        Write-Verbose "Unable to display message box: $($_.Exception.Message)"
    }
}

function Get-LLMBookmarklets {
    [CmdletBinding()]
    param()
    if ($script:LLMBookmarkletsCache) {
        return $script:LLMBookmarkletsCache
    }
    $result = @{}
    try {
        $path = Join-Path -Path (Join-Path $PSScriptRoot "..\scripts") -ChildPath "llm_bookmarklets.json"
        if (-not (Test-Path $path)) {
            $script:LLMBookmarkletsCache = $result
            return $result
        }
        $raw = Get-Content -Path $path -Raw -Encoding UTF8
        $json = $raw | ConvertFrom-Json
        foreach ($prop in $json.PSObject.Properties) {
            $result[$prop.Name.ToLowerInvariant()] = [string]$prop.Value
        }
    } catch {
        Write-Verbose ("Unable to load llm_bookmarklets.json: {0}" -f $_.Exception.Message)
    }
    $script:LLMBookmarkletsCache = $result
    return $script:LLMBookmarkletsCache
}

function Get-LLMUsageSnapshot {
    [CmdletBinding()]
    param()
    $path = $env:LLM_USAGE_HISTORY_PATH
    if (-not $path) {
        $path = Join-Path -Path (Join-Path $PSScriptRoot "..") -ChildPath "run\llm_usage_history.json"
    }
    if (-not (Test-Path $path)) {
        return @{}
    }
    try {
        $raw = Get-Content -Path $path -Raw -Encoding UTF8
        return $raw | ConvertFrom-Json
    } catch {
        Write-Verbose ("Unable to parse usage history {0}: {1}" -f $path, $_.Exception.Message)
        return @{}
    }
}

function Get-LLMQuotaWarning {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string] $Provider,
        [string] $FallbackProvider
    )
    $snapshot = Get-LLMUsageSnapshot
    $historySource = $null
    try {
        $historySource = $snapshot.history
    } catch {
        $historySource = $null
    }
    if ($null -eq $historySource) {
        $history = @()
    } else {
        $history = @($historySource)
    }
    if (-not $history -or $history.Count -lt 6) {
        return $null
    }
    $recent = $history[(-6)..-1]
    $count = 0
    foreach ($item in $recent) {
        if ($item.provider -and ($item.provider.ToString().ToLowerInvariant() -eq $Provider.ToLowerInvariant())) {
            $count += 1
        }
    }
    $ratio = if ($recent.Count -gt 0) { $count / $recent.Count } else { 0.0 }
    $thresholdRaw = $env:LLM_QUOTA_THRESHOLD
    if (-not $thresholdRaw) {
        $thresholdRaw = "0.8"
    }
    try {
        $threshold = [double]::Parse($thresholdRaw, [System.Globalization.CultureInfo]::InvariantCulture)
    } catch {
        $threshold = 0.8
    }
    if ($ratio -lt $threshold) {
        return $null
    }
    if (-not $FallbackProvider) {
        $FallbackProvider = "deepseek"
    }
    return "Warning: {0} handled {1:P0} of the last calls. Consider using {2}." -f (
        $Provider,
        $ratio,
        $FallbackProvider
    )
}

function Invoke-LLMBookmarklet {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string] $Name,
        [Parameter(Mandatory)][string] $Prompt,
        [Parameter(Mandatory)][string] $Prefix,
        [string] $FallbackProvider,
        [string] $InputText
    )
    $key = $Name.ToLowerInvariant()
    $bookmarklets = Get-LLMBookmarklets
    if (-not $bookmarklets.ContainsKey($key)) {
        Show-MenuError -Message ("Bookmarklet '{0}' introuvable." -f $Name)
        return
    }
    if (-not $PSBoundParameters.ContainsKey('InputText')) {
        $InputText = Read-Host -Prompt $Prompt
    }
    if ([string]::IsNullOrWhiteSpace($InputText)) {
        return
    }
    $baseUrl = $script:LLMRoleUrls[$key]
    if (-not $baseUrl) {
        Show-MenuError -Message ("URL de base non définie pour {0}." -f $Name)
        return
    }
    $encoded = [System.Uri]::EscapeDataString(($Prefix + $InputText))
    $url = $baseUrl + $encoded
    $warning = Get-LLMQuotaWarning -Provider $key -FallbackProvider $FallbackProvider
    if ($warning) {
        Write-Warning $warning
    }
    try {
        Start-Process $url | Out-Null
    } catch {
        $msg = "Impossible d'ouvrir le navigateur pour {0}: {1}" -f $Name, $_.Exception.Message
        Show-MenuError -Message $msg
    }
}

function Invoke-GrokQuantAnalysis {
    [CmdletBinding()]
    param(
        [string] $InputText
    )
    Invoke-LLMBookmarklet -Name "grok" -Prompt "Analyse quanti (Grok)" -Prefix "Analyze crypto data: " -FallbackProvider "deepseek" -InputText $InputText
}

function Invoke-DeepSeekSentiment {
    [CmdletBinding()]
    param(
        [string] $InputText
    )
    Invoke-LLMBookmarklet -Name "deepseek" -Prompt "Confirmation sentiment (DeepSeek)" -Prefix "Confirm sentiment: " -FallbackProvider "grok" -InputText $InputText
}

function Invoke-ClaudeEthicsReview {
    [CmdletBinding()]
    param(
        [string] $InputText
    )
    Invoke-LLMBookmarklet -Name "claude" -Prompt "Audit éthique (Claude)" -Prefix "Ethical analysis: " -FallbackProvider "perplexity" -InputText $InputText
}

function Invoke-PerplexityLegalMonitor {
    [CmdletBinding()]
    param(
        [string] $InputText
    )
    Invoke-LLMBookmarklet -Name "perplexity" -Prompt "Vérif. lois crypto (Perplexity)" -Prefix "French/EU crypto laws: " -FallbackProvider "mistral" -InputText $InputText
}

function Invoke-MistralTaxVerify {
    [CmdletBinding()]
    param(
        [string] $InputText
    )
    Invoke-LLMBookmarklet -Name "mistral" -Prompt "Contrôle fiscal crypto (Mistral)" -Prefix "Verify French/EU crypto tax guidance: " -FallbackProvider "perplexity" -InputText $InputText
}

function Get-CryptoPipelinePythonPath {
    [CmdletBinding()]
    param()
    $paths = @(
        (Join-Path -Path $PSScriptRoot -ChildPath "..\.venv\Scripts\python.exe"),
        (Join-Path -Path $PSScriptRoot -ChildPath "..\venv\Scripts\python.exe")
    )
    foreach ($candidate in $paths) {
        $expanded = [System.IO.Path]::GetFullPath($candidate)
        if (Test-Path $expanded) {
            return $expanded
        }
    }
    $msg = "Python virtual environment not found (.venv/venv). Activate the project venv and retry."
    Show-MenuError -Message $msg
    throw $msg
}

function Start-CryptoProcess {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string] $Title,
        [Parameter(Mandatory)] [string[]] $Arguments,
        [hashtable] $Environment = @{},
        [switch] $Wait
    )
    if ($script:CryptoProcessRegistry.ContainsKey($Title)) {
        $existing = $script:CryptoProcessRegistry[$Title]
        if ($existing -and -not $existing.HasExited) {
            $msg = "{0} is already running (PID {1}). Stop it before launching again." -f $Title, $existing.Id
            Show-MenuError -Message $msg
            return
        }
        $script:CryptoProcessRegistry.Remove($Title) | Out-Null
    }
    try {
        $python = Get-CryptoPipelinePythonPath
    } catch {
        return
    }
    $repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $python
    $formattedArgs = foreach ($arg in $Arguments) {
        if ($arg -match '\s') { '"{0}"' -f $arg } else { $arg }
    }
    $psi.Arguments = [string]::Join(' ', $formattedArgs)
    $psi.WorkingDirectory = $repoRoot
    $psi.UseShellExecute = $false
    foreach ($key in $Environment.Keys) {
        $psi.Environment[$key] = [string]$Environment[$key]
    }
    Write-Host "Launching $Title via $python $($psi.Arguments)" -ForegroundColor Cyan
    try {
        $proc = [System.Diagnostics.Process]::Start($psi)
        if ($proc -and $Wait) {
            $proc.WaitForExit()
        }
        if ($proc) {
            $script:CryptoProcessRegistry[$Title] = $proc
            if ($Wait) {
                $script:CryptoProcessRegistry.Remove($Title) | Out-Null
            } else {
                Write-Host ("{0} started (PID {1})." -f $Title, $proc.Id) -ForegroundColor Green
            }
        }
        return $proc
    } catch {
        $msg = "Failed to launch {0}: {1}" -f $Title, $_.Exception.Message
        Show-MenuError -Message $msg
    }
}

function Invoke-CryptoPythonScript {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string] $Path
    )
    $full = [System.IO.Path]::GetFullPath($Path)
    if (-not (Test-Path $full)) {
        Show-MenuError -Message "Script not found: $full"
        return
    }
    Start-CryptoProcess -Title "Run $(Split-Path $full -Leaf)" -Arguments @($full) | Out-Null
}

function Start-MainScheduler {
    [CmdletBinding()]
    param()
    Start-CryptoProcess -Title "Scheduler" -Arguments @("main.py") -Environment @{ "CRYPTO_MONITOR_MODE" = "scheduler" } | Out-Null
}

function Start-MainLegacy {
    [CmdletBinding()]
    param()
    Start-CryptoProcess -Title "Legacy Run" -Arguments @("main.py") -Environment @{ "CRYPTO_MONITOR_MODE" = "legacy" } | Out-Null
}

function Stop-CryptoProcess {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string] $Title,
        [switch] $Force
    )
    if (-not (Get-Variable -Name 'CryptoProcessRegistry' -Scope Script -ErrorAction SilentlyContinue)) {
        Show-MenuError -Message "No tracked processes available."
        return
    }
    if (-not $script:CryptoProcessRegistry.ContainsKey($Title)) {
        Show-MenuError -Message "No running process tracked for $Title."
        return
    }
    $proc = $script:CryptoProcessRegistry[$Title]
    if (-not $proc) {
        $script:CryptoProcessRegistry.Remove($Title) | Out-Null
        Write-Host "$Title entry cleared (process reference missing)." -ForegroundColor Yellow
        return
    }
    if ($proc.HasExited) {
        $script:CryptoProcessRegistry.Remove($Title) | Out-Null
        Write-Host "$Title already stopped." -ForegroundColor Yellow
        return
    }
    try {
        if ($Force) {
            $proc.Kill()
        } else {
            [void]$proc.CloseMainWindow()
            Start-Sleep -Milliseconds 500
            if (-not $proc.HasExited) {
                $proc.Kill()
            }
        }
        $proc.WaitForExit()
        Write-Host ("Stopped {0} (PID {1})." -f $Title, $proc.Id) -ForegroundColor Yellow
    } catch {
        $msg = "Failed to stop {0}: {1}" -f $Title, $_.Exception.Message
        Show-MenuError -Message $msg
    } finally {
        try {
            $proc.Dispose()
        } catch {
            # ignore dispose errors
        }
        $script:CryptoProcessRegistry.Remove($Title) | Out-Null
    }
 }

function Stop-MainScheduler {
    [CmdletBinding()]
    param()
    Stop-CryptoProcess -Title "Scheduler" -Force
 }

function Invoke-PipelinePyTests {
    [Diagnostics.CodeAnalysis.SuppressMessageAttribute("PSUseApprovedVerbs", "Run", Justification="Legacy shortcut")]
    [CmdletBinding()]
    param()
    $skipFlag = $env:CRYPTO_PIPELINE_SKIP_PYTEST
    if ($null -ne $skipFlag) {
        $normalized = $skipFlag.ToString().Trim().ToLowerInvariant()
        if ($normalized -in @("1", "true", "yes", "on", "skip")) {
            Write-Host "CRYPTO_PIPELINE_SKIP_PYTEST is set; skipping pytest launch." -ForegroundColor Yellow
            return
        }
    }
    Start-CryptoProcess -Title "pytest" -Arguments @("-m", "pytest", "-v", "-q", "--cov") -Wait:$false | Out-Null
}

function Start-WhaleMonitor {
    [CmdletBinding()]
    param()
    Start-CryptoProcess -Title "Whale Insider" -Arguments @("-m", "pipeline.collectors.whale_insider") | Out-Null
}

function Start-BybitWS {
    [CmdletBinding()]
    param()
    $env = @{ "BYBIT_WS_AUTOSTART" = "1" }
    Start-CryptoProcess -Title "Bybit WS" -Arguments @("-m", "pipeline.collectors.bybit_ws") -Environment $env | Out-Null
}

function Invoke-PipelinePurgeCaches {
    [Diagnostics.CodeAnalysis.SuppressMessageAttribute("PSUseApprovedVerbs", "Purge", Justification="Legacy operator naming")]
    [CmdletBinding()]
    param()
    Start-CryptoProcess -Title "Purge Caches" -Arguments @("cli_purge.py", "--dry-run") -Wait:$true | Out-Null
}

function Show-CryptoPipelineToolbar {
    [CmdletBinding()]
    param()
    try {
        Add-Type -AssemblyName System.Windows.Forms -ErrorAction Stop | Out-Null
        Add-Type -AssemblyName System.Drawing -ErrorAction Stop | Out-Null
    } catch {
        Show-MenuError -Message "Unable to load Windows Forms assemblies: $($_.Exception.Message)"
        return
    }
    $form = New-Object System.Windows.Forms.Form
    $form.Text = "Crypto Pipeline"
    $form.Size = New-Object System.Drawing.Size(640, 160)
    $form.FormBorderStyle = 'FixedDialog'
    $form.StartPosition = 'CenterScreen'

    $buttons = @(
        @{ Text = "Scheduler"; Handler = { Start-MainScheduler } },
        @{ Text = "Pytest"; Handler = { Invoke-PipelinePyTests } },
        @{ Text = "Whales"; Handler = { Start-WhaleMonitor } },
        @{ Text = "Bybit WS"; Handler = { Start-BybitWS } },
    @{ Text = "Purge"; Handler = { Invoke-PipelinePurgeCaches } },
        @{ Text = "Grok"; Handler = { Invoke-GrokQuantAnalysis } },
        @{ Text = "DeepSeek"; Handler = { Invoke-DeepSeekSentiment } },
        @{ Text = "Claude"; Handler = { Invoke-ClaudeEthicsReview } },
        @{ Text = "Legal"; Handler = { Invoke-PerplexityLegalMonitor } },
        @{ Text = "Tax"; Handler = { Invoke-MistralTaxVerify } }
    )
    $x = 10
    $y = 20
    foreach ($btn in $buttons) {
        $button = New-Object System.Windows.Forms.Button
        $button.Text = $btn.Text
        $button.Size = New-Object System.Drawing.Size(95, 32)
        $button.Location = New-Object System.Drawing.Point($x, $y)
        $button.Add_Click($btn.Handler)
        $form.Controls.Add($button)
        $x += 100
        if ($x -ge 540) {
            $x = 10
            $y += 40
        }
    }
    $form.Add_Shown({ $form.Activate() })
    $form.ShowDialog() | Out-Null
}

function Get-ExistingShortcuts {
    param([object] $Menu)
    $shortcuts = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    if ($null -eq $Menu) {
        return $shortcuts
    }
    foreach ($item in $Menu) {
        if ($item.Shortcut) {
            [void]$shortcuts.Add($item.Shortcut)
        }
        if ($item.SubMenus) {
            $child = Get-ExistingShortcuts -Menu $item.SubMenus
            foreach ($short in $child) {
                [void]$shortcuts.Add($short)
            }
        }
    }
    return $shortcuts
}

function Register-CryptoPipelineMenu {
    [CmdletBinding()]
    param()
    if (-not (Test-Path variable:psISE)) {
        Write-Verbose "PowerShell ISE not detected; skipping Add-ons menu registration."
        return
    }
    $tab = $psISE.CurrentPowerShellTab
    if (-not $tab) {
        return
    }
    $menuCollection = $tab.AddOnsMenu.SubMenus
    $existing = @()
    foreach ($item in $menuCollection) {
        if ($item.DisplayName -eq "Crypto Pipeline Tools") {
            $existing += $item
        }
    }
    foreach ($item in $existing) {
        $menuCollection.Remove($item) | Out-Null
    }
    $root = $menuCollection.Add("Crypto Pipeline Tools", $null, $null)
    $shortcuts = Get-ExistingShortcuts -Menu $menuCollection
        if (-not $shortcuts) {
            $shortcuts = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
        }

    $shortcutMap = @{
        "Start-MainScheduler" = "Ctrl+Shift+M"
        "Start-MainLegacy" = "Ctrl+Shift+L"
        "Invoke-PipelinePyTests" = "Ctrl+Shift+T"
        "Start-WhaleMonitor" = "Ctrl+Shift+W"
        "Start-BybitWS" = "Ctrl+Shift+B"
    "Invoke-PipelinePurgeCaches" = "Ctrl+Shift+P"
        "Show-CryptoPipelineToolbar" = "Ctrl+Shift+G"
        "Invoke-GrokQuantAnalysis" = "Ctrl+Shift+Q"
        "Invoke-DeepSeekSentiment" = "Ctrl+Shift+D"
        "Invoke-ClaudeEthicsReview" = "Ctrl+Shift+E"
        "Invoke-PerplexityLegalMonitor" = "Ctrl+Shift+C"
        "Invoke-MistralTaxVerify" = "Ctrl+Shift+V"
    }

        $addMenuItem = {
            param(
                [string] $Text,
                [scriptblock] $Action,
                [string] $Shortcut
            )
            $effectiveShortcut = $null
            if ($Shortcut) {
                if ($shortcuts.Contains($Shortcut)) {
                    Write-Verbose "Shortcut $Shortcut already in use; skipping for $Text."
                } else {
                    [void]$shortcuts.Add($Shortcut)
                    $effectiveShortcut = $Shortcut
                }
            }
            try {
                $root.SubMenus.Add($Text, $Action, $effectiveShortcut) | Out-Null
            } catch {
                if ($effectiveShortcut) {
                    Write-Verbose ("Unable to assign shortcut {0} for {1}: {2}" -f $effectiveShortcut, $Text, $_.Exception.Message)
                }
                $root.SubMenus.Add($Text, $Action, $null) | Out-Null
            }
        }

        & $addMenuItem -Text "Start Scheduler" -Action { Start-MainScheduler } -Shortcut $shortcutMap["Start-MainScheduler"]
        & $addMenuItem -Text "Stop Scheduler" -Action { Stop-MainScheduler } -Shortcut $null
        & $addMenuItem -Text "Start Legacy Run" -Action { Start-MainLegacy } -Shortcut $shortcutMap["Start-MainLegacy"]
    & $addMenuItem -Text "Run pytest" -Action { Invoke-PipelinePyTests } -Shortcut $shortcutMap["Invoke-PipelinePyTests"]
        & $addMenuItem -Text "Start Whale Monitor" -Action { Start-WhaleMonitor } -Shortcut $shortcutMap["Start-WhaleMonitor"]
        & $addMenuItem -Text "Start Bybit WS" -Action { Start-BybitWS } -Shortcut $shortcutMap["Start-BybitWS"]
    & $addMenuItem -Text "Purge caches (dry-run)" -Action { Invoke-PipelinePurgeCaches } -Shortcut $shortcutMap["Invoke-PipelinePurgeCaches"]
        & $addMenuItem -Text "Toolbar (preview)" -Action { Show-CryptoPipelineToolbar } -Shortcut $shortcutMap["Show-CryptoPipelineToolbar"]
    & $addMenuItem -Text "LLM: Grok quant" -Action { Invoke-GrokQuantAnalysis } -Shortcut $shortcutMap["Invoke-GrokQuantAnalysis"]
    & $addMenuItem -Text "LLM: DeepSeek sentiment" -Action { Invoke-DeepSeekSentiment } -Shortcut $shortcutMap["Invoke-DeepSeekSentiment"]
    & $addMenuItem -Text "LLM: Claude ethics" -Action { Invoke-ClaudeEthicsReview } -Shortcut $shortcutMap["Invoke-ClaudeEthicsReview"]
    & $addMenuItem -Text "LLM: Perplexity légal" -Action { Invoke-PerplexityLegalMonitor } -Shortcut $shortcutMap["Invoke-PerplexityLegalMonitor"]
    & $addMenuItem -Text "LLM: Mistral fiscal" -Action { Invoke-MistralTaxVerify } -Shortcut $shortcutMap["Invoke-MistralTaxVerify"]

    $repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
    $scripts = @(Get-ChildItem -Path (Join-Path $repoRoot "scripts") -Filter '*.py' -File -ErrorAction SilentlyContinue)
    $collectors = @(Get-ChildItem -Path (Join-Path $repoRoot "pipeline\collectors") -Filter '*.py' -File -ErrorAction SilentlyContinue)
    foreach ($item in $scripts + $collectors) {
        $label = "Run {0}" -f $item.BaseName
        $cmd = "Invoke-CryptoPythonScript -Path `"{0}`"" -f $item.FullName
        $root.SubMenus.Add($label, [ScriptBlock]::Create($cmd), $null) | Out-Null
    }

    Write-Host "Crypto Pipeline menu registered in PowerShell ISE." -ForegroundColor Green
}

function Set-CryptoPipelineProfileImport {
    [Diagnostics.CodeAnalysis.SuppressMessageAttribute("PSUseApprovedVerbs", "Ensure", Justification="Compatibility with previous releases")]
    [CmdletBinding()]
    param()
    if ($env:CRYPTO_PIPELINE_DISABLE_PROFILE_IMPORT -in @('1', 'true', 'True')) {
        Write-Verbose "Profile import disabled via environment flag."
        return
    }
    try {
        $profilePath = $PROFILE.CurrentUserCurrentHost
    } catch {
        return
    }
    if (-not $profilePath) {
        return
    }
    $resolved = [System.IO.Path]::GetFullPath($profilePath)
    if (-not (Test-Path $resolved)) {
        New-Item -ItemType File -Path $resolved -Force | Out-Null
    }
    $modulePath = $script:CryptoPipelineModulePath
    if ([string]::IsNullOrWhiteSpace($modulePath)) {
        Write-Verbose "Unable to resolve module path for profile import."
        return
    }
    $modulePath = [System.IO.Path]::GetFullPath($modulePath)
    $importLine = "Import-Module `"$modulePath`""
    try {
        $content = Get-Content -Path $resolved -ErrorAction Stop
    } catch {
        $content = @()
    }
    if ($null -eq $content) {
        $content = @()
    } else {
        $content = @($content)
    }
    $invalidPattern = '^\s*Import-Module\s+""\s*$'
    $filtered = @()
    foreach ($line in $content) {
        if ($line -match $invalidPattern) {
            continue
        }
        $filtered += $line
    }
    if ($filtered.Count -ne $content.Count) {
        Set-Content -Path $resolved -Value $filtered -Force
        $content = $filtered
    }
    if ($content -notcontains $importLine) {
        Add-Content -Path $resolved -Value ($importLine + [Environment]::NewLine)
        Write-Host "Added module import to $resolved" -ForegroundColor Yellow
    }
}

Export-ModuleMember -Function *

    Set-CryptoPipelineProfileImport
Register-CryptoPipelineMenu
