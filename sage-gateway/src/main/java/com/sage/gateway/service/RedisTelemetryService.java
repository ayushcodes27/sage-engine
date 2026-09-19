package com.sage.gateway.service;

import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;
import java.time.Instant;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.TimeUnit;
import java.util.stream.Collectors;

@Service
public class RedisTelemetryService {

    private final StringRedisTemplate redisTemplate;
    private static final int WINDOW_SIZE = 50;
    private static final Duration ML_DECISION_TTL = Duration.ofMinutes(5);

    public RedisTelemetryService(StringRedisTemplate redisTemplate) {
        this.redisTemplate = redisTemplate;
    }

    public Map<String, Double> processAndGetTelemetry(String ip, double payloadSize, String path) {
        long currentTimestamp = Instant.now().toEpochMilli();
        String timeKey = "sage:timestamps:" + ip;
        String pathKey = "sage:paths:" + ip;
        String hashKey = "sage:telemetry:" + ip;

        // Migration: delete old sizeKey if it exists
        String oldSizeKey = "sage:sizes:" + ip;
        if (Boolean.TRUE.equals(redisTemplate.hasKey(oldSizeKey))) {
            redisTemplate.delete(oldSizeKey);
        }

        String canonicalPath = canonicalizePath(path);
        boolean isStatic = isStaticAsset(canonicalPath);
        boolean isCart = isCartPath(canonicalPath);

        // Request counters for e-commerce scraper-focused features.
        redisTemplate.opsForHash().increment(hashKey, "total_hits", 1);
        if (isCart) {
            redisTemplate.opsForHash().increment(hashKey, "cart_hits", 1);
        }
        if (isStatic) {
            redisTemplate.opsForHash().increment(hashKey, "static_hits", 1);
        }

        // Only LPUSH if this is NOT a static asset
        if (!isStatic) {
            // LPUSH new data to the front of the lists
            redisTemplate.opsForList().leftPush(timeKey, String.valueOf(currentTimestamp));
            redisTemplate.opsForList().leftPush(pathKey, canonicalPath);

            // LTRIM to keep only the last WINDOW_SIZE elements
            redisTemplate.opsForList().trim(timeKey, 0, WINDOW_SIZE - 1);
            redisTemplate.opsForList().trim(pathKey, 0, WINDOW_SIZE - 1);
        }

        // Fetch the sliding window
        List<String> rawTimes = redisTemplate.opsForList().range(timeKey, 0, -1);
        List<String> rawPaths = redisTemplate.opsForList().range(pathKey, 0, -1);

        // Parse to doubles
        List<Double> times = rawTimes.stream().map(Double::parseDouble).collect(Collectors.toList());

        // Calculate the 4 Core SAGE Features
        double sessionDepth = times.size();
        double sessionDuration = 0.0;
        if (times.size() >= 2) {
            sessionDuration = (times.get(0) - times.get(times.size() - 1)) / 1000.0;
        }
        double requestVelocity = calculateVelocity(times);
        double temporalVariance = calculateTemporalVariance(times);
        double nonStaticNavigationGap = calculateNonStaticNavigationGap(times);
        double nonStaticLongGapRatio = calculateNonStaticLongGapRatio(times);
        
        // Compute Entropy and Concentration from exact paths
        double behavioralDiversity = calculateEntropy(rawPaths);
        double endpointConcentration = calculateEndpointConcentration(rawPaths);
        
        double totalHits = getCounter(hashKey, "total_hits");
        double cartHits = getCounter(hashKey, "cart_hits");
        double staticHits = getCounter(hashKey, "static_hits");

        double cartRatio = totalHits > 0 ? cartHits / totalHits : 0.0;
        double assetSkipRatio = totalHits > 0 ? 1.0 - (staticHits / totalHits) : 1.0;

        // Update the Redis Hash
        redisTemplate.opsForHash().put(hashKey, "SAGE_Session_Depth", String.valueOf(sessionDepth));
        redisTemplate.opsForHash().put(hashKey, "SAGE_Request_Velocity", String.valueOf(requestVelocity));
        redisTemplate.opsForHash().put(hashKey, "SAGE_Temporal_Variance", String.valueOf(temporalVariance));
        redisTemplate.opsForHash().put(hashKey, "SAGE_Behavioral_Diversity", String.valueOf(behavioralDiversity));
        redisTemplate.opsForHash().put(hashKey, "SAGE_Endpoint_Concentration", String.valueOf(endpointConcentration));
        redisTemplate.opsForHash().put(hashKey, "SAGE_Cart_Ratio", String.valueOf(cartRatio));
        redisTemplate.opsForHash().put(hashKey, "SAGE_Asset_Skip_Ratio", String.valueOf(assetSkipRatio));
        redisTemplate.opsForHash().put(hashKey, "SAGE_NonStatic_Navigation_Gap", String.valueOf(nonStaticNavigationGap));
        redisTemplate.opsForHash().put(hashKey, "SAGE_NonStatic_Long_Gap_Ratio", String.valueOf(nonStaticLongGapRatio));
        redisTemplate.opsForHash().put(hashKey, "SAGE_Session_Duration", String.valueOf(sessionDuration));

        // Set a 5-minute TTL on ALL keys, refreshed on EVERY request (even static)
        redisTemplate.expire(hashKey, Duration.ofMinutes(5));
        redisTemplate.expire(timeKey, Duration.ofMinutes(5));
        redisTemplate.expire(pathKey, Duration.ofMinutes(5));

        Map<String, Double> features = new LinkedHashMap<>();
        features.put("SAGE_Session_Depth", sessionDepth);
        features.put("SAGE_Request_Velocity", requestVelocity);
        features.put("SAGE_Temporal_Variance", temporalVariance);
        features.put("SAGE_Behavioral_Diversity", behavioralDiversity);
        features.put("SAGE_Endpoint_Concentration", endpointConcentration);
        features.put("SAGE_Cart_Ratio", cartRatio);
        features.put("SAGE_Asset_Skip_Ratio", assetSkipRatio);
        features.put("SAGE_NonStatic_Navigation_Gap", nonStaticNavigationGap);
        features.put("SAGE_NonStatic_Long_Gap_Ratio", nonStaticLongGapRatio);
        features.put("SAGE_Session_Duration", sessionDuration);
        return features;
    }

