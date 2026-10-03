# Install script for Fusion 360 URDF Exporter Add-In
$ErrorActionPreference = "Stop"

$sourceDir = $PSScriptRoot
$targetDir = "$env:APPDATA\Autodesk\Autodesk Fusion 360\API\AddIns\Fusion360URDFExporter"

Write-Host "Installing Fusion 360 URDF Exporter..."
Write-Host "Source: $sourceDir"
Write-Host "Target: $targetDir"

if (-not (Test-Path "$env:APPDATA\Autodesk\Autodesk Fusion 360\API\AddIns")) {
    New-Item -ItemType Directory -Force -Path "$env:APPDATA\Autodesk\Autodesk Fusion 360\API\AddIns" | Out-Null
}

# Create or update directory junction or copy
if (Test-Path $targetDir) {
    Write-Host "Target folder already exists. Updating files..."
} else {
    New-Item -ItemType Directory -Force -Path $targetDir | Out-Null
}

Copy-Item -Path "$sourceDir\*" -Destination $targetDir -Recurse -Force -Exclude "tests",".git"

Write-Host "Installation successful! The add-in is now available in Autodesk Fusion 360 under 'Utilities > Scripts and Add-Ins > Add-Ins'."
