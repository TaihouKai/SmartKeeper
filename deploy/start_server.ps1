# SmartKeeper 服务器启动脚本（Windows，局域网部署）。
# 配置在 %APPDATA%\SmartKeeper\server.json（不进仓库）；API key 用 DPAPI 加密存在 %APPDATA%\SmartKeeper\secrets\。
# 由计划任务“SmartKeeper Server”在登录时启动，也可以手动运行：powershell -File deploy\start_server.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$cfgPath = Join-Path $env:APPDATA "SmartKeeper\server.json"
$secrets = Join-Path $env:APPDATA "SmartKeeper\secrets"
$cfg = Get-Content $cfgPath -Raw | ConvertFrom-Json

function Read-Secret([string]$name) {
    $p = Join-Path $secrets "$name.dpapi"
    if (-not (Test-Path $p)) { return $null }
    return [System.Net.NetworkCredential]::new("", (Get-Content $p | ConvertTo-SecureString)).Password
}

$env:PYTHONUTF8 = "1"
$env:SMARTKEEPER_DB_PATH = $cfg.db_path
$env:SMARTKEEPER_MAPS_DIR = $cfg.maps_dir
$env:SMARTKEEPER_SCENARIOS_DIR = $cfg.scenarios_dir
$env:SMARTKEEPER_STATIC_DIR = Join-Path $root "frontend\dist"
$env:SMARTKEEPER_ADMIN_PASSWORD_HASH = $cfg.admin_password_hash
$env:SMARTKEEPER_SESSION_SECRET = (Read-Secret "session_secret")
$env:SMARTKEEPER_JUDGE_PROVIDER = $cfg.judge_provider
$env:SMARTKEEPER_JUDGE_MODEL = $cfg.judge_model
$env:SMARTKEEPER_WRITER_PROVIDER = $cfg.writer_provider
$env:SMARTKEEPER_WRITER_MODEL = $cfg.writer_model
if ($cfg.openai_base_url) { $env:OPENAI_COMPAT_BASE_URL = $cfg.openai_base_url }
if ($cfg.openai_key_secret) { $env:OPENAI_COMPAT_API_KEY = (Read-Secret $cfg.openai_key_secret) }
if ($cfg.openai_compat_web_search) { $env:OPENAI_COMPAT_WEB_SEARCH = "true" }
$anthropic = Read-Secret "anthropic"
if ($anthropic) { $env:ANTHROPIC_API_KEY = $anthropic }
$openai = Read-Secret "openai"
if ($openai) { $env:OPENAI_API_KEY = $openai }

$log = Join-Path (Split-Path -Parent $cfg.db_path) "server.log"
Set-Location $root
# uvicorn 把日志写到 stderr；Windows PowerShell 5.1 会把原生程序的 stderr 当成错误，所以经由 cmd 重定向
$py = Join-Path $root ".venv\Scripts\python.exe"
$ErrorActionPreference = "Continue"
cmd /c "`"$py`" -m uvicorn smartkeeper.web:create_app --factory --host 0.0.0.0 --port $($cfg.port) --log-level info >> `"$log`" 2>&1"
exit $LASTEXITCODE
