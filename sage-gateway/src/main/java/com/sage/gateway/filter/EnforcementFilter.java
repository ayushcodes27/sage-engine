package com.sage.gateway.filter;

import com.sage.gateway.event.RequestEvent;
import com.sage.gateway.service.KafkaProducerService;
import com.sage.gateway.service.RedisTelemetryService;
import io.micrometer.core.instrument.MeterRegistry;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.annotation.Order;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Component;

import java.time.Instant;
import java.util.Map;
import java.util.Optional;

@Component
@Order(5)
public class EnforcementFilter implements GatewayFilter {

    private static final Logger logger = LoggerFactory.getLogger(EnforcementFilter.class);
    
    private final RedisTelemetryService redisTelemetryService;
    private final KafkaProducerService kafkaProducer;
    private final MeterRegistry meterRegistry;

    @org.springframework.beans.factory.annotation.Value("${sage.enforcement.enabled:false}")
    private boolean enforcementEnabled;

    @org.springframework.beans.factory.annotation.Value("${sage.ml.shadow-threshold:0.35}")
    private double shadowThreshold;

    public EnforcementFilter(RedisTelemetryService redisTelemetryService, KafkaProducerService kafkaProducer, MeterRegistry meterRegistry) {
        this.redisTelemetryService = redisTelemetryService;
        this.kafkaProducer = kafkaProducer;
        this.meterRegistry = meterRegistry;
    }

    @Override
    public String getName() {
        return "Enforcement";
    }

    @Override
    public boolean isGlobal() {
        return true;
    }

    @Override
    public Optional<ResponseEntity<String>> filter(HttpServletRequest request, Map<String, String> config) {
        String evaluationStatus = (String) request.getAttribute("SAGE-EvaluationStatus");
        
        if (!"Scored".equals(evaluationStatus) && !"Cached".equals(evaluationStatus)) {
            return Optional.empty();
        }

        boolean isBot = (boolean) request.getAttribute("SAGE-IsBot");
        double botProbability = (double) request.getAttribute("SAGE-BotProbability");
        String ipAddress = (String) request.getAttribute("X-Client-Ip");
        String threatClass = (String) request.getAttribute("SAGE-ThreatClass");

        String enforcementAction = "Allowed";
        
        if (!enforcementEnabled) {
            enforcementAction = "Allowed";
        } else if (isBot && botProbability >= 0.80) {
            enforcementAction = "Blocked";
            redisTelemetryService.banIp(ipAddress);
            logger.warn("🚨 SAGE ENGINE BLOCKED BOT! IP: {} | Prob: {}", ipAddress, botProbability);
        } else if (botProbability >= 0.50 && botProbability < 0.80) {
            enforcementAction = "Challenged";
            request.setAttribute("X-Sage-Challenge", "required");
            logger.info("⚠️ SAGE ENGINE CHALLENGED! IP: {} | Prob: {}", ipAddress, botProbability);
        }

        request.setAttribute("SAGE-EnforcementAction", enforcementAction);
        
        // Compute shadow action
        Double shadowProb = (Double) request.getAttribute("SAGE-ShadowBotProbability");
        String shadowAction = "Allowed";
        if (shadowProb != null) {
            if (shadowProb >= 0.80) {
                shadowAction = "Blocked";
            } else if (shadowProb >= shadowThreshold) {
                shadowAction = "Challenged";
            }
        }
        request.setAttribute("SAGE-ShadowAction", shadowAction);
        
        String shadowStatus = (String) request.getAttribute("SAGE-ShadowStatus");
        logger.info("SHADOW MODE - Session ID: {}, Prob: {}, Threshold: {}, Model: ECLog_Weak, Action: {}", 
                request.getAttribute("X-Request-Id"), shadowProb, shadowThreshold, shadowAction);

        String sageProfile = request.getHeader("X-Sage-Profile") != null ? request.getHeader("X-Sage-Profile") : "unknown";
        meterRegistry.counter("sage_gateway_ml_enforcement_total", "action", enforcementAction, "profile", sageProfile).increment();

        if ("Blocked".equals(enforcementAction)) {
            publishThreatBlockedEvent(request, ipAddress, threatClass, botProbability);
            return Optional.of(buildErrorResponse(HttpStatus.FORBIDDEN, "Traffic blocked by SAGE Engine ML Anomaly Detection"));
        }

        return Optional.empty();
    }

