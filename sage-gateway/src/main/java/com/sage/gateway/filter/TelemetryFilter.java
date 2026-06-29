package com.sage.gateway.filter;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sage.gateway.event.RequestEvent;
import com.sage.gateway.service.KafkaProducerService;
import com.sage.gateway.service.RedisTelemetryService;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.annotation.Order;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Component;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.time.Instant;
import java.util.HashMap;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;

@Component
@Order(3)
public class TelemetryFilter implements GatewayFilter {

    private final RedisTelemetryService redisTelemetryService;
    private final KafkaProducerService kafkaProducer;
    private final ObjectMapper objectMapper;
    private final HttpClient httpClient;

    @org.springframework.beans.factory.annotation.Value("${ML_URL:http://localhost:8000/predict}")
    private String PYTHON_ML_URL;
    private static final boolean DATA_COLLECTION_MODE = false;
    private static final Logger logger = LoggerFactory.getLogger(TelemetryFilter.class);
    private static final double SESSION_DEPTH_THRESHOLD = 20.0;
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
    public String getName() {
        return "Telemetry";
    }

    @Override
    public boolean isGlobal() {
        return true;
    }

    @Override
    @SuppressWarnings("unchecked")
    public Optional<ResponseEntity<String>> filter(HttpServletRequest request, Map<String, String> config) {
        long startTime = System.currentTimeMillis();
        String requestId = request.getHeader("X-Request-Id");
        if (requestId == null || requestId.isBlank()) {
            requestId = UUID.randomUUID().toString();
        }
        request.setAttribute("X-Request-Id", requestId);
        request.setAttribute("X-Start-Time", startTime);
        
        String eventId = requestId;
        String ipAddress = resolveClientIp(request);
        String label = classifyByIP(ipAddress);
        String path = request.getRequestURI();
        String method = request.getMethod();
        long eventTimestamp = Instant.now().toEpochMilli();

        request.setAttribute("X-Event-Timestamp", eventTimestamp);
        request.setAttribute("X-Client-Ip", ipAddress);
        request.setAttribute("X-Client-Label", label);

        // 1. FAST-PATH BLOCK
        if (!DATA_COLLECTION_MODE && redisTelemetryService.isIpBanned(ipAddress)) {
            logger.warn("🚨 FAST-PATH BLOCK: IP " + ipAddress + " is on the 5-minute ban list.");
            return Optional.of(buildErrorResponse(HttpStatus.FORBIDDEN, "Traffic blocked by SAGE Engine Fast-Path"));
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
                "SAGE_Asset_Skip_Ratio", 1.0
        );

        try {
            features = redisTelemetryService.processAndGetTelemetry(ipAddress, payloadSize, path);
            double sessionDepth = features.getOrDefault("SAGE_Session_Depth", 0.0);
            double endpointConcentration = features.getOrDefault("SAGE_Endpoint_Concentration", 0.0);
            double cartRatio = features.getOrDefault("SAGE_Cart_Ratio", 0.0);
            double assetSkipRatio = features.getOrDefault("SAGE_Asset_Skip_Ratio", 1.0);

            logger.info("SAGE feature vector ip={} values={}", ipAddress, features);
            request.setAttribute("SAGE-Features", features);

            // Recon slow-burn: count sensitive probe paths over a 10-minute window.
            if (isSensitiveReconPath(path)) {
                long probeCount = redisTelemetryService.incrementReconProbeCounter(ipAddress);
                reconProbeCounted = true;
                request.setAttribute("SAGE-ReconProbeCounted", true);
                if (!DATA_COLLECTION_MODE && probeCount > RECON_BAN_THRESHOLD) {
                    redisTelemetryService.banIp(ipAddress);
                    publishThreatBlockedEvent(eventId, eventTimestamp, ipAddress, label, method, path, startTime, features, "Recon", botProbability);
                    return Optional.of(buildErrorResponse(HttpStatus.FORBIDDEN, "Traffic blocked by SAGE recon slow-burn rule"));
                }
            }

            // Flood rule: allow a short grace sequence, then hard block rapid bursts from one IP.
            long burstCount = redisTelemetryService.incrementFloodBurstCounter(ipAddress);
            if (!DATA_COLLECTION_MODE
                    && burstCount > FLOOD_GRACE_REQUEST_COUNT
                    && isSuspiciousFloodAgent(request)
                    && !isSensitiveReconPath(path)) {
                redisTelemetryService.banIp(ipAddress);
                publishThreatBlockedEvent(eventId, eventTimestamp, ipAddress, label, method, path, startTime, features, "Flood", 1.0);
                return Optional.of(buildErrorResponse(HttpStatus.FORBIDDEN, "Traffic blocked by SAGE flood rapid-burst rule"));
            }

            // Fast-path scraper detection (rule-based): throttle, then escalate to hard block.
            if (endpointConcentration > 0.85 && cartRatio == 0.0 && assetSkipRatio > 0.95) {
                logger.warn("🚨 SCRAPER FAST-PATH THROTTLE: ip={} endpointConcentration={} cartRatio={} assetSkipRatio={}",
                        ipAddress, endpointConcentration, cartRatio, assetSkipRatio);

                long consecutive429 = redisTelemetryService.incrementScraper429Counter(ipAddress);
                if (!DATA_COLLECTION_MODE && consecutive429 >= SCRAPER_429_ESCALATION_THRESHOLD) {
                    redisTelemetryService.banIp(ipAddress);
                    publishThreatBlockedEvent(eventId, eventTimestamp, ipAddress, label, method, path, startTime, features, "Scraper", 1.0);
                    return Optional.of(buildErrorResponse(HttpStatus.FORBIDDEN, "Traffic blocked by SAGE scraper escalation rule"));
                }

                if (!DATA_COLLECTION_MODE) {
                    RequestEvent.RequestDetails requestDetails = new RequestEvent.RequestDetails(method, path, "api", ipAddress);
                    RequestEvent.ResponseDetails responseDetails = new RequestEvent.ResponseDetails(429, System.currentTimeMillis() - startTime);
                    RequestEvent.FeatureVector featureVector = toFeatureVector(features);
                    RequestEvent.MLMetadata mlMetadata = new RequestEvent.MLMetadata(1.0, 1, "ScraperFastPath");
                    RequestEvent event = new RequestEvent("threat.throttled", eventId, eventTimestamp, "tenant_placeholder", ipAddress, ipAddress + "_session", label, requestDetails, responseDetails, featureVector, mlMetadata);
                    kafkaProducer.publishEvent(event);
                    return Optional.of(buildErrorResponse(HttpStatus.TOO_MANY_REQUESTS, "Traffic throttled by SAGE scraper fast-path"));
                }
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
            double sessionDuration = features.getOrDefault("SAGE_Session_Duration", 0.0);
            if (!isBot && sessionDepth > SESSION_DEPTH_THRESHOLD && sessionDuration >= 3.0) {
                Map<String, Object> mlPayload = new HashMap<>(features);
                mlPayload.put("session_id", eventId);

                String jsonBody = objectMapper.writeValueAsString(mlPayload);

                HttpRequest mlRequest = HttpRequest.newBuilder()
                        .uri(URI.create(PYTHON_ML_URL))
                        .header("Content-Type", "application/json")
                        .header("X-Request-Id", requestId)
                        .timeout(Duration.ofMillis(100))
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

                    if ("Flood".equalsIgnoreCase(threatClass) && sessionDepth > SESSION_DEPTH_THRESHOLD) {
                        isBot = true;
                    }
                } else {
                    logger.warn("ML Service returned non-200 status. Failing open.");
                }
            } else {
                logger.debug("Skipping ML inference for IP {} until session depth exceeds threshold {}. Current depth: {}", ipAddress, SESSION_DEPTH_THRESHOLD, sessionDepth);
            }

        } catch (Exception e) {
            logger.error("SAGE ML Pipeline failed. Bypassing anomaly detection for this request.", e);
        }
        
        request.setAttribute("SAGE-BotProbability", botProbability);
        request.setAttribute("SAGE-IsBot", isBot);
        request.setAttribute("SAGE-ThreatClass", threatClass);

        // 3. ENFORCE DECISION
        if (!DATA_COLLECTION_MODE && isBot) {
            logger.warn("🚨 SAGE ENGINE BLOCKED BOT! IP: " + ipAddress + " | Class: " + threatClass + " | Prob: " + botProbability);
            redisTelemetryService.banIp(ipAddress);
            publishThreatBlockedEvent(eventId, eventTimestamp, ipAddress, label, method, path, startTime, features, threatClass, botProbability);
            return Optional.of(buildErrorResponse(HttpStatus.FORBIDDEN, "Traffic blocked by SAGE Engine Anomaly Detection"));
        }

        // Allow traffic to proceed to next filter
        return Optional.empty();
    }
    