    public Map<String, String> getCachedMlDecision(String ip) {
        String key = "sage:ml-decision:" + ip;
        Map<Object, Object> values = redisTemplate.opsForHash().entries(key);
        if (values.isEmpty()) {
            return Map.of();
        }

        Map<String, String> result = new HashMap<>();
        values.forEach((field, value) -> result.put(String.valueOf(field), String.valueOf(value)));
        return result;
    }

    public void cacheMlDecision(String ip, Map<String, String> decision) {
        if (decision.isEmpty()) {
            return;
        }
        String key = "sage:ml-decision:" + ip;
        Map<String, String> nonNullDecision = new HashMap<>();
        decision.forEach((field, value) -> {
            if (value != null) {
                nonNullDecision.put(field, value);
            }
        });
        redisTemplate.opsForHash().putAll(key, nonNullDecision);
        redisTemplate.expire(key, ML_DECISION_TTL);
    }

    private double getCounter(String hashKey, String field) {
        Object val = redisTemplate.opsForHash().get(hashKey, field);
        if (val == null) {
            return 0.0;
        }
        try {
            return Double.parseDouble(val.toString());
        } catch (NumberFormatException ex) {
            return 0.0;
        }
    }

    public static String canonicalizePath(String path) {
        String canonicalPath = "/";
        if (path != null && !path.isBlank()) {
            canonicalPath = path.split("\\?")[0].split("#")[0];
            canonicalPath = canonicalPath.replaceAll("/+", "/");
            if (canonicalPath.length() > 1 && canonicalPath.endsWith("/")) {
                canonicalPath = canonicalPath.substring(0, canonicalPath.length() - 1);
            }
            canonicalPath = canonicalPath.toLowerCase();
        }
        return canonicalPath;
    }

    public static boolean isStaticAsset(String canonicalPath) {
        if (canonicalPath == null) return false;
        return canonicalPath.startsWith("/static/") ||
                canonicalPath.matches(".*\\.(js|css|png|jpg|jpeg|gif|ico|woff|woff2|ttf|svg|webp)$");
    }

    public static boolean isCartPath(String canonicalPath) {
        if (canonicalPath == null) return false;
        return canonicalPath.matches(".*(cart|checkout|koszyk|platnosc|zamowienie|payment).*");
    }

    public static double calculateVelocity(List<Double> times) {
        if (times.size() < 2) return 1.0;
        double timeSpanSeconds = (times.get(0) - times.get(times.size() - 1)) / 1000.0;

        if (timeSpanSeconds <= 0.001) timeSpanSeconds = 0.001;

        return times.size() / timeSpanSeconds;
    }

    public static double calculateTemporalVariance(List<Double> times) {
        if (times.size() < 2) return 0.0;

        double[] iat = new double[times.size() - 1];
        double sumIat = 0;
        for (int i = 0; i < times.size() - 1; i++) {
            iat[i] = times.get(i) - times.get(i + 1);
            sumIat += iat[i];
        }

        double meanIat = sumIat / iat.length;
        if (meanIat == 0) return 0.0;

        double sumSquaredDiffs = 0;
        for (double val : iat) {
            sumSquaredDiffs += Math.pow(val - meanIat, 2);
        }
        double stdIat = Math.sqrt(sumSquaredDiffs / iat.length);

        return stdIat / meanIat;
    }

