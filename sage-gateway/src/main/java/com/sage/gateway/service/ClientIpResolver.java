package com.sage.gateway.service;

import jakarta.servlet.http.HttpServletRequest;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.net.InetAddress;
import java.net.UnknownHostException;
import java.util.ArrayList;
import java.util.List;

/**
 * Resolves the client IP used for ban lists, rate limiting and per-client telemetry.
 *
 * X-Forwarded-For / X-Real-IP are client-controlled, so they are honoured only when the direct peer
 * (remoteAddr) is a trusted proxy; otherwise the peer address itself is used. The default trusted set is
 * loopback plus private ranges, which covers a reverse proxy on the same host or network and the local
 * traffic generators (they reach the gateway through Docker's bridge network), while a client on the
 * public internet can no longer pick its own IP. Set sage.network.trusted-proxies (env
 * SAGE_TRUSTED_PROXIES) to a comma-separated list of IPs/CIDRs, or "*" to trust every peer.
 */
@Component
public class ClientIpResolver {

    static final String DEFAULT_TRUSTED =
            "127.0.0.0/8,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,fc00::/7";

    private final boolean trustAll;
    private final List<Cidr> trusted = new ArrayList<>();

    public ClientIpResolver(@Value("${sage.network.trusted-proxies:" + DEFAULT_TRUSTED + "}") String trustedProxies) {
        String spec = trustedProxies == null ? "" : trustedProxies.trim();
        if (spec.isEmpty()) {
            spec = DEFAULT_TRUSTED; // docker compose passes an unset variable as "", which must not mean "trust nobody"
        }
        this.trustAll = spec.equals("*");
        if (!trustAll) {
            for (String entry : spec.split(",")) {
                if (!entry.isBlank()) {
                    trusted.add(Cidr.parse(entry.trim()));
                }
            }
        }
    }

    public String resolve(HttpServletRequest request) {
        String peer = request.getRemoteAddr();
        if (isTrustedProxy(peer)) {
            String forwarded = firstHop(request.getHeader("X-Forwarded-For"));
            if (forwarded != null) return forwarded;
            String realIp = firstHop(request.getHeader("X-Real-IP"));
            if (realIp != null) return realIp;
        }
        return peer != null && !peer.isBlank() ? peer : "anonymous";
    }

    boolean isTrustedProxy(String peer) {
        if (trustAll) return true;
        if (peer == null || peer.isBlank() || !isIpLiteral(peer)) return false;
        try {
            byte[] addr = InetAddress.getByName(peer).getAddress(); // literal only: no DNS lookup
            for (Cidr c : trusted) {
                if (c.contains(addr)) return true;
            }
        } catch (UnknownHostException e) {
            return false;
        }
        return false;
    }

    private static String firstHop(String header) {
        if (header == null || header.isBlank()) return null;
        String first = header.split(",")[0].trim();
        return first.isEmpty() ? null : first;
    }

    private static boolean isIpLiteral(String s) {
        if (s.indexOf(':') >= 0) { // IPv6 (optionally with an embedded IPv4 tail)
            return s.chars().allMatch(ch -> Character.digit(ch, 16) >= 0 || ch == '.' || ch == ':');
        }
        return !s.isEmpty() && s.chars().allMatch(ch -> (ch >= '0' && ch <= '9') || ch == '.');
    }

    private record Cidr(byte[] network, int prefix) {
        static Cidr parse(String spec) {
            String[] parts = spec.split("/", 2);
            if (!isIpLiteral(parts[0])) {
                throw new IllegalArgumentException("sage.network.trusted-proxies: not an IP/CIDR: " + spec);
            }
            try {
                byte[] net = InetAddress.getByName(parts[0]).getAddress();
                int prefix = parts.length == 2 ? Integer.parseInt(parts[1]) : net.length * 8;
                if (prefix < 0 || prefix > net.length * 8) {
                    throw new IllegalArgumentException("sage.network.trusted-proxies: bad prefix: " + spec);
                }
                return new Cidr(net, prefix);
            } catch (UnknownHostException | NumberFormatException e) {
                throw new IllegalArgumentException("sage.network.trusted-proxies: not an IP/CIDR: " + spec, e);
            }
        }

        boolean contains(byte[] addr) {
            if (addr.length != network.length) return false;
            int full = prefix / 8, rem = prefix % 8;
            for (int i = 0; i < full; i++) {
                if (addr[i] != network[i]) return false;
            }
            if (rem == 0) return true;
            int mask = (0xFF << (8 - rem)) & 0xFF;
            return (addr[full] & mask) == (network[full] & mask);
        }
    }
}
