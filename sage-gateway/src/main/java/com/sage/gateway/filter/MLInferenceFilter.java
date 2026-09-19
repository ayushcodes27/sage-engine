package com.sage.gateway.filter;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sage.gateway.service.RedisTelemetryService;
import io.micrometer.core.instrument.MeterRegistry;
import jakarta.servlet.http.HttpServletRequest;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.annotation.Order;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Component;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.HashMap;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.Semaphore;
import java.util.concurrent.TimeUnit;

@Component
@Order(4)
public class MLInferenceFilter implements GatewayFilter {

    private static final Logger logger = LoggerFactory.getLogger(MLInferenceFilter.class);
    private static final double SESSION_DEPTH_THRESHOLD = 20.0;
    private static final Semaphore ML_BACKPRESSURE = new Semaphore(50);

    private final RedisTelemetryService redisTelemetryService;
    private final ObjectMapper objectMapper;
    private final MeterRegistry meterRegistry;
    private final HttpClient httpClient;

    @org.springframework.beans.factory.annotation.Value("${ML_URL:http://localhost:8000/predict}")
    private String PYTHON_ML_URL;

    @org.springframework.beans.factory.annotation.Value("${sage.ml.expected-contract-hash}")
    private String expectedContractHash;

    private volatile boolean contractVerified = false;

    public MLInferenceFilter(RedisTelemetryService redisTelemetryService, ObjectMapper objectMapper, MeterRegistry meterRegistry) {
        this.redisTelemetryService = redisTelemetryService;
        this.objectMapper = objectMapper;
        this.meterRegistry = meterRegistry;
        this.httpClient = HttpClient.newBuilder()
                .version(HttpClient.Version.HTTP_1_1)
                .connectTimeout(Duration.ofMillis(500))
                .build();
    }

    @Override
    public String getName() {
        return "MLInference";
    }

    @Override
    public boolean isGlobal() {
        return true;
    }

