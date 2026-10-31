param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$Data,
    [string]$CodexHome
)

$ErrorActionPreference = 'Stop'
$projectPath = (Resolve-Path -LiteralPath $ProjectRoot).Path
$installArgs = @('run', '--project', $projectPath, '--locked', 'godot-knowledge')
if ($Data) { $installArgs += @('--data', $Data) }
$installArgs += 'install'
if ($CodexHome) { $installArgs += @('--codex-home', $CodexHome) }
& uv @installArgs
if ($LASTEXITCODE -ne 0) { throw 'Installation failed.' }
