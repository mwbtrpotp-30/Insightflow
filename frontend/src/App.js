import React, { useState, useCallback } from 'react';
import MetricsDashboard from './components/MetricsDashboard';
import InvestigationPanel from './components/InvestigationPanel';
import InvestigationsList from './components/InvestigationsList';
import NLQueryPanel from './components/NLQueryPanel';

const API = '';  // uses proxy → http://localhost:8000

const SCENARIOS = [
  {
    id: 1,
    label: '1 — Composition Shift',
    desc: 'Google Ads surge floods with low-retention users',
    hint: 'Google Ads paid acquisition surged from 25 to 95 users/day. New paid users have much lower activation (35%) and retention (22%) than organic users. The drop is driven by a composition shift — more low-quality paid users dragging down aggregate retention.',
    metric: 'retention_rate', current: 0.31, baseline: 0.47,
  },
  {
    id: 2,
    label: '2 — Behavioral Change',
    desc: 'UI regression blocks core feature across all segments',
    hint: 'A UI regression introduced 5 days ago is blocking the core feature for users across all acquisition channels. Feature adoption has dropped to 15% of normal. All segments are affected equally — this is a within-group behavioral change, not a composition shift.',
    metric: 'retention_rate', current: 0.29, baseline: 0.46,
  },
  {
    id: 3,
    label: '3 — Cohort Age Effect',
    desc: 'Viral signup spike; users too new to return yet',
    hint: 'Organic signups spiked from 40 to 180/day and referral from 15 to 90/day due to a viral moment. These new users have the same quality as historic users but are too new to have returned yet — the retention drop is a cohort age effect, not real churn.',
    metric: 'retention_rate', current: 0.33, baseline: 0.45,
  },
  {
    id: 4,
    label: '4 — Data Pipeline Artifact',
    desc: 'SDK stops firing session events — not real churn',
    hint: 'The analytics SDK stopped firing session_start and feature_use events for 90% of users over the past 4 days. Actual user behavior is unchanged — this is a data pipeline artifact, not real user churn. Event volume will show a sharp drop.',
    metric: 'retention_rate', current: 0.12, baseline: 0.46,
  },
];

const METRICS = [
  { value: 'retention_rate', label: 'Retention Rate' },
  { value: 'activation_rate', label: 'Activation Rate' },
  { value: 'feature_adoption_rate', label: 'Feature Adoption' },
];

