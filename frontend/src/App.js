import React, { useState, useCallback } from 'react';
import MetricsDashboard from './components/MetricsDashboard';
import InvestigationPanel from './components/InvestigationPanel';
import InvestigationsList from './components/InvestigationsList';
import NLQueryPanel from './components/NLQueryPanel';

const API = '';  // uses proxy → http://localhost:8000

// The agent is never told which scenario is loaded — Trigger only names the
// metric, and the backend measures its values from whatever data is in the DB.
const SCENARIOS = [
  { id: 1, label: '1 — Composition Shift', desc: 'Google Ads surge floods with low-retention users' },
  { id: 2, label: '2 — Behavioral Change', desc: 'UI regression blocks core feature across all segments' },
  { id: 3, label: '3 — Cohort Age Effect', desc: 'Viral signup spike; users too new to return yet' },
  { id: 4, label: '4 — Data Pipeline Artifact', desc: 'SDK stops firing session events — not real churn' },
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

  const handleLoadScenario = useCallback(async () => {
    setLoadingScenario(true);
    setScenarioStatus(null);
    try {
      const res = await fetch(`${API}/api/load-scenario/${selectedScenario}`, { method: 'POST' });
      const data = await res.json();
      if (res.ok) {
        setScenarioStatus({ ok: true, msg: `✅ Loaded: ${data.label} — ${data.users} users, ${data.events} events` });
      } else {
        setScenarioStatus({ ok: false, msg: `❌ Error: ${data.detail}` });
      }
    } catch (e) {
      setScenarioStatus({ ok: false, msg: `❌ Network error: ${e.message}` });
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
    try {
      const res = await fetch(`${API}/investigations/trigger`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          metric_name: 'retention_rate',
          time_window_days: 7,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        alert(`Could not start investigation: ${data.detail}`);
        return;
      }
      setTriggerResult(data);
      setSelectedInvId(data.investigation_id);
      setTab('investigation');
    } catch (e) {
      console.error(e);
    } finally {
      setTriggering(false);
    }
  }, []);

  return (
    <div style={styles.app}>
      {/* Header */}
      <header style={styles.header}>
        <div style={styles.headerLeft}>
          <span style={styles.logo}>⚡ InsightFlow</span>
          <span style={styles.tagline}>Agentic Product Analytics</span>
        </div>

        {/* Scenario Picker */}
        <div style={styles.scenarioPicker}>
          <span style={styles.scenarioLabel}>Demo Scenario:</span>
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
          <button
            onClick={handleLoadScenario}
            disabled={loadingScenario}
            style={styles.loadBtn}
          >
            {loadingScenario ? '⏳ Loading...' : '⬇ Load'}
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
            title="Run KS-test anomaly detector across all metrics"
          >
            {monitorLoading ? '⏳ Scanning...' : '📡 Auto-Detect'}
          </button>
          {monitorResult && !monitorLoading && (
            <span style={{ fontSize: 12, color: monitorResult.anomalies_fired > 0 ? '#fc8181' : '#68d391' }}>
              {monitorResult.error
                ? `❌ ${monitorResult.error}`
                : monitorResult.anomalies_fired > 0
                  ? `🚨 ${monitorResult.anomalies_fired} anomaly detected!`
                  : `✅ All normal`}
            </span>
          )}
          <button
            onClick={handleTrigger}
            disabled={triggering}
            style={styles.triggerBtn}
            title="Manually trigger investigation for selected scenario"
          >
            {triggering ? '🔍 Investigating...' : '🚨 Trigger'}
          </button>
        </div>
      </header>

      {/* Tabs */}
      <nav style={styles.nav}>
        {[
          { id: 'metrics', label: '📊 Metrics' },
          { id: 'investigations', label: '🔍 Investigations' },
          { id: 'investigation', label: '🧠 Investigation Trace' },
          { id: 'query', label: '💬 Ask Data' },
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

      {/* Content */}
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
  logo: { fontSize: 20, fontWeight: 700, color: '#63b3ed' },
  tagline: { fontSize: 13, color: '#718096' },
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
  statusMsg: {
    fontSize: 12,
    maxWidth: 340,
  },
  monitorBtn: {
    background: '#2f855a',
    color: '#fff',
    border: 'none',
    borderRadius: 6,
    padding: '8px 14px',
    cursor: 'pointer',
    fontWeight: 600,
    fontSize: 13,
    whiteSpace: 'nowrap',
  },
  triggerBtn: {
    background: '#e53e3e',
    color: '#fff',
    border: 'none',
    borderRadius: 6,
    padding: '8px 16px',
    cursor: 'pointer',
    fontWeight: 600,
    fontSize: 13,
    whiteSpace: 'nowrap',
  },
  nav: {
    display: 'flex',
    gap: 2,
    padding: '8px 24px',
    background: '#151822',
    borderBottom: '1px solid #2d3748',
  },
  navBtn: {
    background: 'transparent',
    color: '#a0aec0',
    border: 'none',
    borderRadius: 6,
    padding: '8px 16px',
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
