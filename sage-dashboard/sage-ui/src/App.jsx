import React, { useState, useEffect } from 'react';
import { io } from 'socket.io-client';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, PieChart, Pie, Cell } from 'recharts';
import { Activity, ShieldCheck, ShieldAlert, Server, ChevronDown, ChevronUp } from 'lucide-react';

// Connect to your Node.js Bridge
const socket = io('http://localhost:6006');

export default function App() {
  const [isConnected, setIsConnected] = useState(false);
  const [events, setEvents] = useState([]);
  const [stats, setStats] = useState({ total: 0, blocked: 0, throttled: 0, allowed: 0 });
  const [expandedRow, setExpandedRow] = useState(null);

  useEffect(() => {
    socket.on('connect', () => setIsConnected(true));
    socket.on('disconnect', () => setIsConnected(false));

    socket.on('telemetry_update', (data) => {
      setEvents((prev) => {
        // Keep the last 50 events in the Kill Feed to prevent memory leaks
        const newEvents = [data, ...prev].slice(0, 50);
        return newEvents;
      });

      setStats((prev) => {
        const isBlock = data.response?.status === 403;
        const isThrottle = data.response?.status === 429;
        return {
          total: prev.total + 1,
          blocked: prev.blocked + (isBlock ? 1 : 0),
          throttled: prev.throttled + (isThrottle ? 1 : 0),
          allowed: prev.allowed + (!isBlock && !isThrottle ? 1 : 0),
        };
      });
    });

    return () => {
      socket.off('connect');
      socket.off('disconnect');
      socket.off('telemetry_update');
    };
  }, []);

  // Calculate Action Distribution Percentages
  const allowPct = stats.total ? ((stats.allowed / stats.total) * 100).toFixed(1) : 0;
  const throttlePct = stats.total ? ((stats.throttled / stats.total) * 100).toFixed(1) : 0;
  const blockPct = stats.total ? ((stats.blocked / stats.total) * 100).toFixed(1) : 0;

  // Mock threat distribution based on recent blocks
  const threatData = [
    { name: 'Benign', value: stats.allowed || 1 },
    { name: 'Bot/Scraper', value: stats.blocked || 0 },
    { name: 'Flood', value: stats.throttled || 0 }
  ];
  const COLORS = ['#10b981', '#f59e0b', '#ef4444'];

  const toggleRow = (id) => {
    setExpandedRow(expandedRow === id ? null : id);
  };

  return (
      <div className="min-h-screen bg-slate-900 text-slate-200 p-6 font-sans">

        {/* HEADER */}
        <header className="flex justify-between items-center mb-8 border-b border-slate-700 pb-4">
          <div>
            <h1 className="text-3xl font-bold text-white flex items-center gap-3">
              <ShieldCheck className="text-emerald-500" size={32} />
              SAGE Command Center
            </h1>
            <p className="text-slate-400 mt-1 text-sm">Real-Time Threat Intelligence & API Gateway Monitoring</p>
          </div>
          <div className="flex gap-6 text-sm font-semibold">
            <div className="flex items-center gap-2">
              <div className={`w-3 h-3 rounded-full ${isConnected ? 'bg-emerald-500 animate-pulse' : 'bg-red-500'}`}></div>
              <span>Kafka: {isConnected ? 'Connected' : 'Offline'}</span>
            </div>
            <div className="flex items-center gap-2">
              <Server className="text-blue-400" size={16} />
              <span>Gateway: Active</span>
            </div>
            <div className="flex items-center gap-2">
              <Activity className="text-purple-400" size={16} />
              <span>ML Service: Active ({events[0]?.response?.latencyMs || 0}ms avg)</span>
            </div>
          </div>
        </header>

        {/* TOP ROW: Global Stats & Action Distribution */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-8">
          <div className="bg-slate-800 rounded-lg p-6 border border-slate-700 shadow-lg">
            <h2 className="text-slate-400 text-sm font-bold tracking-wider mb-2">TOTAL REQUESTS</h2>
            <p className="text-4xl font-bold text-white">{stats.total.toLocaleString()}</p>
          </div>
          <div className="bg-slate-800 rounded-lg p-6 border border-slate-700 shadow-lg">
            <h2 className="text-slate-400 text-sm font-bold tracking-wider mb-2">THREATS BLOCKED</h2>
            <p className="text-4xl font-bold text-red-500">{stats.blocked.toLocaleString()}</p>
          </div>
          <div className="bg-slate-800 rounded-lg p-6 border border-slate-700 shadow-lg">
            <h2 className="text-slate-400 text-sm font-bold tracking-wider mb-4">ACTION DISTRIBUTION</h2>
            <div className="w-full bg-slate-700 h-4 rounded-full flex overflow-hidden">
              <div style={{ width: `${allowPct}%` }} className="bg-emerald-500 h-full transition-all duration-500"></div>
              <div style={{ width: `${throttlePct}%` }} className="bg-yellow-500 h-full transition-all duration-500"></div>
              <div style={{ width: `${blockPct}%` }} className="bg-red-500 h-full transition-all duration-500"></div>
            </div>
            <div className="flex justify-between mt-2 text-xs font-bold">
              <span className="text-emerald-500">ALLOW {allowPct}%</span>
              <span className="text-yellow-500">THROTTLE {throttlePct}%</span>
              <span className="text-red-500">BLOCK {blockPct}%</span>
            </div>
          </div>
        </div>

        {/* ANALYSIS ROW */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-8">

          {/* Threat Donut Chart */}
          <div className="bg-slate-800 rounded-lg p-6 border border-slate-700 shadow-lg flex flex-col items-center">
            <h2 className="text-slate-400 text-sm font-bold tracking-wider w-full mb-4">THREAT CLASSIFICATION</h2>
            <div className="h-48 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={threatData} innerRadius={60} outerRadius={80} paddingAngle={5} dataKey="value">
                    {threatData.map((entry, index) => (
                        <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip contentStyle={{ backgroundColor: '#1e293b', borderColor: '#334155' }} />
                </PieChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Rolling Latency Chart */}
          <div className="bg-slate-800 rounded-lg p-6 border border-slate-700 shadow-lg lg:col-span-2">
            <h2 className="text-slate-400 text-sm font-bold tracking-wider mb-4">GATEWAY LATENCY (ms)</h2>
            <div className="h-48 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={[...events].reverse()}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                  <XAxis dataKey="timestamp" hide />
                  <YAxis stroke="#94a3b8" />
                  <Tooltip contentStyle={{ backgroundColor: '#1e293b', borderColor: '#334155' }} />
                  <Line type="monotone" dataKey="response.latencyMs" stroke="#8b5cf6" strokeWidth={2} dot={false} isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>

        {/* BOTTOM ROW: The Kill Feed */}
        <div className="bg-slate-800 rounded-lg border border-slate-700 shadow-lg overflow-hidden">
          <div className="p-4 border-b border-slate-700 bg-slate-800 flex justify-between items-center">
            <h2 className="text-slate-400 text-sm font-bold tracking-wider">LIVE EVENT KILL FEED</h2>
            <div className="flex items-center gap-2 text-xs text-slate-400">
              <span className="w-2 h-2 rounded-full bg-emerald-500"></span> Allow
              <span className="w-2 h-2 rounded-full bg-yellow-500 ml-2"></span> Tier 1 (429)
              <span className="w-2 h-2 rounded-full bg-red-500 ml-2"></span> Tier 2 ML (403)
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="bg-slate-900 text-slate-400">
              <tr>
                <th className="px-6 py-3">Timestamp</th>
                <th className="px-6 py-3">IP Address</th>
                <th className="px-6 py-3">Target Path</th>
                <th className="px-6 py-3">ML Confidence</th>
                <th className="px-6 py-3">Action</th>
                <th className="px-6 py-3"></th>
              </tr>
              </thead>
              <tbody>
              {events.length === 0 ? (
                  <tr><td colSpan="6" className="text-center py-8 text-slate-500">Waiting for gateway traffic...</td></tr>
              ) : events.map((event, idx) => {
                const isBlocked = event.response?.status === 403;
                const isThrottled = event.response?.status === 429;
                const statusColor = isBlocked ? 'text-red-500' : isThrottled ? 'text-yellow-500' : 'text-emerald-500';
                const actionText = isBlocked ? 'BLOCK (403)' : isThrottled ? 'THROTTLE (429)' : 'ALLOW (200)';

                const timeStr = new Date(event.timestamp).toLocaleTimeString();
                const prob = event.mlMetadata?.botProbability || 0;

                return (
                    <React.Fragment key={event.eventId || idx}>
                      <tr className="border-b border-slate-700 hover:bg-slate-750 transition-colors">
                        <td className="px-6 py-4 font-mono text-xs">{timeStr}</td>
                        <td className="px-6 py-4 font-mono">{event.request?.ip || event.userId || 'Unknown'}</td>
                        <td className="px-6 py-4 text-slate-400">{event.request?.path || '/api/unknown'}</td>
                        <td className="px-6 py-4">{(prob * 100).toFixed(1)}%</td>
                        <td className={`px-6 py-4 font-bold ${statusColor}`}>{actionText}</td>
                        <td className="px-6 py-4 text-right cursor-pointer" onClick={() => toggleRow(event.eventId)}>
                          {expandedRow === event.eventId ? <ChevronUp size={18} /> : <ChevronDown size={18} />}
                        </td>
                      </tr>

                      {/* EXPANDED RAW FEATURES ROW */}
                      {expandedRow === event.eventId && (
                          <tr className="bg-slate-900 border-b border-slate-700">
                            <td colSpan="6" className="px-6 py-4">
                              <div className="grid grid-cols-4 gap-4 text-xs font-mono text-slate-400">
                                <div className="bg-slate-800 p-2 rounded border border-slate-700">
                                  <span className="block text-slate-500 mb-1">Session Depth</span>
                                  <span className="text-white">{event.mlMetadata?.isBotFlag === 1 ? '> 5 (Ban Threshold Met)' : 'Analyzing...'}</span>
                                </div>
                                <div className="bg-slate-800 p-2 rounded border border-slate-700">
                                  <span className="block text-slate-500 mb-1">Temporal Variance</span>
                                  <span className="text-white">Extracted via Redis</span>
                                </div>
                                <div className="bg-slate-800 p-2 rounded border border-slate-700">
                                  <span className="block text-slate-500 mb-1">Request Velocity</span>
                                  <span className="text-white">Monitored</span>
                                </div>
                                <div className="bg-slate-800 p-2 rounded border border-slate-700">
                                  <span className="block text-slate-500 mb-1">Behavioral Diversity</span>
                                  <span className="text-white">Active</span>
                                </div>
                              </div>
                            </td>
                          </tr>
                      )}
                    </React.Fragment>
                );
              })}
              </tbody>
            </table>
          </div>
        </div>
      </div>
  );
}