    @Override
    @SuppressWarnings("unchecked")
    public void postProcess(HttpServletRequest request, ResponseEntity<String> response, long latencyMs, Exception ex) {
        String eventId = (String) request.getAttribute("X-Request-Id");
        if (eventId == null) return;
        
        Map<String, Double> features = (Map<String, Double>) request.getAttribute("SAGE-Features");
        if (features == null) return;
        
        String ipAddress = (String) request.getAttribute("X-Client-Ip");
        double botProbability = request.getAttribute("SAGE-BotProbability") != null ? (double) request.getAttribute("SAGE-BotProbability") : 0.0;
        boolean isBot = request.getAttribute("SAGE-IsBot") != null ? (boolean) request.getAttribute("SAGE-IsBot") : false;
        String threatClass = request.getAttribute("SAGE-ThreatClass") != null ? (String) request.getAttribute("SAGE-ThreatClass") : "Benign";
        String evaluationStatus = request.getAttribute("SAGE-EvaluationStatus") != null ? (String) request.getAttribute("SAGE-EvaluationStatus") : "Skipped";

        int statusCode = response != null ? response.getStatusCode().value() : (ex != null ? 500 : 200);
        String method = request.getMethod();
        String path = request.getRequestURI();
        long eventTimestamp = Instant.now().toEpochMilli();

        RequestEvent.RequestDetails requestDetails = new RequestEvent.RequestDetails(method, path, "api", ipAddress);
        RequestEvent.ResponseDetails responseDetails = new RequestEvent.ResponseDetails(statusCode, latencyMs);
        RequestEvent.FeatureVector featureVector = toFeatureVector(features);
        
        Double shadowBotProb = (Double) request.getAttribute("SAGE-ShadowBotProbability");
        Boolean shadowIsBot = (Boolean) request.getAttribute("SAGE-ShadowIsBot");
        String shadowThreat = (String) request.getAttribute("SAGE-ShadowThreatClass");
        String shadowAction = (String) request.getAttribute("SAGE-ShadowAction");
        String shadowStatus = (String) request.getAttribute("SAGE-ShadowStatus");
        Double prodLat = (Double) request.getAttribute("SAGE-ProdInferenceLatencyMs");
        Double shadLat = (Double) request.getAttribute("SAGE-ShadowInferenceLatencyMs");
        String contractHash = (String) request.getAttribute("SAGE-ContractHash");
        String modelVer = (String) request.getAttribute("SAGE-ModelVersion");
        
        Integer shadowIsBotInt = null;
        if (shadowIsBot != null) {
            shadowIsBotInt = shadowIsBot ? 1 : 0;
        }

        String decisionSource = (String) request.getAttribute("SAGE-DecisionSource");
        if (decisionSource == null) {
            decisionSource = "none";
        }
        Double scoringDepth = (Double) request.getAttribute("SAGE-ScoringDepth");
        Long scoringTimestampMs = (Long) request.getAttribute("SAGE-ScoringTimestampMs");
        String prodModelSha256 = (String) request.getAttribute("SAGE-ProdModelSha256");
        String shadowModelSha256 = (String) request.getAttribute("SAGE-ShadowModelSha256");
        String shadowContractHash = (String) request.getAttribute("SAGE-ShadowContractHash");
        String shadowFeatureListHash = (String) request.getAttribute("SAGE-ShadowFeatureListHash");

        RequestEvent.MLMetadata mlMetadata = new RequestEvent.MLMetadata(
                botProbability, isBot ? 1 : 0, threatClass, evaluationStatus,
                shadowBotProb, shadowIsBotInt, shadowThreat, shadowAction, shadowStatus,
                prodLat, shadLat, contractHash, modelVer, shadowThreshold,
                decisionSource, scoringDepth, scoringTimestampMs,
                prodModelSha256, shadowModelSha256, shadowContractHash, shadowFeatureListHash
        );

        String runId = (String) request.getAttribute("X-SAGE-Run-Id");
        String clientId = (String) request.getAttribute("X-SAGE-Client-Id");

        RequestEvent event = new RequestEvent(
                "1.1",
                "request.processed",
                eventId,
                eventTimestamp,
                "tenant_placeholder",
                clientId != null ? clientId : ipAddress,
                eventId,
                runId != null ? runId : "unknown",
                "unknown",
                requestDetails,
                responseDetails,
                featureVector,
                mlMetadata
        );

        kafkaProducer.publishEvent(event);
    }