    @Override
    public Optional<ResponseEntity<String>> filter(HttpServletRequest request, Map<String, String> config) {
        String ipAddress = (String) request.getAttribute("X-Client-Ip");
        if (ipAddress == null) {
            ipAddress = "anonymous";
        }
        
        String requestId = (String) request.getAttribute("X-Request-Id");
        double payloadSize = request.getContentLength() > 0 ? request.getContentLength() : 0.0;
        String path = request.getRequestURI();

        boolean isBot = false;
        double botProbability = 0.0;
        String threatClass = "Benign";
        String evaluationStatus = "Skipped";
        String decisionSource = "none";
        Double scoringDepth = null;
        Long scoringTimestampMs = null;

        Map<String, Double> features = Map.of(
                "SAGE_Session_Depth", 0.0,
                "SAGE_Temporal_Variance", 0.0,
                "SAGE_Request_Velocity", 0.0,
                "SAGE_Behavioral_Diversity", 0.0,
                "SAGE_Endpoint_Concentration", 0.0,
                "SAGE_Cart_Ratio", 0.0,
                "SAGE_Asset_Skip_Ratio", 1.0,
                "SAGE_NonStatic_Navigation_Gap", 0.0,
                "SAGE_NonStatic_Long_Gap_Ratio", 0.0
        );
        
        Double shadowBotProbability = null;
        Boolean shadowIsBot = null;
        String shadowThreatClass = null;
        String shadowStatus = "skipped";
        Double prodInferenceLatencyMs = null;
        Double shadowInferenceLatencyMs = null;
        String contractHash = "unknown";
        String modelVersion = "unknown";

        try {
            features = redisTelemetryService.processAndGetTelemetry(ipAddress, payloadSize, path);
            request.setAttribute("SAGE-Features", features);
            
            double sessionDepth = features.getOrDefault("SAGE_Session_Depth", 0.0);
            double sessionDuration = features.getOrDefault("SAGE_Session_Duration", 0.0);

            Map<String, String> cachedDecision = redisTelemetryService.getCachedMlDecision(ipAddress);
            boolean isProbe = "true".equalsIgnoreCase(request.getHeader("X-SAGE-Probe"));
            boolean shouldScoreFresh = false;

            if (sessionDepth > SESSION_DEPTH_THRESHOLD && sessionDuration >= 3.0) {
                if (cachedDecision.isEmpty() || isProbe) {
                    shouldScoreFresh = true;
                }
            }

            String prodModelSha256 = null;
            String shadowModelSha256 = null;
            String shadowContractHash = null;
            String shadowFeatureListHash = null;

            if (!cachedDecision.isEmpty() && !shouldScoreFresh) {
                isBot = Boolean.parseBoolean(cachedDecision.getOrDefault("isBot", "false"));
                botProbability = Double.parseDouble(cachedDecision.getOrDefault("botProbability", "0.0"));
                threatClass = cachedDecision.getOrDefault("threatClass", "Benign");
                evaluationStatus = "Cached";
                decisionSource = "cached";
                shadowStatus = cachedDecision.getOrDefault("shadowStatus", "unavailable");
                if (cachedDecision.containsKey("shadowIsBot")) {
                    shadowIsBot = Boolean.parseBoolean(cachedDecision.get("shadowIsBot"));
                }
                if (cachedDecision.containsKey("shadowBotProbability")) {
                    shadowBotProbability = Double.parseDouble(cachedDecision.get("shadowBotProbability"));
                }
                shadowThreatClass = cachedDecision.get("shadowThreatClass");
                contractHash = cachedDecision.getOrDefault("contractHash", "unknown");
                modelVersion = cachedDecision.getOrDefault("modelVersion", "unknown");
                prodModelSha256 = cachedDecision.get("prodModelSha256");
                shadowModelSha256 = cachedDecision.get("shadowModelSha256");
                shadowContractHash = cachedDecision.get("shadowContractHash");
                shadowFeatureListHash = cachedDecision.get("shadowFeatureListHash");
                if (cachedDecision.containsKey("scoringDepth")) {
                    try {
                        scoringDepth = Double.parseDouble(cachedDecision.get("scoringDepth"));
                    } catch (Exception ignored) {}
                }
                if (cachedDecision.containsKey("scoringTimestamp")) {
                    try {
                        scoringTimestampMs = Long.parseLong(cachedDecision.get("scoringTimestamp"));
                    } catch (Exception ignored) {}
                }
                logger.debug("Reusing cached ML decision for IP {}", ipAddress);
            }

            if (shouldScoreFresh) {
                Map<String, Object> mlPayload = new HashMap<>(features);
                mlPayload.put("session_id", requestId);
                mlPayload.put("gateway_timestamp_ms", System.currentTimeMillis());

                String jsonBody = objectMapper.writeValueAsString(mlPayload);

                HttpRequest mlRequest = HttpRequest.newBuilder()
                        .uri(URI.create(PYTHON_ML_URL))
                        .header("Content-Type", "application/json")
                        .header("X-Request-Id", requestId != null ? requestId : "unknown")
                        .POST(HttpRequest.BodyPublishers.ofString(jsonBody))
                        .build();

                boolean acquired = false;
                try {
                    acquired = ML_BACKPRESSURE.tryAcquire(5, TimeUnit.MILLISECONDS);
                    if (!acquired) {
                        evaluationStatus = "Timeout";
                        logger.warn("ML Backpressure kicked in. Rejecting request to ML queue.");
                    } else {
                        HttpResponse<String> mlResponse = httpClient.sendAsync(mlRequest, HttpResponse.BodyHandlers.ofString())
                                .get(1000, TimeUnit.MILLISECONDS);

                        if (mlResponse.statusCode() == 200) {
                            evaluationStatus = "Scored";
                            decisionSource = "fresh";
                            scoringDepth = sessionDepth;
                            scoringTimestampMs = System.currentTimeMillis();

                            JsonNode responseNode = objectMapper.readTree(mlResponse.body());
                            isBot = responseNode.path("is_bot").asBoolean(false);
                            botProbability = responseNode.path("bot_probability").asDouble(0.0);
                            threatClass = responseNode.path("threat_class").asText("Benign");
                            
                            // Extract Shadow fields
                            shadowStatus = responseNode.path("shadow_status").asText("unavailable");
                            if (!responseNode.path("shadow_is_bot").isNull()) {
                                shadowIsBot = responseNode.path("shadow_is_bot").asBoolean();
                            }
                            if (!responseNode.path("shadow_bot_probability").isNull()) {
                                shadowBotProbability = responseNode.path("shadow_bot_probability").asDouble();
                            }
                            if (!responseNode.path("shadow_threat_class").isNull()) {
                                shadowThreatClass = responseNode.path("shadow_threat_class").asText();
                            }
                            if (!responseNode.path("production_processing_time_ms").isNull()) {
                                prodInferenceLatencyMs = responseNode.path("production_processing_time_ms").asDouble();
                            }
                            if (!responseNode.path("shadow_processing_time_ms").isNull()) {
                                shadowInferenceLatencyMs = responseNode.path("shadow_processing_time_ms").asDouble();
                            }
                            
                            contractHash = responseNode.path("contract_hash").asText("unknown");
                            modelVersion = responseNode.path("model_version").asText("unknown");

                            // Extract Cryptographic Identity
                            if (!responseNode.path("prod_model_sha256").isNull()) {
                                prodModelSha256 = responseNode.path("prod_model_sha256").asText();
                            }
                            if (!responseNode.path("shadow_model_sha256").isNull()) {
                                shadowModelSha256 = responseNode.path("shadow_model_sha256").asText();
                            }
                            if (!responseNode.path("shadow_contract_hash").isNull()) {
                                shadowContractHash = responseNode.path("shadow_contract_hash").asText();
                            }
                            if (!responseNode.path("shadow_feature_list_hash").isNull()) {
                                shadowFeatureListHash = responseNode.path("shadow_feature_list_hash").asText();
                            }

                            Map<String, String> decision = new HashMap<>();
                            decision.put("isBot", Boolean.toString(isBot));
                            decision.put("botProbability", Double.toString(botProbability));
                            decision.put("threatClass", threatClass);
                            decision.put("shadowStatus", shadowStatus);
                            decision.put("shadowThreatClass", shadowThreatClass);
                            decision.put("contractHash", contractHash);
                            decision.put("modelVersion", modelVersion);
                            decision.put("scoringDepth", Double.toString(scoringDepth));
                            decision.put("scoringTimestamp", Long.toString(scoringTimestampMs));
                            if (shadowIsBot != null) decision.put("shadowIsBot", Boolean.toString(shadowIsBot));
                            if (shadowBotProbability != null) decision.put("shadowBotProbability", Double.toString(shadowBotProbability));
                            if (prodModelSha256 != null) decision.put("prodModelSha256", prodModelSha256);
                            if (shadowModelSha256 != null) decision.put("shadowModelSha256", shadowModelSha256);
                            if (shadowContractHash != null) decision.put("shadowContractHash", shadowContractHash);
                            if (shadowFeatureListHash != null) decision.put("shadowFeatureListHash", shadowFeatureListHash);
                            redisTelemetryService.cacheMlDecision(ipAddress, decision);
                            
                            if (!contractVerified) {
                                if (!expectedContractHash.equals(contractHash)) {
                                    logger.error("CRITICAL: SAGE Engine Contract Hash Mismatch! Expected {}, Got {}", expectedContractHash, contractHash);
                                } else {
                                    logger.info("SAGE Engine Contract Hash Verified: {}", contractHash);
                                    contractVerified = true;
                                }
                            }
                            
                            logger.info("🎯 ML SCORED - IP: {} | Prob: {} | Bot: {} | Shadow Status: {} | Source: {}", 
                                    ipAddress, botProbability, isBot, shadowStatus, decisionSource);
                        } else {
                            evaluationStatus = "Failed";
                            logger.warn("ML Service returned non-200 status.");
                        }
                    }
                } catch (java.util.concurrent.TimeoutException | InterruptedException e) {
                    evaluationStatus = "Timeout";
                    logger.error("SAGE ML Pipeline failed (Timeout).");
                } catch (java.util.concurrent.ExecutionException e) {
                    evaluationStatus = "Error";
                    logger.error("SAGE ML Pipeline failed (Execution Error).", e);
                } finally {
                    if (acquired) {
                        ML_BACKPRESSURE.release();
                    }
                }
            } else if (cachedDecision.isEmpty()) {
                logger.debug("Skipping ML inference for IP {} until depth > {}.", ipAddress, SESSION_DEPTH_THRESHOLD);
            }
        } catch (Exception e) {
            evaluationStatus = "Error";
            logger.error("SAGE ML Inference Filter failed processing.", e);
        }

        meterRegistry.counter("sage_gateway_ml_inference_outcomes_total", "outcome", evaluationStatus).increment();
        
        request.setAttribute("SAGE-BotProbability", botProbability);
        request.setAttribute("SAGE-IsBot", isBot);
        request.setAttribute("SAGE-ThreatClass", threatClass);
        request.setAttribute("SAGE-EvaluationStatus", evaluationStatus);
        request.setAttribute("SAGE-DecisionSource", decisionSource);
        request.setAttribute("SAGE-ScoringDepth", scoringDepth);
        request.setAttribute("SAGE-ScoringTimestampMs", scoringTimestampMs);
        
        request.setAttribute("SAGE-ShadowBotProbability", shadowBotProbability);
        request.setAttribute("SAGE-ShadowIsBot", shadowIsBot);
        request.setAttribute("SAGE-ShadowThreatClass", shadowThreatClass);
        request.setAttribute("SAGE-ShadowStatus", shadowStatus);
        request.setAttribute("SAGE-ProdInferenceLatencyMs", prodInferenceLatencyMs);
        request.setAttribute("SAGE-ShadowInferenceLatencyMs", shadowInferenceLatencyMs);
        request.setAttribute("SAGE-ContractHash", contractHash);
        request.setAttribute("SAGE-ModelVersion", modelVersion);
        request.setAttribute("SAGE-ProdModelSha256", prodModelSha256);
        request.setAttribute("SAGE-ShadowModelSha256", shadowModelSha256);
        request.setAttribute("SAGE-ShadowContractHash", shadowContractHash);
        request.setAttribute("SAGE-ShadowFeatureListHash", shadowFeatureListHash);
        
        return Optional.empty();
    }
}
