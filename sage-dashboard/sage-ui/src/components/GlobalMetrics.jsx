import Card from "./common/Card";
import { formatNumber } from "../utils/formatters";

export default function GlobalMetrics({ metrics }) {
  return (
    <div className="metric-grid fade-in-delay-1" style={{ gridTemplateColumns: 'repeat(3, 1fr)' }}>
      <Card title="Total Requests" className="metric-card-neutral">
        <p className="metric-value" style={{ fontSize: '2.4rem' }}>{formatNumber(metrics.totalRequests)}</p>
      </Card>
      <Card title="Threats Blocked" className="metric-card-urgent">
        <p className="metric-value metric-danger" style={{ fontSize: '2.4rem' }}>{formatNumber(metrics.threatsBlocked)}</p>
      </Card>
      <Card title="Throttled Requests" className="metric-card-warn">
        <p className="metric-value metric-warn" style={{ fontSize: '2.4rem' }}>{formatNumber(metrics.throttledRequests)}</p>
      </Card>
    </div>
  );
}
