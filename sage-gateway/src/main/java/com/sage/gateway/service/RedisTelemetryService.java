package com.sage.gateway.service;

import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

@Service
public class RedisTelemetryService {

    private final StringRedisTemplate redisTemplate;
    private static final int WINDOW_SIZE = 50;

    public RedisTelemetryService(StringRedisTemplate redisTemplate) {
        this.redisTemplate = redisTemplate;
    }

    public Map<String, Double> processAndGetTelemetry(String ip, double payloadSize) {
        long currentTimestamp = Instant.now().toEpochMilli();
        String timeKey = "sage:timestamps:" + ip;
        String sizeKey = "sage:sizes:" + ip;
        String hashKey = "sage:telemetry:" + ip;

        // LPUSH new data to the front of the lists
        redisTemplate.opsForList().leftPush(timeKey, String.valueOf(currentTimestamp));
        redisTemplate.opsForList().leftPush(sizeKey, String.valueOf(payloadSize));

        // LTRIM to keep only the last WINDOW_SIZE elements
        redisTemplate.opsForList().trim(timeKey, 0, WINDOW_SIZE - 1);
        redisTemplate.opsForList().trim(sizeKey, 0, WINDOW_SIZE - 1);

        // Fetch the sliding window
        List<String> rawTimes = redisTemplate.opsForList().range(timeKey, 0, -1);
        List<String> rawSizes = redisTemplate.opsForList().range(sizeKey, 0, -1);

        // Parse to doubles
        List<Double> times = rawTimes.stream().map(Double::parseDouble).collect(Collectors.toList());
        List<Double> sizes = rawSizes.stream().map(Double::parseDouble).collect(Collectors.toList());

        // Calculate the 4 Core SAGE Features
        double sessionDepth = times.size();
        double requestVelocity = calculateVelocity(times);
        double temporalVariance = calculateTemporalVariance(times);
        double behavioralDiversity = calculateStandardDeviation(sizes);

        // Update the Redis Hash
        redisTemplate.opsForHash().put(hashKey, "SAGE_Session_Depth", String.valueOf(sessionDepth));
        redisTemplate.opsForHash().put(hashKey, "SAGE_Request_Velocity", String.valueOf(requestVelocity));
        redisTemplate.opsForHash().put(hashKey, "SAGE_Temporal_Variance", String.valueOf(temporalVariance));
        redisTemplate.opsForHash().put(hashKey, "SAGE_Behavioral_Diversity", String.valueOf(behavioralDiversity));

        // Set a 1-hour TTL
        redisTemplate.expire(hashKey, java.time.Duration.ofHours(1));
        redisTemplate.expire(timeKey, java.time.Duration.ofHours(1));
        redisTemplate.expire(sizeKey, java.time.Duration.ofHours(1));

        return Map.of(
                "SAGE_Session_Depth", sessionDepth,
                "SAGE_Request_Velocity", requestVelocity,
                "SAGE_Temporal_Variance", temporalVariance,
                "SAGE_Behavioral_Diversity", behavioralDiversity
        );
    }

    private double calculateVelocity(List<Double> times) {
        if (times.size() < 2) return 1.0;
        double timeSpanSeconds = (times.get(0) - times.get(times.size() - 1)) / 1000.0;

        if (timeSpanSeconds <= 0.001) timeSpanSeconds = 0.001;

        return times.size() / timeSpanSeconds;
    }

    private double calculateTemporalVariance(List<Double> times) {
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

    private double calculateStandardDeviation(List<Double> values) {
        if (values.size() < 2) return 100.0;

        double sum = 0;
        for (double val : values) sum += val;
        double mean = sum / values.size();

        double sumSquaredDiffs = 0;
        for (double val : values) {
            sumSquaredDiffs += Math.pow(val - mean, 2);
        }
        return Math.sqrt(sumSquaredDiffs / values.size());
    }
    public boolean isIpBanned(String ip) {
        // Instantly checks if the IP is on the temporary ban list
        return Boolean.TRUE.equals(redisTemplate.hasKey("sage:ban:" + ip));
    }

    public void banIp(String ip) {
        // Bans the IP for 5 minutes (300 seconds)
        redisTemplate.opsForValue().set("sage:ban:" + ip, "true", java.time.Duration.ofMinutes(5));
    }
}