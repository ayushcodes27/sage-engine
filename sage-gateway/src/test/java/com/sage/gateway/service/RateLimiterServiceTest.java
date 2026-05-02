package com.sage.gateway.service;

import com.sage.gateway.config.RateLimitProperties;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.RedisScript;
import org.springframework.mock.web.MockHttpServletRequest;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.Mockito.mock;

class RateLimiterServiceTest {

    @Test
    void shouldUseFirstForwardedIpWhenHeaderContainsProxyChain() {
        RateLimiterService rateLimiterService = new RateLimiterService(
                mock(StringRedisTemplate.class),
                mock(RedisScript.class),
                new RateLimitProperties()
        );

        MockHttpServletRequest request = new MockHttpServletRequest();
        request.addHeader("X-Forwarded-For", "203.0.113.10, 10.0.0.5");
        request.addHeader("X-Real-IP", "10.0.0.5");
        request.setRemoteAddr("127.0.0.1");

        assertEquals("203.0.113.10", rateLimiterService.extractClientIp(request));
    }
}
