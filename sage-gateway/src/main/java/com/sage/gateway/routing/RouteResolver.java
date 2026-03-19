package com.sage.gateway.routing;

import jakarta.servlet.http.HttpServletRequest;
import java.util.HashMap;
import java.util.Map;

public class RouteResolver {

    public RouteDefinition resolve(RouteNode root, String requestUri, HttpServletRequest request) {
        String[] rawSegments = requestUri.split("/");
        RouteNode currentNode = root;

        for (String segment : rawSegments) {
            if (segment == null || segment.isEmpty()) continue;

            if (currentNode.exactChildren.containsKey(segment)) {
                currentNode = currentNode.exactChildren.get(segment);
            }
            else if (currentNode.variableChild != null) {
                // Store the variable in the request
                Map<String, String> vars = (Map<String, String>) request.getAttribute("SAGE_VARS");
                if (vars == null) vars = new HashMap<>();
                vars.put(currentNode.variableName, segment);
                request.setAttribute("SAGE_VARS", vars);

                currentNode = currentNode.variableChild;
            }
            else {
                return null; // 404 Not Found
            }
        }
        return currentNode.route; // Returns the route if it's a leaf, or null
    }
}