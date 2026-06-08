# SAGE: Real-Time Bot Detection and Mitigation Engine

SAGE is a real-time, ML-driven security engine designed to detect and mitigate sophisticated bot attacks against web applications.

## Overview

Malicious bots are a growing threat responsible for credential stuffing, content scraping, inventory scalping, and application-layer DDoS attacks. Traditional security measures often fail to detect sophisticated bots that mimic human behavior. SAGE provides a self-hosted, scalable solution that analyzes user behavior in real-time, using a machine learning pipeline to distinguish between human and bot activity and blocking threats before they impact your services.

## Key Features

-   **Real-Time Threat Mitigation**: Intercepts and analyzes every incoming request to block malicious traffic in real-time.
-   **ML-Powered Behavioral Analysis**: Utilizes a machine learning model to score traffic based on behavioral patterns, not just static signatures.
-   **High-Performance Reverse Proxy**: Built on a scalable, non-blocking architecture to handle high-throughput traffic with minimal latency.
-   **Live Monitoring Dashboard**: A dedicated interface to visualize traffic, monitor security events, and observe system performance.
-   **Extensible Feature Engineering**: The ML pipeline is designed with a modular feature extraction process, allowing for easy addition of new behavioral indicators.

## Architecture

SAGE operates as a multi-component, orchestrated system designed for high availability and performance.

1.  **`sage-gateway` (Spring Boot)**: The entry point for all traffic. This high-performance reverse proxy intercepts requests, extracts key metadata, and forwards it to the ML inference service for analysis. Based on the returned score, it either blocks the request or forwards it to the target application.
2.  **`ml_pipeline` (Python/FastAPI)**: A high-performance inference service exposing a REST API. It receives telemetry from the gateway and uses a pre-trained 4-class Random Forest model to classify traffic (Human, Flood, Scraper, Recon) and return a real-time confidence score.
3.  **`sage-dashboard` (React)**: A single-page application that provides a live dashboard for monitoring traffic, viewing security events, and configuring the gateway. It communicates with the gateway via a WebSocket bridge.
4.  **`mock-target-site` (Node.js/Express)**: A simple web application that serves as a backend for the gateway, allowing for safe testing and demonstration of SAGE's capabilities.
5.  **Monitoring Stack (Prometheus & Grafana)**: A pre-configured monitoring stack scrapes metrics from the gateway and other services to provide insights into system health and performance.

## Tech Stack

-   **Backend**: Java, Spring Boot, Spring Cloud Gateway
-   **Machine Learning**: Python, Scikit-learn, FastAPI, Pandas
-   **Frontend**: JavaScript, React, Vite, Tailwind CSS
-   **Infrastructure**: Docker, Docker Compose, Kafka, Redis
-   **Monitoring**: Prometheus, Grafana
-   **Load Testing**: Locust

## How It Works

1.  A user sends a request to a web application fronted by SAGE.
2.  The `sage-gateway` intercepts the request and asynchronously sends request metadata (headers, IP, etc.) to the `ml_pipeline` for scoring.
3.  The `ml_pipeline` evaluates 8 behavioral features (e.g., request velocity, endpoint concentration, asset skip ratio) against a 4-class Random Forest model.
4.  The model returns a specific threat classification (`human`, `flood`, `scraper`, `recon`) and a confidence score.
5.  If the classification is malicious and meets the strict confidence threshold (e.g., > 0.75), the gateway blocks the request with a `403 Forbidden`. Otherwise, the request is proxied to the upstream application.
6.  All request data and security events are published to a stream for real-time visualization in the `sage-dashboard`.

## Key Engineering Highlights

-   **Asynchronous, Non-Blocking I/O**: The gateway is built on Spring WebFlux and Project Reactor, allowing it to handle a high volume of concurrent connections with minimal resource overhead.
-   **Decoupled ML Inference**: The ML inference service is decoupled from the gateway, allowing it to be scaled independently and updated without service interruption. This design also allows for the use of different ML frameworks or models in the future.
-   **Adversarial Training Data**: Replaced static datasets (like CIC-IDS2018) with a dynamic, synthesized data pipeline. Locust generates adversarial bot profiles (stealth scrapers, bursty floods) which are streamed via Kafka to train robust, production-ready models.
-   **Scalable Infrastructure**: The entire system is containerized and orchestrated with Docker Compose, enabling horizontal scaling of individual components to meet demand.

## Setup and Run

The entire SAGE platform can be run locally using Docker Compose.

1.  Navigate to the `infra` directory:
    ```bash
    cd infra
    ```
2.  Start all services in detached mode:
    ```bash
    docker-compose up -d
    ```

-   **SAGE Gateway**: `http://localhost:8081`
-   **SAGE Dashboard**: `http://localhost:5173`
-   **Grafana Dashboard**: `http://localhost:5050`

## Future Improvements

-   **Automated Model Retraining**: Implement a CI/CD pipeline to automatically retrain and deploy the ML model based on new traffic data collected from the gateway.
-   **Dynamic Rule Engine**: Introduce a dynamic rule engine that allows administrators to create and manage custom security rules from the dashboard without requiring a code change.
-   **Support for Additional Protocols**: Extend the gateway to support protocols beyond HTTP/S, such as WebSockets, for broader application protection.
