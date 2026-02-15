package com.sage.gateway.service;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.RedisScript;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.util.Arrays;
import java.util.List;

@Service
public class RateLimiterService {

    private static final Logger logger = LoggerFactory.getLogger(RateLimiterService.class);

    private final StringRedisTemplate redisTemplate;
    private final RedisScript<Long> rateLimitScript;

    // Hardcoded System Limits for SAGE (The Global Tier)
    private static final int GLOBAL_LIMIT = 100_000;
    private static final int GLOBAL_BURST = 100_000;

    public RateLimiterService(StringRedisTemplate redisTemplate, RedisScript<Long> rateLimitScript) {
        this.redisTemplate = redisTemplate;
        this.rateLimitScript = rateLimitScript;
    }

    /**
     * The Main Entry Point.
     * Returns TRUE if allowed, FALSE if blocked.
     */
    public boolean isAllowed(String tenantId, String userId) {
        long now = Instant.now().getEpochSecond(); // Current time in seconds

        // 1. Construct Keys (Hierarchy)
        // usage: sage:ratelimit:{tier}:{id}
        String globalKey = "sage:ratelimit:global";
        String tenantKey = "sage:ratelimit:tenant:" + tenantId;
        String userKey = "sage:ratelimit:user:" + userId;

        List<String> keys = Arrays.asList(userKey, tenantKey, globalKey);

        // 2. Resolve Limits (Simulated Config Lookup)
        // In real life, these come from DB/Cache based on tenantId/userId plan
        int[] userLimits = getUserLimits(userId);
        int[] tenantLimits = getTenantLimits(tenantId);

        // 3. Prepare Arguments for Lua
        // Order matches Lua script ARGV[]:
        // UserLimit, UserBurst, TenantLimit, TenantBurst, GlobalLimit, GlobalBurst, Now, Cost
        Object[] args = {
                String.valueOf(userLimits[0]), // ARGV[1]: User Limit
                String.valueOf(userLimits[1]), // ARGV[2]: User Burst
                String.valueOf(tenantLimits[0]), // ARGV[3]: Tenant Limit
                String.valueOf(tenantLimits[1]), // ARGV[4]: Tenant Burst
                String.valueOf(GLOBAL_LIMIT),    // ARGV[5]: Global Limit
                String.valueOf(GLOBAL_BURST),    // ARGV[6]: Global Burst
                String.valueOf(now),             // ARGV[7]: Timestamp
                "1"                              // ARGV[8]: Cost (1 token)
        };

        // 4. Execute Script
        // The .execute call handles the SHA1 hashing and serialization automatically
        try {
            Long result = redisTemplate.execute(rateLimitScript, keys, args);
            return result != null && result == 1L;
        } catch (Exception e) {
            // FAIL OPEN STRATEGY: If Redis is down, we log error but ALLOW traffic
            // so we don't cause a total outage due to a rate-limiter failure.
            logger.error("Redis Rate Limiter failed: {}", e.getMessage());
            return true;
        }
    }

    // --- Helper Methods (Configuration Placeholders) ---

    private int[] getUserLimits(String userId) {
        // Return {Rate, Burst}
        // VIP User gets more
        if ("vip_user".equals(userId)) return new int[] { 500, 1000 };
        return new int[] { 1, 5 }; // Default User
    }

    private int[] getTenantLimits(String tenantId) {
        // Partner A vs Partner B
        if ("partner_b".equals(tenantId)) return new int[] { 20_000, 40_000 };
        return new int[] { 10_000, 20_000 }; // Default Partner
    }
}