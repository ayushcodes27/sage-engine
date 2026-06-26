import { Activity } from "lucide-react";
import Card from "./common/Card";

export default function EndpointHeatmap({ hotspots }) {
  const maxHits = hotspots.length ? hotspots[0].hits : 1;

  return (
    <Card title="Endpoint Hotspots (Top 5)" className="fade-in-delay-3">
      <div className="endpoint-heatmap-list">
        {hotspots.length ? (
          hotspots.map((row) => (
            <div key={row.path} className="endpoint-heatmap-row" style={{ display: 'grid', gridTemplateColumns: '1fr 60px', alignItems: 'center', gap: '8px' }}>
              <div style={{ position: 'relative', height: '28px', backgroundColor: '#1d1d22', borderRadius: '4px', overflow: 'hidden' }}>
                <div
                  className={`threat-${row.dominantClass}`}
                  style={{ 
                    position: 'absolute', top: 0, left: 0, height: '100%', 
                    width: `${Math.max(2, (row.hits / maxHits) * 100)}%`, 
                    opacity: 0.4,
                    transition: 'width 0.4s ease'
                  }}
                />
                <div style={{ position: 'absolute', top: 0, left: '8px', height: '100%', display: 'flex', alignItems: 'center', right: '8px' }}>
                  <span className="mono endpoint-path" style={{ fontSize: '0.75rem', color: '#fff', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{row.path}</span>
                </div>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', justifyContent: 'center' }}>
                <span className="mono" style={{ fontSize: '0.85rem', fontWeight: 'bold' }}>{row.hits}</span>
                <span style={{ fontSize: '0.6rem', color: 'var(--text-muted)', textTransform: 'uppercase' }}>{row.dominantClass}</span>
              </div>
            </div>
          ))
        ) : (
          <div className="empty-state-container" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '180px', color: 'var(--text-muted)' }}>
            <Activity size={32} className="pulse-warn" style={{ marginBottom: '12px', color: 'var(--throttle)', borderRadius: '50%' }} />
            <p style={{ margin: 0, fontSize: '0.85rem' }}>Waiting for traffic...</p>
          </div>
        )}
      </div>
    </Card>
  );
}
