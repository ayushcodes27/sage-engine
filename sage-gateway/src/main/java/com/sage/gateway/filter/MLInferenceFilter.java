package com.sage.gateway.filter;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sage.gateway.event.RequestEvent;
import com.sage.gateway.service.KafkaProducerService;
import com.sage.gateway.service.RedisTelemetryService;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
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
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
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
    private final KafkaProducerService kafkaProducer;
    private final HttpClient httpClient;
    private final ExecutorService asyncMlExecutor = Executors.newVirtualThreadPerTaskExecutor();

    @org.springframework.beans.factory.annotation.Value("${ML_URL:http://localhost:8000/predict}")
    private String PYTHON_ML_URL = "http://localhost:8000/predict";

    @org.springframework.beans.factory.annotation.Value("${sage.ml.expected-contract-hash}")
    private String expectedContractHash;

    @org.springframework.beans.factory.annotation.Value("${sage.probe.secret:}")
    private String probeSecret;

    @org.springframework.beans.factory.annotation.Value("${sage.telemetry.rescore-frequency:20}")
    private int rescoreFrequency = 20;

    /** Cooldown after a failed score before the client is scored again (0 disables). */
    @org.springframework.beans.factory.annotation.Value("${sage.ml.failure-cooldown-ms:5000}")
    private long failureCooldownMs = 5000;

    @org.springframework.beans.factory.annotation.Value("${sage.ml.shadow-threshold:0.35}")
    private double shadowThreshold = 0.35;

    /**
     * Benchmark / deployment mode (B2):
     *   off      - proxy only: no Redis features, no telemetry, no ML
     *   features - Redis features + telemetry, no ML scoring
     *   sync     - ML scoring inline on the request path
     *   async    - ML scoring off the request path (default)
     * All modes are shadow-only; enforcement is controlled separately by sage.enforcement.enabled.
     */
    @org.springframework.beans.factory.annotation.Value("${sage.ml.mode:async}")
    private String mlMode = "async";

    private volatile boolean contractVerified = false;

    public MLInferenceFilter(RedisTelemetryService redisTelemetryService, ObjectMapper objectMapper,
                             MeterRegistry meterRegistry, KafkaProducerService kafkaProducer) {
        this.redisTelemetryService = redisTelemetryService;
        this.objectMapper = objectMapper;
        this.meterRegistry = meterRegistry;
        this.kafkaProducer = kafkaProducer;
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
        if ("off".equalsIgnoreCase(mlMode)) {
            return Optional.empty();
        }
        String ipAddress = (String) request.getAttribute("X-Client-Ip");
        if (ipAddress == null) {
            ipAddress = "anonymous";
        }
        
        String requestId = (String) request.getAttribute("X-Request-Id");
        String clientId = (String) request.getAttribute("X-SAGE-Client-Id");
        String runId = (String) request.getAttribute("X-SAGE-Run-Id");
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
        String prodModelSha256 = null;
        String shadowModelSha256 = null;
        String shadowContractHash = null;
        String shadowFeatureListHash = null;

        try {
            final String telemetryIp = ipAddress;
            features = Timer.builder("sage_gateway_redis_telemetry_seconds")
                    .description("Redis round trips to update and read session features for one request")
                    .publishPercentileHistogram()
                    .register(meterRegistry)
                    .record(() -> redisTelemetryService.processAndGetTelemetry(telemetryIp, payloadSize, path));
            request.setAttribute("SAGE-Features", features);
            
            double sessionDepth = features.getOrDefault("SAGE_Session_Depth", 0.0);
            double sessionDuration = features.getOrDefault("SAGE_Session_Duration", 0.0);
            // f0 is capped at 50, so re-scoring is scheduled on the uncapped non-static request count.
            double requestCount = features.getOrDefault(RedisTelemetryService.NON_STATIC_REQUEST_COUNT, sessionDepth);

            Map<String, String> cachedDecision = redisTelemetryService.getCachedMlDecision(ipAddress);

            // Reviewer Item 2: Secure X-SAGE-Probe bypass with secret authentication
            boolean isProbeHeader = "true".equalsIgnoreCase(request.getHeader("X-SAGE-Probe"));
            boolean isProbeAuthorized = false;
            if (isProbeHeader) {
                String providedSecret = request.getHeader("X-SAGE-Probe-Secret");
                if (probeSecret != null && !probeSecret.isBlank()) {
                    isProbeAuthorized = probeSecret.equals(providedSecret);
                    if (!isProbeAuthorized) {
                        logger.warn("X-SAGE-Probe unauthorized: invalid secret provided for IP {}", ipAddress);
                    }
                } else {
                    logger.warn("X-SAGE-Probe ignored: sage.probe.secret not configured.");
                }
            }

            // Reviewer Item 2: Re-score clients every 20 new non-static requests instead of trusting one decision for 5 min
            double lastScoredCount = 0.0;
            String lastScored = cachedDecision.getOrDefault("scoringCount", cachedDecision.get("scoringDepth"));
            if (lastScored != null) {
                try {
                    lastScoredCount = Double.parseDouble(lastScored);
                } catch (Exception ignored) {}
            }

            boolean shouldScoreFresh = false;
            if (sessionDepth > SESSION_DEPTH_THRESHOLD && sessionDuration >= 3.0) {
                if (cachedDecision.isEmpty() || isProbeAuthorized) {
                    shouldScoreFresh = true;
                } else if ((requestCount - lastScoredCount) >= rescoreFrequency) {
                    shouldScoreFresh = true; // Periodic re-scoring trigger
                }
            }

            // Apply cached decision if present
            if (!cachedDecision.isEmpty()) {
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
            }

            if ("features".equalsIgnoreCase(mlMode)) {
                shouldScoreFresh = false;
            }

            boolean inCooldown = false;
            if (shouldScoreFresh && !isProbeAuthorized && failureCooldownMs > 0
                    && redisTelemetryService.inScoringCooldown(ipAddress)) {
                shouldScoreFresh = false;
                inCooldown = true;
            }

            // Reviewer Item 3: Move scoring off the request path asynchronously
            if (shouldScoreFresh) {
                boolean forceSync = isProbeAuthorized && "true".equalsIgnoreCase(request.getHeader("X-SAGE-Sync-Score"));
                boolean inlineMode = "sync".equalsIgnoreCase(mlMode);
                if (forceSync || inlineMode) {
                    String syncSource = forceSync ? "fresh_sync" : "inline_sync";
                    Map<String, String> freshResult = performMlInference(ipAddress, requestId, features, sessionDepth, requestCount,
                            new ScoreContext(clientId, runId, path, syncSource));
                    if ("Scored".equals(freshResult.get("evaluationStatus"))) {
                        evaluationStatus = "Scored";
                        decisionSource = syncSource;
                        scoringDepth = sessionDepth;
                        scoringTimestampMs = Long.parseLong(freshResult.get("scoringTimestamp"));
                        isBot = Boolean.parseBoolean(freshResult.getOrDefault("isBot", "false"));
                        botProbability = Double.parseDouble(freshResult.getOrDefault("botProbability", "0.0"));
                        threatClass = freshResult.getOrDefault("threatClass", "Benign");
                        shadowStatus = freshResult.getOrDefault("shadowStatus", "unavailable");
                        contractHash = freshResult.getOrDefault("contractHash", "unknown");
                        modelVersion = freshResult.getOrDefault("modelVersion", "unknown");
                        // N8: the synchronous result must carry the shadow decision, identity and timings too.
                        shadowIsBot = freshResult.containsKey("shadowIsBot") ? Boolean.parseBoolean(freshResult.get("shadowIsBot")) : null;
                        shadowBotProbability = parseDoubleOrNull(freshResult.get("shadowBotProbability"));
                        shadowThreatClass = freshResult.get("shadowThreatClass");
                        prodModelSha256 = freshResult.get("prodModelSha256");
                        shadowModelSha256 = freshResult.get("shadowModelSha256");
                        shadowContractHash = freshResult.get("shadowContractHash");
                        shadowFeatureListHash = freshResult.get("shadowFeatureListHash");
                        prodInferenceLatencyMs = parseDoubleOrNull(freshResult.get("prodInferenceLatencyMs"));
                        shadowInferenceLatencyMs = parseDoubleOrNull(freshResult.get("shadowInferenceLatencyMs"));
                    } else {
                        evaluationStatus = freshResult.getOrDefault("evaluationStatus", "Failed");
                    }
                } else {
                    // Normal async path: request proceeds immediately without blocking
                    if (redisTelemetryService.acquireScoringLock(ipAddress)) {
                        final Map<String, Double> asyncFeatures = new HashMap<>(features);
                        final String asyncIp = ipAddress;
                        final String asyncReqId = requestId;
                        final double asyncDepth = sessionDepth;
                        final double asyncCount = requestCount;
                        final ScoreContext asyncContext = new ScoreContext(clientId, runId, path, "async");
                        asyncMlExecutor.submit(() -> {
                            try {
                                performMlInference(asyncIp, asyncReqId, asyncFeatures, asyncDepth, asyncCount, asyncContext);
                            } finally {
                                redisTelemetryService.releaseScoringLock(asyncIp);
                            }
                        });
                    }
                    if (cachedDecision.isEmpty()) {
                        evaluationStatus = "AsyncScheduled";
                        decisionSource = "async_pending";
                    }
                }
            } else if (cachedDecision.isEmpty()) {
                // Reviewer Item 3: Log every 'not scored' event with its granular reason
                if (sessionDepth <= SESSION_DEPTH_THRESHOLD) {
                    evaluationStatus = "GateDepthNotMet";
                } else if (sessionDuration < 3.0) {
                    evaluationStatus = "GateDurationNotMet";
                } else if (inCooldown) {
                    evaluationStatus = "ScoringCooldown";
                } else {
                    evaluationStatus = "features".equalsIgnoreCase(mlMode) ? "ScoringDisabled" : "Skipped";
                }
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

    /** Identity of the request that triggered a score, carried into the score telemetry event. */
    record ScoreContext(String clientId, String runId, String path, String decisionSource) {}

    private static Double parseDoubleOrNull(String value) {
        if (value == null) return null;
        try {
            return Double.parseDouble(value);
        } catch (NumberFormatException e) {
            return null;
        }
    }

    private Map<String, String> performMlInference(String ipAddress, String requestId, Map<String, Double> features,
                                                   double sessionDepth, double requestCount, ScoreContext context) {
        Map<String, String> result = scoreOnce(ipAddress, requestId, features, sessionDepth, requestCount);
        String status = result.getOrDefault("evaluationStatus", "Error");
        meterRegistry.counter("sage_gateway_ml_score_attempts_total", "status", status, "source", context.decisionSource()).increment();
        if (!"Scored".equals(status) && failureCooldownMs > 0) {
            redisTelemetryService.startScoringCooldown(ipAddress, Duration.ofMillis(failureCooldownMs));
        }
        publishScoreEvent(ipAddress, requestId, features, result, context);
        return result;
    }

    /**
     * Every scoring attempt is logged as its own event, so a score triggered by a client's last
     * request (async: never visible on a later request) and every async failure reach telemetry.
     * The event carries the exact feature vector that was scored.
     */
    private void publishScoreEvent(String ipAddress, String requestId, Map<String, Double> features,
                                   Map<String, String> result, ScoreContext context) {
        if (kafkaProducer == null) return;
        try {
            String status = result.getOrDefault("evaluationStatus", "Error");
            boolean scored = "Scored".equals(status);
            Double shadowProb = parseDoubleOrNull(result.get("shadowBotProbability"));
            String shadowAction = null;
            if (shadowProb != null) {
                shadowAction = shadowProb >= 0.80 ? "Blocked" : (shadowProb >= shadowThreshold ? "Challenged" : "Allowed");
            }
            Integer shadowIsBotFlag = result.containsKey("shadowIsBot") ? (Boolean.parseBoolean(result.get("shadowIsBot")) ? 1 : 0) : null;
            RequestEvent.MLMetadata ml = new RequestEvent.MLMetadata(
                    parseDoubleOrNull(result.get("botProbability")),
                    result.containsKey("isBot") ? (Boolean.parseBoolean(result.get("isBot")) ? 1 : 0) : null,
                    result.get("threatClass"), status,
                    shadowProb, shadowIsBotFlag, result.get("shadowThreatClass"), shadowAction,
                    result.getOrDefault("shadowStatus", scored ? "unavailable" : status.toLowerCase()),
                    parseDoubleOrNull(result.get("prodInferenceLatencyMs")),
                    parseDoubleOrNull(result.get("shadowInferenceLatencyMs")),
                    result.get("contractHash"), result.get("modelVersion"), shadowThreshold,
                    context.decisionSource(), sessionDepth(features),
                    result.containsKey("scoringTimestamp") ? Long.parseLong(result.get("scoringTimestamp")) : System.currentTimeMillis(),
                    result.get("prodModelSha256"), result.get("shadowModelSha256"),
                    result.get("shadowContractHash"), result.get("shadowFeatureListHash"));
            long roundTrip = result.containsKey("mlRoundTripMs") ? Math.round(Double.parseDouble(result.get("mlRoundTripMs"))) : 0L;
            RequestEvent event = new RequestEvent(
                    "1.1",
                    scored ? "score.completed" : "score.failed",
                    UUID.randomUUID().toString(),
                    System.currentTimeMillis(),
                    "tenant_placeholder",
                    context.clientId() != null ? context.clientId() : ipAddress,
                    requestId,
                    context.runId() != null ? context.runId() : "unknown",
                    "unknown",
                    new RequestEvent.RequestDetails("SCORE", context.path(), "score", ipAddress),
                    new RequestEvent.ResponseDetails(0, roundTrip),
                    toFeatureVector(features),
                    ml);
            kafkaProducer.publishEvent(event);
        } catch (Exception e) {
            meterRegistry.counter("sage_gateway_score_event_publish_errors_total").increment();
            logger.error("Failed to publish score event for IP {}", ipAddress, e);
        }
    }

    private static double sessionDepth(Map<String, Double> features) {
        return features.getOrDefault("SAGE_Session_Depth", 0.0);
    }

    private static RequestEvent.FeatureVector toFeatureVector(Map<String, Double> f) {
        return new RequestEvent.FeatureVector(
                f.getOrDefault("SAGE_Session_Depth", 0.0),
                f.getOrDefault("SAGE_Temporal_Variance", 0.0),
                f.getOrDefault("SAGE_Request_Velocity", 0.0),
                f.getOrDefault("SAGE_Behavioral_Diversity", 0.0),
                f.getOrDefault("SAGE_Endpoint_Concentration", 0.0),
                f.getOrDefault("SAGE_Cart_Ratio", 0.0),
                f.getOrDefault("SAGE_Asset_Skip_Ratio", 1.0),
                f.getOrDefault("SAGE_NonStatic_Navigation_Gap", 0.0),
                f.getOrDefault("SAGE_NonStatic_Long_Gap_Ratio", 0.0));
    }

    private Map<String, String> scoreOnce(String ipAddress, String requestId, Map<String, Double> features,
                                          double sessionDepth, double requestCount) {
        Map<String, String> result = new HashMap<>();
        boolean acquired = false;
        try {
            acquired = ML_BACKPRESSURE.tryAcquire(5, TimeUnit.MILLISECONDS);
            if (!acquired) {
                logger.warn("ML Backpressure kicked in. Semaphore full.");
                result.put("evaluationStatus", "SemaphoreFull");
                return result;
            }

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

            long sentNanos = System.nanoTime();
            java.util.concurrent.CompletableFuture<HttpResponse<String>> pending =
                    httpClient.sendAsync(mlRequest, HttpResponse.BodyHandlers.ofString());
            HttpResponse<String> mlResponse;
            try {
                mlResponse = pending.get(1000, TimeUnit.MILLISECONDS);
            } catch (java.util.concurrent.TimeoutException | InterruptedException e) {
                pending.cancel(true); // abort the exchange instead of leaving it queued at the inference service
                throw e;
            }
            long roundTripNanos = System.nanoTime() - sentNanos;
            result.put("mlRoundTripMs", Double.toString(roundTripNanos / 1_000_000.0));
            Timer.builder("sage_gateway_ml_roundtrip_seconds")
                    .description("Gateway-measured HTTP round trip to the inference service")
                    .publishPercentileHistogram()
                    .register(meterRegistry)
                    .record(roundTripNanos, TimeUnit.NANOSECONDS);

            if (mlResponse.statusCode() == 200) {
                JsonNode responseNode = objectMapper.readTree(mlResponse.body());
                result.put("evaluationStatus", "Scored");
                // Defect 3: model execution times as measured by the inference service.
                if (responseNode.hasNonNull("production_processing_time_ms")) result.put("prodInferenceLatencyMs", responseNode.get("production_processing_time_ms").asText());
                if (responseNode.hasNonNull("shadow_processing_time_ms")) result.put("shadowInferenceLatencyMs", responseNode.get("shadow_processing_time_ms").asText());
                result.put("isBot", Boolean.toString(responseNode.path("is_bot").asBoolean(false)));
                result.put("botProbability", Double.toString(responseNode.path("bot_probability").asDouble(0.0)));
                result.put("threatClass", responseNode.path("threat_class").asText("Benign"));
                result.put("shadowStatus", responseNode.path("shadow_status").asText("unavailable"));
                if (!responseNode.path("shadow_is_bot").isNull()) result.put("shadowIsBot", Boolean.toString(responseNode.path("shadow_is_bot").asBoolean()));
                if (!responseNode.path("shadow_bot_probability").isNull()) result.put("shadowBotProbability", Double.toString(responseNode.path("shadow_bot_probability").asDouble()));
                if (!responseNode.path("shadow_threat_class").isNull()) result.put("shadowThreatClass", responseNode.path("shadow_threat_class").asText());
                result.put("contractHash", responseNode.path("contract_hash").asText("unknown"));
                result.put("modelVersion", responseNode.path("model_version").asText("unknown"));
                result.put("scoringDepth", Double.toString(sessionDepth));
                result.put("scoringCount", Double.toString(requestCount));
                result.put("scoringTimestamp", Long.toString(System.currentTimeMillis()));
                if (!responseNode.path("prod_model_sha256").isNull()) result.put("prodModelSha256", responseNode.path("prod_model_sha256").asText());
                if (!responseNode.path("shadow_model_sha256").isNull()) result.put("shadowModelSha256", responseNode.path("shadow_model_sha256").asText());
                if (!responseNode.path("shadow_contract_hash").isNull()) result.put("shadowContractHash", responseNode.path("shadow_contract_hash").asText());
                if (!responseNode.path("shadow_feature_list_hash").isNull()) result.put("shadowFeatureListHash", responseNode.path("shadow_feature_list_hash").asText());

                redisTelemetryService.cacheMlDecision(ipAddress, result);

                if (!contractVerified) {
                    if (!expectedContractHash.equals(result.get("contractHash"))) {
                        logger.error("CRITICAL: SAGE Engine Contract Hash Mismatch! Expected {}, Got {}", expectedContractHash, result.get("contractHash"));
                    } else {
                        logger.info("SAGE Engine Contract Hash Verified: {}", result.get("contractHash"));
                        contractVerified = true;
                    }
                }

                logger.info("🎯 ML SCORED (Async/Sync) - IP: {} | Prob: {} | Bot: {} | Shadow Status: {}", 
                        ipAddress, result.get("botProbability"), result.get("isBot"), result.get("shadowStatus"));
                return result;
            } else {
                result.put("evaluationStatus", "Failed");
                return result;
            }
        } catch (java.util.concurrent.TimeoutException | InterruptedException e) {
            result.put("evaluationStatus", "Timeout");
            logger.error("SAGE ML Pipeline failed (Timeout).");
            return result;
        } catch (java.util.concurrent.ExecutionException e) {
            result.put("evaluationStatus", "Error");
            logger.error("SAGE ML Pipeline failed (Execution Error).", e);
            return result;
        } catch (Exception e) {
            result.put("evaluationStatus", "Error");
            logger.error("SAGE ML Inference execution error for IP {}", ipAddress, e);
            return result;
        } finally {
            if (acquired) {
                ML_BACKPRESSURE.release();
            }
        }
    }
}
