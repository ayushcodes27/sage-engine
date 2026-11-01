package com.sage.gateway.filter;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sage.gateway.event.RequestEvent;
import com.sage.gateway.service.KafkaProducerService;
import com.sage.gateway.service.RedisTelemetryService;
import com.sun.net.httpserver.HttpServer;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.test.util.ReflectionTestUtils;

import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/**
 * Defect 3 / N8: score results must reach telemetry with model timings, including scores that a
 * client's last request triggers asynchronously, and the synchronous probe must log the shadow decision.
 */
class ScoreTelemetryTest {

    private static final String ML_RESPONSE = "{\"session_id\":\"s\",\"is_bot\":false,\"bot_probability\":0.12,"
            + "\"threat_class\":\"Benign\",\"confidence\":0.88,\"production_processing_time_ms\":1.25,"
            + "\"shadow_status\":\"ok\",\"shadow_is_bot\":true,\"shadow_bot_probability\":0.61,"
            + "\"shadow_threat_class\":\"Bot\",\"shadow_processing_time_ms\":2.5,\"contract_hash\":\"ch\","
            + "\"model_version\":\"v1\",\"shadow_threshold\":0.35,\"prod_model_sha256\":\"p\","
            + "\"shadow_model_sha256\":\"s\",\"shadow_contract_hash\":\"sc\",\"shadow_feature_list_hash\":\"sf\"}";

    private HttpServer server;
    private int responseStatus = 200;
    private RedisTelemetryService telemetry;
    private KafkaProducerService kafka;
    private MLInferenceFilter filter;
    private Map<String, Double> features;

    @BeforeEach
    void setUp() throws Exception {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/predict", exchange -> {
            byte[] body = ML_RESPONSE.getBytes(StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(responseStatus, body.length);
            try (OutputStream os = exchange.getResponseBody()) {
                os.write(body);
            }
        });
        server.start();

        telemetry = mock(RedisTelemetryService.class);
        kafka = mock(KafkaProducerService.class);
        filter = new MLInferenceFilter(telemetry, new ObjectMapper(), new SimpleMeterRegistry(), kafka);
        ReflectionTestUtils.setField(filter, "PYTHON_ML_URL", "http://127.0.0.1:" + server.getAddress().getPort() + "/predict");
        ReflectionTestUtils.setField(filter, "expectedContractHash", "ch");
        ReflectionTestUtils.setField(filter, "probeSecret", "secret");
        ReflectionTestUtils.setField(filter, "rescoreFrequency", 20);

        features = new HashMap<>();
        features.put("SAGE_Session_Depth", 21.0);
        features.put("SAGE_Session_Duration", 9.0);
        features.put("SAGE_Request_Velocity", 2.25);
        features.put("SAGE_NonStatic_Navigation_Gap", 0.44);
        features.put(RedisTelemetryService.NON_STATIC_REQUEST_COUNT, 21.0);
        when(telemetry.processAndGetTelemetry(anyString(), anyDouble(), anyString())).thenReturn(features);
        when(telemetry.getCachedMlDecision(anyString())).thenReturn(Map.of());
        when(telemetry.acquireScoringLock(anyString())).thenReturn(true);
    }

    @AfterEach
    void tearDown() {
        server.stop(0);
    }

    private MockHttpServletRequest request(boolean syncProbe) {
        MockHttpServletRequest r = new MockHttpServletRequest();
        r.setAttribute("X-Client-Ip", "198.51.100.7");
        r.setAttribute("X-Request-Id", "req-last");
        r.setAttribute("X-SAGE-Client-Id", "fast_scraper-07");
        r.setAttribute("X-SAGE-Run-Id", "diverse-test");
        r.setRequestURI("/api/price/9");
        if (syncProbe) {
            r.addHeader("X-SAGE-Probe", "true");
            r.addHeader("X-SAGE-Probe-Secret", "secret");
            r.addHeader("X-SAGE-Sync-Score", "true");
        }
        return r;
    }

    private RequestEvent awaitScoreEvent() {
        ArgumentCaptor<RequestEvent> captor = ArgumentCaptor.forClass(RequestEvent.class);
        verify(kafka, timeout(3000)).publishEvent(captor.capture());
        return captor.getValue();
    }

    @Test
    @DisplayName("Async score triggered by a client's last request is published with latencies and the scored vector")
    void asyncScoreIsPublishedWithoutAFollowUpRequest() {
        MockHttpServletRequest r = request(false);
        filter.filter(r, Map.of());
        assertEquals("AsyncScheduled", r.getAttribute("SAGE-EvaluationStatus"));

        RequestEvent e = awaitScoreEvent();
        assertEquals("score.completed", e.eventType());
        assertEquals("fast_scraper-07", e.userId());
        assertEquals("diverse-test", e.runId());
        assertEquals("req-last", e.sessionId());
        assertEquals("async", e.mlMetadata().decisionSource());
        assertEquals(1.25, e.mlMetadata().prodInferenceLatencyMs());
        assertEquals(2.5, e.mlMetadata().shadowInferenceLatencyMs());
        assertEquals(1, e.mlMetadata().shadowIsBotFlag());
        assertEquals("s", e.mlMetadata().shadowModelSha256());
        assertEquals(21.0, e.features().sessionDepth());
        assertEquals(2.25, e.features().requestVelocity());
        assertEquals(0.44, e.features().nonStaticNavigationGap());
        verify(telemetry, timeout(3000)).releaseScoringLock("198.51.100.7");
    }

    @Test
    @DisplayName("N8: synchronous probe score carries shadow decision, identity and model timings")
    void syncProbeCarriesShadowFields() {
        MockHttpServletRequest r = request(true);
        filter.filter(r, Map.of());

        assertEquals("Scored", r.getAttribute("SAGE-EvaluationStatus"));
        assertEquals("fresh_sync", r.getAttribute("SAGE-DecisionSource"));
        assertEquals(Boolean.TRUE, r.getAttribute("SAGE-ShadowIsBot"));
        assertEquals(0.61, r.getAttribute("SAGE-ShadowBotProbability"));
        assertEquals("s", r.getAttribute("SAGE-ShadowModelSha256"));
        assertEquals("sf", r.getAttribute("SAGE-ShadowFeatureListHash"));
        assertEquals(1.25, r.getAttribute("SAGE-ProdInferenceLatencyMs"));
        assertEquals(2.5, r.getAttribute("SAGE-ShadowInferenceLatencyMs"));
        assertEquals("fresh_sync", awaitScoreEvent().mlMetadata().decisionSource());
    }

    @Test
    @DisplayName("Async scoring failure is published as score.failed so failure gates can see it")
    void asyncFailureIsPublished() {
        responseStatus = 500;
        filter.filter(request(false), Map.of());

        RequestEvent e = awaitScoreEvent();
        assertEquals("score.failed", e.eventType());
        assertEquals("Failed", e.mlMetadata().evaluationStatus());
        assertNull(e.mlMetadata().shadowBotProbability());
    }
}
