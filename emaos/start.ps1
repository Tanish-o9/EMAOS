# ============================================================
#  EMAOS - Enterprise Multi-Agent AI Operating System
#  Startup Script for Windows PowerShell
# ============================================================

Write-Host ""
Write-Host "  =================================================" -ForegroundColor Cyan
Write-Host "  EMAOS - Enterprise Multi-Agent AI Operating System" -ForegroundColor White
Write-Host "  v1.0.0 | Built with LangGraph + Groq" -ForegroundColor Gray
Write-Host "  =================================================" -ForegroundColor Cyan
Write-Host ""

# Check prerequisites
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "  [X] Docker not found. Please install Docker Desktop." -ForegroundColor Red
    exit 1
}

if (-not (Test-Path ".env")) {
    Write-Host "  [!] .env not found - copying from .env.example" -ForegroundColor Yellow
    Copy-Item ".env.example" ".env"
    Write-Host "  ! Please edit .env and add your GROQ_API_KEY before continuing." -ForegroundColor Yellow
    Write-Host "  Press Enter to continue after editing .env..." -ForegroundColor Gray
    Read-Host
}

# Load env variables from .env
Write-Host "  -> Loading environment..." -ForegroundColor Blue
Get-Content ".env" | ForEach-Object {
    if ($_ -match "^([^#=]+)=(.+)$") {
        $name = $matches[1].Trim()
        $value = $matches[2].Trim()
        [System.Environment]::SetEnvironmentVariable($name, $value, "Process")
    }
}

if (-not $env:GROQ_API_KEY -or $env:GROQ_API_KEY -eq "your_groq_api_key_here") {
    Write-Host "  [X] GROQ_API_KEY is not set. Please update it in .env." -ForegroundColor Red
    exit 1
}

# Start containers
Write-Host "  -> Starting Docker containers (postgres, redis, backend, prometheus)..." -ForegroundColor Blue
docker-compose up -d --build

if ($LASTEXITCODE -ne 0) {
    Write-Host "  [X] Failed to spin up Docker containers." -ForegroundColor Red
    exit 1
}

# Wait for backend
Write-Host "  -> Waiting for API backend to become ready..." -ForegroundColor Blue
$ready = $false
for ($i = 0; $i -lt 30; $i++) {
    try {
        $resp = Invoke-WebRequest -Uri "http://localhost:8000/health" -UseBasicParsing -TimeoutSec 2
        if ($resp.StatusCode -eq 200) {
            $ready = $true
            break
        }
    } catch {
        # ignore
    }
    Start-Sleep -Seconds 2
}

if ($ready) {
    Write-Host "  [OK] Backend is healthy and ready!" -ForegroundColor Green
    Write-Host "  -> Launching Mission Control Dashboard..." -ForegroundColor Blue
    
    $dashboardPath = (Get-Item "frontend/dashboard/index.html").FullName
    Start-Process $dashboardPath
    
    Write-Host ""
    Write-Host "  =================================================" -ForegroundColor Green
    Write-Host "  EMAOS IS NOW RUNNING!" -ForegroundColor Green
    Write-Host "  - Backend API:       http://localhost:8000" -ForegroundColor Gray
    Write-Host "  - Prometheus:        http://localhost:9090" -ForegroundColor Gray
    Write-Host "  - Dashboard UI:      $dashboardPath" -ForegroundColor Gray
    Write-Host "  =================================================" -ForegroundColor Green
} else {
    Write-Host "  [X] Backend failed to start. Check Docker logs." -ForegroundColor Red
}
