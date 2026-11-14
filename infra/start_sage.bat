@echo off
setlocal

for %%I in ("%~dp0..") do set "ROOT=%%~fI\"
set "BRIDGE_PORT=6006"
set "KAFKA_GROUP_ID=sage-dashboard-live-v1"

echo ===================================================
echo Initiating SAGE Engine Microservice Architecture...
echo ===================================================

docker info >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo Docker daemon is not running. Start Docker Desktop first, then run this script again.
    pause
    exit /b 1
)

echo [1/3] Starting the SAGE stack with Docker Compose (Redis, Kafka, ML service, gateway, mock shop, monitoring)...
cd /d "%ROOT%"
docker compose -f "%ROOT%infra\docker-compose.yml" up -d
if %ERRORLEVEL% NEQ 0 (
    echo Failed to start Docker Compose services.
    pause
    exit /b 1
)

echo [Prep] Checking dashboard bridge dependencies...
if not exist "%ROOT%sage-dashboard\node_modules" (
    call npm --prefix "%ROOT%sage-dashboard" install
    if %ERRORLEVEL% NEQ 0 (
        echo Failed to install dependencies in sage-dashboard.
        pause
        exit /b 1
    )
)

echo [Prep] Checking dashboard UI dependencies...
if not exist "%ROOT%sage-dashboard\sage-ui\node_modules" (
    call npm --prefix "%ROOT%sage-dashboard\sage-ui" install
    if %ERRORLEVEL% NEQ 0 (
        echo Failed to install dependencies in sage-dashboard\sage-ui.
        pause
        exit /b 1
    )
)

echo [Prep] Releasing bridge port %BRIDGE_PORT% if occupied...
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%BRIDGE_PORT% .*LISTENING"') do (
    echo Found process %%P on port %BRIDGE_PORT%. Stopping it...
    taskkill /PID %%P /F >nul 2>&1
)

echo [2/3] Starting Node.js Kafka Bridge...
start "SAGE - WebSocket Bridge" cmd /k "cd /d ""%ROOT%sage-dashboard"" && set BRIDGE_PORT=%BRIDGE_PORT% && set KAFKA_GROUP_ID=%KAFKA_GROUP_ID% && set GATEWAY_HEALTH_URL=http://localhost:8083/echo && set ML_HEALTH_URL=http://localhost:8000/docs && node bridge.js"

echo [3/3] Starting React UI Dashboard...
start "SAGE - React UI" cmd /k "cd /d ""%ROOT%sage-dashboard\sage-ui"" && npm run dev"

echo.
echo All SAGE services have been launched.
echo Gateway:   http://localhost:8083/echo
echo ML:        http://localhost:8000/health
echo Bridge:    http://localhost:6006/api/status
echo Dashboard running at: http://localhost:5173
echo ===================================================
pause
