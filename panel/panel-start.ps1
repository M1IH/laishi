# Miruku panel launcher: SSH tunnel + local panel. Closing the window kills both.
# ASCII-ONLY ON PURPOSE: Windows PowerShell 5.1 decodes BOM-less UTF-8 .ps1 as
# the system ANSI codepage (GBK here), so any non-ASCII literal corrupts the
# script and breaks parsing ("string missing terminator"). Keep it English.
$ErrorActionPreference = 'Continue'
$panelPort = 8642
$here      = Split-Path -Parent $MyInvocation.MyCommand.Path

# Server target: env var > project-root .env > documented placeholder.
# The public repo only ships the RFC 5737 placeholder (203.0.113.10), so the
# real host must come from MIRUKU_SSH or from the gitignored .env file.
$target = $env:MIRUKU_SSH
if (-not $target) {
    $envFile = Join-Path $here '..\.env'
    if (Test-Path -LiteralPath $envFile) {
        foreach ($line in Get-Content -LiteralPath $envFile -Encoding UTF8) {
            if ($line -match '^\s*MIRUKU_SSH\s*=\s*(.+?)\s*$') {
                $target = $Matches[1].Trim('"', "'")
                break
            }
        }
    }
}
if ($target -match '203\.0\.113\.10') {
    Write-Host ''
    Write-Host '[ERROR] Server address not configured.' -ForegroundColor Red
    Write-Host '        Add this line to the project-root .env file:'
    Write-Host '            MIRUKU_SSH=root@<your-server-ip>'
    Write-Host '        (203.0.113.10 is the documentation placeholder that ships'
    Write-Host '         with the public repo and is not a real host.)'
    Write-Host ''
    Read-Host 'Press Enter to exit'
    exit 3
}
$panelPy   = Join-Path $here 'panel.py'

# 1) Python: prefer the AstrBot Launcher venv, fall back to system python
$py = 'C:\Users\OTTO\.astrbot_launcher\instances\298681be-6ba8-4137-818c-28ed67ec9176\venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $py)) {
    $c = Get-Command python -ErrorAction SilentlyContinue
    if ($c) { $py = $c.Source }
}
if (-not $py -or -not (Test-Path -LiteralPath $py)) {
    Write-Host '[ERROR] Python not found.' -ForegroundColor Red
    Read-Host 'Press Enter to exit'
    exit 1
}

# 2) Panel already running? just open the browser
$panelProc = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -like 'python*' -and $_.CommandLine -like '*panel.py*' }
if ($panelProc) {
    Write-Host '[INFO] Panel already running, opening browser.'
    Start-Process "http://127.0.0.1:$panelPort/"
    exit 0
}

# 3) Locate the private key and probe the server.
#    Explicit -i does NOT depend on ssh-agent, which is unreliable here (the
#    agent named pipe is often invisible from some shells). Loading into the
#    agent stays as a best-effort so hand-typed plain `ssh` keeps working.
Write-Host '[1/3] Locating key and checking connectivity...'
$keyPath = $env:MIRUKU_KEY
if (-not $keyPath) { $keyPath = Join-Path $env:USERPROFILE '.ssh\miruku_deploy.pem' }
if (-not (Test-Path -LiteralPath $keyPath)) {
    $projDir = 'C:\Users\OTTO\Desktop\' + [string][char]0x6765 + [string][char]0x4E16
    $found = Get-ChildItem -LiteralPath $projDir -Filter '*.pem' -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($found) { $keyPath = $found.FullName }
}
$sshArgs = @('-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10')
if ($keyPath -and (Test-Path -LiteralPath $keyPath)) {
    Write-Host "      Using key: $keyPath"
    $sshArgs += @('-i', $keyPath, '-o', 'IdentitiesOnly=yes')
    $agentSvc = Get-Service ssh-agent -ErrorAction SilentlyContinue
    if ($agentSvc -and $agentSvc.Status -ne 'Running') {
        try { Start-Service ssh-agent -ErrorAction Stop } catch {}
    }
    $ErrorActionPreference = 'SilentlyContinue'
    ssh-add $keyPath 2>&1 | Out-Null
    $ErrorActionPreference = 'Continue'
} else {
    Write-Host '      [WARN] No .pem found; relying on ssh-agent.' -ForegroundColor Yellow
}
$probe = & ssh @sshArgs $target 'echo ok' 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host ''
    Write-Host '[ERROR] Cannot reach the server.' -ForegroundColor Red
    Write-Host '        Expected key: %USERPROFILE%\.ssh\miruku_deploy.pem'
    Write-Host '        If missing, run once in PowerShell:'
    Write-Host '            ssh-add $env:USERPROFILE\.ssh\miruku_deploy.pem'
    Write-Host ''
    Write-Host ($probe | Select-Object -First 3)
    Read-Host 'Press Enter to exit'
    exit 2
}

