$env:CRYPTO_PIPELINE_DISABLE_PROFILE_IMPORT = "1"
$modulePath = Join-Path $PSScriptRoot "..\modules\CryptoPipelineMenu.psm1"
Import-Module $modulePath -Force
$moduleName = "CryptoPipelineMenu"

Describe "CryptoPipelineMenu" {
    Context "process launch helpers" {
        It "starts scheduler with scheduler mode" {
            Mock -CommandName Start-CryptoProcess -ModuleName $moduleName -MockWith { }
            Start-MainScheduler
            Assert-MockCalled Start-CryptoProcess -ModuleName $moduleName -Times 1 -ParameterFilter {
                $Title -eq "Scheduler" -and $Environment["CRYPTO_MONITOR_MODE"] -eq "scheduler"
            }
        }

        It "runs pytest with module flag" {
            Mock -CommandName Start-CryptoProcess -ModuleName $moduleName -MockWith { }
            Invoke-PipelinePyTests
            Assert-MockCalled Start-CryptoProcess -ModuleName $moduleName -Times 1 -ParameterFilter {
                $Arguments -contains "-m" -and $Arguments -contains "pytest"
            }
        }

        It "skips pytest when environment flag is set" {
            Mock -CommandName Start-CryptoProcess -ModuleName $moduleName -MockWith { }
            $env:CRYPTO_PIPELINE_SKIP_PYTEST = "1"
            try {
                Invoke-PipelinePyTests
                Assert-MockCalled Start-CryptoProcess -ModuleName $moduleName -Times 0 -Scope It
            } finally {
                Remove-Item Env:CRYPTO_PIPELINE_SKIP_PYTEST -ErrorAction SilentlyContinue
            }
        }
    }

    Context "menu registration" {
        It "skips registration outside ISE" {
            if (Test-Path variable:psISE) {
                Remove-Variable -Name psISE -Force
            }
            { Register-CryptoPipelineMenu } | Should Not Throw
        }
    }

    Context "process management" {
        It "stops scheduler via stop helper" {
            Mock -CommandName Stop-CryptoProcess -ModuleName $moduleName -MockWith { }
            Stop-MainScheduler
            Assert-MockCalled Stop-CryptoProcess -ModuleName $moduleName -Times 1 -ParameterFilter {
                $Title -eq "Scheduler"
            }
        }
    }

    Context "LLM helpers" {
        BeforeAll {
            $script:llmTempHistory = Join-Path $env:TEMP ([System.Guid]::NewGuid().ToString() + ".json")
            $env:LLM_USAGE_HISTORY_PATH = $script:llmTempHistory
        }

        AfterAll {
            if (Test-Path $script:llmTempHistory) {
                Remove-Item $script:llmTempHistory -ErrorAction SilentlyContinue
            }
            Remove-Item Env:LLM_USAGE_HISTORY_PATH -ErrorAction SilentlyContinue
        }

        It "launches grok analysis via bookmarklet helper" {
            Mock -CommandName Start-Process -ModuleName $moduleName -MockWith {
                param($FilePath)
                Set-Variable -Name lastUrl -Value $FilePath -Scope Global
            }
            Invoke-GrokQuantAnalysis -InputText "BTC volatility"
            Assert-MockCalled Start-Process -ModuleName $moduleName -Times 1
            $global:lastUrl | Should Match "https://grok.x.ai/\?q=Analyze%20crypto%20data%3A%20BTC%20volatility"
            Remove-Variable -Name lastUrl -Scope Global -ErrorAction SilentlyContinue
        }

        It "launches perplexity legal monitor" {
            Mock -CommandName Start-Process -ModuleName $moduleName -MockWith {
                param($FilePath)
                Set-Variable -Name lastLegalUrl -Value $FilePath -Scope Global
            }
            Invoke-PerplexityLegalMonitor -InputText "MiCA taxation"
            Assert-MockCalled Start-Process -ModuleName $moduleName -Times 1
            $global:lastLegalUrl | Should Match "https://www.perplexity.ai/search\?q=French%2FEU%20crypto%20laws%3A%20MiCA%20taxation"
            Remove-Variable -Name lastLegalUrl -Scope Global -ErrorAction SilentlyContinue
        }
    }
}
