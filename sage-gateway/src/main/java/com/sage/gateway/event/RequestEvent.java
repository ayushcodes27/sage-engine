package com.sage.gateway.event;

public record RequestEvent(
        String eventId,
        long timestamp,
        String tenantId,
        String userId,
        String sessionId,
        RequestDetails request,
        ResponseDetails response,
        MLMetadata mlMetadata
) {
    public record RequestDetails(String method, String path, String category, String ip) {}
    public record ResponseDetails(int status, long latencyMs) {}
    public record MLMetadata(double botProbability, int isBotFlag, String threatClass) {}
}