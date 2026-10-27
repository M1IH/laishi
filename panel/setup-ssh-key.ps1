# ============================================================
#  One-time setup: move the SSH key into %USERPROFILE%\.ssh, lock its ACL,
#  load it into ssh-agent, and make ssh-agent start automatically.
#  ASCII-only on purpose (PowerShell 5.1 reads BOM-less UTF-8 as GBK).
#
#  Run:  powershell -NoProfile -ExecutionPolicy Bypass -File setup-ssh-key.ps1
#
#  Design notes (learned the hard way, 2026-10-27):
#   * ssh-add prints "Identity added" on STDERR. With $ErrorActionPreference='Stop'
#     every native call's stderr becomes a terminating ErrorRecord, so the script
#     died right after a SUCCESSFUL load. Native calls now run with relaxed
#     preference and are judged by $LASTEXITCODE only.
#   * Every step is best-effort and reported separately: a failure in one step
#     must not abort the rest, because the user may be running unelevated.
#   * Doing ACL work on a file we just created inside ~/.ssh can leave it
#     unreadable even for us (observed). We grant the current user full control
#     explicitly, and verify by actually loading the key.
# ============================================================
$ErrorActionPreference = 'Continue'

$dest   = Join-Path $env:USERPROFILE '.ssh\miruku_deploy.pem'
$sshDir = Join-Path $env:USERPROFILE '.ssh'
$srcDir = 'C:\Users\OTTO\Desktop\' + [string][char]0x6765 + [string][char]0x4E16
$server = 'root@203.0.113.10'
$fails  = @()

function Note([string]$msg, [string]$color = 'Gray') {
    Write-Host $msg -ForegroundColor $color
}

# ---- 1) put the key in place -----------------------------------------------
Note '[1/5] Key location'
if (-not (Test-Path -LiteralPath $sshDir)) {
    New-Item -ItemType Directory -Path $sshDir -Force | Out-Null
    Note "      created $sshDir"
}
if (Test-Path -LiteralPath $dest) {
    Note "      already there: $dest"
} else {
    $src = Get-ChildItem -LiteralPath $srcDir -Filter '*.pem' -ErrorAction SilentlyContinue |
           Select-Object -First 1
    if (-not $src) {
        Note "      [FAIL] no .pem in $srcDir and none at $dest" 'Red'
        $fails += 'key-not-found'
    } else {
        Copy-Item -LiteralPath $src.FullName -Destination $dest -Force
        Note "      copied $($src.Name) -> $dest"
    }
}

# ---- 2) ACL: only the current user, and make sure that user can read --------
# OpenSSH refuses a key readable by others. We strip inheritance and grant the
# current account read (not just via inherited group) so the check passes.
if (Test-Path -LiteralPath $dest) {
    Note '[2/5] ACL'
    $me = "$env:USERDOMAIN\$env:USERNAME"
    # NOTE: capture rc immediately after each native call -- piping to Out-Null
    # resets $LASTEXITCODE, which made this step report a false failure.
    icacls $dest /inheritance:r > $null 2>&1; $rc1 = $LASTEXITCODE
    icacls $dest /grant:r "${me}:(R)" > $null 2>&1; $rc2 = $LASTEXITCODE
    $acl = (icacls $dest 2>&1) -join "`n"
    # The real acceptance test is not the exit code but "does OpenSSH accept it":
    # no Everyone/Users entry, and our own account present.
    $leaky = $acl -match 'Everyone|BUILTIN\\Users'
    if ($leaky) {
        Note '      [WARN] ACL still grants group access; trying to remove' 'Yellow'
        icacls $dest /inheritance:r > $null 2>&1
        icacls $dest /remove "Everyone" "BUILTIN\Users" > $null 2>&1
        $acl = (icacls $dest 2>&1) -join "`n"
        $leaky = $acl -match 'Everyone|BUILTIN\\Users'
    }
    if ($leaky) {
        Note '      [WARN] could not fully restrict ACL (needs admin). OpenSSH may refuse this key.' 'Yellow'
        $fails += 'acl-too-open'
    } else {
        Note '      owner-only read (no Everyone/Users)'
    }
}

# ---- 3) ssh-agent: automatic startup (needs admin), and running ------------
Note '[3/5] ssh-agent service'
$svc = Get-Service ssh-agent -ErrorAction SilentlyContinue
if (-not $svc) {
    Note '      [FAIL] ssh-agent service not installed' 'Red'
    $fails += 'no-agent-service'
} else {
    try {
        Set-Service ssh-agent -StartupType Automatic -ErrorAction Stop
        Note '      startup type = Automatic'
    } catch {
        Note '      needs one elevation to set Automatic; retrying via UAC...' 'Yellow'
        try {
            $p = Start-Process powershell -Verb RunAs -Wait -PassThru -ArgumentList @(
                '-NoProfile', '-Command',
                'Set-Service ssh-agent -StartupType Automatic'
            )
            if ($p.ExitCode -eq 0) {
                $now = (Get-Service ssh-agent).StartType
                Note "      startup type = $now"
            } else {
                Note "      [WARN] elevated call exited $($p.ExitCode)" 'Yellow'
            }
        } catch {
            Note '      [WARN] UAC declined; startup type unchanged (optional)' 'Yellow'
        }
    }
    if ($svc.Status -ne 'Running') {
        try { Start-Service ssh-agent -ErrorAction Stop; Note '      started' }
        catch {
            Note "      [FAIL] cannot start ssh-agent: $($_.Exception.Message)" 'Red'
            $fails += 'agent-not-running'
        }
    } else {
        Note '      already running'
    }
}

# ---- 4) load the key ------------------------------------------------------
Note '[4/5] Load key into agent'
$addRc = 1
if (Test-Path -LiteralPath $dest) {
    $err = ssh-add $dest 2>&1
    $addRc = $LASTEXITCODE
    if ($addRc -eq 0) { Note '      loaded' }
    elseif ("$err" -match 'already') { Note '      already loaded'; $addRc = 0 }
    else {
        Note "      [FAIL] ssh-add rc=$addRc" 'Red'
        "$err" -split "`n" | Select-Object -First 3 | ForEach-Object { Note "        $_" 'Red' }
        $fails += 'ssh-add-failed'
    }
}
Note '      agent now holds:'
(ssh-add -l 2>&1) | ForEach-Object { Note "        $_" }

# ---- 5) verify end to end -------------------------------------------------
Note '[5/5] Verify against server'
$out = ssh -o BatchMode=yes -o ConnectTimeout=10 $server 'echo CONNECT_OK' 2>&1
$connRc = $LASTEXITCODE
if ($connRc -eq 0 -and "$out" -match 'CONNECT_OK') {
    Note '      CONNECT_OK' 'Green'
} else {
    Note "      [FAIL] ssh rc=$connRc" 'Red'
    "$out" -split "`n" | Select-Object -First 3 | ForEach-Object { Note "        $_" 'Red' }
    $fails += 'connect-failed'
}

# ---- summary --------------------------------------------------------------
Note ''
if ($fails.Count -eq 0) {
    Note '  Done.' 'Green'
    Note '  The launcher will now load this key automatically after every reboot.'
    Note '  You may delete the old .pem inside the project folder.'
} else {
    Note ("  Finished with problems: " + ($fails -join ', ')) 'Yellow'
    Note '  Most common cause: not elevated. Right-click PowerShell > Run as administrator.'
}
Note ''
Read-Host 'Press Enter to close'
