package com.sage.gateway.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.HashOperations;
import org.springframework.data.redis.core.StringRedisTemplate;

import java.util.HashMap;
import java.util.Map;

import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class MlDecisionCacheTest {

    @Test
    @SuppressWarnings("unchecked")
    @DisplayName("N9: a new decision replaces the cached one atomically instead of merging into it")
    void decisionIsReplacedNotMerged() {
        StringRedisTemplate redis = mock(StringRedisTemplate.class);
        HashOperations<String, Object, Object> hashOps = mock(HashOperations.class);
        when(redis.opsForHash()).thenReturn(hashOps);

        Map<String, String> decision = new HashMap<>();
        decision.put("isBot", "false");
        decision.put("shadowBotProbability", null);
        new RedisTelemetryService(redis).cacheMlDecision("192.0.2.50", decision);

        verify(hashOps, never()).putAll(eq("sage:ml-decision:192.0.2.50"), anyMap());
        verify(hashOps).putAll(startsWith("sage:ml-decision:192.0.2.50:staging:"), eq(Map.of("isBot", "false")));
        verify(redis).rename(startsWith("sage:ml-decision:192.0.2.50:staging:"), eq("sage:ml-decision:192.0.2.50"));
    }
}
