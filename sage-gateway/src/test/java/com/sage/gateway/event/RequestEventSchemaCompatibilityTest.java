package com.sage.gateway.event;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

class RequestEventSchemaCompatibilityTest {

    private final ObjectMapper objectMapper = new ObjectMapper();

    @Test
    void shouldSupportBackwardsCompatibleSevenFeatureConstructor() throws Exception {
        RequestEvent.FeatureVector fv7 = new RequestEvent.FeatureVector(10.0, 0.5, 2.0, 1.2, 0.4, 0.1, 0.8);
        assertEquals(10.0, fv7.sessionDepth());
        assertEquals(0.8, fv7.assetSkipRatio());
        assertEquals(0.0, fv7.nonStaticNavigationGap());
        assertEquals(0.0, fv7.nonStaticLongGapRatio());

        String json = objectMapper.writeValueAsString(fv7);
        assertTrue(json.contains("\"sessionDepth\":10.0"));
        assertTrue(json.contains("\"nonStaticNavigationGap\":0.0"));
        assertTrue(json.contains("\"nonStaticLongGapRatio\":0.0"));

        RequestEvent.FeatureVector deserialized = objectMapper.readValue(json, RequestEvent.FeatureVector.class);
        assertEquals(fv7.sessionDepth(), deserialized.sessionDepth());
    }

    @Test
    void shouldSupportNineFeatureConstructor() throws Exception {
        RequestEvent.FeatureVector fv9 = new RequestEvent.FeatureVector(25.0, 0.8, 3.5, 2.1, 0.6, 0.2, 0.9, 0.75, 0.65);
        assertEquals(25.0, fv9.sessionDepth());
        assertEquals(0.75, fv9.nonStaticNavigationGap());
        assertEquals(0.65, fv9.nonStaticLongGapRatio());

        String json = objectMapper.writeValueAsString(fv9);
        RequestEvent.FeatureVector deserialized = objectMapper.readValue(json, RequestEvent.FeatureVector.class);
        assertEquals(0.75, deserialized.nonStaticNavigationGap(), 1e-6);
        assertEquals(0.65, deserialized.nonStaticLongGapRatio(), 1e-6);
    }

    @Test
    void shouldSupportMLMetadataWithDecisionSourceAndScoringDetails() throws Exception {
        RequestEvent.MLMetadata ml = new RequestEvent.MLMetadata(
                0.85, 1, "Bot", "Scored",
                0.90, 1, "Bot", "Challenged", "ok",
                12.5, 15.0, "abc123hash", "timing-v1", 0.35,
                "fresh", 22.0, 1726700000000L
        );

        assertEquals("fresh", ml.decisionSource());
        assertEquals(22.0, ml.scoringDepth());
        assertEquals(1726700000000L, ml.scoringTimestampMs());

        String json = objectMapper.writeValueAsString(ml);
        assertTrue(json.contains("\"decisionSource\":\"fresh\""));
        assertTrue(json.contains("\"scoringDepth\":22.0"));
        assertTrue(json.contains("\"scoringTimestampMs\":1726700000000"));

        RequestEvent.MLMetadata deserialized = objectMapper.readValue(json, RequestEvent.MLMetadata.class);
        assertEquals(ml.decisionSource(), deserialized.decisionSource());
        assertEquals(ml.scoringDepth(), deserialized.scoringDepth());
        assertEquals(ml.scoringTimestampMs(), deserialized.scoringTimestampMs());
    }

    @Test
    void shouldSupportMLMetadataWithFullCryptographicIdentity() throws Exception {
        RequestEvent.MLMetadata ml = new RequestEvent.MLMetadata(
                0.85, 1, "Bot", "Scored",
                0.90, 1, "Bot", "Challenged", "ok",
                12.5, 15.0, "contract-hash-123", "timing-v1", 0.35,
                "fresh", 22.0, 1726700000000L,
                "prod-model-sha-256", "shadow-model-sha-256",
                "shadow-contract-hash-456", "shadow-feat-hash-789"
        );

        assertEquals("prod-model-sha-256", ml.prodModelSha256());
        assertEquals("shadow-model-sha-256", ml.shadowModelSha256());
        assertEquals("shadow-contract-hash-456", ml.shadowContractHash());
        assertEquals("shadow-feat-hash-789", ml.shadowFeatureListHash());

        String json = objectMapper.writeValueAsString(ml);
        assertTrue(json.contains("\"prodModelSha256\":\"prod-model-sha-256\""));
        assertTrue(json.contains("\"shadowModelSha256\":\"shadow-model-sha-256\""));
        assertTrue(json.contains("\"shadowContractHash\":\"shadow-contract-hash-456\""));
        assertTrue(json.contains("\"shadowFeatureListHash\":\"shadow-feat-hash-789\""));

        RequestEvent.MLMetadata deserialized = objectMapper.readValue(json, RequestEvent.MLMetadata.class);
        assertEquals(ml.prodModelSha256(), deserialized.prodModelSha256());
        assertEquals(ml.shadowModelSha256(), deserialized.shadowModelSha256());
        assertEquals(ml.shadowContractHash(), deserialized.shadowContractHash());
        assertEquals(ml.shadowFeatureListHash(), deserialized.shadowFeatureListHash());
    }

