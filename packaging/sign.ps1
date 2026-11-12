param(
    [ValidateSet("App", "Installer", "All")]
    [string]$Target = "All",
    [string]$TimestampServer = "http://timestamp.digicert.com"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$subject = "CN=FRAME AI, O=FRAME AI, C=CN"

$cert = Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert |
    Where-Object { $_.Subject -eq $subject } |
    Sort-Object NotAfter -Descending |
    Select-Object -First 1
if (-not $cert) {
    throw "Code-signing certificate not found in Cert:\CurrentUser\My (subject: $subject)"
}

$files = @()
if ($Target -in @("App", "All")) {
    $files += Join-Path $root "dist\FRAME AI\FRAME AI.exe"
}
if ($Target -in @("Installer", "All")) {
    $files += Join-Path $root "dist-installer\FRAME-AI-setup.exe"
}

foreach ($file in $files) {
    if (-not (Test-Path $file)) {
        throw "File not found: $file"
    }
    Write-Host "Signing $file"
    $result = Set-AuthenticodeSignature -FilePath $file -Certificate $cert `
        -HashAlgorithm SHA256 -TimestampServer $TimestampServer
    if ($result.Status -ne "Valid") {
        throw "Signing failed for $file : $($result.Status) $($result.StatusMessage)"
    }
    $verify = Get-AuthenticodeSignature -FilePath $file
    Write-Host ("  status={0} signer={1} timestamped={2}" -f `
        $verify.Status, $verify.SignerCertificate.Subject, [bool]$verify.TimeStamperCertificate)
}
