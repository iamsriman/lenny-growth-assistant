<#
  Setup helper for Windows machines with a small C: drive.

  It puts Ollama's model files on a drive you choose (default D:), pulls the
  two models this project needs, and checks that Docker and the ports are free.

  Run in PowerShell:
      powershell -ExecutionPolicy Bypass -File scripts\setup-windows.ps1
      powershell -ExecutionPolicy Bypass -File scripts\setup-windows.ps1 -ModelDrive Q
#>

param(
  [string]$ModelDrive = "D",
  [string]$ChatModel  = "llama3.2:3b",
  [string]$EmbedModel = "nomic-embed-text"
)

$ErrorActionPreference = "Stop"

function Say($msg, $colour = "White") { Write-Host $msg -ForegroundColor $colour }

Say "`n== Lenny Growth Assistant — Windows setup ==`n" Cyan

# 1. Model storage off the system drive -------------------------------------
$modelPath = "${ModelDrive}:\ollama\models"
if (-not (Test-Path "${ModelDrive}:\")) {
  Say "Drive ${ModelDrive}: not found. Re-run with -ModelDrive <letter>." Red
  exit 1
}
New-Item -ItemType Directory -Force -Path $modelPath | Out-Null
[Environment]::SetEnvironmentVariable("OLLAMA_MODELS", $modelPath, "User")
$env:OLLAMA_MODELS = $modelPath
Say "OLLAMA_MODELS -> $modelPath" Green

$free = [math]::Round((Get-PSDrive -Name $ModelDrive).Free / 1GB, 1)
Say "Free space on ${ModelDrive}: ${free} GB (need about 3 GB for both models)"

# 2. Ollama ------------------------------------------------------------------
if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
  Say "`nOllama is not installed. Get it from https://ollama.com/download" Yellow
  Say "Install it, then run this script again." Yellow
  exit 1
}

Say "`nRestarting Ollama so it picks up the new model path..."
Get-Process ollama -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 2
Start-Process -WindowStyle Hidden ollama -ArgumentList "serve"
Start-Sleep -Seconds 4

Say "Pulling $ChatModel ..." Cyan
ollama pull $ChatModel
Say "Pulling $EmbedModel ..." Cyan
ollama pull $EmbedModel

try {
  $tags = Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -TimeoutSec 5
  Say "Ollama is up. Models present: $(($tags.models | ForEach-Object { $_.name }) -join ', ')" Green
} catch {
  Say "Ollama did not answer on port 11434. Start it with: ollama serve" Red
}

# 3. .env --------------------------------------------------------------------
if (-not (Test-Path ".env")) {
  Copy-Item ".env.example" ".env"
  Say "`nCreated .env from .env.example — open it and set DATABASE_URL." Green
} else {
  Say "`n.env already exists; leaving it alone." Yellow
}

# 4. Docker and ports --------------------------------------------------------
if (Get-Command docker -ErrorAction SilentlyContinue) {
  try {
    docker info *> $null
    Say "Docker is running." Green
  } catch {
    Say "Docker is installed but not running. Start Docker Desktop." Yellow
  }
} else {
  Say "Docker not found. You can still run the app natively — see README." Yellow
}

foreach ($port in 8000, 5173, 5432) {
  $busy = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
  if ($busy) { Say "Port $port is already in use — change it in .env." Yellow }
}

Say "`nDone. Next:" Cyan
Say "  docker compose up --build"
Say "  then open http://localhost:5173`n"
