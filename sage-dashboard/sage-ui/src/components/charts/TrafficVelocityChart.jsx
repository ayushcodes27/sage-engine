import {
  CartesianGrid,
  RadialBar,
  RadialBarChart,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import Card from "../common/Card";

export default function TrafficVelocityChart({ data }) {
  const latestRps = data.length ? data[data.length - 1].rps : 0;
  const maxRps = Math.max(120, ...data.map((point) => point.rps || 0));
  const gaugeValue = Math.max(0, Math.min(100, (latestRps / maxRps) * 100));

  return (
    <Card title="Traffic Velocity (RPS)" className="fade-in-delay-2">
      <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
        <div className="gauge-wrap" style={{ height: '140px', position: 'relative' }}>
          <ResponsiveContainer width="100%" height="100%">
            <RadialBarChart
              cx="50%"
              cy="80%"
              innerRadius="65%"
              outerRadius="100%"
              barSize={14}
              data={[{ name: "rps", value: gaugeValue, fill: "#2f8f4e" }]}
              startAngle={180}
              endAngle={0}
            >
              <RadialBar dataKey="value" cornerRadius={10} background />
            </RadialBarChart>
          </ResponsiveContainer>

          <div style={{ position: 'absolute', bottom: '15%', left: '15%', color: 'var(--text-muted)', fontSize: '0.65rem' }}>0</div>
          <div style={{ position: 'absolute', top: '15%', left: '22%', color: 'var(--text-muted)', fontSize: '0.65rem' }}>{Math.round(maxRps * 0.25)}</div>
          <div style={{ position: 'absolute', top: '0', left: '50%', transform: 'translateX(-50%)', color: 'var(--text-muted)', fontSize: '0.65rem' }}>{Math.round(maxRps * 0.5)}</div>
          <div style={{ position: 'absolute', top: '15%', right: '22%', color: 'var(--text-muted)', fontSize: '0.65rem' }}>{Math.round(maxRps * 0.75)}</div>
          <div style={{ position: 'absolute', bottom: '15%', right: '15%', color: 'var(--text-muted)', fontSize: '0.65rem' }}>{Math.round(maxRps)}</div>

          <div className="gauge-readout mono" style={{ bottom: '10px' }}>
            <strong style={{ fontSize: '1.8rem' }}>{latestRps.toFixed(1)}</strong>
            <span style={{ fontSize: '0.65rem' }}>RPS</span>
          </div>
        </div>

        <div className="velocity-sparkline" style={{ height: '60px', marginTop: '10px' }}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data}>
              <CartesianGrid stroke="#222228" vertical={false} />
              <XAxis dataKey="tick" tick={false} axisLine={false} tickLine={false} />
              <Tooltip
                contentStyle={{
                  backgroundColor: "#141417",
                  border: "1px solid #222228",
                  borderRadius: "8px",
                  color: "#e8e8ec",
                  padding: "4px 8px",
                  fontSize: "0.75rem"
                }}
              />
              <Line type="monotone" dataKey="rps" stroke="#8fa0b8" strokeWidth={1.5} dot={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
    </Card>
  );
}
