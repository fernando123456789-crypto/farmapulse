$ErrorActionPreference = 'Stop'
$projectDirectory = Split-Path -Parent $PSScriptRoot
$tlsDirectory = Join-Path $projectDirectory 'instance\tls'
$certificatePath = Join-Path $tlsDirectory 'localhost.pem'
$privateKeyPath = Join-Path $tlsDirectory 'localhost-key.pem'
$opensslCommand = Get-Command openssl -ErrorAction SilentlyContinue
$opensslPath = if ($opensslCommand) { $opensslCommand.Source } else { Join-Path $env:ProgramFiles 'Git\usr\bin\openssl.exe' }
if (-not (Test-Path -LiteralPath $opensslPath)) { throw 'Instala OpenSSL o Git para Windows antes de configurar HTTPS local.' }
New-Item -ItemType Directory -Path $tlsDirectory -Force | Out-Null
$opensslArguments = @(
    'req', '-x509', '-newkey', 'rsa:2048', '-sha256', '-nodes', '-days', '30',
    '-subj', '"/CN=FarmaPulse localhost"',
    '-addext', 'subjectAltName=DNS:localhost,IP:127.0.0.1,IP:::1',
    '-addext', 'basicConstraints=critical,CA:FALSE',
    '-addext', 'keyUsage=critical,digitalSignature,keyEncipherment',
    '-addext', 'extendedKeyUsage=serverAuth',
    '-keyout', ('"' + $privateKeyPath + '"'), '-out', ('"' + $certificatePath + '"')
)
$opensslLog = Join-Path $tlsDirectory 'openssl.log'
$opensslProcess = Start-Process -FilePath $opensslPath -ArgumentList $opensslArguments -WindowStyle Hidden -RedirectStandardError $opensslLog -Wait -PassThru
if ($opensslProcess.ExitCode -ne 0) { throw "No se pudo generar el certificado de desarrollo. Revisa $opensslLog" }
$currentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
& icacls.exe $privateKeyPath /inheritance:r /grant:r "${currentIdentity}:(F)" | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'No se pudieron limitar los permisos de la clave privada.' }
Import-Certificate -FilePath $certificatePath -CertStoreLocation 'Cert:\CurrentUser\Root' | Out-Null
Push-Location $projectDirectory
try {
    @'
from dotenv import set_key
set_key('.env', 'LOCAL_HTTPS_CERT', 'instance/tls/localhost.pem')
set_key('.env', 'LOCAL_HTTPS_KEY', 'instance/tls/localhost-key.pem')
set_key('.env', 'LOCAL_HTTPS_PORT', '5443')
'@ | python -
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo actualizar la configuración privada.' }
} finally { Pop-Location }
Write-Output 'HTTPS local configurado en https://127.0.0.1:5443/comparador. Reinicia python app.py.'
