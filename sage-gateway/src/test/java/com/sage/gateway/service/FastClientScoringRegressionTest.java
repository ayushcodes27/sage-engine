package com.sage.gateway.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.HashOperations;
import org.springframework.data.redis.core.ListOperations;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;

import java.time.Duration;
import java.util.*;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/**
 * Regression Test for Reviewer Item 1:
 * Verifies that a fast client sending at 30 req/s for 10 s is NOT trapped by the 50-entry sliding list
 * window-span truncation, but correctly computes session duration from the sage:first_seen key.
 */
class FastClientScoringRegressionTest {

    @Test
    @DisplayName("Fast client at 30 req/s for 10s should compute valid session duration >= 3.0s via first_seen key")
    void fastClientWindowSpanRegressionTest() {
        StringRedisTemplate redisTemplate = mock(StringRedisTemplate.class);
        ValueOperations<String, String> valueOps = mock(ValueOperations.class);
        ListOperations<String, String> listOps = mock(ListOperations.class);
        HashOperations<String, Object, Object> hashOps = mock(HashOperations.class);

        when(redisTemplate.opsForValue()).thenReturn(valueOps);
        when(redisTemplate.opsForList()).thenReturn(listOps);
        when(redisTemplate.opsForHash()).thenReturn(hashOps);

        String ip = "198.51.100.42";
        String firstSeenKey = "sage:first_seen:" + ip;
        String timeKey = "sage:timestamps:" + ip;
        String pathKey = "sage:paths:" + ip;

        // Simulate client started 10.0 seconds ago (10000 ms ago)
        long startTime = System.currentTimeMillis() - 10_000L;
        when(valueOps.get(firstSeenKey)).thenReturn(String.valueOf(startTime));

        // In the 50-item trimmed list at 30 req/s, the last 50 requests span only ~1.63 seconds
        List<String> rawTimes = new ArrayList<>();
        long now = System.currentTimeMillis();
        for (int i = 0; i < 50; i++) {
            // each request 33.3 ms apart
            rawTimes.add(String.valueOf(now - (i * 33L)));
        }
        when(listOps.range(eq(timeKey), eq(0L), eq(-1L))).thenReturn(rawTimes);

        List<String> rawPaths = new ArrayList<>();
        for (int i = 0; i < 50; i++) {
            rawPaths.add("/api/products/" + (i % 5));
        }
        when(listOps.range(eq(pathKey), eq(0L), eq(-1L))).thenReturn(rawPaths);

        RedisTelemetryService service = new RedisTelemetryService(redisTemplate);
        Map<String, Double> features = service.processAndGetTelemetry(ip, 120.0, "/api/products/1");

        // Verify first-seen key was registered with setIfAbsent
        verify(valueOps).setIfAbsent(eq(firstSeenKey), anyString(), eq(Duration.ofMinutes(5)));

        double sessionDepth = features.get("SAGE_Session_Depth");
        double sessionDuration = features.get("SAGE_Session_Duration");

        assertEquals(50.0, sessionDepth, "Sliding window depth should be capped at 50");
        assertTrue(sessionDuration >= 9.5 && sessionDuration <= 10.5,
                "Session duration must reflect full 10s via first_seen key, but was: " + sessionDuration);
        
        // Assert client meets the scoring gate criteria (depth > 20 && duration >= 3.0s)
        assertTrue(sessionDepth > 20.0, "Session depth must pass gate threshold > 20");
        assertTrue(sessionDuration >= 3.0, "Session duration must pass gate threshold >= 3.0s");
    }
}

