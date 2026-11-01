package com.sage.gateway.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.HashOperations;
import org.springframework.data.redis.core.ListOperations;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.*;

/** Defect 2: the re-scoring counter must keep counting after f0 hits the 50-entry cap. */
class RescoreCounterTest {

    @SuppressWarnings("unchecked")
    private RedisTelemetryService serviceWith(long counterValue, String counterStored, int windowEntries) {
        StringRedisTemplate redis = mock(StringRedisTemplate.class);
        ValueOperations<String, String> valueOps = mock(ValueOperations.class);
        ListOperations<String, String> listOps = mock(ListOperations.class);
        HashOperations<String, Object, Object> hashOps = mock(HashOperations.class);
        when(redis.opsForValue()).thenReturn(valueOps);
        when(redis.opsForList()).thenReturn(listOps);
        when(redis.opsForHash()).thenReturn(hashOps);

        long now = System.currentTimeMillis();
        List<String> times = new ArrayList<>();
        List<String> paths = new ArrayList<>();
        for (int i = 0; i < windowEntries; i++) {
            times.add(String.valueOf(now - i * 100L));
            paths.add("/api/price/" + i);
        }
        when(listOps.range(eq("sage:timestamps:203.0.113.9"), eq(0L), eq(-1L))).thenReturn(times);
        when(listOps.range(eq("sage:paths:203.0.113.9"), eq(0L), eq(-1L))).thenReturn(paths);
        when(valueOps.increment("sage:reqcount:203.0.113.9")).thenReturn(counterValue);
        when(valueOps.get("sage:reqcount:203.0.113.9")).thenReturn(counterStored);
        when(valueOps.get(startsWith("sage:first_seen:"))).thenReturn(String.valueOf(now - 20_000L));
        return new RedisTelemetryService(redis);
    }

    @Test
    @DisplayName("Non-static request: counter increments past the cap; f0 stays capped at 50")
    void counterIsUncappedWhileDepthIsCapped() {
        Map<String, Double> f = serviceWith(70L, null, 50).processAndGetTelemetry("203.0.113.9", 0.0, "/api/price/7");
        assertEquals(50.0, f.get("SAGE_Session_Depth"));
        assertEquals(70.0, f.get(RedisTelemetryService.NON_STATIC_REQUEST_COUNT));
    }

    @Test
    @DisplayName("Static request: counter is read, not incremented")
    void staticRequestDoesNotIncrement() {
        RedisTelemetryService svc = serviceWith(99L, "64", 50);
        Map<String, Double> f = svc.processAndGetTelemetry("203.0.113.9", 0.0, "/static/app.js");
        assertEquals(64.0, f.get(RedisTelemetryService.NON_STATIC_REQUEST_COUNT));
    }

    private static String startsWith(String prefix) {
        return argThat(s -> s != null && s.startsWith(prefix));
    }
}