export default function App() {
  const [tab, setTab] = useState('metrics');
  const [selectedInvId, setSelectedInvId] = useState(null);
  const [triggerResult, setTriggerResult] = useState(null);
  const [triggering, setTriggering] = useState(false);
  const [monitorResult, setMonitorResult] = useState(null);
  const [monitorLoading, setMonitorLoading] = useState(false);

  const [selectedScenario, setSelectedScenario] = useState(1);
  const [loadingScenario, setLoadingScenario] = useState(false);
  const [scenarioStatus, setScenarioStatus] = useState(null);
  const [selectedMetric, setSelectedMetric] = useState('retention_rate');

  const handleLoadScenario = useCallback(async () => {
    setLoadingScenario(true);
    setScenarioStatus(null);
    try {
      const res = await fetch(`${API}/api/load-scenario/${selectedScenario}`, { method: 'POST' });
      const data = await res.json();
      if (res.ok) {
        setScenarioStatus({ ok: true, msg: `Loaded: ${data.label} — ${data.users} users, ${data.events} events` });
      } else {
        setScenarioStatus({ ok: false, msg: `Error: ${data.detail}` });
      }
    } catch (e) {
      setScenarioStatus({ ok: false, msg: `Network error: ${e.message}` });
    } finally {
      setLoadingScenario(false);
    }
  }, [selectedScenario]);

  const handleMonitorCheck = useCallback(async () => {
    setMonitorLoading(true);
    setMonitorResult(null);
    try {
      const res = await fetch(`${API}/api/monitor/check`, { method: 'POST' });
      const data = await res.json();
      setMonitorResult(data);
      if (data.anomalies_fired > 0) {
        setTab('investigations');
      }
    } catch (e) {
      setMonitorResult({ error: e.message });
    } finally {
      setMonitorLoading(false);
    }
  }, []);

  const handleTrigger = useCallback(async () => {
    setTriggering(true);
    const scenario = SCENARIOS.find(s => s.id === selectedScenario) || SCENARIOS[0];
    try {
      await fetch(`${API}/api/load-scenario/${scenario.id}`, { method: 'POST' });

      // Fetch real current and baseline values for the selected metric from the DB
      let currentValue = scenario.current;
      let baselineValue = scenario.baseline;
      try {
        const mRes = await fetch(`${API}/metrics/retention?days=30`
          .replace('retention', selectedMetric === 'retention_rate' ? 'retention'
            : selectedMetric === 'activation_rate' ? 'activation'
            : 'feature_adoption'));
        const mData = await mRes.json();
        const points = mData.points || [];
        if (points.length >= 14) {
          const recent = points.slice(-7).map(p => p.value);
          const baseline = points.slice(-14, -7).map(p => p.value);
          const avg = arr => arr.reduce((s, v) => s + v, 0) / arr.length;
          currentValue = parseFloat(avg(recent).toFixed(4));
          baselineValue = parseFloat(avg(baseline).toFixed(4));
        }
      } catch (_) { /* fall back to scenario values */ }

      const res = await fetch(`${API}/investigations/trigger`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          metric_name: selectedMetric,
          current_value: currentValue,
          baseline_value: baselineValue,
          time_window_days: 7,
          scenario_hint: scenario.hint,
        }),
      });
      const data = await res.json();
      setTriggerResult(data);
      setSelectedInvId(data.investigation_id);
      setTab('investigation');
    } catch (e) {
      console.error(e);
    } finally {
      setTriggering(false);
    }
  }, [selectedScenario, selectedMetric]);

  return (
    <div style={styles.app}>
      <header style={styles.header}>
        <div style={styles.headerLeft}>
          <span style={styles.logo}>InsightFlow</span>
          <span style={styles.tagline}>Product Analytics</span>
        </div>

        <div style={styles.scenarioPicker}>
          <span style={styles.scenarioLabel}>Demo Scenario</span>
          <select
            value={selectedScenario}
            onChange={e => { setSelectedScenario(Number(e.target.value)); setScenarioStatus(null); }}
            style={styles.scenarioSelect}
            title={SCENARIOS.find(s => s.id === selectedScenario)?.desc}
          >
            {SCENARIOS.map(s => (
              <option key={s.id} value={s.id}>{s.label}</option>
            ))}
          </select>
          <button onClick={handleLoadScenario} disabled={loadingScenario} style={styles.loadBtn}>
            {loadingScenario ? 'Loading...' : 'Load'}
          </button>
          {scenarioStatus && (
            <span style={{ ...styles.statusMsg, color: scenarioStatus.ok ? '#68d391' : '#fc8181' }}>
              {scenarioStatus.msg}
            </span>
          )}
        </div>

        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <button
            onClick={handleMonitorCheck}
            disabled={monitorLoading}
            style={styles.monitorBtn}
            title="Scan all metrics for anomalies automatically"
          >
            {monitorLoading ? 'Scanning...' : 'Auto-Detect'}
          </button>
          {monitorResult && !monitorLoading && (
            <span style={{ fontSize: 12, color: monitorResult.anomalies_fired > 0 ? '#fc8181' : '#68d391' }}>
              {monitorResult.error
                ? `Error: ${monitorResult.error}`
                : monitorResult.anomalies_fired > 0
                  ? `${monitorResult.anomalies_fired} anomaly detected`
                  : 'All metrics normal'}
            </span>
          )}
          <select
            value={selectedMetric}
            onChange={e => setSelectedMetric(e.target.value)}
            style={styles.metricSelect}
            disabled={triggering}
            title="Select metric to investigate"
          >
            {METRICS.map(m => (
              <option key={m.value} value={m.value}>{m.label}</option>
            ))}
          </select>
          <button
            onClick={handleTrigger}
            disabled={triggering}
            style={styles.triggerBtn}
            title="Start an investigation for the selected metric"
          >
            {triggering ? 'Investigating...' : 'Investigate'}
          </button>
        </div>
      </header>

      <nav style={styles.nav}>
        {[
          { id: 'metrics', label: 'Metrics' },
          { id: 'investigations', label: 'Investigations' },
          { id: 'investigation', label: 'Analysis Trace' },
          { id: 'query', label: 'Ask Data' },
        ].map(t => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            style={{ ...styles.navBtn, ...(tab === t.id ? styles.navBtnActive : {}) }}
          >
            {t.label}
          </button>
        ))}
      </nav>

      <main style={styles.main}>
        {tab === 'metrics' && <MetricsDashboard api={API} />}
        {tab === 'investigations' && (
          <InvestigationsList
            api={API}
            onSelect={(id) => { setSelectedInvId(id); setTab('investigation'); }}
          />
        )}
        {tab === 'investigation' && (
          <InvestigationPanel api={API} investigationId={selectedInvId} />
        )}
        {tab === 'query' && <NLQueryPanel api={API} />}
      </main>
    </div>
  );
}

