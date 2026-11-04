package com.sage.gateway.filter;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sage.gateway.service.KafkaProducerService;
import com.sage.gateway.service.RedisTelemetryService;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.test.util.ReflectionTestUtils;

import com.sun.net.httpserver.HttpServer;

import java.net.InetSocketAddress;
import java.time.Duration;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class MLInferenceFilterTest {

    private RedisTelemetryService telemetryService;
    private MLInferenceFilter filter;

    @BeforeEach
    void setUp() {
        telemetryService = mock(RedisTelemetryService.class);
        ObjectMapper objectMapper = new ObjectMapper();
        SimpleMeterRegistry meterRegistry = new SimpleMeterRegistry();
        filter = new MLInferenceFilter(telemetryService, objectMapper, meterRegistry, mock(KafkaProducerService.class));
        ReflectionTestUtils.setField(filter, "expectedContractHash", "dummy-contract-hash");
        ReflectionTestUtils.setField(filter, "probeSecret", "super-secret-probe-key");
        ReflectionTestUtils.setField(filter, "rescoreFrequency", 20);
    }

    @Test
    @DisplayName("Item 2: X-SAGE-Probe should be ignored if probe secret is invalid or missing")
    void shouldRejectUnauthorizedProbe() {
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.setAttribute("X-Client-Ip", "192.0.2.1");
        request.setAttribute("X-Request-Id", "req-1");
        request.setRequestURI("/products");
        request.addHeader("X-SAGE-Probe", "true");
        // No X-SAGE-Probe-Secret header

        when(telemetryService.processAndGetTelemetry(anyString(), anyDouble(), anyString()))
                .thenReturn(Map.of("SAGE_Session_Depth", 10.0, "SAGE_Session_Duration", 1.0));
        when(telemetryService.getCachedMlDecision(anyString())).thenReturn(Map.of());

        filter.filter(request, Map.of());

        String status = (String) request.getAttribute("SAGE-EvaluationStatus");
        assertEquals("GateDepthNotMet", status, "Unauthorized probe must not bypass scoring gate");
    }

    @Test
    @DisplayName("Item 3: First-time scoring should dispatch async and return AsyncScheduled without blocking")
    void shouldScheduleAsyncScoringWhenGatePassed() {
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.setAttribute("X-Client-Ip", "192.0.2.2");
        request.setAttribute("X-Request-Id", "req-2");
        request.setRequestURI("/products");

        // Client has crossed depth 21 and duration 5s
        when(telemetryService.processAndGetTelemetry(anyString(), anyDouble(), anyString()))
                .thenReturn(Map.of("SAGE_Session_Depth", 21.0, "SAGE_Session_Duration", 5.0));
        when(telemetryService.getCachedMlDecision("192.0.2.2")).thenReturn(Map.of());
        when(telemetryService.acquireScoringLock("192.0.2.2")).thenReturn(true);

        filter.filter(request, Map.of());

        String status = (String) request.getAttribute("SAGE-EvaluationStatus");
        String source = (String) request.getAttribute("SAGE-DecisionSource");

        assertEquals("AsyncScheduled", status, "Request must not block; should be AsyncScheduled");
        assertEquals("async_pending", source);
        verify(telemetryService).acquireScoringLock("192.0.2.2");
    }

    @Test
    @DisplayName("Item 2: Re-scoring should trigger when depth increases by rescoreFrequency (20)")
    void shouldTriggerRescoringAfter20Requests() {
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.setAttribute("X-Client-Ip", "192.0.2.3");
        request.setAttribute("X-Request-Id", "req-3");
        request.setRequestURI("/products");

        // Client previously scored at depth 21, now at depth 42 (delta = 21 >= 20)
        Map<String, String> cached = Map.of(
                "isBot", "false",
                "botProbability", "0.05",
                "threatClass", "Benign",
                "scoringDepth", "21.0"
        );
        when(telemetryService.getCachedMlDecision("192.0.2.3")).thenReturn(cached);
        when(telemetryService.processAndGetTelemetry(anyString(), anyDouble(), anyString()))
                .thenReturn(Map.of("SAGE_Session_Depth", 42.0, "SAGE_Session_Duration", 15.0));
        when(telemetryService.acquireScoringLock("192.0.2.3")).thenReturn(true);

        filter.filter(request, Map.of());

        // Uses cached decision for current request without blocking
        String status = (String) request.getAttribute("SAGE-EvaluationStatus");
        assertEquals("Cached", status);
        // And triggers async re-score
        verify(telemetryService).acquireScoringLock("192.0.2.3");
    }

    @Test
    @DisplayName("Defect 2: re-scoring continues past k=41 although session depth (f0) is capped at 50")
    void shouldRescoreOnUncappedCountWhenDepthIsCapped() {
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.setAttribute("X-Client-Ip", "192.0.2.4");
        request.setAttribute("X-Request-Id", "req-4");
        request.setRequestURI("/products");

        // Last score at non-static request 41; f0 is now capped at 50 while 61 non-static requests were seen.
        when(telemetryService.getCachedMlDecision("192.0.2.4")).thenReturn(Map.of(
                "isBot", "false", "botProbability", "0.05", "scoringDepth", "41.0", "scoringCount", "41.0"));
        when(telemetryService.processAndGetTelemetry(anyString(), anyDouble(), anyString()))
                .thenReturn(Map.of("SAGE_Session_Depth", 50.0, "SAGE_Session_Duration", 30.0,
                        RedisTelemetryService.NON_STATIC_REQUEST_COUNT, 61.0));
        when(telemetryService.acquireScoringLock("192.0.2.4")).thenReturn(true);

        filter.filter(request, Map.of());

        verify(telemetryService).acquireScoringLock("192.0.2.4");
    }

    @Test
    @DisplayName("Re-scoring is not scheduled before rescoreFrequency new non-static requests")
    void shouldNotRescoreBeforeFrequencyReached() {
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.setAttribute("X-Client-Ip", "192.0.2.5");
        request.setAttribute("X-Request-Id", "req-5");
        request.setRequestURI("/products");

        when(telemetryService.getCachedMlDecision("192.0.2.5")).thenReturn(Map.of(
                "isBot", "false", "botProbability", "0.05", "scoringDepth", "50.0", "scoringCount", "61.0"));
        when(telemetryService.processAndGetTelemetry(anyString(), anyDouble(), anyString()))
                .thenReturn(Map.of("SAGE_Session_Depth", 50.0, "SAGE_Session_Duration", 30.0,
                        RedisTelemetryService.NON_STATIC_REQUEST_COUNT, 80.0));

        filter.filter(request, Map.of());

        verify(telemetryService, never()).acquireScoringLock("192.0.2.5");
        assertEquals("Cached", request.getAttribute("SAGE-EvaluationStatus"));
    }

    @Test
    @DisplayName("B2: mode=off is a pure proxy (no Redis, no features, no scoring)")
    void offModeSkipsEverything() {
        ReflectionTestUtils.setField(filter, "mlMode", "off");
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.setAttribute("X-Client-Ip", "192.0.2.6");
        request.setRequestURI("/products");

        filter.filter(request, Map.of());

        verifyNoInteractions(telemetryService);
        assertNull(request.getAttribute("SAGE-Features"));
    }

    @Test
    @DisplayName("B2: mode=features computes features but never schedules scoring")
    void featuresModeNeverScores() {
        ReflectionTestUtils.setField(filter, "mlMode", "features");
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.setAttribute("X-Client-Ip", "192.0.2.7");
        request.setRequestURI("/products");
        when(telemetryService.processAndGetTelemetry(anyString(), anyDouble(), anyString()))
                .thenReturn(Map.of("SAGE_Session_Depth", 30.0, "SAGE_Session_Duration", 10.0));
        when(telemetryService.getCachedMlDecision("192.0.2.7")).thenReturn(Map.of());

        filter.filter(request, Map.of());

        verify(telemetryService, never()).acquireScoringLock(anyString());
        assertEquals("ScoringDisabled", request.getAttribute("SAGE-EvaluationStatus"));
        assertNotNull(request.getAttribute("SAGE-Features"));
    }

    /** Inference stub that answers only after delayMs; counts requests it receives. */
    private static HttpServer slowInferenceStub(int delayMs, AtomicInteger hits) throws Exception {
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.setExecutor(java.util.concurrent.Executors.newCachedThreadPool());
        server.createContext("/predict", exchange -> {
            hits.incrementAndGet();
            try {
                Thread.sleep(delayMs);
                exchange.sendResponseHeaders(500, -1);
            } catch (Exception ignored) {
            } finally {
                exchange.close();
            }
        });
        server.start();
        return server;
    }

    private MockHttpServletRequest gatedRequest(String ip) {
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.setAttribute("X-Client-Ip", ip);
        request.setAttribute("X-Request-Id", "req-" + ip);
        request.setRequestURI("/products");
        when(telemetryService.processAndGetTelemetry(anyString(), anyDouble(), anyString()))
                .thenReturn(Map.of("SAGE_Session_Depth", 25.0, "SAGE_Session_Duration", 10.0));
        when(telemetryService.getCachedMlDecision(ip)).thenReturn(Map.of());
        return request;
    }

    @Test
    @DisplayName("Overload: a timed-out score starts the per-client failure cooldown")
    void timeoutStartsCooldown() throws Exception {
        AtomicInteger hits = new AtomicInteger();
        HttpServer stub = slowInferenceStub(1500, hits);
        try {
            ReflectionTestUtils.setField(filter, "mlMode", "sync");
            ReflectionTestUtils.setField(filter, "PYTHON_ML_URL", "http://127.0.0.1:" + stub.getAddress().getPort() + "/predict");
            MockHttpServletRequest request = gatedRequest("192.0.2.8");

            filter.filter(request, Map.of());

            assertEquals("Timeout", request.getAttribute("SAGE-EvaluationStatus"));
            verify(telemetryService).startScoringCooldown("192.0.2.8", Duration.ofMillis(5000));
        } finally {
            stub.stop(0);
        }
    }

    @Test
    @DisplayName("Overload: a client in cooldown is not re-scored (sync makes no ML call, async takes no lock)")
    void cooldownSuppressesRetries() throws Exception {
        AtomicInteger hits = new AtomicInteger();
        HttpServer stub = slowInferenceStub(0, hits);
        try {
            ReflectionTestUtils.setField(filter, "PYTHON_ML_URL", "http://127.0.0.1:" + stub.getAddress().getPort() + "/predict");
            when(telemetryService.inScoringCooldown("192.0.2.9")).thenReturn(true);

            ReflectionTestUtils.setField(filter, "mlMode", "sync");
            MockHttpServletRequest syncRequest = gatedRequest("192.0.2.9");
            filter.filter(syncRequest, Map.of());
            assertEquals("ScoringCooldown", syncRequest.getAttribute("SAGE-EvaluationStatus"));
            assertEquals(0, hits.get(), "no ML call during cooldown");

            ReflectionTestUtils.setField(filter, "mlMode", "async");
            MockHttpServletRequest asyncRequest = gatedRequest("192.0.2.9");
            filter.filter(asyncRequest, Map.of());
            assertEquals("ScoringCooldown", asyncRequest.getAttribute("SAGE-EvaluationStatus"));
            verify(telemetryService, never()).acquireScoringLock(anyString());
        } finally {
            stub.stop(0);
        }
    }

    @Test
    @DisplayName("Overload: an authorised probe is scored even during cooldown")
    void probeOverridesCooldown() {
        MockHttpServletRequest request = gatedRequest("192.0.2.10");
        request.addHeader("X-SAGE-Probe", "true");
        request.addHeader("X-SAGE-Probe-Secret", "super-secret-probe-key");
        when(telemetryService.inScoringCooldown("192.0.2.10")).thenReturn(true);
        when(telemetryService.acquireScoringLock("192.0.2.10")).thenReturn(false);

        filter.filter(request, Map.of());

        verify(telemetryService, never()).inScoringCooldown(anyString());
        verify(telemetryService).acquireScoringLock("192.0.2.10");
    }
}
