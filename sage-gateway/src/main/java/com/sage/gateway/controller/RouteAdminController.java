package com.sage.gateway.controller;

import com.sage.gateway.routing.RouteDefinition;
import com.sage.gateway.service.RouteManagerService;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;

@RestController
@RequestMapping("/admin/routes")
public class RouteAdminController {
    static final String TOKEN_HEADER = "X-SAGE-Admin-Token";

    private final RouteManagerService routeManagerService;
    private final String adminToken;

    /**
     * @param adminToken shared secret for the admin API (env SAGE_ADMIN_TOKEN). When blank the admin API is disabled,
     *                   so a gateway started without one never lets an anonymous caller add routes.
     */
    public RouteAdminController(RouteManagerService routeManagerService,
                                @Value("${sage.admin.token:}") String adminToken) {
        this.routeManagerService = routeManagerService;
        this.adminToken = adminToken == null ? "" : adminToken;
    }

    @PostMapping
    public ResponseEntity<String> addRoute(@RequestHeader(value = TOKEN_HEADER, required = false) String token,
                                           @RequestBody RouteDefinition newRoute) {
        if (adminToken.isBlank()) {
            return ResponseEntity.status(HttpStatus.FORBIDDEN)
                    .body("Admin API disabled: set SAGE_ADMIN_TOKEN on the gateway to enable it.");
        }
        if (token == null || !MessageDigest.isEqual(
                token.getBytes(StandardCharsets.UTF_8), adminToken.getBytes(StandardCharsets.UTF_8))) {
            return ResponseEntity.status(HttpStatus.UNAUTHORIZED).body("Missing or invalid " + TOKEN_HEADER + " header.");
        }
        try {
            routeManagerService.addRoute(newRoute);
            return ResponseEntity.ok("Route successfully added and dynamically loaded into SAGE.");
        } catch (Exception e) {
            return ResponseEntity.internalServerError().body("Failed to load route: " + e.getMessage());
        }
    }
}
