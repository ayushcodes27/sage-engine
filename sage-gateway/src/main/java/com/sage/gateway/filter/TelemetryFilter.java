package com.sage.gateway.filter;

import com.sage.gateway.event.RequestEvent; // Or .model.RequestEvent
import com.sage.gateway.service.KafkaProducerService;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.time.Duration;
import java.time.Instant;
import java.util.UUID;

@Component
@Order(Ordered.HIGHEST_PRECEDENCE)
public class TelemetryFilter extends OncePerRequestFilter {

    // Switched to the synchronous template for the Tomcat Servlet stack
    private final StringRedisTemplate redisTemplate;
    private final KafkaProducerService kafkaProducer;

    private static final String LAST_REQUEST_PREFIX = "sage:last_request:";

    public TelemetryFilter(StringRedisTemplate redisTemplate, KafkaProducerService kafkaProducer) {
        this.redisTemplate = redisTemplate;
        this.kafkaProducer = kafkaProducer;
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain filterChain)
            throws ServletException, IOException {

        long startTime = System.currentTimeMillis();
        String eventId = UUID.randomUUID().toString();

        String ipAddress = request.getRemoteAddr() != null ? request.getRemoteAddr() : "anonymous";
        String redisKey = LAST_REQUEST_PREFIX + ipAddress;

        long timeSinceLastMs = 0;

        try {
            //  Synchronous Redis GET
            String lastTimestampString = redisTemplate.opsForValue().get(redisKey);

            if (lastTimestampString != null) {
                long lastMs = Long.parseLong(lastTimestampString);
                timeSinceLastMs = startTime - lastMs;
            }

            redisTemplate.opsForValue().set(redisKey, String.valueOf(startTime), Duration.ofHours(24));

        } catch (Exception e) {
            logger.error("Redis sequence tracking failed", e);
        }

        try {
            // Route the request down the chain (to the Controller / Backend)
            filterChain.doFilter(request, response);

        } finally {
            // The 'finally' block acts just like '.doFinally()' in WebFlux.
            // It runs after the response is sent, calculating total round-trip time.
            long latencyMs = System.currentTimeMillis() - startTime;
            int statusCode = response.getStatus();
            String path = request.getRequestURI();
            String method = request.getMethod();

            RequestEvent.RequestDetails requestDetails = new RequestEvent.RequestDetails(method, path, "api", ipAddress);
            RequestEvent.ResponseDetails responseDetails = new RequestEvent.ResponseDetails(statusCode, latencyMs);
            RequestEvent.MLMetadata mlMetadata = new RequestEvent.MLMetadata(timeSinceLastMs, 1);

            RequestEvent event = new RequestEvent(
                    eventId,
                    Instant.now().toEpochMilli(),
                    "tenant_placeholder",
                    ipAddress,
                    ipAddress + "_session",
                    requestDetails,
                    responseDetails,
                    mlMetadata
            );

            System.out.println("🚨 SERVLET FILTER TRIGGERED: Sending to Kafka! EventID: " + eventId);
            kafkaProducer.publishEvent(event);
        }
    }
}