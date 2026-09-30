$ErrorActionPreference = 'Stop'

$installDir = Join-Path $env:LOCALAPPDATA "CeroMailer"
$baseUrl = "https://raw.githubusercontent.com/UlquiorraCiffer/CeroMailer/main"
$files = @("cli.py", "ceromailer.cmd")

Write-Host "Installing CeroMailer..." -ForegroundColor Cyan

# 1. Create target directory
try {
    if (-not (Test-Path -Path $installDir)) {
        New-Item -ItemType Directory -Path $installDir -Force | Out-Null
    }
}
catch {
    Write-Error "Failed to create installation directory: $installDir. $($_.Exception.Message)"
    exit 1
}

# 2. Download files (overwrites existing files for easy updates)
foreach ($file in $files) {
    $fileUrl = "$baseUrl/$file"
    $destination = Join-Path $installDir $file
    Write-Host "Downloading $file..."
    try {
        Invoke-RestMethod -Uri $fileUrl -OutFile $destination
    }
    catch {
        Write-Error "Failed to download $file from $fileUrl. Installation aborted."
        exit 1
    }
}

# 3. Add to user PATH environment variable if not already present
try {
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $normalizedInstallDir = $installDir.TrimEnd('\', '/')
    $pathParts = if ($userPath) { $userPath -split ';' } else { @() }
    $alreadyInPath = $false

    foreach ($part in $pathParts) {
        if ($part.Trim().TrimEnd('\', '/') -ieq $normalizedInstallDir) {
            $alreadyInPath = $true
            break
        }
    }

    if (-not $alreadyInPath) {
        $newUserPath = if ([string]::IsNullOrWhiteSpace($userPath)) {
            $installDir
        } else {
            ($pathParts + $installDir) -join ';'
        }
        [Environment]::SetEnvironmentVariable("Path", $newUserPath, "User")
    }

    # Also update current session's PATH
    $sessionPathParts = $env:Path -split ';'
    $inSession = $false
    foreach ($part in $sessionPathParts) {
        if ($part.Trim().TrimEnd('\', '/') -ieq $normalizedInstallDir) {
            $inSession = $true
            break
        }
    }
    if (-not $inSession) {
        $env:Path = "$env:Path;$installDir"
    }
}
catch {
    Write-Warning "Could not update user PATH environment variable: $($_.Exception.Message)"
}

# 4. Print clear success message
Write-Host "`n==========================================" -ForegroundColor Green
Write-Host "  CeroMailer installed successfully!" -ForegroundColor Green
Write-Host "==========================================`n" -ForegroundColor Green
Write-Host "To launch CeroMailer, simply type:"
Write-Host "  ceromailer`n" -ForegroundColor Yellow
Write-Host "If 'ceromailer' is not recognized immediately, open a new terminal window or run:"
Write-Host "  cd `"$installDir`" ; .\ceromailer`n" -ForegroundColor Gray
