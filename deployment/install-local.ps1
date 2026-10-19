param([string]$Model = 'qwen2.5-coder:7b', [switch]$PlanOnly)
$ErrorActionPreference = 'Stop'
# Safe to rerun after a Windows restart. No vault files or quiz JSON are deleted.
if ($Model -notmatch '^[a-zA-Z0-9_.:/-]+$') { throw 'Invalid model name.' }
$packages = @('Python.Python.3.13', 'Ollama.Ollama', 'Docker.DockerDesktop')
if ($PlanOnly) { Write-Output "Install/check: $($packages -join ', '); prepare python:3.13-alpine; pull $Model"; exit 0 }
$logDir = Join-Path $env:LOCALAPPDATA 'MarkdownQuizSetup'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
function Run-Hidden([string]$File, [string[]]$Arguments) {
  $out = Join-Path $logDir 'stdout.log'; $err = Join-Path $logDir 'stderr.log'
  $process = Start-Process -FilePath $File -ArgumentList $Arguments -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput $out -RedirectStandardError $err
  if ($process.ExitCode -ne 0) { throw "Setup command failed ($($process.ExitCode)). Read $out and $err. If Windows requires a restart, restart and rerun setup." }
}
$winget = (Get-Command winget -ErrorAction Stop).Source
foreach ($package in $packages) {
  # List first: winget returns a nonzero 'no upgrade' result for already installed packages.
  & $winget list --id $package --exact --accept-source-agreements *> $null
  if ($LASTEXITCODE -ne 0) { Run-Hidden $winget @('install', '--id', $package, '--exact', '--source', 'winget', '--accept-source-agreements', '--accept-package-agreements', '--silent') }
}
$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')
$docker = (Get-Command docker -ErrorAction Stop).Source
$ollama = (Get-Command ollama -ErrorAction Stop).Source
try { Invoke-RestMethod 'http://127.0.0.1:11434/api/tags' -TimeoutSec 3 | Out-Null }
catch { Start-Process -FilePath $ollama -ArgumentList 'serve' -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDir 'ollama-out.log') -RedirectStandardError (Join-Path $logDir 'ollama-err.log') | Out-Null }
$desktop = Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'
if (-not (Test-Path -LiteralPath $desktop)) { $desktop = Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\Docker Desktop.exe' }
if (Test-Path -LiteralPath $desktop) { Start-Process -FilePath $desktop -WindowStyle Hidden | Out-Null }
$ready = $false
for ($attempt = 0; $attempt -lt 40; $attempt++) {
  try { Run-Hidden $docker @('info', '--format', '{{.OSType}}'); if ((Get-Content (Join-Path $logDir 'stdout.log') -Raw).Trim() -eq 'linux') { $ready = $true; break } } catch { }
  Start-Sleep -Seconds 3
}
if (-not $ready) { throw 'Docker Linux engine is unavailable. Finish Docker Desktop setup (WSL/virtualization may require a Windows restart), then rerun this installer.' }
Run-Hidden $docker @('pull', 'python:3.13-alpine')
Run-Hidden $ollama @('pull', $Model)
Write-Output 'Dependencies ready. Copy the included markdown-quiz-generator folder into your vault .obsidian/plugins, enable it, choose Local computer, then click Start backend.'
Write-Output 'If Obsidian was already open, restart it to refresh PATH. Choose the installed Ollama model in plugin settings.'
