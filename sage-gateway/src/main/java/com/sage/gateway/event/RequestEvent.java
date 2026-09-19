package com.sage.gateway.event;

public record RequestEvent(
    String schemaVersion,
    String eventType,
    String eventId,
    long timestamp,
    String tenantId,
    String userId,
    String sessionId,
    String runId,
    String label,
    RequestDetails request,
    ResponseDetails response,
    FeatureVector features,
    MLMetadata mlMetadata
) {
    public record RequestDetails(String method, String path, String category, String ip) {}
    public record ResponseDetails(int status, long latencyMs) {}
    public record FeatureVector(
        double sessionDepth,
        double temporalVariance,
        double requestVelocity,
        double behavioralDiversity,
        double endpointConcentration,
        double cartRatio,
        double assetSkipRatio,
        double nonStaticNavigationGap,
        double nonStaticLongGapRatio
    ) {
        public FeatureVector(double sessionDepth, double temporalVariance, double requestVelocity,
                             double behavioralDiversity, double endpointConcentration, double cartRatio,
                             double assetSkipRatio) {
            this(sessionDepth, temporalVariance, requestVelocity, behavioralDiversity, endpointConcentration,
                 cartRatio, assetSkipRatio, 0.0, 0.0);
        }
    }
    public record MLMetadata(
        Double botProbability,
        Integer isBotFlag,
        String threatClass,
        String evaluationStatus,
        Double shadowBotProbability,
        Integer shadowIsBotFlag,
        String shadowThreatClass,
        String shadowAction,
        String shadowStatus,
        Double prodInferenceLatencyMs,
        Double shadowInferenceLatencyMs,
        String contractHash,
        String modelVersion,
        Double shadowThreshold,
        String decisionSource,
        Double scoringDepth,
        Long scoringTimestampMs,
        String prodModelSha256,
        String shadowModelSha256,
        String shadowContractHash,
        String shadowFeatureListHash
    ) {
        public MLMetadata(
            Double botProbability,
            Integer isBotFlag,
            String threatClass,
            String evaluationStatus,
            Double shadowBotProbability,
            Integer shadowIsBotFlag,
            String shadowThreatClass,
            String shadowAction,
            String shadowStatus,
            Double prodInferenceLatencyMs,
            Double shadowInferenceLatencyMs,
            String contractHash,
            String modelVersion,
            Double shadowThreshold,
            String decisionSource,
            Double scoringDepth,
            Long scoringTimestampMs
        ) {
            this(botProbability, isBotFlag, threatClass, evaluationStatus, shadowBotProbability,
                 shadowIsBotFlag, shadowThreatClass, shadowAction, shadowStatus, prodInferenceLatencyMs,
                 shadowInferenceLatencyMs, contractHash, modelVersion, shadowThreshold, decisionSource,
                 scoringDepth, scoringTimestampMs, null, null, null, null);
        }

        public MLMetadata(
            Double botProbability,
            Integer isBotFlag,
            String threatClass,
            String evaluationStatus,
            Double shadowBotProbability,
            Integer shadowIsBotFlag,
            String shadowThreatClass,
            String shadowAction,
            String shadowStatus,
            Double prodInferenceLatencyMs,
            Double shadowInferenceLatencyMs,
            String contractHash,
            String modelVersion,
            Double shadowThreshold
        ) {
            this(botProbability, isBotFlag, threatClass, evaluationStatus, shadowBotProbability,
                 shadowIsBotFlag, shadowThreatClass, shadowAction, shadowStatus, prodInferenceLatencyMs,
                 shadowInferenceLatencyMs, contractHash, modelVersion, shadowThreshold, "fresh",
                 null, null, null, null, null, null);
        }

        public MLMetadata(
            Double botProbability,
            Integer isBotFlag,
            String threatClass,
            String evaluationStatus,
            Double shadowBotProbability,
            Integer shadowIsBotFlag,
            String shadowThreatClass,
            String shadowAction,
            String shadowStatus,
            Double prodInferenceLatencyMs,
            Double shadowInferenceLatencyMs,
            String contractHash,
            String modelVersion,
            Double shadowThreshold,
            String decisionSource
        ) {
            this(botProbability, isBotFlag, threatClass, evaluationStatus, shadowBotProbability,
                 shadowIsBotFlag, shadowThreatClass, shadowAction, shadowStatus, prodInferenceLatencyMs,
                 shadowInferenceLatencyMs, contractHash, modelVersion, shadowThreshold, decisionSource,
                 null, null, null, null, null, null);
        }
    }
}