    private void publishThreatBlockedEvent(HttpServletRequest request, String ipAddress, String threatClass, double botProbability) {
        String eventId = (String) request.getAttribute("X-Request-Id");
        String method = request.getMethod();
        String path = request.getRequestURI();
        long startTime = request.getAttribute("X-Start-Time") != null ? (long) request.getAttribute("X-Start-Time") : System.currentTimeMillis();
        long eventTimestamp = Instant.now().toEpochMilli();

        @SuppressWarnings("unchecked")
        Map<String, Double> features = (Map<String, Double>) request.getAttribute("SAGE-Features");

        RequestEvent.RequestDetails requestDetails = new RequestEvent.RequestDetails(method, path, "api", ipAddress);
        RequestEvent.ResponseDetails responseDetails = new RequestEvent.ResponseDetails(403, System.currentTimeMillis() - startTime);
        RequestEvent.FeatureVector featureVector = toFeatureVector(features);
        
        Double shadowBotProb = (Double) request.getAttribute("SAGE-ShadowBotProbability");
        Boolean shadowIsBot = (Boolean) request.getAttribute("SAGE-ShadowIsBot");
        String shadowThreat = (String) request.getAttribute("SAGE-ShadowThreatClass");
        String shadowAction = (String) request.getAttribute("SAGE-ShadowAction");
        String shadowStatus = (String) request.getAttribute("SAGE-ShadowStatus");
        Double prodLat = (Double) request.getAttribute("SAGE-ProdInferenceLatencyMs");
        Double shadLat = (Double) request.getAttribute("SAGE-ShadowInferenceLatencyMs");
        String contractHash = (String) request.getAttribute("SAGE-ContractHash");
        String modelVer = (String) request.getAttribute("SAGE-ModelVersion");
        String decisionSource = (String) request.getAttribute("SAGE-DecisionSource");
        if (decisionSource == null) {
            decisionSource = "fresh";
        }
        Double scoringDepth = (Double) request.getAttribute("SAGE-ScoringDepth");
        Long scoringTimestampMs = (Long) request.getAttribute("SAGE-ScoringTimestampMs");
        String prodModelSha256 = (String) request.getAttribute("SAGE-ProdModelSha256");
        String shadowModelSha256 = (String) request.getAttribute("SAGE-ShadowModelSha256");
        String shadowContractHash = (String) request.getAttribute("SAGE-ShadowContractHash");
        String shadowFeatureListHash = (String) request.getAttribute("SAGE-ShadowFeatureListHash");
        
        Integer shadowIsBotInt = null;
        if (shadowIsBot != null) {
            shadowIsBotInt = shadowIsBot ? 1 : 0;
        }

        RequestEvent.MLMetadata mlMetadata = new RequestEvent.MLMetadata(
                botProbability, 1, threatClass, "Scored",
                shadowBotProb, shadowIsBotInt, shadowThreat, shadowAction, shadowStatus,
                prodLat, shadLat, contractHash, modelVer, shadowThreshold,
                decisionSource, scoringDepth, scoringTimestampMs,
                prodModelSha256, shadowModelSha256, shadowContractHash, shadowFeatureListHash
        );

        String runId = (String) request.getAttribute("X-SAGE-Run-Id");
        String clientId = (String) request.getAttribute("X-SAGE-Client-Id");

        RequestEvent event = new RequestEvent(
                "1.1",
                "threat.blocked",
                eventId,
                eventTimestamp,
                "tenant_placeholder",
                clientId != null ? clientId : ipAddress,
                eventId,
                runId != null ? runId : "unknown",
                "bot", // Label as bot instead of IP-derived
                requestDetails,
                responseDetails,
                featureVector,
                mlMetadata
        );
        
        kafkaProducer.publishEvent(event);
    }

    private ResponseEntity<String> buildErrorResponse(HttpStatus status, String message) {
        return ResponseEntity.status(status)
                .header("Content-Type", "application/json")
                .body("{\"error\": \"" + status.getReasonPhrase() + "\", \"message\": \"" + message + "\"}");
    }

    private RequestEvent.FeatureVector toFeatureVector(Map<String, Double> features) {
        if (features == null) {
            return new RequestEvent.FeatureVector(0,0,0,0,0,0,1,0,0);
        }
        return new RequestEvent.FeatureVector(
                features.getOrDefault("SAGE_Session_Depth", 0.0),
                features.getOrDefault("SAGE_Temporal_Variance", 0.0),
                features.getOrDefault("SAGE_Request_Velocity", 0.0),
                features.getOrDefault("SAGE_Behavioral_Diversity", 0.0),
                features.getOrDefault("SAGE_Endpoint_Concentration", 0.0),
                features.getOrDefault("SAGE_Cart_Ratio", 0.0),
                features.getOrDefault("SAGE_Asset_Skip_Ratio", 1.0),
                features.getOrDefault("SAGE_NonStatic_Navigation_Gap", 0.0),
                features.getOrDefault("SAGE_NonStatic_Long_Gap_Ratio", 0.0)
        );
    }
}
