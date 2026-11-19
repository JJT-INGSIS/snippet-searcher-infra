param(
    [string]$IdentityFile = (Join-Path $env:USERPROFILE '.ssh\snippet_searcher_cd_dev')
)

$ErrorActionPreference = 'Stop'
$knownHosts = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..\..\docs\ssh_known_hosts')).Path
$identity = (Resolve-Path -LiteralPath $IdentityFile).Path
$username = Read-Host 'Correo de la cuenta Auth0 dedicada de SNI-85'
$securePassword = Read-Host 'Contraseña Auth0 de esa cuenta' -AsSecureString
$pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
$payload = $null
$connection = $null
try {
    $payload = [Text.Encoding]::UTF8.GetBytes((@{
        username = $username
        password = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    } | ConvertTo-Json -Compress))
    $ssh = New-Object Diagnostics.ProcessStartInfo
    $ssh.FileName = (Get-Command ssh.exe -ErrorAction Stop).Source
    $ssh.Arguments = '-i "{0}" -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=yes -o "UserKnownHostsFile={1}" -o HostKeyAlgorithms=ssh-ed25519 azureuser@57.156.69.174 "sudo -n python3 -B /opt/snippet-observability/dev/functional/run.py --provision-credentials"' -f $identity, $knownHosts
    $ssh.UseShellExecute = $false
    $ssh.RedirectStandardInput = $true
    $connection = [Diagnostics.Process]::Start($ssh)
    $connection.StandardInput.BaseStream.Write($payload, 0, $payload.Length)
    $connection.StandardInput.Close()
    $connection.WaitForExit()
    if ($connection.ExitCode -ne 0) { throw 'La VM no confirmó la configuración de la cuenta.' }
    Write-Host 'Credencial dedicada guardada en DEV.'
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    $securePassword.Dispose()
    if ($null -ne $payload) { [Array]::Clear($payload, 0, $payload.Length) }
    if ($null -ne $connection) { $connection.Dispose() }
}
