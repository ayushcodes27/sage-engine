package com.sage.gateway.routing;

import java.util.Map;package com.sage.gateway.routing;

// record to hold the final destination data
public record RouteDefinition(String pattern, String backendUrl
                                                Map<String, Map<String, String>> filters) {

}
