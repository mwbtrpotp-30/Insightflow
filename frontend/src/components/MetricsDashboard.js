import React, { useState, useEffect } from 'react';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  Legend, ResponsiveContainer, BarChart, Bar
} from 'recharts';

const CHANNEL_COLORS = {
  retention_organic: '#48bb78',
  retention_referral: '#63b3ed',
  retention_facebook_ads: '#f6ad55',
  retention_google_ads: '#fc8181',
};

export default function MetricsDashboard({ api }) {
  const [retention, setRetention] = useState([]);
  const [dau, setDau] = useState([]);
  const [channelRetention, setChannelRetention] = useState([]);
  const [funnel, setFunnel] = useState({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = async () => {
      try {
        const [r1, r2, r3, r4] = await Promise.all([
          fetch(`${api}/metrics/retention?days=30`).then(r => r.json()),
          fetch(`${api}/metrics/dau?days=30`).then(r => r.json()),
          fetch(`${api}/metrics/retention_by_channel?days=30`).then(r => r.json()),
          fetch(`${api}/metrics/funnel`).then(r => r.json()),
        ]);
        setRetention(r1.points || []);
        setDau(r2.points || []);

        // Merge channel retention into date-keyed rows
        const merged = {};
        (r3 || []).forEach(series => {
          const key = series.metric_name; // retention_google_ads etc
          series.points.forEach(p => {
            if (!merged[p.date]) merged[p.date] = { date: p.date };
            merged[p.date][key] = p.value;
          });
        });
        setChannelRetention(Object.values(merged).sort((a, b) => a.date.localeCompare(b.date)));
        setFunnel(r4);
      } catch (e) {
        console.error(e);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [api]);

  const funnelData = [
    { step: 'Signup', users: funnel.signup || 0 },
    { step: 'Onboarding', users: funnel.onboarding_complete || 0 },
    { step: 'Feature Used', users: funnel.feature_used || 0 },
    { step: 'Session Start', users: funnel.session_start || 0 },
  ];

  if (loading) return <div style={styles.loading}>Loading metrics...</div>;

  // Find the anomaly dip (last 7 points)
  const recentRetention = retention.slice(-7);
  const baselineRetention = retention.slice(-21, -7);
  const recentAvg = recentRetention.reduce((s, p) => s + p.value, 0) / (recentRetention.length || 1);
  const baselineAvg = baselineRetention.reduce((s, p) => s + p.value, 0) / (baselineRetention.length || 1);
  const drop = baselineAvg > 0 ? ((recentAvg - baselineAvg) / baselineAvg * 100) : 0;

  return (
    <div style={styles.container}>
      {/* Anomaly Alert Banner */}
      {drop < -5 && (
        <div style={styles.alertBanner}>
          
          <div>
            <strong>Anomaly Detected:</strong> Retention rate dropped {Math.abs(drop).toFixed(1)}%
            vs prior period ({baselineAvg.toFixed(1)}% → {recentAvg.toFixed(1)}%).
            Click <strong>"Trigger Investigation"</strong> to run the adaptive causal analysis.
          </div>
        </div>
      )}

      {/* Stat Cards */}
      <div style={styles.statRow}>
        <StatCard label="Avg Retention (Recent 7d)" value={`${recentAvg.toFixed(1)}%`} change={drop} />
        <StatCard label="Avg Retention (Baseline)" value={`${baselineAvg.toFixed(1)}%`} />
        <StatCard label="Total Signups (7d)" value={funnel.signup?.toLocaleString() || '–'} />
        <StatCard label="Feature Adoption" value={`${funnel.feature_used ? Math.round(funnel.feature_used/funnel.signup*100) : 0}%`} />
      </div>

      <div style={styles.chartsGrid}>
        {/* Aggregate Retention */}
        <ChartCard title="Retention Rate — Last 30 Days" subtitle="% of all-time users who were active each day">
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={retention} margin={{ top: 5, right: 10, bottom: 5, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#2d3748" />
              <XAxis dataKey="date" tick={{ fill: '#718096', fontSize: 10 }} tickFormatter={d => d.slice(5)} />
              <YAxis tick={{ fill: '#718096', fontSize: 10 }} tickFormatter={v => `${v}%`} />
              <Tooltip
                contentStyle={{ background: '#1a1f2e', border: '1px solid #2d3748', color: '#e2e8f0' }}
                formatter={(v) => [`${v}%`, 'Retention']}
              />
              <Line type="monotone" dataKey="value" stroke="#63b3ed" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </ChartCard>

        {/* Retention by Channel */}
        <ChartCard title="Retention by Acquisition Channel" subtitle="Shows Google Ads users dragging aggregate down">
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={channelRetention} margin={{ top: 5, right: 10, bottom: 5, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#2d3748" />
              <XAxis dataKey="date" tick={{ fill: '#718096', fontSize: 10 }} tickFormatter={d => d.slice(5)} />
              <YAxis tick={{ fill: '#718096', fontSize: 10 }} tickFormatter={v => `${v}%`} />
              <Tooltip
                contentStyle={{ background: '#1a1f2e', border: '1px solid #2d3748', color: '#e2e8f0' }}
                formatter={(v, name) => [`${v}%`, name.replace('retention_', '')]}
              />
              <Legend formatter={n => n.replace('retention_', '')} />
              {Object.keys(CHANNEL_COLORS).map(key => (
                <Line key={key} type="monotone" dataKey={key}
                  stroke={CHANNEL_COLORS[key]} strokeWidth={1.5} dot={false} />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </ChartCard>

        {/* DAU */}
        <ChartCard title="Daily Active Users" subtitle="Session starts + feature usage">
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={dau} margin={{ top: 5, right: 10, bottom: 5, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#2d3748" />
              <XAxis dataKey="date" tick={{ fill: '#718096', fontSize: 10 }} tickFormatter={d => d.slice(5)} />
              <YAxis tick={{ fill: '#718096', fontSize: 11 }} />
              <Tooltip contentStyle={{ background: '#1a1f2e', border: '1px solid #2d3748', color: '#e2e8f0' }} />
              <Line type="monotone" dataKey="value" stroke="#68d391" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </ChartCard>

        {/* Funnel */}
        <ChartCard title="Activation Funnel (Last 7 Days)">
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={funnelData} margin={{ top: 5, right: 10, bottom: 5, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#2d3748" />
              <XAxis dataKey="step" tick={{ fill: '#718096', fontSize: 11 }} />
              <YAxis tick={{ fill: '#718096', fontSize: 11 }} />
              <Tooltip contentStyle={{ background: '#1a1f2e', border: '1px solid #2d3748', color: '#e2e8f0' }} />
              <Bar dataKey="users" fill="#805ad5" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>
      </div>
    </div>
  );
}

function StatCard({ label, value, change }) {
  return (
    <div style={styles.statCard}>
      <div style={styles.statLabel}>{label}</div>
      <div style={styles.statValue}>{value}</div>
      {change !== undefined && (
        <div style={{ color: change < 0 ? '#fc8181' : '#68d391', fontSize: 12, marginTop: 2 }}>
          {change > 0 ? '+' : ''}{change.toFixed(1)}% vs prior period
        </div>
      )}
    </div>
  );
}

function ChartCard({ title, subtitle, children }) {
  return (
    <div style={styles.chartCard}>
      <div style={styles.chartTitle}>{title}</div>
      {subtitle && <div style={styles.chartSubtitle}>{subtitle}</div>}
      {children}
    </div>
  );
}

const styles = {
  container: { display: 'flex', flexDirection: 'column', gap: 20 },
  loading: { color: '#718096', padding: 40, textAlign: 'center' },
  alertBanner: {
    display: 'flex', alignItems: 'flex-start', gap: 12,
    background: '#742a2a', border: '1px solid #fc8181',
    borderRadius: 8, padding: '12px 16px', color: '#fed7d7',
  },
  alertIcon: { fontSize: 20, flexShrink: 0 },
  statRow: { display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 },
  statCard: {
    background: '#1a1f2e', border: '1px solid #2d3748',
    borderRadius: 8, padding: '14px 16px',
  },
  statLabel: { fontSize: 11, color: '#718096', textTransform: 'uppercase', letterSpacing: 1 },
  statValue: { fontSize: 26, fontWeight: 700, color: '#e2e8f0', marginTop: 4 },
  chartsGrid: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 },
  chartCard: {
    background: '#1a1f2e', border: '1px solid #2d3748',
    borderRadius: 8, padding: '16px',
  },
  chartTitle: { fontSize: 14, fontWeight: 600, color: '#e2e8f0', marginBottom: 2 },
  chartSubtitle: { fontSize: 11, color: '#718096', marginBottom: 12 },
};