    public static double calculateNonStaticNavigationGap(List<Double> times) {
        if (times.size() < 2) return 0.0;
        double[] gaps = new double[times.size() - 1];
        for (int i = 0; i < times.size() - 1; i++) {
            gaps[i] = (times.get(i) - times.get(i + 1)) / 1000.0; // convert to seconds
        }
        Arrays.sort(gaps);
        int mid = gaps.length / 2;
        return (gaps.length % 2 == 1) ? gaps[mid] : (gaps[mid - 1] + gaps[mid]) / 2.0;
    }

    public static double calculateNonStaticLongGapRatio(List<Double> times) {
        if (times.size() < 2) return 0.0;
        long longGaps = 0;
        for (int i = 0; i < times.size() - 1; i++) {
            double gapSec = (times.get(i) - times.get(i + 1)) / 1000.0;
            if (gapSec >= 0.50) {
                longGaps++;
            }
        }
        return (double) longGaps / (times.size() - 1);
    }

    public static double calculateEntropy(List<String> paths) {
        if (paths == null || paths.size() < 2) return 0.0;
        Map<String, Long> counts = paths.stream().collect(Collectors.groupingBy(p -> p, Collectors.counting()));
        double entropy = 0.0;
        int n = paths.size();
        for (long count : counts.values()) {
            double p = (double) count / n;
            entropy -= p * Math.log(p);
        }
        return entropy;
    }

    public static double calculateEndpointConcentration(List<String> paths) {
        if (paths == null || paths.isEmpty()) return 0.0;
        Map<String, Long> counts = paths.stream().collect(Collectors.groupingBy(p -> p, Collectors.counting()));
        long maxFreq = counts.values().stream().mapToLong(Long::longValue).max().orElse(0L);
        return (double) maxFreq / paths.size();
    }
    public boolean isIpBanned(String ip) {
        // Instantly checks if the IP is on the temporary ban list
        return Boolean.TRUE.equals(redisTemplate.hasKey("sage:ban:" + ip));
    }

    public long incrementFloodBurstCounter(String ip) {
        String key = "sage:flood:burst:" + ip;
        Long count = redisTemplate.opsForValue().increment(key);
        if (count != null && count == 1L) {
            // Keep a short sliding burst window so only rapid sequences are escalated.
            redisTemplate.expire(key, java.time.Duration.ofSeconds(10));
        }
        return count == null ? 0L : count;
    }

    public void banIp(String ip) {
        // Bans the IP for 5 minutes (300 seconds)
        redisTemplate.opsForValue().set("sage:ban:" + ip, "true", java.time.Duration.ofMinutes(5));
    }

    public long incrementScraper429Counter(String ip) {
        String key = "sage:scraper:429:" + ip;
        Long count = redisTemplate.opsForValue().increment(key);
        if (count != null && count == 1L) {
            redisTemplate.expire(key, java.time.Duration.ofMinutes(5));
        }
        return count == null ? 0L : count;
    }

    public void resetScraper429Counter(String ip) {
        redisTemplate.delete("sage:scraper:429:" + ip);
    }

    public long incrementReconProbeCounter(String ip) {
        String key = "sage:recon:probe:" + ip;
        Long count = redisTemplate.opsForValue().increment(key);
        if (count != null && count == 1L) {
            redisTemplate.expire(key, java.time.Duration.ofMinutes(10));
        }
        return count == null ? 0L : count;
    }

    public boolean isGlobalPathFlooding(String path, long thresholdPerSecond) {
        if (path == null || path.isBlank()) {
            return false;
        }

        long currentSecond = Instant.now().getEpochSecond();
        String safePath = path.replaceAll("[^a-zA-Z0-9_:/.-]", "_");
        String key = "sage:global:path:" + safePath + ":" + currentSecond;
        String blockKey = "sage:global:block:" + safePath;

        // If a short endpoint cooldown is active, keep blocking immediately.
        if (Boolean.TRUE.equals(redisTemplate.hasKey(blockKey))) {
            return true;
        }

        Long currentCount = redisTemplate.opsForValue().increment(key);
        if (currentCount != null && currentCount == 1L) {
            redisTemplate.expire(key, java.time.Duration.ofSeconds(2));
        }

        if (currentCount != null && currentCount > thresholdPerSecond) {
            // Create a short-lived global endpoint block to prevent per-second burst escapes.
            redisTemplate.opsForValue().set(blockKey, "1", java.time.Duration.ofSeconds(2));
            return true;
        }

        return false;
    }
}