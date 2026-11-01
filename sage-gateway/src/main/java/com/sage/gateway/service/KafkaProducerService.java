package com.sage.gateway.service;

import com.sage.gateway.event.RequestEvent;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.kafka.support.SendResult;
import org.springframework.stereotype.Service;

import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;

@Service
public class KafkaProducerService {

    private static final Logger log = LoggerFactory.getLogger(KafkaProducerService.class);
    private static final String TOPIC = "gateway-telemetry";

    private final KafkaTemplate<String, Object> kafkaTemplate;
    private final MeterRegistry meterRegistry;

    public KafkaProducerService(KafkaTemplate<String, Object> kafkaTemplate, MeterRegistry meterRegistry) {
        this.kafkaTemplate = kafkaTemplate;
        this.meterRegistry = meterRegistry;
    }

    /**
     * Events are keyed by client (userId), so all events of one client land on one partition in
     * send order. Keying by the per-request UUID spread a client over all partitions (N5).
     */
    static String routingKey(RequestEvent event) {
        return event.userId() != null ? event.userId() : event.sessionId();
    }

    public void publishEvent(RequestEvent event) {
        long start = System.nanoTime();
        try {
            CompletableFuture<SendResult<String, Object>> future = kafkaTemplate.send(TOPIC, routingKey(event), event);

            future.whenComplete((result, ex) -> {
                if (ex != null) {
                    meterRegistry.counter("sage_gateway_kafka_send_failures_total", "eventType", String.valueOf(event.eventType())).increment();
                    log.warn("Kafka broker rejected telemetry event {}", event.eventId(), ex);
                } else {
                    Timer.builder("sage_gateway_kafka_publish_seconds").register(meterRegistry)
                            .record(System.nanoTime() - start, TimeUnit.NANOSECONDS);
                }
            });
        } catch (Exception e) {
            meterRegistry.counter("sage_gateway_kafka_send_failures_total", "eventType", String.valueOf(event.eventType())).increment();
            log.warn("Skipping telemetry publish for event {}", event.eventId(), e);
        }
    }
}
