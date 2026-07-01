$ErrorActionPreference = "Stop"

$GitRoot = "C:\Users\16052\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\git"
$Git = Join-Path $GitRoot "cmd\git.exe"
$env:Path = (Join-Path $GitRoot "mingw64\bin") + ";" + (Join-Path $GitRoot "cmd") + ";" + $env:Path
$env:GIT_EXEC_PATH = Join-Path $GitRoot "mingw64\bin"

Write-Host "GitHub username:" -ForegroundColor Cyan
$Username = Read-Host

Write-Host "GitHub Personal Access Token (输入时不会显示):" -ForegroundColor Cyan
$SecureToken = Read-Host -AsSecureString
$Bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureToken)
try {
    $Token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($Bstr)
}
finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Bstr)
}

$Pair = "$Username`:$Token"
$Bytes = [Text.Encoding]::ASCII.GetBytes($Pair)
$Basic = [Convert]::ToBase64String($Bytes)

& $Git -c credential.helper= -c http.sslBackend=openssl -c "http.extraHeader=Authorization: Basic $Basic" push -u origin main

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "推送成功。接下来到 GitHub 仓库 Settings -> Pages 开启 main / root。" -ForegroundColor Green
}
else {
    throw "git push failed with exit code $LASTEXITCODE"
}