const styles = {
  app: {
    fontFamily: "'Inter', 'Segoe UI', system-ui, sans-serif",
    background: '#0f1117',
    color: '#e2e8f0',
    minHeight: '100vh',
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '12px 24px',
    background: '#1a1f2e',
    borderBottom: '1px solid #2d3748',
    gap: 16,
    flexWrap: 'wrap',
  },
  headerLeft: { display: 'flex', alignItems: 'center', gap: 12 },
  logo: { fontSize: 18, fontWeight: 700, color: '#63b3ed', letterSpacing: '-0.3px' },
  tagline: { fontSize: 12, color: '#718096' },
  scenarioPicker: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    flex: 1,
    flexWrap: 'wrap',
  },
  scenarioLabel: { fontSize: 12, color: '#a0aec0', whiteSpace: 'nowrap' },
  scenarioSelect: {
    background: '#2d3748',
    color: '#e2e8f0',
    border: '1px solid #4a5568',
    borderRadius: 6,
    padding: '6px 10px',
    fontSize: 13,
    cursor: 'pointer',
    minWidth: 220,
  },
  loadBtn: {
    background: '#2b6cb0',
    color: '#fff',
    border: 'none',
    borderRadius: 6,
    padding: '6px 14px',
    cursor: 'pointer',
    fontWeight: 600,
    fontSize: 13,
    whiteSpace: 'nowrap',
  },
  statusMsg: { fontSize: 12, maxWidth: 340 },
  monitorBtn: {
    background: '#276749',
    color: '#fff',
    border: 'none',
    borderRadius: 6,
    padding: '7px 14px',
    cursor: 'pointer',
    fontWeight: 600,
    fontSize: 13,
    whiteSpace: 'nowrap',
  },
  metricSelect: {
    background: '#2d3748',
    color: '#e2e8f0',
    border: '1px solid #4a5568',
    borderRadius: 6,
    padding: '6px 10px',
    fontSize: 13,
    cursor: 'pointer',
  },
  triggerBtn: {
    background: '#c53030',
    color: '#fff',
    border: 'none',
    borderRadius: 6,
    padding: '7px 16px',
    cursor: 'pointer',
    fontWeight: 600,
    fontSize: 13,
    whiteSpace: 'nowrap',
  },
  nav: {
    display: 'flex',
    gap: 2,
    padding: '6px 24px',
    background: '#151822',
    borderBottom: '1px solid #2d3748',
  },
  navBtn: {
    background: 'transparent',
    color: '#718096',
    border: 'none',
    borderRadius: 6,
    padding: '7px 14px',
    cursor: 'pointer',
    fontSize: 13,
    fontWeight: 500,
  },
  navBtnActive: {
    background: '#2d3748',
    color: '#e2e8f0',
  },
  main: { padding: 24 },
};
