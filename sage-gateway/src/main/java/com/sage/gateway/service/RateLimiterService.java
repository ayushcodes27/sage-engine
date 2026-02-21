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
     * Primary decision method.
     * Returns true if the request is permitted, false if it is blocked.
     */
    public boolean isAllowed(String tenantId, String userId) {
        long now = Instant.now().getEpochSecond(); // Current time in seconds

        // Build the hierarchical Redis key in the format:
        // sage:ratelimit:{tier}:{id}
        String globalKey = "sage:ratelimit:global";
        String tenantKey = "sage:ratelimit:tenant:" + tenantId;
        String userKey = "sage:ratelimit:user:" + userId;

        List<String> keys = Arrays.asList(userKey, tenantKey, globalKey);

        // Resolve rate limits (simulated configuration lookup).
        // In production, limits would be fetched from a DB or cache
        // based on the tenant/user subscription plan.
        int[] userLimits = getUserLimits(userId);
        int[] tenantLimits = getTenantLimits(tenantId);

        // Prepare arguments for the Lua script in the exact ARGV[] order:
        // userLimit, userBurst, tenantLimit, tenantBurst,
        // globalLimit, globalBurst, currentTime, requestCost
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

    // Helper methods used as configuration placeholders
    // (to be replaced with actual configuration or lookup logic).

    private int[] getUserLimits(String userId) {
        // Returns {rate, burst} values.
        // Higher limits are assigned for VIP users.
        if ("vip_user".equals(userId)) return new int[] { 500, 1000 };
        return new int[] { 1, 5 }; // Default User
    }

    private int[] getTenantLimits(String tenantId) {
        // Partner A vs Partner B
        if ("partner_b".equals(tenantId)) return new int[] { 20_000, 40_000 };
        return new int[] { 10_000, 20_000 }; // Default Partner
    }
}