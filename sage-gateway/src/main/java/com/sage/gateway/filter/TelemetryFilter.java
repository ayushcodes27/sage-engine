package com.sage.gateway.filter;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sage.gateway.event.RequestEvent;
import com.sage.gateway.service.KafkaProducerService;
import com.sage.gateway.service.RedisTelemetryService;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.time.Instant;
import java.util.HashMap;
import java.util.Map;
import java.util.UUID;

@Component
@Order(Ordered.HIGHEST_PRECEDENCE)
public class TelemetryFilter extends OncePerRequestFilter {

    private final RedisTelemetryService redisTelemetryService;
    private final KafkaProducerService kafkaProducer;
    private final ObjectMapper objectMapper;
    private final HttpClient httpClient;

    private static final String PYTHON_ML_URL = "http://localhost:8000/predict";

    public TelemetryFilter(RedisTelemetryService redisTelemetryService, KafkaProducerService kafkaProducer, ObjectMapper objectMapper) {
        this.redisTelemetryService = redisTelemetryService;
        this.kafkaProducer = kafkaProducer;
        this.objectMapper = objectMapper;
        this.httpClient = HttpClient.newBuilder()
                .version(HttpClient.Version.HTTP_1_1)
                .connectTimeout(Duration.ofMillis(500)) // Aggressive timeout to protect the SLA
                .build();
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain filterChain)
            throws ServletException, IOException {

        long startTime = System.currentTimeMillis();
        String eventId = UUID.randomUUID().toString();
        String ipAddress = request.getRemoteAddr() != null ? request.getRemoteAddr() : "anonymous";

        if (redisTelemetryService.isIpBanned(ipAddress)) {
            logger.warn("🚨 FAST-PATH BLOCK: IP " + ipAddress + " is on the 5-minute ban list.");
            response.setStatus(HttpServletResponse.SC_FORBIDDEN);
            response.setContentType("application/json");
            response.getWriter().write("{\"error\": \"Forbidden\", \"message\": \"Traffic blocked by SAGE Engine Fast-Path\"}");
            return; // HALT IMMEDIATELY!
        }

        // 1. Extract payload size (Defaults to 0 for GET requests without bodies)
        double payloadSize = request.getContentLength() > 0 ? request.getContentLength() : 0.0;

        boolean isBot = false;
        double botProbability = 0.0;

        try {
            // 2. Update Redis Sliding Window & Get Features
            Map<String, Double> features = redisTelemetryService.processAndGetTelemetry(ipAddress, payloadSize);

            // 3. Prepare payload for Python
            Map<String, Object> mlPayload = new HashMap<>(features);
            mlPayload.put("session_id", eventId); // FastAPI schema requires this


            String jsonBody = objectMapper.writeValueAsString(mlPayload);

            // 4. Call Python ML Service
            HttpRequest mlRequest = HttpRequest.newBuilder()
                    .uri(URI.create(PYTHON_ML_URL))
                    .header("Content-Type", "application/json")
                    .timeout(Duration.ofMillis(2000))
                    .POST(HttpRequest.BodyPublishers.ofString(jsonBody))
                    .build();

            HttpResponse<String> mlResponse = httpClient.send(mlRequest, HttpResponse.BodyHandlers.ofString());

            // 5. Parse Decision
            if (mlResponse.statusCode() == 200) {
                JsonNode responseNode = objectMapper.readTree(mlResponse.body());
                isBot = responseNode.get("is_bot").asBoolean();
                botProbability = responseNode.get("bot_probability").asDouble();
            } else {
                logger.warn("ML Service returned non-200 status. Failing open.");
            }

        } catch (Exception e) {
            // FAIL-OPEN DESIGN: If Redis or Python crashes, we log the error but DO NOT block the traffic
            logger.error("SAGE ML Pipeline failed. Bypassing anomaly detection for this request.", e);
        }

        // 6. ENFORCE THE DECISION
        if (isBot) {
            logger.warn("🚨 SAGE ENGINE BLOCKED BOT! IP: " + ipAddress + " | Prob: " + botProbability);
            redisTelemetryService.banIp(ipAddress);
            response.setStatus(HttpServletResponse.SC_FORBIDDEN);
            response.setContentType("application/json");
            response.getWriter().write("{\"error\": \"Forbidden\", \"message\": \"Traffic blocked by SAGE Engine Anomaly Detection\"}");
            return; // HALT EXECUTION: Do not pass down the filter chain
        }

        // Standard Processing for Legitimate Traffic
        try {
            filterChain.doFilter(request, response);
        } finally {
            // Post-Processing & Kafka Logging
            long latencyMs = System.currentTimeMillis() - startTime;
            int statusCode = response.getStatus();
            String path = request.getRequestURI();
            String method = request.getMethod();

            RequestEvent.RequestDetails requestDetails = new RequestEvent.RequestDetails(method, path, "api", ipAddress);
            RequestEvent.ResponseDetails responseDetails = new RequestEvent.ResponseDetails(statusCode, latencyMs);

            // Note: We've replaced your old timeSinceLastMs calculation.
            // We can now pass the botProbability straight into the MLMetadata for your dashboards!
            RequestEvent.MLMetadata mlMetadata = new RequestEvent.MLMetadata(botProbability, isBot ? 1 : 0);

            RequestEvent event = new RequestEvent(
                    eventId,
                    Instant.now().toEpochMilli(),
                    "tenant_placeholder",
                    ipAddress,
                    ipAddress + "_session",
                    requestDetails,
                    responseDetails,
                    mlMetadata
            );

            kafkaProducer.publishEvent(event);

        }
    }
}