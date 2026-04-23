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
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
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
import java.util.Set;
import java.util.UUID;

@Component
@Order(Ordered.HIGHEST_PRECEDENCE)
public class TelemetryFilter extends OncePerRequestFilter {

    private final RedisTelemetryService redisTelemetryService;
    private final KafkaProducerService kafkaProducer;
    private final ObjectMapper objectMapper;
    private final HttpClient httpClient;

    private static final String PYTHON_ML_URL = "http://localhost:8000/predict";
    private static final Logger logger = LoggerFactory.getLogger(TelemetryFilter.class);
    private static final double SESSION_DEPTH_THRESHOLD = 6.0;
    private static final double BLOCK_PROBABILITY_THRESHOLD = 0.85;
    private static final long ECHO_FLOOD_RPS_THRESHOLD = 30;
    private static final int FLOOD_GRACE_REQUEST_COUNT = 6;
    private static final int SCRAPER_429_ESCALATION_THRESHOLD = 3;
    private static final int RECON_BAN_THRESHOLD = 15;
    private static final Set<String> RECON_SENSITIVE_PREFIXES = Set.of(
            "/admin",
            "/routes",
            "/config",
            "/actuator",
            "/internal",
            "/debug"
    );

    public TelemetryFilter(RedisTelemetryService redisTelemetryService, KafkaProducerService kafkaProducer, ObjectMapper objectMapper) {
        this.redisTelemetryService = redisTelemetryService;
        this.kafkaProducer = kafkaProducer;
        this.objectMapper = objectMapper;
        this.httpClient = HttpClient.newBuilder()
                .version(HttpClient.Version.HTTP_1_1)
                .connectTimeout(Duration.ofMillis(500))
                .build();
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain filterChain)
            throws ServletException, IOException {

        long startTime = System.currentTimeMillis();
        String eventId = UUID.randomUUID().toString();
        String ipAddress = resolveClientIp(request);
        String label = classifyByIP(ipAddress);
        String path = request.getRequestURI();
        String method = request.getMethod();
        long eventTimestamp = Instant.now().toEpochMilli();

        // 1. FAST-PATH BLOCK
        if (redisTelemetryService.isIpBanned(ipAddress)) {
            logger.warn("🚨 FAST-PATH BLOCK: IP " + ipAddress + " is on the 5-minute ban list.");

            try {
                RequestEvent.RequestDetails requestDetails = new RequestEvent.RequestDetails(method, path, "api", ipAddress);
                RequestEvent.ResponseDetails responseDetails = new RequestEvent.ResponseDetails(HttpServletResponse.SC_FORBIDDEN, System.currentTimeMillis() - startTime);
                RequestEvent.FeatureVector featureVector = new RequestEvent.FeatureVector(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0);
                RequestEvent.MLMetadata mlMetadata = new RequestEvent.MLMetadata(1.0, 1, "FastPathBlock");

                RequestEvent event = new RequestEvent(
                        "request.blocked",
                        eventId,
                        eventTimestamp,
                        "tenant_placeholder",
                        ipAddress,
                        ipAddress + "_session",
                        label,
                        requestDetails,
                        responseDetails,
                        featureVector,
                        mlMetadata
                );

                kafkaProducer.publishEvent(event);

            } catch (Exception e) {
                logger.error("Failed to publish fast-path block to Kafka", e);
            }

            response.setStatus(HttpServletResponse.SC_FORBIDDEN);
            response.setContentType("application/json");
            response.getWriter().write("{\"error\": \"Forbidden\", \"message\": \"Traffic blocked by SAGE Engine Fast-Path\"}");
            return;
        }

        // 2. FEATURE EXTRACTION & ML INFERENCE
        double payloadSize = request.getContentLength() > 0 ? request.getContentLength() : 0.0;
        boolean isBot = false;
        double botProbability = 0.0;
        String threatClass = "Benign";
        boolean reconProbeCounted = false;
        Map<String, Double> features = Map.of(
                "SAGE_Session_Depth", 0.0,
                "SAGE_Temporal_Variance", 0.0,
                "SAGE_Request_Velocity", 0.0,
                "SAGE_Behavioral_Diversity", 0.0,
                "SAGE_Endpoint_Concentration", 0.0,
                "SAGE_Cart_Ratio", 0.0,
            "SAGE_Asset_Skip_Ratio", 1.0,
            "SAGE_Sequential_Traversal", 0.0
        );

        try {
            features = redisTelemetryService.processAndGetTelemetry(ipAddress, payloadSize, path);
            double sessionDepth = features.getOrDefault("SAGE_Session_Depth", 0.0);
            double endpointConcentration = features.getOrDefault("SAGE_Endpoint_Concentration", 0.0);
            double cartRatio = features.getOrDefault("SAGE_Cart_Ratio", 0.0);
            double assetSkipRatio = features.getOrDefault("SAGE_Asset_Skip_Ratio", 1.0);

            logger.info("SAGE feature vector ip={} values={}", ipAddress, features);

            // Recon slow-burn: count sensitive probe paths over a 10-minute window.
            if (isSensitiveReconPath(path)) {
                long probeCount = redisTelemetryService.incrementReconProbeCounter(ipAddress);
                reconProbeCounted = true;
                if (probeCount > RECON_BAN_THRESHOLD) {
                    redisTelemetryService.banIp(ipAddress);
                    publishThreatBlockedEvent(eventId, eventTimestamp, ipAddress, label, method, path, startTime, features, "Recon", botProbability);
                    response.setStatus(HttpServletResponse.SC_FORBIDDEN);
                    response.setContentType("application/json");
                    response.getWriter().write("{\"error\": \"Forbidden\", \"message\": \"Traffic blocked by SAGE recon slow-burn rule\"}");
                    return;
                }
            }

            // Flood rule: allow a short grace sequence, then hard block rapid bursts from one IP.
            long burstCount = redisTelemetryService.incrementFloodBurstCounter(ipAddress);
                if (burstCount > FLOOD_GRACE_REQUEST_COUNT
                    && isSuspiciousFloodAgent(request)
                    && !isSensitiveReconPath(path)) {
                redisTelemetryService.banIp(ipAddress);
                publishThreatBlockedEvent(eventId, eventTimestamp, ipAddress, label, method, path, startTime, features, "Flood", 1.0);
                response.setStatus(HttpServletResponse.SC_FORBIDDEN);
                response.setContentType("application/json");
                response.getWriter().write("{\"error\": \"Forbidden\", \"message\": \"Traffic blocked by SAGE flood rapid-burst rule\"}");
                return;
            }

            // Fast-path scraper detection (rule-based): throttle, then escalate to hard block.
            if (endpointConcentration > 0.85 && cartRatio == 0.0 && assetSkipRatio > 0.95) {
                logger.warn("🚨 SCRAPER FAST-PATH THROTTLE: ip={} endpointConcentration={} cartRatio={} assetSkipRatio={}",
                        ipAddress,
                        endpointConcentration,
                        cartRatio,
                        assetSkipRatio);

                long consecutive429 = redisTelemetryService.incrementScraper429Counter(ipAddress);
                if (consecutive429 >= SCRAPER_429_ESCALATION_THRESHOLD) {
                    redisTelemetryService.banIp(ipAddress);
                    publishThreatBlockedEvent(eventId, eventTimestamp, ipAddress, label, method, path, startTime, features, "Scraper", 1.0);
                    response.setStatus(HttpServletResponse.SC_FORBIDDEN);
                    response.setContentType("application/json");
                    response.getWriter().write("{\"error\": \"Forbidden\", \"message\": \"Traffic blocked by SAGE scraper escalation rule\"}");
                    return;
                }

                RequestEvent.RequestDetails requestDetails = new RequestEvent.RequestDetails(request.getMethod(), path, "api", ipAddress);
                RequestEvent.ResponseDetails responseDetails = new RequestEvent.ResponseDetails(429, System.currentTimeMillis() - startTime);
                RequestEvent.FeatureVector featureVector = toFeatureVector(features);
                RequestEvent.MLMetadata mlMetadata = new RequestEvent.MLMetadata(1.0, 1, "ScraperFastPath");
                RequestEvent event = new RequestEvent(
                        "threat.throttled",
                        eventId,
                        eventTimestamp,
                        "tenant_placeholder",
                        ipAddress,
                        ipAddress + "_session",
                        label,
                        requestDetails,
                        responseDetails,
                        featureVector,
                        mlMetadata
                );
                kafkaProducer.publishEvent(event);
                response.setStatus(429);
                response.setContentType("application/json");
                response.getWriter().write("{\"error\": \"Too Many Requests\", \"message\": \"Traffic throttled by SAGE scraper fast-path\"}");
                return;
            }

            redisTelemetryService.resetScraper429Counter(ipAddress);

            // Global echo flood signal catches distributed spray patterns that evade per-IP depth growth.
            boolean globalEchoFlood = "/echo".equals(path)
                    && redisTelemetryService.isGlobalPathFlooding(path, ECHO_FLOOD_RPS_THRESHOLD)
                    && isSuspiciousFloodAgent(request);

            if (globalEchoFlood) {
                threatClass = "Flood";
                botProbability = 0.98;
                isBot = true;
            }

            // GRACE PERIOD
            if (!isBot && sessionDepth > SESSION_DEPTH_THRESHOLD) {
                Map<String, Object> mlPayload = new HashMap<>(features);
                mlPayload.put("session_id", eventId);

                String jsonBody = objectMapper.writeValueAsString(mlPayload);

                HttpRequest mlRequest = HttpRequest.newBuilder()
                        .uri(URI.create(PYTHON_ML_URL))
                        .header("Content-Type", "application/json")
                        .timeout(Duration.ofMillis(2000))
                        .POST(HttpRequest.BodyPublishers.ofString(jsonBody))
                        .build();

                HttpResponse<String> mlResponse = httpClient.send(mlRequest, HttpResponse.BodyHandlers.ofString());

                if (mlResponse.statusCode() == 200) {
                    JsonNode responseNode = objectMapper.readTree(mlResponse.body());
                    boolean predictedMalicious = responseNode.path("is_bot").asBoolean(false);
                    botProbability = responseNode.path("bot_probability").asDouble(0.0);
                    threatClass = responseNode.path("threat_class").asText("Benign");

                        isBot = predictedMalicious
                            && !"Benign".equalsIgnoreCase(threatClass)
                            && botProbability >= BLOCK_PROBABILITY_THRESHOLD;

                    // Flood enforcement: if classified as Flood after grace depth, enforce hard ban.
                    if ("Flood".equalsIgnoreCase(threatClass) && sessionDepth > SESSION_DEPTH_THRESHOLD) {
                        isBot = true;
                    }
                } else {
                    logger.warn("ML Service returned non-200 status. Failing open.");
                }
            } else {
                logger.debug("Skipping ML inference for IP {} until session depth exceeds threshold {}. Current depth: {}",
                        ipAddress,
                        SESSION_DEPTH_THRESHOLD,
                        sessionDepth);
            }

        } catch (Exception e) {
            logger.error("SAGE ML Pipeline failed. Bypassing anomaly detection for this request.", e);
        }

        // 3. ENFORCE DECISION
        if (isBot) {
            logger.warn("🚨 SAGE ENGINE BLOCKED BOT! IP: " + ipAddress + " | Class: " + threatClass + " | Prob: " + botProbability);
            redisTelemetryService.banIp(ipAddress);
            publishThreatBlockedEvent(eventId, eventTimestamp, ipAddress, label, method, path, startTime, features, threatClass, botProbability);
            response.setStatus(HttpServletResponse.SC_FORBIDDEN);
            response.setContentType("application/json");
            response.getWriter().write("{\"error\": \"Forbidden\", \"message\": \"Traffic blocked by SAGE Engine Anomaly Detection\"}");
            return;
        }

        // 4. ALLOW TRAFFIC & LOG
        try {
            filterChain.doFilter(request, response);
        } finally {
            long latencyMs = System.currentTimeMillis() - startTime;
            int statusCode = response.getStatus();
            RequestEvent.RequestDetails requestDetails = new RequestEvent.RequestDetails(method, path, "api", ipAddress);
            RequestEvent.ResponseDetails responseDetails = new RequestEvent.ResponseDetails(statusCode, latencyMs);
            RequestEvent.FeatureVector featureVector = toFeatureVector(features);
            RequestEvent.MLMetadata mlMetadata = new RequestEvent.MLMetadata(botProbability, isBot ? 1 : 0, threatClass);

            if (statusCode == HttpServletResponse.SC_NOT_FOUND && !reconProbeCounted) {
                long probeCount = redisTelemetryService.incrementReconProbeCounter(ipAddress);
                if (probeCount > RECON_BAN_THRESHOLD && !redisTelemetryService.isIpBanned(ipAddress)) {
                    redisTelemetryService.banIp(ipAddress);
                    publishThreatBlockedEvent(eventId, eventTimestamp, ipAddress, label, method, path, startTime, features, "Recon", botProbability);

                    if (!response.isCommitted()) {
                        response.resetBuffer();
                        response.setStatus(HttpServletResponse.SC_FORBIDDEN);
                        response.setContentType("application/json");
                        response.getWriter().write("{\"error\": \"Forbidden\", \"message\": \"Traffic blocked by SAGE recon slow-burn rule\"}");
                        statusCode = HttpServletResponse.SC_FORBIDDEN;
                        responseDetails = new RequestEvent.ResponseDetails(statusCode, latencyMs);
                        mlMetadata = new RequestEvent.MLMetadata(botProbability, 1, "Recon");
                    }
                }
            }

            RequestEvent event = new RequestEvent(
                    "request.processed",
                    eventId,
                    Instant.now().toEpochMilli(),
                    "tenant_placeholder",
                    ipAddress,
                    ipAddress + "_session",
                    label,
                    requestDetails,
                    responseDetails,
                    featureVector,
                    mlMetadata
            );

            kafkaProducer.publishEvent(event);
        }
    }

