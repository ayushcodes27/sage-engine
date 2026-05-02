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
2.  **`ml_pipeline` (Python/Flask)**: An inference service that exposes a REST API for the gateway. It receives request data, processes it through a feature engineering pipeline, and uses a pre-trained Random Forest model to generate a real-time risk score.
3.  **`sage-dashboard` (React)**: A single-page application that provides a live dashboard for monitoring traffic, viewing security events, and configuring the gateway. It communicates with the gateway via a WebSocket bridge.
4.  **`mock-target-site` (Node.js/Express)**: A simple web application that serves as a backend for the gateway, allowing for safe testing and demonstration of SAGE's capabilities.
5.  **Monitoring Stack (Prometheus & Grafana)**: A pre-configured monitoring stack scrapes metrics from the gateway and other services to provide insights into system health and performance.

## Tech Stack

-   **Backend**: Java, Spring Boot, Spring Cloud Gateway
-   **Machine Learning**: Python, Scikit-learn, Flask, Pandas
-   **Frontend**: JavaScript, React, Vite, Tailwind CSS
-   **Infrastructure**: Docker, Docker Compose
-   **Monitoring**: Prometheus, Grafana
-   **Load Testing**: k6, Locust

## How It Works

1.  A user sends a request to a web application fronted by SAGE.
2.  The `sage-gateway` intercepts the request and asynchronously sends request metadata (headers, IP, etc.) to the `ml_pipeline` for scoring.
3.  The `ml_pipeline` extracts behavioral features (e.g., request velocity, session depth, temporal variance) and feeds them into the Random Forest model.
4.  The model returns a risk score to the gateway.
5.  If the score exceeds a configured threshold, the gateway blocks the request with a `403 Forbidden` status. Otherwise, the request is proxied to the upstream application.
6.  All request data and security events are published to a stream for real-time visualization in the `sage-dashboard`.

## Key Engineering Highlights

-   **Asynchronous, Non-Blocking I/O**: The gateway is built on Spring WebFlux and Project Reactor, allowing it to handle a high volume of concurrent connections with minimal resource overhead.
-   **Decoupled ML Inference**: The ML inference service is decoupled from the gateway, allowing it to be scaled independently and updated without service interruption. This design also allows for the use of different ML frameworks or models in the future.
-   **Scalable Infrastructure**: The entire system is containerized and orchestrated with Docker Compose, enabling horizontal scaling of individual components to meet demand.
-   **Comprehensive Load Testing**: The project includes a suite of load tests (stress, soak, spike) written with k6 and Locust to validate the system's performance and reliability under pressure.

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
-   **SAGE Dashboard**: `http://localhost:3000`
-   **Grafana Dashboard**: `http://localhost:3001`

## Future Improvements

-   **Automated Model Retraining**: Implement a CI/CD pipeline to automatically retrain and deploy the ML model based on new traffic data collected from the gateway.
-   **Dynamic Rule Engine**: Introduce a dynamic rule engine that allows administrators to create and manage custom security rules from the dashboard without requiring a code change.
-   **Support for Additional Protocols**: Extend the gateway to support protocols beyond HTTP/S, such as WebSockets, for broader application protection.
