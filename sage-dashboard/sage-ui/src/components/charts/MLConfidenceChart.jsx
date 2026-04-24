import { Cell, Pie, PieChart, ResponsiveContainer } from "recharts";
import Card from "../common/Card";

function getConfidenceLabel(score) {
  if (score >= 75) return "High Threat";
  if (score >= 45) return "Suspicious";
  return "Likely Benign";
}

export default function MLConfidenceChart({ score, hasData = true }) {
  const clampedScore = Math.max(0, Math.min(100, score));
  const data = hasData ? [
    { name: "Score", value: clampedScore },
    { name: "Remaining", value: 100 - clampedScore },
  ] : [
    { name: "Empty", value: 100 }
  ];

  return (
    <Card title="ML Confidence" className="fade-in-delay-2">
      <div className="ml-wrap">
        <div className="chart-wrap small">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie 
                data={data} 
                dataKey="value" 
                innerRadius={45} 
                outerRadius={70} 
                startAngle={90} 
                endAngle={-270}
                stroke="none"
              >
                {!hasData ? (
                  <Cell fill="#222228" opacity={0.5} />
                ) : (
                  <>
                    <Cell fill="#9e3d3d" />
                    <Cell fill="#222228" />
                  </>
                )}
              </Pie>
            </PieChart>
          </ResponsiveContainer>
        </div>
        <div className="ml-info mono">
          {!hasData ? (
            <p className="ml-label" style={{ color: "var(--text-muted)", fontStyle: "italic", marginTop: "12px" }}>No data yet</p>
          ) : (
            <>
              <p className="ml-score">{clampedScore.toFixed(1)}%</p>
              <p className="ml-label">{getConfidenceLabel(clampedScore)}</p>
            </>
          )}
        </div>
        <div style={{ textAlign: "center", marginTop: "4px" }}>
          <span style={{ fontSize: "0.65rem", color: "var(--text-muted)", display: "flex", alignItems: "center", justifyContent: "center", gap: "4px" }}>
            <span style={{ width: "8px", height: "8px", backgroundColor: "#9e3d3d", borderRadius: "2px" }}></span>
            Bot Probability Score
          </span>
        </div>
      </div>
    </Card>
  );
}
