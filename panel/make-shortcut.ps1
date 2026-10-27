# Make "Miruku panel" shortcuts (workspace + Desktop).
# ASCII-ONLY on purpose: Windows PowerShell 5.1 decodes BOM-less UTF-8 .ps1
# as GBK, so any Chinese literal in this file would become mojibake.
# Chinese strings are built from code points instead.
$ErrorActionPreference = 'Stop'

$mian = [string][char]0x9762 + [string][char]0x677F   # "mian ban" (panel)
$lai  = [string][char]0x6765 + [string][char]0x4E16   # project dir name
$root = 'C:\Users\OTTO\Desktop\' + $lai
if (-not (Test-Path -LiteralPath $root)) { throw "root missing: $root" }

$bat = Get-ChildItem -LiteralPath $root -Filter '*.bat' |
    Where-Object { $_.BaseName.Contains($mian) } |
    Select-Object -First 1
if (-not $bat) { throw "no launcher .bat under $root" }
Write-Output "target: $($bat.FullName)"

$sh = New-Object -ComObject WScript.Shell
$lnkName = 'Miruku ' + $mian + '.lnk'

function Make($path) {
    $l = $sh.CreateShortcut($path)
    $l.TargetPath       = $bat.FullName
    $l.WorkingDirectory = $root
    $l.Description      = 'SSH tunnel + Miruku admin panel'
    $l.IconLocation     = 'shell32.dll,137'
    $l.Save()
    return (Test-Path -LiteralPath $path)
}

$a = Make (Join-Path $root $lnkName)
$b = Make (Join-Path ([Environment]::GetFolderPath('Desktop')) $lnkName)
Write-Output "workspace=$a desktop=$b"
