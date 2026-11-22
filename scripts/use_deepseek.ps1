# 在当前 PowerShell 会话里切到 DeepSeek（OpenAI 兼容接口）做测试。
# 用法：. .\scripts\use_deepseek.ps1   （注意前面的点，环境变量才会留在当前会话）
# Key 用 Windows DPAPI 加密存在 %APPDATA%\SmartKeeper\secrets\deepseek.dpapi，只有本机这个用户能解开；不进仓库。
$path = Join-Path $env:APPDATA "SmartKeeper\secrets\deepseek.dpapi"
if (-not (Test-Path $path)) { throw "missing $path" }
$env:OPENAI_COMPAT_API_KEY = [System.Net.NetworkCredential]::new("", (Get-Content $path | ConvertTo-SecureString)).Password
$env:OPENAI_COMPAT_BASE_URL = "https://api.deepseek.com"
$env:SMARTKEEPER_JUDGE_PROVIDER = "openai_compat"
$env:SMARTKEEPER_WRITER_PROVIDER = "openai_compat"
$env:SMARTKEEPER_JUDGE_MODEL = "deepseek-v4-pro"
$env:SMARTKEEPER_WRITER_MODEL = "deepseek-flash"
Write-Host "DeepSeek test provider configured for this session"
