package com.sage.gateway.service;

import com.sage.gateway.event.RequestEvent;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.kafka.support.SendResult;
import org.springframework.stereotype.Service;

import java.util.concurrent.CompletableFuture;

@Service
public class KafkaProducerService {

    private static final Logger log = LoggerFactory.getLogger(KafkaProducerService.class);
    private static final String TOPIC = "gateway-telemetry";

    // Changing this to <String, Object> perfectly matches Spring's AutoConfiguration.
    // The JsonSerializer we defined in application.yml will automatically parse our RequestEvent payload into JSON.
    private final KafkaTemplate<String, Object> kafkaTemplate;

    public KafkaProducerService(KafkaTemplate<String, Object> kafkaTemplate) {
        this.kafkaTemplate = kafkaTemplate;
    }

    public void publishEvent(RequestEvent event) {
        log.info("1: publishEvent called for EventId: {}", event.eventId());

        try {
            String routingKey = event.sessionId();
            CompletableFuture<SendResult<String, Object>> future = kafkaTemplate.send(TOPIC, routingKey, event);

            future.whenComplete((result, ex) -> {
                if (ex != null) {
                    log.error("❌ STEP 2: Kafka broker rejected the event!", ex);
                } else {
                    log.info("✅ STEP 2: Event saved successfully. Partition: {}", result.getRecordMetadata().partition());
                }
            });
        } catch (Exception e) {
            log.error("CRITICAL: Failed before sending to Kafka! JSON Serialization error.", e);
        }
    }
}