    private ResponseEntity<String> buildErrorResponse(HttpStatus status, String message) {
        return ResponseEntity.status(status)
                .header("Content-Type", "application/json")
                .body("{\"error\": \"" + status.getReasonPhrase() + "\", \"message\": \"" + message + "\"}");
    }

    @Override
    @SuppressWarnings("unchecked")
    public void postProcess(HttpServletRequest request, ResponseEntity<String> response, long latencyMs, Exception ex) {
        String eventId = (String) request.getAttribute("X-Request-Id");
        if (eventId == null) return; // If we didn't even start processing

        String ipAddress = (String) request.getAttribute("X-Client-Ip");
        String label = (String) request.getAttribute("X-Client-Label");
        long eventTimestamp = request.getAttribute("X-Event-Timestamp") != null ? (long) request.getAttribute("X-Event-Timestamp") : Instant.now().toEpochMilli();
        long startTime = request.getAttribute("X-Start-Time") != null ? (long) request.getAttribute("X-Start-Time") : System.currentTimeMillis();
        
        Map<String, Double> features = (Map<String, Double>) request.getAttribute("SAGE-Features");
        if (features == null) return; // Features not extracted, meaning it failed super early

        double botProbability = request.getAttribute("SAGE-BotProbability") != null ? (double) request.getAttribute("SAGE-BotProbability") : 0.0;
        boolean isBot = request.getAttribute("SAGE-IsBot") != null ? (boolean) request.getAttribute("SAGE-IsBot") : false;
        String threatClass = request.getAttribute("SAGE-ThreatClass") != null ? (String) request.getAttribute("SAGE-ThreatClass") : "Benign";
        boolean reconProbeCounted = request.getAttribute("SAGE-ReconProbeCounted") != null ? (boolean) request.getAttribute("SAGE-ReconProbeCounted") : false;

        int statusCode = response != null ? response.getStatusCode().value() : (ex != null ? 500 : 200);
        String method = request.getMethod();
        String path = request.getRequestURI();

        RequestEvent.RequestDetails requestDetails = new RequestEvent.RequestDetails(method, path, "api", ipAddress);
        RequestEvent.ResponseDetails responseDetails = new RequestEvent.ResponseDetails(statusCode, latencyMs);
        RequestEvent.FeatureVector featureVector = toFeatureVector(features);
        RequestEvent.MLMetadata mlMetadata = new RequestEvent.MLMetadata(botProbability, isBot ? 1 : 0, threatClass);

        if (statusCode == HttpServletResponse.SC_NOT_FOUND && !reconProbeCounted) {
            long probeCount = redisTelemetryService.incrementReconProbeCounter(ipAddress);
            if (!DATA_COLLECTION_MODE && probeCount > RECON_BAN_THRESHOLD && !redisTelemetryService.isIpBanned(ipAddress)) {
                redisTelemetryService.banIp(ipAddress);
                publishThreatBlockedEvent(eventId, eventTimestamp, ipAddress, label, method, path, startTime, features, "Recon", botProbability);
                // Note: since this is postProcess, the response is already generated. We can't change it. 
                // But we still logged the ban and event. The NEXT request will be blocked by fast-path.
                mlMetadata = new RequestEvent.MLMetadata(botProbability, 1, "Recon");
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
        RequestEvent.ResponseDetails responseDetails = new RequestEvent.ResponseDetails(403, System.currentTimeMillis() - startTime);
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
        if (ip.startsWith("172.25.")) {
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
                features.getOrDefault("SAGE_Asset_Skip_Ratio", 1.0)
        );
    }
}