    private void publishThreatBlockedEvent(String eventId,
                                           long timestamp,
                                           String ipAddress,
                                           String label,
                                           String method,
                                           String path,
                                           long startTime,
                                           Map<String, Double> features,
                                           String threatClass,
                                           double botProbability) {
        RequestEvent.RequestDetails requestDetails = new RequestEvent.RequestDetails(method, path, "api", ipAddress);
        RequestEvent.ResponseDetails responseDetails = new RequestEvent.ResponseDetails(HttpServletResponse.SC_FORBIDDEN, System.currentTimeMillis() - startTime);
        RequestEvent.FeatureVector featureVector = toFeatureVector(features);
        RequestEvent.MLMetadata mlMetadata = new RequestEvent.MLMetadata(botProbability, 1, threatClass);

        RequestEvent event = new RequestEvent(
                "threat.blocked",
                eventId,
                timestamp,
                "tenant_placeholder",
                ipAddress,
                ipAddress + "_session",
                label,
                requestDetails,
                responseDetails,
                featureVector,
                mlMetadata
        );
        kafkaProducer.publishEvent(event);
    }

    private boolean isSensitiveReconPath(String path) {
        if (path == null || path.isBlank()) {
            return false;
        }
        String normalizedPath = path.toLowerCase();
        for (String prefix : RECON_SENSITIVE_PREFIXES) {
            if (normalizedPath.equals(prefix) || normalizedPath.startsWith(prefix + "/")) {
                return true;
            }
        }
        return false;
    }

