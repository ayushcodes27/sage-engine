@echo off
echo ===================================================
echo Initiating SAGE Engine Microservice Architecture...
echo ===================================================

echo [0/4] Starting infrastructure services with Docker Compose...
docker compose up -d
if %ERRORLEVEL% NEQ 0 (
    echo Failed to start Docker Compose services.
    pause
    exit /b 1
)

echo [1/4] Starting Python ML Inference Service...
start "SAGE - Python ML Brain" cmd /k "cd /d ml_pipeline\inference_service && py -m uvicorn main:app --reload --port 8000"

echo [2/4] Starting Java Spring Boot Gateway...
start "SAGE - Java API Gateway" cmd /k "cd /d sage-gateway && mvnw.cmd spring-boot:run"

echo [3/4] Starting Node.js Kafka Bridge...
start "SAGE - WebSocket Bridge" cmd /k "cd /d sage-dashboard && node bridge.js"

echo [4/4] Starting React UI Dashboard...
start "SAGE - React UI" cmd /k "cd /d sage-dashboard\sage-ui && npm run dev"

echo.
echo All SAGE services have been launched.
echo Dashboard running at: http://localhost:5173
echo ===================================================
pause
