package com.sage.gateway.event;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sage.gateway.service.RedisTelemetryService;
import org.junit.jupiter.api.Test;

import java.io.File;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.*;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class CrossLanguageParityTest {

    private final ObjectMapper objectMapper = new ObjectMapper();

    @Test
    void shouldMatchSharedGoldenFixtureParity() throws Exception {
        Path fixturePath = Paths.get("..", "ml_pipeline", "models", "fixtures", "feature_parity_golden.json").toAbsolutePath().normalize();
        if (!fixturePath.toFile().exists()) {
            fixturePath = Paths.get("ml_pipeline", "models", "fixtures", "feature_parity_golden.json").toAbsolutePath().normalize();
        }
        assertTrue(fixturePath.toFile().exists(), "Golden fixture must exist at " + fixturePath);

        JsonNode root = objectMapper.readTree(fixturePath.toFile());
        JsonNode cases = root.path("cases");
        assertTrue(cases.isArray() && cases.size() > 0, "Fixture cases must not be empty");

        for (JsonNode testCase : cases) {
            String caseId = testCase.path("case_id").asText();
            int evalAtRequest = testCase.path("eval_at_request").asInt();
            JsonNode requestsNode = testCase.path("requests");
            JsonNode expectedFeatures = testCase.path("expected_features");

            Map<String, Double> computed = computeFeaturesAsOfK(requestsNode, evalAtRequest);

            expectedFeatures.fields().forEachRemaining(entry -> {
                String featName = entry.getKey();
                double expectedVal = entry.getValue().asDouble();
                double actualVal = computed.getOrDefault(featName, 0.0);
                double diff = Math.abs(expectedVal - actualVal);
                assertEquals(expectedVal, actualVal, 1e-5,
                        "[" + caseId + "] Feature " + featName + " mismatch: expected " + expectedVal + ", got " + actualVal + " (diff " + diff + ")");
            });
        }
    }

    private Map<String, Double> computeFeaturesAsOfK(JsonNode requestsNode, int evalAtRequest) {
        Map<String, Double> features = new HashMap<>();
        if (requestsNode.size() == 0 || evalAtRequest <= 0) {
            features.put("SAGE_Session_Depth", 0.0);
            features.put("SAGE_Temporal_Variance", 0.0);
            features.put("SAGE_Request_Velocity", 0.0);
            features.put("SAGE_Behavioral_Diversity", 0.0);
            features.put("SAGE_Endpoint_Concentration", 0.0);
            features.put("SAGE_Cart_Ratio", 0.0);
            features.put("SAGE_Asset_Skip_Ratio", 1.0);
            features.put("SAGE_NonStatic_Navigation_Gap", 0.0);
            features.put("SAGE_NonStatic_Long_Gap_Ratio", 0.0);
            return features;
        }

        List<JsonNode> active = new ArrayList<>();
        for (int i = 0; i < evalAtRequest; i++) {
            active.add(requestsNode.get(i));
        }

        long latestTs = active.get(active.size() - 1).path("timestamp_ms").asLong();
        long cutoffTs = latestTs - 300_000L; // 5-minute inactivity horizon

        List<JsonNode> windowRequests = new ArrayList<>();
        for (JsonNode r : active) {
            if (r.path("timestamp_ms").asLong() >= cutoffTs) {
                windowRequests.add(r);
            }
        }

        double totalHits = windowRequests.size();
        double cartHits = 0.0;
        double staticHits = 0.0;

        List<String> rawPaths = new ArrayList<>();
        List<Double> nonStaticTimes = new ArrayList<>(); // LPUSH order: index 0 is most recent

        // Collect non-static requests in chronological order
        List<Double> chronologicalTimes = new ArrayList<>();
        List<String> chronologicalPaths = new ArrayList<>();

        for (JsonNode r : windowRequests) {
            String rawPath = r.has("raw_path") ? r.path("raw_path").asText() : r.path("path").asText();
            String canonical = RedisTelemetryService.canonicalizePath(rawPath);
            boolean isStatic = RedisTelemetryService.isStaticAsset(canonical);
            boolean isCart = RedisTelemetryService.isCartPath(canonical);

            if (isStatic) {
                staticHits += 1.0;
            }
            if (isCart) {
                cartHits += 1.0;
            }

            if (!isStatic) {
                chronologicalTimes.add(r.path("timestamp_ms").asDouble());
                chronologicalPaths.add(canonical);
            }
        }

        // Apply 50-item sliding window cap to non-static requests
        int nonStaticCount = chronologicalTimes.size();
        int startIndex = Math.max(0, nonStaticCount - 50);

        // Build LPUSH order (most recent first)
        for (int i = nonStaticCount - 1; i >= startIndex; i--) {
            nonStaticTimes.add(chronologicalTimes.get(i));
            rawPaths.add(chronologicalPaths.get(i));
        }

        double sessionDepth = nonStaticTimes.size();
        double requestVelocity = RedisTelemetryService.calculateVelocity(nonStaticTimes);
        double temporalVariance = RedisTelemetryService.calculateTemporalVariance(nonStaticTimes);
        double nonStaticNavigationGap = RedisTelemetryService.calculateNonStaticNavigationGap(nonStaticTimes);
        double nonStaticLongGapRatio = RedisTelemetryService.calculateNonStaticLongGapRatio(nonStaticTimes);
        double behavioralDiversity = RedisTelemetryService.calculateEntropy(rawPaths);
        double endpointConcentration = RedisTelemetryService.calculateEndpointConcentration(rawPaths);

        double cartRatio = totalHits > 0 ? cartHits / totalHits : 0.0;
        double assetSkipRatio = totalHits > 0 ? 1.0 - (staticHits / totalHits) : 1.0;

        features.put("SAGE_Session_Depth", sessionDepth);
        features.put("SAGE_Temporal_Variance", temporalVariance);
        features.put("SAGE_Request_Velocity", requestVelocity);
        features.put("SAGE_Behavioral_Diversity", behavioralDiversity);
        features.put("SAGE_Endpoint_Concentration", endpointConcentration);
        features.put("SAGE_Cart_Ratio", cartRatio);
        features.put("SAGE_Asset_Skip_Ratio", assetSkipRatio);
        features.put("SAGE_NonStatic_Navigation_Gap", nonStaticNavigationGap);
        features.put("SAGE_NonStatic_Long_Gap_Ratio", nonStaticLongGapRatio);

        return features;
    }
}
