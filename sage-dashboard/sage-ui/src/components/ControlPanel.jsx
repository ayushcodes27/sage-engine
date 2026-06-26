import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import Card from "./common/Card";

const SERVICE_LABELS = {
  allow: "Online",
  throttle: "Degraded",
  block: "Offline",
};

export default function ControlPanel({ services, logCount, isOpen, onToggle }) {
  if (!isOpen) {
    return (
      <aside className="control-column collapsed fade-in-delay-1">
        <button 
          onClick={() => onToggle(true)} 
          className="collapse-toggle-btn" 
          title="Expand Sidebar"
        >
          <PanelLeftOpen size={20} />
        </button>
      </aside>
    );
  }

  return (
    <aside className="control-column expanded fade-in-delay-1">
      <div className="sidebar-header">
        <button 
          onClick={() => onToggle(false)} 
          className="collapse-toggle-btn" 
          title="Collapse Sidebar"
        >
          <PanelLeftClose size={20} />
        </button>
      </div>
      <Card title="Monitoring Scope" className="full-height">
        <div className="monitoring-note">
          Read-only mode enabled. This dashboard only visualizes live telemetry from Gateway, Kafka, Redis, and the ML service.
        </div>

        <div className="process-list-wrap">
          <h4>Service Health</h4>
          <ul className="process-list mono">
            {services.map((service) => (
              <li key={service.name}>
                {service.name}:{" "}
                <span className={service.status === "throttle" ? "service-degraded service-tooltip" : ""}>
                  {SERVICE_LABELS[service.status] || "Unknown"}
                  {service.status === "throttle" && (
                    <span className="tooltip-text">Last ping: {service.lastPing || "Unknown"}</span>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </div>

        <div className="process-list-wrap">
          <h4>Stream Snapshot</h4>
          <ul className="process-list mono">
            <li>Live Threat Rows: {logCount}</li>
            <li>Telemetry Source: Kafka topic gateway-telemetry</li>
            <li>Interaction Mode: Observe-only</li>
          </ul>
        </div>
      </Card>
    </aside>
  );
}
