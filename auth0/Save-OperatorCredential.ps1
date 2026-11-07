# Windows-only bootstrap. No network requests, plan or apply.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9_-]+$')]
    [string]$ClientId
)

$ErrorActionPreference = 'Stop'
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw 'This helper requires Windows DPAPI. Do not use Export-Clixml for credentials on other platforms.'
}

$taskSecret = Read-Host 'Pegá el Client Secret de snippet-searcher-terraform (entrada oculta)' -AsSecureString
if ($taskSecret.Length -eq 0) {
    $taskSecret.Dispose()
    throw 'No se guardó nada: el secreto está vacío.'
}

try {
    $taskFolder = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../.sni71'))
    [IO.Directory]::CreateDirectory($taskFolder) | Out-Null
    $taskPath = Join-Path $taskFolder 'auth0-operator.credential.xml'
    $taskCredential = New-Object System.Management.Automation.PSCredential($ClientId, $taskSecret)
    # On Windows Export-Clixml protects the SecureString with current-user DPAPI.
    # Client ID is public; the secret is encrypted and tied to this user/machine.
    $taskCredential | Export-Clixml -LiteralPath $taskPath -Force
    Write-Output 'Credencial guardada cifrada para este usuario de Windows. No se consultó ni modificó Auth0.'
} finally {
    $taskSecret.Dispose()
}
