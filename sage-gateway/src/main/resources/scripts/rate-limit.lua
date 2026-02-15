-- KEYS[]: The Redis keys for the 3 tiers
-- KEYS[1]: User Key (e.g., sage:ratelimit:user:123)
-- KEYS[2]: Partner Key (e.g., sage:ratelimit:partner:ABC)
-- KEYS[3]: Global Key (e.g., sage:ratelimit:global)

-- ARGV[]: Arguments we pass in from Java
-- ARGV[1]: User Limit (Tokens per second)
-- ARGV[2]: User Burst (Bucket Size)
-- ARGV[3]: Partner Limit
-- ARGV[4]: Partner Burst
-- ARGV[5]: Global Limit
-- ARGV[6]: Global Burst
-- ARGV[7]: Current Timestamp (Epoch seconds)
-- ARGV[8]: Tokens to consume (usually 1)

local allowed = 1

-- Helper function to check a single bucket
local function check_bucket(key, limit_arg, burst_arg, now_arg, cost_arg)
    -- 1. EXPLICIT CONVERSION (Fixes the crash)
    local limit = tonumber(limit_arg)
    local burst = tonumber(burst_arg)
    local now = tonumber(now_arg)
    local cost = tonumber(cost_arg)

    -- If conversion failed (nil), play it safe and allow (or handle error)
    if not limit or not burst or not now then return 1 end

    local last_refill = tonumber(redis.call('HGET', key, 'last_refill') or 0)
    -- If key doesn't exist, we start with full burst
    local tokens = tonumber(redis.call('HGET', key, 'tokens') or burst)

    -- 2. Calculate Refill
    if last_refill > 0 then
        local delta = math.max(0, now - last_refill)
        local refill = delta * limit
        tokens = math.min(burst, tokens + refill)
    end

    -- 3. Check if enough tokens exist
    if tokens >= cost then
        tokens = tokens - cost
        redis.call('HSET', key, 'last_refill', now, 'tokens', tokens)
        redis.call('EXPIRE', key, 60)
        return 1
    else
        return 0
    end
end

-- CHECK ALL 3 TIERS
-- If ANY tier returns 0 (blocked), the whole request is blocked.
local global_res = check_bucket(KEYS[3], ARGV[5], ARGV[6], ARGV[7], ARGV[8])
if global_res == 0 then return 0 end

local tenant_res = check_bucket(KEYS[2], ARGV[3], ARGV[4], ARGV[7], ARGV[8])
if tenant_res == 0 then return 0 end

local user_res = check_bucket(KEYS[1], ARGV[1], ARGV[2], ARGV[7], ARGV[8])
if user_res == 0 then return 0 end

return 1