package com.sage.gateway.service;

import com.sage.gateway.event.RequestEvent;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;

class KafkaRoutingKeyTest {

    private static RequestEvent event(String userId, String sessionId) {
        return new RequestEvent("1.1", "request.processed", "e", 0L, "t", userId, sessionId, "r", "unknown",
                null, null, null, null);
    }

    @Test
    @DisplayName("N5: events are keyed by client so one client's events keep their order on one partition")
    void keyIsClientId() {
        assertEquals("normal_browser-03", KafkaProducerService.routingKey(event("normal_browser-03", "uuid-1")));
        assertEquals(KafkaProducerService.routingKey(event("normal_browser-03", "uuid-1")),
                KafkaProducerService.routingKey(event("normal_browser-03", "uuid-2")));
    }

    @Test
    void fallsBackToSessionIdWithoutClient() {
        assertEquals("uuid-9", KafkaProducerService.routingKey(event(null, "uuid-9")));
    }
}
