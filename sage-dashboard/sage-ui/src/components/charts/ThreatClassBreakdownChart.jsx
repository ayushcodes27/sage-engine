import Card from "../common/Card";
import { formatPercent } from "../../utils/formatters";

const CLASS_COLORS = {
  human: "#2f8f4e",
  scraper: "#9e3d3d",
  flood: "#d14e4e",
  recon: "#b7852e",
};

const LABELS = {
  human: "Human",
  scraper: "Scraper",
  flood: "Flood",
  recon: "Recon",
};

export default function ThreatClassBreakdownChart({ totals }) {
  const total = Object.values(totals).reduce((acc, value) => acc + value, 0);
  const rows = Object.keys(CLASS_COLORS).map((key) => ({
    key,
    name: LABELS[key],
    value: totals[key] || 0,
  }));

  return (
    <Card title="Threat Class Distribution" className="fade-in-delay-2">
      <div className="distribution-wrap">
        <div className="distribution-bar-stack" aria-label="Threat class distribution segmented bar">
          {total === 0 ? (
            <span className="distribution-segment" style={{ width: '100%', backgroundColor: '#222228' }} />
          ) : (
            rows.map((entry) => {
              const segmentPercent = total ? (entry.value / total) * 100 : 0;
              return (
                <span
                  key={entry.key}
                  className="distribution-segment"
                  style={{
                    width: `${segmentPercent}%`,
                    backgroundColor: CLASS_COLORS[entry.key],
                  }}
                />
              );
            })
          )}
        </div>

        <div className="legend-list mono">
          {rows.map((entry) => {
            const percent = total ? (entry.value / total) * 100 : 0;
            const displayPercent = Math.max(5, percent);
            const isZero = entry.value === 0;
            return (
              <div 
                key={entry.key} 
                className="legend-item" 
                style={{ 
                  borderLeft: `3px solid ${CLASS_COLORS[entry.key]}`, 
                  paddingLeft: '8px',
                  paddingTop: '4px',
                  paddingBottom: '4px',
                  position: 'relative', 
                  zIndex: 1
                }}
              >
                <div 
                  style={{ 
                    position: 'absolute', 
                    top: 0, left: 0, height: '100%', 
                    width: `${displayPercent}%`, 
                    backgroundColor: CLASS_COLORS[entry.key], 
                    opacity: isZero ? 0.1 : 0.2, 
                    zIndex: -1,
                    transition: 'width 0.3s ease'
                  }} 
                />
                <span>{entry.name}</span>
                <span>{entry.value}</span>
                <strong style={{ color: !isZero ? CLASS_COLORS[entry.key] : 'inherit' }}>{formatPercent(percent)}</strong>
              </div>
            );
          })}
        </div>
      </div>
    </Card>
  );
}
