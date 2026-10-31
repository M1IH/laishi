# Miruku panel launcher: SSH tunnel + local panel. Closing the window kills both.
# ASCII-ONLY ON PURPOSE: Windows PowerShell 5.1 decodes BOM-less UTF-8 .ps1 as
# the system ANSI codepage (GBK here), so any non-ASCII literal corrupts the
# script and breaks parsing ("string missing terminator"). Keep it English.
$ErrorActionPreference = 'Continue'
$target    = 'root@203.0.113.10'
$panelPort = 8642
$here      = Split-Path -Parent $MyInvocation.MyCommand.Path
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

# 3) Make sure the key is loaded, then check SSH reachability.
#    The key now lives in %USERPROFILE%\.ssh (moved out of the workspace, where it
#    did not belong). After a reboot the agent is empty, so load it here -- the
#    user then never has to run ssh-add by hand again.
Write-Host '[1/3] Checking SSH agent and connectivity...'
$agentSvc = Get-Service ssh-agent -ErrorAction SilentlyContinue
if ($agentSvc -and $agentSvc.Status -ne 'Running') {
    Write-Host '      Starting ssh-agent service...'
    try { Set-Service ssh-agent -StartupType Automatic -ErrorAction Stop; Start-Service ssh-agent -ErrorAction Stop }
    catch { Write-Host '[WARN] Could not start ssh-agent (needs admin once).' -ForegroundColor Yellow }
}
$loaded = (ssh-add -l 2>&1)
if ($LASTEXITCODE -ne 0 -or $loaded -match 'no identities') {
    # Prefer the tidy location (%USERPROFILE%\.ssh), fall back to the in-project
    # copy so the launcher keeps working before the one-time move is done.
    $candidates = @()
    $candidates += (Join-Path $env:USERPROFILE '.ssh\miruku_deploy.pem')
    $projDir = 'C:\Users\OTTO\Desktop\' + [string][char]0x6765 + [string][char]0x4E16
    $candidates += @(Get-ChildItem -LiteralPath $projDir -Filter '*.pem' -ErrorAction SilentlyContinue |
                     ForEach-Object { $_.FullName })
    foreach ($k in $candidates) {
        if (Test-Path -LiteralPath $k) {
            Write-Host "      Loading key: $k"
            # ssh-add reports success on STDERR; never let that look like a failure
            $ErrorActionPreference = 'SilentlyContinue'
            ssh-add $k 2>&1 | Out-Null
            $addRc = $LASTEXITCODE
            $ErrorActionPreference = 'Continue'
            if ($addRc -ne 0) { Write-Host "      [WARN] ssh-add returned $addRc" -ForegroundColor Yellow }
            break
        }
    }
}
$probe = ssh -o BatchMode=yes -o ConnectTimeout=10 $target 'echo ok' 2>&1
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
    $fwd = @('-N','-o','BatchMode=yes','-o','ServerAliveInterval=30','-o','ServerAliveCountMax=3',
             '-o','ExitOnForwardFailure=yes',
             '-L','6185:127.0.0.1:6185','-L','5099:127.0.0.1:5099',
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