    @Test
    void shouldDeserializeLegacyMLMetadataWithNullIdentityFields() throws Exception {
        String legacyJson = """
            {
              "botProbability": 0.12,
              "isBotFlag": 0,
              "threatClass": "Benign",
              "evaluationStatus": "Scored",
              "shadowBotProbability": 0.05,
              "shadowIsBotFlag": 0,
              "shadowThreatClass": "Benign",
              "shadowAction": "Allowed",
              "shadowStatus": "ok",
              "prodInferenceLatencyMs": 10.0,
              "shadowInferenceLatencyMs": 12.0,
              "contractHash": "old-contract-hash",
              "modelVersion": "sage-binary-v1",
              "shadowThreshold": 0.35,
              "decisionSource": "fresh",
              "scoringDepth": 21.0,
              "scoringTimestampMs": 1726700000000
            }
            """;

        RequestEvent.MLMetadata deserialized = objectMapper.readValue(legacyJson, RequestEvent.MLMetadata.class);
        assertEquals(0.12, deserialized.botProbability());
        assertEquals("old-contract-hash", deserialized.contractHash());
        org.junit.jupiter.api.Assertions.assertNull(deserialized.prodModelSha256());
        org.junit.jupiter.api.Assertions.assertNull(deserialized.shadowModelSha256());
        org.junit.jupiter.api.Assertions.assertNull(deserialized.shadowContractHash());
        org.junit.jupiter.api.Assertions.assertNull(deserialized.shadowFeatureListHash());
    }

    @Test
    void shouldParsePythonInferenceResultPayload() throws Exception {
        String pythonResponseJson = """
            {
              "session_id": "test-sess-1",
              "is_bot": false,
              "bot_probability": 0.005,
              "threat_class": "Benign",
              "confidence": 0.995,
              "production_processing_time_ms": 5.2,
              "shadow_status": "ok",
              "shadow_is_bot": false,
              "shadow_bot_probability": 0.002,
              "shadow_threat_class": "Benign",
              "shadow_processing_time_ms": 2.1,
              "contract_hash": "075677d319331d2172c900f7fb3ce9d4b2dd3e26a2dd6854fd2d1de53bf3262a",
              "model_version": "sage_binary_v1",
              "shadow_threshold": 0.35,
              "prod_model_sha256": "a979d5c2f6d463851fbc02c6a5a4892a05bb34bc644e977e42712bba4c9bf70f",
              "shadow_model_sha256": "7b29ee3b574ce43cf9984408ff2d19096a6205c6389deff907cebf67e8e7f193",
              "shadow_contract_hash": "2fb47afb4dae24d3345aa0d1f270e622477da729e9f9c64a7cc001edc1260dfc",
              "shadow_feature_list_hash": "72081fb42d97e0d7f1c245d4bb95c654518235c53ea5521c7277b625e0b8da4f"
            }
            """;

        com.fasterxml.jackson.databind.JsonNode root = objectMapper.readTree(pythonResponseJson);
        assertEquals("test-sess-1", root.path("session_id").asText());
        assertEquals(0.005, root.path("bot_probability").asDouble());
        assertEquals("ok", root.path("shadow_status").asText());
        assertEquals("a979d5c2f6d463851fbc02c6a5a4892a05bb34bc644e977e42712bba4c9bf70f", root.path("prod_model_sha256").asText());
        assertEquals("7b29ee3b574ce43cf9984408ff2d19096a6205c6389deff907cebf67e8e7f193", root.path("shadow_model_sha256").asText());
        assertEquals("2fb47afb4dae24d3345aa0d1f270e622477da729e9f9c64a7cc001edc1260dfc", root.path("shadow_contract_hash").asText());
        assertEquals("72081fb42d97e0d7f1c245d4bb95c654518235c53ea5521c7277b625e0b8da4f", root.path("shadow_feature_list_hash").asText());
    }

    @Test
    void shouldSupportFullRequestEventSerialization() throws Exception {
        RequestEvent.RequestDetails req = new RequestEvent.RequestDetails("GET", "/products/1", "api", "127.0.0.1");
        RequestEvent.ResponseDetails res = new RequestEvent.ResponseDetails(200, 45L);
        RequestEvent.FeatureVector fv = new RequestEvent.FeatureVector(21.0, 0.4, 2.0, 1.5, 0.5, 0.0, 1.0, 0.85, 0.70);
        RequestEvent.MLMetadata ml = new RequestEvent.MLMetadata(
                0.20, 0, "Benign", "Scored",
                0.15, 0, "Benign", "Allowed", "ok",
                8.0, 9.0, "hash", "timing-v1", 0.35,
                "fresh", 21.0, 1726700000000L,
                "prod-sha", "shadow-sha", "shadow-c-hash", "shadow-f-hash"
        );

        RequestEvent event = new RequestEvent(
                "1.1", "request.processed", "evt-123", System.currentTimeMillis(),
                "tenant", "user-1", "evt-123", "run-101", "normal_browser",
                req, res, fv, ml
        );

        String json = objectMapper.writeValueAsString(event);
        assertNotNull(json);
        assertTrue(json.contains("\"nonStaticNavigationGap\":0.85"));
        assertTrue(json.contains("\"decisionSource\":\"fresh\""));
        assertTrue(json.contains("\"prodModelSha256\":\"prod-sha\""));
        assertTrue(json.contains("\"shadowModelSha256\":\"shadow-sha\""));
    }
}
