import Card from "./common/Card";

const FEATURE_LABELS = [
  ["sessionDepth", "Session Depth"],
  ["temporalVariance", "Temporal Variance"],
  ["requestVelocity", "Request Velocity"],
  ["behavioralDiversity", "Behavioral Diversity"],
  ["endpointConcentration", "Endpoint Concentration"],
  ["cartRatio", "Cart Ratio"],
  ["assetSkipRatio", "Asset Skip Ratio"],
];

export default function FeatureMonitor({ features }) {
  const isPopulated = Object.values(features || {}).some(f => f.value > 0);

  return (
    <Card title="Feature Monitor" className="fade-in-delay-3">
      {isPopulated ? (
        <div className="feature-list" style={{ marginTop: '8px' }}>
          {FEATURE_LABELS.map(([key, label]) => {
            const feature = features[key] || { value: 0, percent: 0, unit: "" };
            return (
              <div key={key} style={{ display: 'grid', gridTemplateColumns: '1.2fr 1.5fr 70px', gap: '12px', alignItems: 'center', marginBottom: '8px' }}>
                <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>{label}</span>
                <div className="feature-bar-track" style={{ height: '4px', marginTop: '2px' }}>
                  <div className="feature-bar-fill" style={{ width: `${Math.max(2, feature.percent)}%` }} />
                </div>
                <div style={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'baseline', gap: '4px' }}>
                  <span className="mono" style={{ fontSize: '0.85rem' }}>{feature.value.toFixed(1)}</span>
                  <span style={{ fontSize: '0.65rem', color: 'var(--text-muted)' }}>{feature.unit}</span>
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '220px', color: 'var(--text-muted)' }}>
          <p style={{ margin: 0, fontSize: '0.85rem', fontStyle: 'italic' }}>Awaiting ML feature extraction...</p>
        </div>
      )}
    </Card>
  );
}
