package com.sage.gateway.routing;

import java.util.HashMap;
import java.util.Map;

public class RouteNode {
    String segment;
    Map<String, RouteNode> exactChildren = new HashMap<>();

    RouteNode variableChild;
    String variableName;

    RouteDefinition route;

    public RouteNode(String segment) {
        this.segment = segment;
    }
}