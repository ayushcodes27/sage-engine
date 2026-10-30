package com.sage.gateway.filter;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sage.gateway.service.RedisTelemetryService;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.Map;

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
        filter = new MLInferenceFilter(telemetryService, objectMapper, meterRegistry);
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
}

