package com.sage.gateway.service;

import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

class ClientIpResolverTest {

    private static MockHttpServletRequest req(String peer, String xff, String realIp) {
        MockHttpServletRequest r = new MockHttpServletRequest();
        r.setRemoteAddr(peer);
        if (xff != null) r.addHeader("X-Forwarded-For", xff);
        if (realIp != null) r.addHeader("X-Real-IP", realIp);
        return r;
    }

    private final ClientIpResolver defaults = new ClientIpResolver(ClientIpResolver.DEFAULT_TRUSTED);

    @Test
    void trustedPeersMayForwardTheClientIp() {
        // loopback and Docker bridge peers: the traffic generators' path, unchanged behaviour
        assertEquals("203.0.113.10", defaults.resolve(req("127.0.0.1", "203.0.113.10, 10.0.0.5", null)));
        assertEquals("198.51.100.4", defaults.resolve(req("172.18.0.1", "198.51.100.4", null)));
        assertEquals("198.51.100.9", defaults.resolve(req("192.168.65.1", null, "198.51.100.9")));
        assertEquals("203.0.113.7", defaults.resolve(req("::1", "203.0.113.7", null)));
    }

    @Test
    void publicPeersCannotSpoofTheirIp() {
        assertEquals("8.8.8.8", defaults.resolve(req("8.8.8.8", "1.2.3.4", "5.6.7.8")));
        assertEquals("172.32.0.1", defaults.resolve(req("172.32.0.1", "1.2.3.4", null))); // just outside 172.16/12
    }

    @Test
    void fallsBackToPeerWhenNoHeaders() {
        assertEquals("10.1.2.3", defaults.resolve(req("10.1.2.3", null, null)));
        assertEquals("anonymous", defaults.resolve(req("", null, null)));
    }

    @Test
    void configurableTrustList() {
        ClientIpResolver lb = new ClientIpResolver("203.0.113.5");
        assertEquals("1.2.3.4", lb.resolve(req("203.0.113.5", "1.2.3.4", null)));
        assertEquals("127.0.0.1", lb.resolve(req("127.0.0.1", "1.2.3.4", null)));

        ClientIpResolver all = new ClientIpResolver("*");
        assertEquals("1.2.3.4", all.resolve(req("8.8.8.8", "1.2.3.4", null)));

        ClientIpResolver blank = new ClientIpResolver(""); // unset compose variable -> defaults, not "trust nobody"
        assertEquals("1.2.3.4", blank.resolve(req("127.0.0.1", "1.2.3.4", null)));
        assertEquals("8.8.8.8", blank.resolve(req("8.8.8.8", "1.2.3.4", null)));
    }

    @Test
    void rejectsHostnamesInTrustList() {
        assertThrows(IllegalArgumentException.class, () -> new ClientIpResolver("proxy.example.com"));
        assertThrows(IllegalArgumentException.class, () -> new ClientIpResolver("cafe.bad")); // all-hex hostname
    }
}
