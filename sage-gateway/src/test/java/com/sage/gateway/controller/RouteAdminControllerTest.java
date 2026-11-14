package com.sage.gateway.controller;

import com.sage.gateway.routing.RouteDefinition;
import com.sage.gateway.service.RouteManagerService;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;

class RouteAdminControllerTest {

    private final RouteDefinition route = new RouteDefinition("r", "/x", "http://upstream", null);

    @Test
    void disabledWhenNoTokenConfigured() {
        RouteManagerService manager = mock(RouteManagerService.class);
        RouteAdminController controller = new RouteAdminController(manager, "");

        assertEquals(403, controller.addRoute("anything", route).getStatusCode().value());
        verify(manager, never()).addRoute(any());
    }

    @Test
    void rejectsMissingOrWrongToken() {
        RouteManagerService manager = mock(RouteManagerService.class);
        RouteAdminController controller = new RouteAdminController(manager, "s3cret");

        assertEquals(401, controller.addRoute(null, route).getStatusCode().value());
        assertEquals(401, controller.addRoute("wrong", route).getStatusCode().value());
        verify(manager, never()).addRoute(any());
    }

    @Test
    void addsRouteWithCorrectToken() {
        RouteManagerService manager = mock(RouteManagerService.class);
        RouteAdminController controller = new RouteAdminController(manager, "s3cret");

        assertEquals(200, controller.addRoute("s3cret", route).getStatusCode().value());
        verify(manager).addRoute(route);
    }
}
