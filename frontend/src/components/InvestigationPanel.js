import React, { useState, useEffect, useRef } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell
} from 'recharts';

const TEST_LABELS = {
  kitagawa_oaxaca:       'User Mix Analysis',
  segment_share_drift:   'Segment Breakdown',
  funnel_drop_test:      'Funnel Drop Check',
  feature_adoption_test: 'Feature Usage Check',
  cohort_age_test:       'New User Age Check',
  event_volume_test:     'Data Volume Check',
};

const HYPOTHESIS_LABELS = {
  composition_shift: 'User mix changed',
  behavioral_change: 'User behavior changed',
  feature_rollout:   'A feature change caused this',
  cohort_age_effect: 'New users are too recent to count',
  data_artifact:     'Tracking or data issue',
};

function friendlyTestName(name) {
  if (!name) return name;
  return TEST_LABELS[name] || name.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

function friendlyLabel(label, id) {
  if (id && HYPOTHESIS_LABELS[id]) return HYPOTHESIS_LABELS[id];
  return label;
}

export default function InvestigationPanel({ api, investigationId }) {
  const [investigation, setInvestigation] = useState(null);
  const [loading, setLoading] = useState(false);
  const [selectedStep, setSelectedStep] = useState(0);
  const pollRef = useRef(null);
  const autoFollow = useRef(true);
  const prevStepCount = useRef(0);

  useEffect(() => {
    if (!investigationId) return;
    setLoading(true);
    setSelectedStep(0);
    autoFollow.current = true;
    prevStepCount.current = 0;

    const poll = async () => {
      try {
        const res = await fetch(`${api}/investigations/${investigationId}`);
        const data = await res.json();
        setInvestigation(prev => {
          const newCount = (data.steps || []).length;
          if (newCount > prevStepCount.current && autoFollow.current) {
            setSelectedStep(newCount - 1);
            prevStepCount.current = newCount;
          }
          return data;
        });
        if (data.status === 'running') {
          pollRef.current = setTimeout(poll, 1500);
        } else {
          setLoading(false);
        }
      } catch (e) {
        setLoading(false);
      }
    };

    poll();
    return () => clearTimeout(pollRef.current);
  }, [api, investigationId]);

  if (!investigationId) {
    return (
      <div style={styles.empty}>
        <div style={{ fontSize: 15, color: '#a0aec0', marginBottom: 6 }}>No investigation selected</div>
        <div style={{ fontSize: 13, color: '#718096' }}>
          Select a metric and click <strong>Investigate</strong>, or pick one from the Investigations tab.
        </div>
      </div>
    );
  }

  if (!investigation) return <div style={styles.loading}>Loading...</div>;

  const steps = investigation.steps || [];
  const currentStep = steps[selectedStep];
  const prevStep = selectedStep > 0 ? steps[selectedStep - 1] : null;
  const isRunning = investigation.status === 'running';

  return (
    <div style={styles.container}>
      <div style={styles.invHeader}>
        <div style={styles.invMeta}>
          <span style={styles.invId}>Investigation #{investigation.id}</span>
          <StatusBadge status={investigation.status} />
          {isRunning && (
            <span style={styles.runningText}>Step {steps.length + 1} in progress...</span>
          )}
        </div>
        <div style={styles.invStats}>
          <div style={styles.statBlock}>
            <span style={styles.statLabel}>{investigation.triggered_metric?.replace(/_/g, ' ')}</span>
            <span style={{ ...styles.statValue, color: '#fc8181' }}>
              {investigation.magnitude_pct > 0 ? '+' : ''}{investigation.magnitude_pct?.toFixed(1)}%
            </span>
          </div>
          <div style={styles.statBlock}>
            <span style={styles.statLabel}>steps done</span>
            <span style={styles.statValue}>{investigation.tests_run}</span>
          </div>
          {isRunning && (
            <div style={styles.statBlock}>
              <span style={styles.statLabel}>max steps</span>
              <span style={{ ...styles.statValue, color: '#a0aec0' }}>6</span>
            </div>
          )}
        </div>
      </div>

      <div style={styles.mainGrid}>
        <div style={styles.stepsPanel}>
          <div style={styles.panelTitle}>Analysis Steps</div>

          {steps.length === 0 && isRunning && (
            <div style={styles.loadingSteps}>
              <div style={styles.spinner} />
              Choosing the first check to run...
            </div>
          )}

          {steps.map((step, i) => (
            <div
              key={i}
              onClick={() => { autoFollow.current = false; setSelectedStep(i); }}
              style={{ ...styles.stepCard, ...(selectedStep === i ? styles.stepCardActive : {}) }}
            >
              <div style={styles.stepNumber}>Step {step.step_number}</div>
              <div style={styles.stepName}>{friendlyTestName(step.test_name)}</div>
              <div style={styles.stepRationale}>{step.test_rationale}</div>
              <div style={styles.stepResult}>{step.result_summary}</div>
              {step.eliminated?.length > 0 && (
                <div style={styles.eliminated}>
                  Ruled out: {step.eliminated.map(e => HYPOTHESIS_LABELS[e] || e).join(', ')}
                </div>
              )}
            </div>
          ))}

          {isRunning && steps.length > 0 && (
            <div style={styles.thinkingCard}>
              <div style={styles.spinner} />
              <div>
                <div style={{ fontSize: 12, color: '#a0aec0', fontWeight: 600 }}>Step {steps.length + 1}</div>
                <div style={{ fontSize: 11, color: '#718096', marginTop: 2 }}>Choosing and running next check...</div>
              </div>
            </div>
          )}
        </div>

        <div style={styles.rightPanel}>
          {currentStep && (
            <>
              <div style={styles.panelTitle}>
                How likely is each explanation?
                {prevStep && (
                  <span style={{ fontSize: 10, color: '#718096', fontWeight: 400, marginLeft: 8 }}>
                    change from step {prevStep.step_number}
                  </span>
                )}
              </div>
              <HypothesisChart
                hypotheses={currentStep.hypotheses_after}
                prevHypotheses={prevStep ? prevStep.hypotheses_after : null}
              />

              {prevStep && currentStep.hypotheses_after && (
                <ConfidenceDeltaSummary
                  current={currentStep.hypotheses_after}
                  prev={prevStep.hypotheses_after}
                />
              )}

              <HypothesisReasoningPanel hypotheses={currentStep.hypotheses_after} />

              <div style={{ ...styles.panelTitle, marginTop: 16 }}>Evidence</div>
              <EvidenceBlock evidence={currentStep.evidence} />

              {currentStep.intermediate_conclusion && (
                <div style={styles.intermediateCard}>
                  <div style={styles.panelTitle}>Current Assessment (Step {currentStep.step_number})</div>
                  <p style={styles.intermediateText}>{currentStep.intermediate_conclusion}</p>
                </div>
              )}
            </>
          )}

          {!currentStep && steps.length === 0 && !isRunning && (
            <div style={{ color: '#718096', fontSize: 13 }}>No steps recorded.</div>
          )}

          {investigation.status === 'completed' && (!currentStep || selectedStep === steps.length - 1) && (
            <div style={styles.conclusionCard}>
              <div style={styles.panelTitle}>Conclusion</div>
              <p style={styles.conclusionText}>{investigation.conclusion}</p>
              <div style={{ ...styles.panelTitle, marginTop: 12 }}>What to do</div>
              <p style={styles.recommendationText}>{investigation.recommendation}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function StatusBadge({ status }) {
  const map = {
    running:   { bg: '#2d3748', color: '#f6ad55', label: 'Running' },
    completed: { bg: '#1a4731', color: '#68d391', label: 'Done' },
    failed:    { bg: '#742a2a', color: '#fc8181', label: 'Failed' },
  };
  const c = map[status] || map.running;
  return (
    <span style={{ ...styles.badge, background: c.bg, color: c.color }}>
      {c.label}
    </span>
  );
}

function HypothesisReasoningPanel({ hypotheses }) {
  const [open, setOpen] = React.useState(false);
  if (!hypotheses || hypotheses.length === 0) return null;

  return (
    <div style={{ marginTop: 14 }}>
      <button onClick={() => setOpen(o => !o)} style={styles.toggleBtn}>
        {open ? 'Hide' : 'Show'} reasoning behind each explanation
      </button>
      {open && (
        <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 8 }}>
          {[...hypotheses].sort((a, b) => b.confidence - a.confidence).map(h => (
            <div key={h.id} style={{
              background: '#151822',
              border: `1px solid ${h.active ? '#2d3748' : '#1a1f2e'}`,
              borderRadius: 6,
              padding: '8px 12px',
              opacity: h.active ? 1 : 0.5,
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                <span style={{ fontSize: 12, fontWeight: 600, color: h.active ? '#e2e8f0' : '#718096' }}>
                  {friendlyLabel(h.label, h.id)}
                </span>
                <span style={{ fontSize: 11, color: '#a0aec0' }}>
                  {h.active ? `${Math.round(h.confidence * 100)}%` : 'ruled out'}
                </span>
              </div>
              <div style={{ fontSize: 11, color: '#718096', lineHeight: 1.5 }}>
                {h.description}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ConfidenceDeltaSummary({ current, prev }) {
  if (!current || !prev) return null;

  const prevMap = {};
  prev.forEach(h => { prevMap[h.id] = h.confidence; });

  const deltas = current
    .map(h => ({
      label: friendlyLabel(h.label, h.id).split(' ').slice(0, 3).join(' '),
      delta: h.confidence - (prevMap[h.id] || h.confidence),
      active: h.active,
    }))
    .filter(d => Math.abs(d.delta) > 0.001)
    .sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta));

  if (deltas.length === 0) return (
    <div style={{ fontSize: 11, color: '#4a5568', marginTop: 6, marginBottom: 4 }}>
      No significant change from previous step.
    </div>
  );

  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 6, marginBottom: 4 }}>
      {deltas.map((d, i) => (
        <span key={i} style={{
          fontSize: 11,
          background: d.delta > 0 ? '#1a3a1a' : '#3a1a1a',
          color: d.delta > 0 ? '#68d391' : '#fc8181',
          border: `1px solid ${d.delta > 0 ? '#276749' : '#742a2a'}`,
          borderRadius: 4,
          padding: '2px 7px',
        }}>
          {d.delta > 0 ? '+' : '-'} {d.label}: {(Math.abs(d.delta) * 100).toFixed(1)}%
        </span>
      ))}
    </div>
  );
}

function HypothesisChart({ hypotheses, prevHypotheses }) {
  if (!hypotheses || hypotheses.length === 0) return (
    <div style={{ color: '#718096', fontSize: 12, padding: '12px 0' }}>No data for this step.</div>
  );

  const prevMap = {};
  if (prevHypotheses) {
    prevHypotheses.forEach(h => { prevMap[h.id] = h.confidence; });
  }

  const data = [...hypotheses]
    .sort((a, b) => b.confidence - a.confidence)
    .map(h => ({
      id: h.id,
      name: friendlyLabel(h.label, h.id).split(' ').slice(0, 4).join(' '),
      confidence: Math.round(h.confidence * 100),
      active: h.active,
      delta: prevMap[h.id] !== undefined ? h.confidence - prevMap[h.id] : 0,
    }));

  return (
    <div>
      <ResponsiveContainer width="100%" height={180}>
        <BarChart data={data} layout="vertical" margin={{ top: 0, right: 40, bottom: 0, left: 120 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#2d3748" horizontal={false} />
          <XAxis type="number" domain={[0, 100]} tick={{ fill: '#718096', fontSize: 10 }} tickFormatter={v => `${v}%`} />
          <YAxis type="category" dataKey="name" tick={{ fill: '#a0aec0', fontSize: 10 }} width={120} />
          <Tooltip
            contentStyle={{ background: '#1a1f2e', border: '1px solid #2d3748', color: '#e2e8f0' }}
            formatter={(v, name, props) => {
              const d = props.payload;
              const deltaStr = d.delta !== 0
                ? ` (${d.delta > 0 ? '+' : ''}${(d.delta * 100).toFixed(1)}% from prev step)`
                : '';
              return [`${v}%${deltaStr}`, 'Likelihood'];
            }}
          />
          <Bar dataKey="confidence" radius={[0, 4, 4, 0]}>
            {data.map((d, i) => (
              <Cell
                key={i}
                fill={
                  !d.active ? '#2d3748'
                  : d.delta > 0.02 ? '#48bb78'
                  : d.delta < -0.02 ? '#fc8181'
                  : i === 0 ? '#63b3ed'
                  : '#4a5568'
                }
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <div style={{ fontSize: 10, color: '#4a5568', marginTop: 2 }}>
        Green = more likely &nbsp;·&nbsp; Red = less likely &nbsp;·&nbsp; Blue = leading &nbsp;·&nbsp; Grey = ruled out
      </div>
    </div>
  );
}

function EvidenceBlock({ evidence }) {
  if (!evidence) return null;

  if (evidence.segments) {
    return (
      <div style={styles.evidenceBlock}>
        {evidence.composition_share_pct !== undefined && (
          <div style={styles.evidenceRow}>
            <span style={styles.evidenceKey}>How much is due to user mix changing</span>
            <span style={{ color: '#f6ad55' }}>{evidence.composition_share_pct}%</span>
          </div>
        )}
        {evidence.rate_share_pct !== undefined && (
          <div style={styles.evidenceRow}>
            <span style={styles.evidenceKey}>How much is due to behavior changing</span>
            <span style={{ color: '#63b3ed' }}>{evidence.rate_share_pct}%</span>
          </div>
        )}
        <div style={{ marginTop: 8, fontSize: 11, color: '#718096' }}>Breakdown by channel:</div>
        {evidence.segments.map((s, i) => (
          <div key={i} style={styles.segmentRow}>
            <span style={{ color: '#e2e8f0', fontWeight: 500 }}>{s.channel}</span>
            <span style={{ color: '#a0aec0' }}>
              {(s.baseline_rate * 100).toFixed(0)}% then, {(s.current_rate * 100).toFixed(0)}% now
            </span>
            <span style={{ color: '#718096' }}>
              share: {(s.weight_baseline * 100).toFixed(0)}% then, {(s.weight_current * 100).toFixed(0)}% now
            </span>
          </div>
        ))}
      </div>
    );
  }

  return (
    <div style={styles.evidenceBlock}>
      {Object.entries(evidence).map(([k, v]) => {
        if (typeof v === 'object') return null;
        return (
          <div key={k} style={styles.evidenceRow}>
            <span style={styles.evidenceKey}>{k.replace(/_/g, ' ')}</span>
            <span style={{ color: '#e2e8f0' }}>
              {typeof v === 'number'
                ? (k.includes('pct') || k.includes('rate') ? `${(v * 100).toFixed(1)}%` : v.toFixed ? v.toFixed(3) : v)
                : String(v)}
            </span>
          </div>
        );
      })}
    </div>
  );
}

const styles = {
  container: { display: 'flex', flexDirection: 'column', gap: 16 },
  empty: {
    display: 'flex', flexDirection: 'column', alignItems: 'center',
    justifyContent: 'center', height: 300, color: '#718096',
  },
  loading: { color: '#718096', padding: 40, textAlign: 'center' },
  invHeader: {
    background: '#1a1f2e', border: '1px solid #2d3748',
    borderRadius: 8, padding: '14px 16px',
    display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between',
  },
  invMeta: { display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' },
  invId: { fontSize: 15, fontWeight: 700, color: '#e2e8f0' },
  runningText: { fontSize: 12, color: '#f6ad55', fontStyle: 'italic' },
  invStats: { display: 'flex', gap: 24, alignItems: 'center' },
  statBlock: { textAlign: 'center' },
  statLabel: { fontSize: 11, color: '#718096', display: 'block' },
  statValue: { fontSize: 22, fontWeight: 700, color: '#63b3ed', display: 'block' },
  badge: { borderRadius: 4, padding: '2px 8px', fontSize: 12, fontWeight: 600 },
  mainGrid: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 },
  stepsPanel: {
    background: '#1a1f2e', border: '1px solid #2d3748',
    borderRadius: 8, padding: 16, display: 'flex', flexDirection: 'column', gap: 8,
  },
  rightPanel: {
    background: '#1a1f2e', border: '1px solid #2d3748',
    borderRadius: 8, padding: 16,
  },
  panelTitle: {
    fontSize: 11, fontWeight: 700, color: '#a0aec0',
    textTransform: 'uppercase', letterSpacing: 0.5,
    marginBottom: 10, display: 'flex', alignItems: 'center', gap: 8,
  },
  stepCard: {
    background: '#151822', border: '1px solid #2d3748',
    borderRadius: 6, padding: '10px 12px', cursor: 'pointer',
    transition: 'border-color 0.15s',
  },
  stepCardActive: { border: '1px solid #63b3ed', background: '#1a2744' },
  stepNumber: { fontSize: 10, color: '#718096', textTransform: 'uppercase', letterSpacing: 1 },
  stepName: { fontSize: 13, fontWeight: 600, color: '#e2e8f0', marginTop: 2 },
  stepRationale: { fontSize: 11, color: '#718096', marginTop: 4, fontStyle: 'italic' },
  stepResult: { fontSize: 12, color: '#a0aec0', marginTop: 6 },
  eliminated: { fontSize: 11, color: '#fc8181', marginTop: 4 },
  loadingSteps: {
    color: '#718096', fontSize: 13, padding: '12px 0',
    display: 'flex', gap: 8, alignItems: 'center',
  },
  thinkingCard: {
    background: '#151822', border: '1px dashed #4a5568',
    borderRadius: 6, padding: '10px 12px',
    display: 'flex', gap: 10, alignItems: 'center',
    opacity: 0.8,
  },
  spinner: {
    width: 14, height: 14, border: '2px solid #2d3748',
    borderTop: '2px solid #63b3ed', borderRadius: '50%',
    animation: 'spin 0.8s linear infinite',
  },
  toggleBtn: {
    background: 'none', border: '1px solid #2d3748', borderRadius: 4,
    color: '#63b3ed', cursor: 'pointer', fontSize: 11, padding: '4px 10px',
  },
  evidenceBlock: {
    background: '#151822', borderRadius: 6, padding: '10px 12px',
    fontSize: 12, display: 'flex', flexDirection: 'column', gap: 4,
  },
  evidenceRow: { display: 'flex', justifyContent: 'space-between', alignItems: 'center' },
  evidenceKey: { color: '#718096', textTransform: 'capitalize' },
  segmentRow: {
    display: 'flex', justifyContent: 'space-between',
    padding: '2px 0', borderTop: '1px solid #2d3748', fontSize: 11,
  },
  intermediateCard: {
    marginTop: 14, background: '#1a2535',
    border: '1px solid #2c5282', borderRadius: 8, padding: 14,
  },
  intermediateText: { fontSize: 13, color: '#bee3f8', lineHeight: 1.6, margin: '8px 0 0' },
  conclusionCard: {
    marginTop: 16, background: '#1a2f1a',
    border: '1px solid #276749', borderRadius: 8, padding: 14,
  },
  conclusionText: { fontSize: 13, color: '#c6f6d5', lineHeight: 1.6, margin: '8px 0' },
  recommendationText: { fontSize: 13, color: '#9ae6b4', lineHeight: 1.6, margin: '8px 0 0' },
};
