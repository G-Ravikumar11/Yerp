# Puts a private copy of Python, with pyodbc, in the "python" folder beside this script - nothing is installed in
# Windows, and nothing else on the computer is touched. SETUP.bat runs this when that folder is not there yet.
# Both files come from their official homes and are checked against the fingerprints below before they are used.
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = Join-Path $here 'python'
if (Test-Path (Join-Path $py 'python.exe')) { exit 0 }

if (-not [Environment]::Is64BitOperatingSystem) {
  Write-Host 'This is 32-bit Windows. Install 32-bit Python 3 from python.org (tick "Add python.exe to PATH"), then run SETUP.bat again.'
  exit 2
}
$v = [Environment]::OSVersion.Version
if ($v.Major -lt 6 -or ($v.Major -eq 6 -and $v.Minor -lt 3)) {
  Write-Host 'This Windows is older than Windows 8.1 / Server 2012 R2. Install Python 3.8 from python.org (tick "Add python.exe to PATH"), then run SETUP.bat again.'
  exit 3
}

$files = @(
  @{ url = 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip'; name = 'python.zip';
     sha = '4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3' },
  @{ url = 'https://files.pythonhosted.org/packages/c0/70/5e61b216cc13c7f833ef87f4cdeab253a7873f8709253f5076e9bb16c1b3/pyodbc-5.3.0-cp312-cp312-win_amd64.whl'; name = 'pyodbc.whl';
     sha = 'fe77eb9dcca5fc1300c9121f81040cc9011d28cff383e2c35416e9ec06d4bc95' }
)

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Add-Type -AssemblyName System.IO.Compression.FileSystem
$tmp = Join-Path $here '_download'
New-Item -ItemType Directory -Force -Path $tmp | Out-Null
try {
  foreach ($f in $files) {
    $file = Join-Path $tmp $f.name
    Write-Host ('  downloading ' + (Split-Path $f.url -Leaf) + ' ...')
    (New-Object System.Net.WebClient).DownloadFile($f.url, $file)
    $got = (Get-FileHash -Path $file -Algorithm SHA256).Hash.ToLower()
    if ($got -ne $f.sha) { throw ('The download of ' + $f.url + ' did not match its fingerprint, so it was not used.') }
  }
  [IO.Compression.ZipFile]::ExtractToDirectory((Join-Path $tmp 'python.zip'), $py)
  $site = Join-Path $py 'Lib\site-packages'
  New-Item -ItemType Directory -Force -Path $site | Out-Null
  [IO.Compression.ZipFile]::ExtractToDirectory((Join-Path $tmp 'pyodbc.whl'), $site)
  # This Python reads its search path from python312._pth: add the folder pyodbc went into.
  $pth = Get-ChildItem -Path $py -Filter 'python*._pth' | Select-Object -First 1
  [IO.File]::AppendAllText($pth.FullName, "`r`nLib\site-packages`r`n")
} catch {
  if (Test-Path $py) { Remove-Item -Recurse -Force $py }
  Write-Host ('  ' + $_.Exception.Message)
  Write-Host '  Check that this computer can open https://www.python.org, then run SETUP.bat again.'
  exit 1
} finally {
  if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
}
& (Join-Path $py 'python.exe') -c "import sys, pyodbc; print('  ready: Python ' + sys.version.split()[0] + ', pyodbc ' + pyodbc.version)"
exit $LASTEXITCODE
