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

    private final KafkaTemplate<String, Object> kafkaTemplate;

    public KafkaProducerService(KafkaTemplate<String, Object> kafkaTemplate) {
        this.kafkaTemplate = kafkaTemplate;
    }

    public void publishEvent(RequestEvent event) {
        try {
            String routingKey = event.sessionId();
            CompletableFuture<SendResult<String, Object>> future = kafkaTemplate.send(TOPIC, routingKey, event);

            future.whenComplete((result, ex) -> {
                if (ex != null) {
                    log.debug("Kafka broker rejected telemetry event {}", event.eventId(), ex);
                }
            });
        } catch (Exception e) {
            log.debug("Skipping telemetry publish for event {}", event.eventId(), e);
        }
    }
}
