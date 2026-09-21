<#
.SYNOPSIS
    Install the mdtohtml release binary on Windows.
.DESCRIPTION
    Downloads the latest release: the themeless Windows binary zip plus the
    separate themes asset, unpacks both (binary + themes/) into an install
    directory, and adds that directory to your user PATH. Re-runnable. After
    this, `mdtohtml update` keeps the binary and themes current.

    Install to a custom location:
        $env:MDTOHTML_INSTALL_DIR = 'C:\tools\mdtohtml'
        irm https://raw.githubusercontent.com/MatLomax/mdtohtml/main/scripts/install.ps1 | iex
#>
$ErrorActionPreference = 'Stop'
# Windows PowerShell 5.1 does not enable TLS 1.2 by default, but api.github.com
# requires it; and the progress bar makes a multi-MB download crawl.
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
$ProgressPreference = 'SilentlyContinue'

$repo = if ($env:MDTOHTML_REPO) { $env:MDTOHTML_REPO } else { 'MatLomax/mdtohtml' }
$installDir = if ($env:MDTOHTML_INSTALL_DIR) { $env:MDTOHTML_INSTALL_DIR } else { Join-Path $env:LOCALAPPDATA 'Programs\mdtohtml' }
# Normalise to an absolute path (resolves a relative override and unifies slashes),
# then drop any trailing separator.
$installDir = [System.IO.Path]::GetFullPath($installDir).TrimEnd('\', '/')

# The installer replaces this directory wholesale — never let a stray override
# point it at a drive root or the user profile.
if ($installDir -eq '' -or $installDir -eq $env:USERPROFILE.TrimEnd('\', '/') -or $installDir -match '^[A-Za-z]:[\\/]?$') {
    throw "refusing to install into '$installDir'; set MDTOHTML_INSTALL_DIR to a dedicated directory"
}

# Only x86_64 Windows binaries are published.
if ($env:PROCESSOR_ARCHITECTURE -ne 'AMD64') {
    throw "no prebuilt binary for Windows/$($env:PROCESSOR_ARCHITECTURE); build from source: https://github.com/$repo"
}
# The binary and its themes ship as two separate assets; install both.
$asset = 'mdtohtml-windows-x86_64.zip'
$themesAsset = 'mdtohtml-themes.zip'
$headers = @{ 'User-Agent' = 'mdtohtml-install' }

Write-Host "Resolving the latest mdtohtml release ..."
$release = Invoke-RestMethod -Uri "https://api.github.com/repos/$repo/releases/latest" -Headers $headers
$tag = $release.tag_name
if (-not $tag) { throw 'could not determine the latest release (offline?)' }

Write-Host "Installing mdtohtml $tag ($asset + $themesAsset) ..."
$tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("mdtohtml-install-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $tmp | Out-Null
try {
    # Download one named asset and verify its sha256 (GitHub publishes a per-asset digest).
    function Get-Verified($name) {
        $info = $release.assets | Where-Object { $_.name -eq $name } | Select-Object -First 1
        if (-not $info) { throw "the latest release ($tag) has no asset $name" }
        $out = Join-Path $tmp $name
        Invoke-WebRequest -Uri $info.browser_download_url -OutFile $out -Headers $headers
        $digest = $info.digest
        if ($digest -and $digest.StartsWith('sha256:')) {
            $expected = $digest.Substring(7).ToLower()
            $actual = (Get-FileHash -Algorithm SHA256 -Path $out).Hash.ToLower()
            if ($actual -ne $expected) {
                throw "checksum mismatch for ${name}: expected $expected, got $actual"
            }
            Write-Host "  sha256 verified ($name)"
        } else {
            Write-Host "  (${name}: release digest unavailable; verification skipped, downloaded over HTTPS)"
        }
        return $out
    }
    $binZip = Get-Verified $asset
    $themesZip = Get-Verified $themesAsset

    # Unpack both into a sibling of the install dir (same volume), then swap.
    $parent = Split-Path $installDir
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    $stage = "$installDir.new-$([guid]::NewGuid().ToString('N'))"
    Expand-Archive -Path $binZip -DestinationPath $stage -Force
    Expand-Archive -Path $themesZip -DestinationPath $stage -Force
    if (-not (Test-Path (Join-Path $stage 'mdtohtml.exe'))) { throw 'binary archive has no mdtohtml.exe' }
    if (-not (Test-Path (Join-Path $stage 'themes'))) { throw 'themes archive has no themes directory' }

    if (Test-Path $installDir) {
        # Only ever replace a prior mdtohtml install or an empty dir.
        if (-not (Test-Path (Join-Path $installDir 'mdtohtml.exe')) -and @(Get-ChildItem -Force $installDir).Count -gt 0) {
            Remove-Item -Recurse -Force $stage
            throw "refusing to overwrite non-empty $installDir (not a prior mdtohtml install)"
        }
        $old = "$installDir.old-$([guid]::NewGuid().ToString('N'))"
        Move-Item $installDir $old
        try {
            Move-Item $stage $installDir
        } catch {
            Move-Item $old $installDir  # restore the previous install on failure
            Remove-Item -Recurse -Force $stage, $old -ErrorAction SilentlyContinue
            throw
        }
        Remove-Item -Recurse -Force $old -ErrorAction SilentlyContinue
    } else {
        Move-Item $stage $installDir
    }
} finally {
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
}

# Add the install dir to the user PATH, preserving %VAR% indirections
# (read the raw REG_EXPAND_SZ value; write it back as an expandable string).
# CreateSubKey opens the existing Environment key (or creates it), never null.
$key = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey('Environment')
$pathChanged = $false
try {
    $raw = [string]$key.GetValue('Path', '', [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
    $entries = @($raw -split ';' | Where-Object { $_ -ne '' })
    if ($entries -notcontains $installDir) {
        $newRaw = (@($entries) + $installDir) -join ';'
        $key.SetValue('Path', $newRaw, [Microsoft.Win32.RegistryValueKind]::ExpandString)
        $pathChanged = $true
    }
} finally {
    $key.Dispose()
}

if ($pathChanged) {
    # Broadcast WM_SETTINGCHANGE so already-running explorer.exe refreshes its
    # environment block; without this, terminals spawned from the shell keep the
    # stale PATH until logoff. (A raw registry write, unlike
    # [Environment]::SetEnvironmentVariable, does not broadcast on its own.)
    if (-not ('MdtohtmlEnv.Native' -as [type])) {
        Add-Type -Namespace MdtohtmlEnv -Name Native -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("user32.dll", SetLastError=true, CharSet=System.Runtime.InteropServices.CharSet.Auto)]
public static extern System.IntPtr SendMessageTimeout(System.IntPtr hWnd, uint Msg, System.IntPtr wParam, string lParam, uint fuFlags, uint uTimeout, out System.UIntPtr lpdwResult);
'@
    }
    $HWND_BROADCAST = [System.IntPtr]0xffff
    $WM_SETTINGCHANGE = 0x1A
    $result = [System.UIntPtr]::Zero
    [void][MdtohtmlEnv.Native]::SendMessageTimeout($HWND_BROADCAST, $WM_SETTINGCHANGE, [System.IntPtr]::Zero, 'Environment', 2, 5000, [ref]$result)
    Write-Host ""
    Write-Host "Added $installDir to your user PATH. Open a new terminal for it to take effect."
}

Write-Host ""
Write-Host "Installed: $installDir\mdtohtml.exe"
Write-Host "Done. Run 'mdtohtml --help' to get started."
