# Install script for FusionLaserJoints Add-In
$ErrorActionPreference = "Stop"

$sourceDir = $PSScriptRoot
$targetDir = "$env:APPDATA\Autodesk\Autodesk Fusion 360\API\AddIns\FusionLaserJoints"

Write-Host "=========================================================="
Write-Host " Installing FusionLaserJoints Add-In for Autodesk Fusion  "
Write-Host "=========================================================="
Write-Host "Source directory : $sourceDir"
Write-Host "Target directory : $targetDir"
Write-Host ""

$addinBaseDir = "$env:APPDATA\Autodesk\Autodesk Fusion 360\API\AddIns"
if (-not (Test-Path $addinBaseDir)) {
    Write-Host "Creating Fusion 360 AddIns base directory..."
    New-Item -ItemType Directory -Force -Path $addinBaseDir | Out-Null
}

if (Test-Path $targetDir) {
    Write-Host "Existing installation found. Updating files..."
} else {
    Write-Host "Creating target add-in directory..."
    New-Item -ItemType Directory -Force -Path $targetDir | Out-Null
}

# Copy files excluding git and pycache
Copy-Item -Path "$sourceDir\*" -Destination $targetDir -Recurse -Force -Exclude ".git","__pycache__"

Write-Host ""
Write-Host "Installation completed successfully!" -ForegroundColor Green
Write-Host ""
Write-Host "How to use in Autodesk Fusion:"
Write-Host "1. Open Autodesk Fusion."
Write-Host "2. Go to 'UTILITIES' tab > 'ADD-INS' > 'Scripts and Add-Ins' (or press Shift+S)."
Write-Host "3. Click on the 'Add-Ins' tab."
Write-Host "4. Select 'FusionLaserJoints' and click 'Run' (check 'Run on Startup' to launch automatically)."
Write-Host "5. The 'Laser Cut Joints' icon will appear on your SOLID > MODIFY and UTILITIES ribbons."
Write-Host "=========================================================="
