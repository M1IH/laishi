# ============================================================
#  One-time setup: move the SSH key into %USERPROFILE%\.ssh, lock its ACL,
#  load it into ssh-agent, and make ssh-agent start automatically.
#  ASCII-only on purpose (PowerShell 5.1 reads BOM-less UTF-8 as GBK).
#
#  Run once:  powershell -NoProfile -ExecutionPolicy Bypass -File setup-ssh-key.ps1
# ============================================================
$ErrorActionPreference = 'Stop'

# 1) Locate the key: prefer the new location, else the workspace copy
$dest    = Join-Path $env:USERPROFILE '.ssh\miruku_deploy.pem'
$sshDir  = Join-Path $env:USERPROFILE '.ssh'
$srcDir  = 'C:\Users\OTTO\Desktop\' + [string][char]0x6765 + [string][char]0x4E16
$sources = @(Get-ChildItem -LiteralPath $srcDir -Filter '*.pem' -ErrorAction SilentlyContinue)

if (-not (Test-Path -LiteralPath $sshDir)) { New-Item -ItemType Directory -Path $sshDir -Force | Out-Null }

if (-not (Test-Path -LiteralPath $dest)) {
    if ($sources.Count -eq 0) {
        Write-Host "[ERROR] No .pem found in $srcDir and no $dest" -ForegroundColor Red
        exit 1
    }
    $src = $sources[0].FullName
    Write-Host "Moving: $src"
    Write-Host "    -> $dest"
    Copy-Item -LiteralPath $src -Destination $dest -Force
} else {
    Write-Host "Key already present: $dest"
}

# 2) Lock down ACL: only the current user may read it (OpenSSH refuses otherwise)
Write-Host 'Tightening ACL...'
icacls $dest /inheritance:r | Out-Null
icacls $dest /grant:r "$($env:USERNAME):(R)" | Out-Null

# 3) ssh-agent: automatic + running
Write-Host 'Configuring ssh-agent...'
Set-Service ssh-agent -StartupType Automatic
$svc = Get-Service ssh-agent
if ($svc.Status -ne 'Running') { Start-Service ssh-agent }
Start-Sleep 1

# 4) Load the key (idempotent: ssh-add fails harmlessly if already loaded)
ssh-add $dest 2>&1 | ForEach-Object { if ($_ -notmatch 'already') { Write-Host "  $_" } }
Write-Host ''
Write-Host 'Agent keys:'
ssh-add -l
Write-Host ''

# 5) Verify against the server
Write-Host 'Verifying connection...'
ssh -o BatchMode=yes -o ConnectTimeout=10 root@203.0.113.10 'echo CONNECT_OK'
if ($LASTEXITCODE -eq 0) {
    Write-Host ''
    Write-Host '  Done. The launcher will now load this key automatically after reboot.' -ForegroundColor Green
    Write-Host '  You may delete the old copy in the project folder if it is still there.'
} else {
    Write-Host '[WARN] Key loaded but the connection failed. Check the server IP / security group.' -ForegroundColor Yellow
}
Write-Host ''
Read-Host 'Press Enter to close'
