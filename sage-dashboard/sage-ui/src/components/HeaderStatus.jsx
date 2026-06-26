import { formatUptime } from "../utils/formatters";

function ServiceDot({ status }) {
  const pulseClass = status === 'throttle' ? 'pulse-warn' : '';
  return <span className={`status-dot status-${status} ${pulseClass}`} aria-hidden="true" />;
}

export default function HeaderStatus({ services, metrics }) {
  return (
    <header className="dashboard-header fade-in">
      <div>
        <h1>SAGE Command Center</h1>
        <p>Threat telemetry, traffic controls, and ML defense insights</p>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '12px' }}>
        <div className="uptime-badge" style={{ fontSize: '0.82rem', color: 'var(--text-muted)' }}>
          System Uptime: <strong className="mono" style={{ color: 'var(--text)', marginLeft: '6px' }}>{formatUptime(metrics?.uptimeSeconds || 0)}</strong>
        </div>
        <div className="service-grid">
          {services.map((service) => {
            const isConnecting = service.name === "ML Service" && service.meta === "-- ms";
            return (
              <div key={service.name} className="service-item">
                <ServiceDot status={service.status} />
                <span>{service.name}</span>
                {service.meta ? (
                  isConnecting ? (
                    <strong className="connecting-text" style={{ fontSize: '0.7rem', color: 'var(--text-muted)', animation: 'pulse 1.5s infinite' }}>Connecting...</strong>
                  ) : (
                    <strong>{service.meta}</strong>
                  )
                ) : null}
              </div>
            );
          })}
        </div>
      </div>
    </header>
  );
}