# 4) Tunnel: reuse an existing one if present, otherwise start it
#    2026-10-29: SnowLuma era. 6185 AstrBot WebUI, 5099 SnowLuma WebUI,
#    6081 noVNC (QQ login/QR), 14100 -> 4100 meme plugin WebUI.
Write-Host '[2/3] Setting up SSH tunnel...'
$existing = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -eq 'ssh.exe' -and $_.CommandLine -like '*6081:127.0.0.1:6081*' }
$ssh = $null
if ($existing) {
    Write-Host '      Existing tunnel found, reusing it.'
} else {
    # Reuse the same key flags resolved in step 3; without -i the tunnel falls
    # back to ssh-agent and dies with "Permission denied (publickey)".
    $fwd = @('-N','-o','ServerAliveInterval=30','-o','ServerAliveCountMax=3',
             '-o','ExitOnForwardFailure=yes')
    $fwd += $sshArgs
    $fwd += @('-L','6185:127.0.0.1:6185','-L','5099:127.0.0.1:5099',
              '-L','6081:127.0.0.1:6081','-L','14100:127.0.0.1:4100',$target)
    $ssh = Start-Process ssh -ArgumentList $fwd -NoNewWindow -PassThru
}

$deadline = (Get-Date).AddSeconds(30)
$tun = $false
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 800
    try { Invoke-WebRequest 'http://127.0.0.1:6081/vnc.html' -UseBasicParsing -TimeoutSec 3 | Out-Null; $tun = $true; break } catch {}
}
if (-not $tun) { Write-Host '[WARN] Tunnel not ready after 30s; panel may show no data.' -ForegroundColor Yellow }

# 5) Panel
#    Bind 0.0.0.0 so a phone on the same WiFi can open the QR page at
#    http://<lan-ip>:8642/scan (the panel relays to the server over SSH,
#    so no extra cloud security-group port is needed).
Write-Host "[3/3] Starting panel on http://127.0.0.1:$panelPort/ ..."
$env:MIRUKU_PANEL_BIND = '0.0.0.0'
$panel = Start-Process $py -ArgumentList ('"' + $panelPy + '"') -NoNewWindow -PassThru
$deadline = (Get-Date).AddSeconds(30)
$up = $false
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 700
    try { Invoke-WebRequest "http://127.0.0.1:$panelPort/healthz" -UseBasicParsing -TimeoutSec 3 | Out-Null; $up = $true; break } catch {}
}
if ($up) {
    Start-Process "http://127.0.0.1:$panelPort/"
    $lan = (Get-NetIPAddress -AddressFamily IPv4 |
            Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } |
            Select-Object -First 1).IPAddress
    if ($lan) { Write-Host "  Phone QR page (same WiFi): http://${lan}:$panelPort/scan" -ForegroundColor Cyan }
}
else { Write-Host '[WARN] Panel did not answer; check panel.py output.' -ForegroundColor Yellow }

Write-Host ''
Write-Host '  Ready. Closing this window stops the tunnel AND the panel.' -ForegroundColor Green
Write-Host '  QQ login/QR: noVNC tab (http://127.0.0.1:6081/vnc.html) or /scan on your phone.'
Write-Host '  Credentials: Status tab, "扫码登录" card (noVNC password + phone QR link).'
Write-Host ''

# 6) Keep the console alive while the tunnel lives; clean up when it dies
if ($ssh) {
    Wait-Process -Id $ssh.Id -ErrorAction SilentlyContinue
    Stop-Process -Id $panel.Id -Force -ErrorAction SilentlyContinue
    Write-Host '[INFO] SSH tunnel closed (network drop or server reboot). Start again to reconnect.' -ForegroundColor Yellow
} else {
    Wait-Process -Id $panel.Id -ErrorAction SilentlyContinue
}
Start-Sleep 8