    private String resolveClientIp(HttpServletRequest request) {
        String forwarded = request.getHeader("X-Forwarded-For");
        if (forwarded != null && !forwarded.isBlank()) {
            String firstHop = forwarded.split(",")[0].trim();
            if (!firstHop.isEmpty()) {
                return firstHop;
            }
        }

        String realIp = request.getHeader("X-Real-IP");
        if (realIp != null && !realIp.isBlank()) {
            return realIp.trim();
        }

        return request.getRemoteAddr() != null ? request.getRemoteAddr() : "anonymous";
    }

    private boolean isSuspiciousFloodAgent(HttpServletRequest request) {
        String userAgent = request.getHeader("User-Agent");
        if (userAgent == null) {
            return false;
        }

        String lowerUserAgent = userAgent.toLowerCase();
        return lowerUserAgent.contains("curl")
                || lowerUserAgent.contains("scraperbot")
                || lowerUserAgent.contains("locust");
    }

    private String classifyByIP(String ip) {
        if (ip == null) {
            return "flood";
        }
        if (ip.startsWith("192.168") || ip.startsWith("10.")) {
            return "human";
        }
        if (ip.startsWith("52.") || ip.startsWith("34.")) {
            return "scraper";
        }
        if (ip.startsWith("185.") || ip.startsWith("176.")) {
            return "recon";
        }
        return "flood";
    }

    private RequestEvent.FeatureVector toFeatureVector(Map<String, Double> features) {
        return new RequestEvent.FeatureVector(
                features.getOrDefault("SAGE_Session_Depth", 0.0),
                features.getOrDefault("SAGE_Temporal_Variance", 0.0),
                features.getOrDefault("SAGE_Request_Velocity", 0.0),
                features.getOrDefault("SAGE_Behavioral_Diversity", 0.0),
                features.getOrDefault("SAGE_Endpoint_Concentration", 0.0),
                features.getOrDefault("SAGE_Cart_Ratio", 0.0),
            features.getOrDefault("SAGE_Asset_Skip_Ratio", 1.0),
            features.getOrDefault("SAGE_Sequential_Traversal", 0.0)
        );
    }
}