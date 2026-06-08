# SAGE Engine - Demonstration Quick Start

This document provides a quick reference for demonstrating the Sequence-Aware Gateway Engine (SAGE).

## 🚀 Quick Start Commands

To launch the complete microservice architecture (Docker Compose, API Gateway, ML Inference Engine, React Dashboard, and Node.js Bridge), run the following script from the root directory:

```bat
cd infra
start_sage.bat
```
*(Ensure Docker Desktop is running before executing this command).*

## 🔗 Service Links

Once the architecture is fully running, you can access the services using the links below:

| Service | URL | Description |
|---|---|---|
| **React UI Dashboard** | [http://localhost:5173](http://localhost:5173) | Primary real-time threat monitoring UI |
| **SAGE Gateway (Protected)** | [http://localhost:8081](http://localhost:8081) | SAGE Proxy entrypoint for client traffic |
| **SAGE Gateway Health** | [http://localhost:8081/echo](http://localhost:8081/echo) | Reachability ping endpoint |
| **Mock Target Site (Direct)**| [http://localhost:3030](http://localhost:3030) | Unprotected e-commerce shell backend |
| **ML Inference Docs** | [http://localhost:8000/docs](http://localhost:8000/docs) | Python FastAPI interactive documentation |
| **Node.js Bridge Status** | [http://localhost:6006/api/status](http://localhost:6006/api/status) | WebSocket streaming service health |
| **Grafana** | [http://localhost:5050](http://localhost:5050) | Observability metrics (admin/admin) |
| **Prometheus** | [http://localhost:9091](http://localhost:9091) | Raw metrics collection endpoint |
| **Kafka UI** | [http://localhost:8090](http://localhost:8090) | Kafka topics and stream visualization |
| **RedisInsight** | [http://localhost:5540](http://localhost:5540) | Redis state management UI |

## ⚔️ Load Testing Commands (The 4 Attack Profiles)

To simulate traffic and trigger SAGE's detection mechanisms, ensure your Python virtual environment is active and Locust is installed (`pip install locust`). 

Run these four commands **one by one** from the project root. Observe the React Dashboard after initiating each run:

### 1. Human Browsing Baseline (Normal Traffic)
Simulates benign human behavior, building session depth and distributing traffic organically.
```bash
locust -f load-tests/locustfile.py --tags human --headless -u 12 -r 5 --run-time 5m --host http://localhost:8081
```

### 2. Akamai-Style Scraper (Fast-Path Throttle)
Simulates a headless crawler sweeping products without loading static assets or cart endpoints.
```bash
locust -f load-tests/locustfile.py --tags akamai_scraper --headless -u 14 -r 5 --run-time 5m --host http://localhost:8081
```

### 3. Cloudflare-Style Distributed Flood (Fast-Path Block)
Simulates volumetric distributed attacks by rapidly changing the `X-Forwarded-For` header.
```bash
locust -f load-tests/locustfile.py --tags cloudflare_flood --headless -u 8 -r 5 --run-time 5m --host http://localhost:8081
```

### 4. Low-And-Slow Recon Bot (ML Engine Block)
Simulates insidious behavior such as path traversals, SQL injections, and Prometheus actuator probes hiding in standard intervals.
```bash
locust -f load-tests/locustfile.py --tags recon --headless -u 6 -r 5 --run-time 5m --host http://localhost:8081
```
