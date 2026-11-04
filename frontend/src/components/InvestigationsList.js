import React, { useState, useEffect } from 'react';

export default function InvestigationsList({ api, onSelect }) {
  const [investigations, setInvestigations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [deleting, setDeleting] = useState(null);

  const load = async () => {
    try {
      const res = await fetch(`${api}/investigations/`);
      const data = await res.json();
      setInvestigations(data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    const interval = setInterval(load, 5000);
    return () => clearInterval(interval);
  }, [api]);

  const handleDelete = async (e, id) => {
    e.stopPropagation();
    if (!window.confirm(`Delete investigation #${id}?`)) return;
    setDeleting(id);
    try {
      await fetch(`${api}/investigations/${id}`, { method: 'DELETE' });
      setInvestigations(prev => prev.filter(inv => inv.id !== id));
    } catch (err) {
      console.error('Delete failed', err);
    } finally {
      setDeleting(null);
    }
  };

  if (loading) return <div style={styles.loading}>Loading investigations...</div>;
  if (!investigations.length) return (
    <div style={styles.empty}>
      No investigations yet. Click "Trigger Investigation" to run the first one.
    </div>
  );

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        Recent Investigations
        <span style={styles.count}>{investigations.length} total</span>
      </div>
      <div style={styles.list}>
        {investigations.map(inv => (
          <div
            key={inv.id}
            onClick={() => onSelect(inv.id)}
            style={styles.row}
          >
            <div style={styles.rowLeft}>
              <div style={styles.invId}>#{inv.id}</div>
              <div>
                <div style={styles.metric}>{inv.triggered_metric}</div>
                <div style={styles.preview}>{inv.conclusion_preview || '—'}</div>
              </div>
            </div>
            <div style={styles.rowRight}>
              <div style={{
                ...styles.status,
                color: inv.status === 'completed' ? '#68d391' : inv.status === 'running' ? '#f6ad55' : '#fc8181',
              }}>
                {inv.status === 'completed' ? 'Done' : inv.status === 'running' ? 'Running' : 'Failed'}
              </div>
              <div style={styles.magnitude}>
                {inv.magnitude_pct > 0 ? '+' : ''}{inv.magnitude_pct?.toFixed(1)}%
              </div>
              <div style={styles.testsRun}>
                {inv.tests_run} test{inv.tests_run !== 1 ? 's' : ''}
              </div>
              <div style={styles.timestamp}>
                {new Date(inv.created_at).toLocaleTimeString()}
              </div>
              <button
                onClick={(e) => handleDelete(e, inv.id)}
                disabled={deleting === inv.id}
                style={{
                  ...styles.deleteBtn,
                  opacity: deleting === inv.id ? 0.4 : 1,
                }}
                title="Delete investigation"
              >
                Delete
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

const styles = {
  container: { display: 'flex', flexDirection: 'column', gap: 12 },
  loading: { color: '#718096', padding: 40, textAlign: 'center' },
  empty: { color: '#718096', padding: 40, textAlign: 'center', fontSize: 14 },
  header: {
    fontSize: 11, fontWeight: 700, color: '#e2e8f0',
    display: 'flex', alignItems: 'center', gap: 10,
  },
  count: {
    background: '#2d3748', color: '#a0aec0',
    borderRadius: 10, padding: '2px 8px', fontSize: 11,
  },
  list: { display: 'flex', flexDirection: 'column', gap: 6 },
  row: {
    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    background: '#1a1f2e', border: '1px solid #2d3748',
    borderRadius: 8, padding: '12px 16px', cursor: 'pointer',
    transition: 'border-color 0.15s',
  },
  rowLeft: { display: 'flex', gap: 12, alignItems: 'flex-start' },
  invId: { fontSize: 11, color: '#718096', minWidth: 28, marginTop: 2 },
  metric: { fontSize: 11, fontWeight: 600, color: '#e2e8f0' },
  preview: { fontSize: 12, color: '#718096', marginTop: 2, maxWidth: 500 },
  rowRight: { display: 'flex', gap: 16, alignItems: 'center' },
  status: { fontSize: 12, fontWeight: 600 },
  magnitude: { fontSize: 16, fontWeight: 700, color: '#fc8181', minWidth: 50, textAlign: 'right' },
  testsRun: { fontSize: 11, color: '#718096', minWidth: 50, textAlign: 'center' },
  timestamp: { fontSize: 11, color: '#718096', minWidth: 70, textAlign: 'right' },
  deleteBtn: {
    background: 'none', border: '1px solid #4a5568', borderRadius: 4,
    color: '#fc8181', cursor: 'pointer', fontSize: 11,
    padding: '2px 6px', lineHeight: 1,
  },
};
