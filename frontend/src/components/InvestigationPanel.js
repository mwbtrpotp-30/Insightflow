import React, { useState, useEffect, useRef } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell
} from 'recharts';

export default function InvestigationPanel({ api, investigationId }) {
  const [investigation, setInvestigation] = useState(null);
  const [loading, setLoading] = useState(false);
  const [selectedStep, setSelectedStep] = useState(0);
  const pollRef = useRef(null);

  useEffect(() => {
    if (!investigationId) return;
    setLoading(true);
    setSelectedStep(0);

    const poll = async () => {
      try {
        const res = await fetch(`${api}/investigations/${investigationId}`);
        const data = await res.json();
        setInvestigation(data);
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
        <div style={{ fontSize: 40, marginBottom: 12 }}>🧠</div>
        <div style={{ fontSize: 16, color: '#a0aec0' }}>No investigation selected.</div>
        <div style={{ fontSize: 13, color: '#718096', marginTop: 6 }}>
          Click <strong>"Trigger Investigation"</strong> in the header, or select one from the Investigations tab.
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
      {/* Investigation Header */}
      <div style={styles.invHeader}>
        <div style={styles.invMeta}>
          <span style={styles.invId}>Investigation #{investigation.id}</span>
          <StatusBadge status={investigation.status} />
          {isRunning && <span style={styles.runningDots}>running adaptive investigation...</span>}
        </div>
        <div style={styles.invStats}>
          <div style={styles.metricDrop}>
            <span style={styles.metricName}>{investigation.triggered_metric}</span>
            <span style={styles.metricChange}>
              {investigation.magnitude_pct > 0 ? '+' : ''}{investigation.magnitude_pct?.toFixed(1)}%
            </span>
          </div>
          <div style={styles.testCount}>
            <span style={styles.testCountNum}>{investigation.tests_run}</span>
            <span style={styles.testCountLabel}>tests run</span>
          </div>
          <div style={styles.testCount}>
            <span style={{ fontSize: 22, fontWeight: 700, color: '#68d391', display: 'block' }}>
              {Math.max(0, 6 - (investigation.tests_run || 0))}
            </span>
            <span style={styles.testCountLabel}>budget saved</span>
          </div>
        </div>
      </div>

      <div style={styles.mainGrid}>
        {/* Step-by-step trace */}
        <div style={styles.stepsPanel}>
          <div style={styles.panelTitle}>
            🔍 Adaptive Investigation Trace
            <span style={styles.noveltyTag}>Novel: Greedy Info-Gain Selector</span>
          </div>

          {steps.length === 0 && isRunning && (
            <div style={styles.loadingSteps}>
              <div style={styles.spinner} />
              Generating hypotheses and selecting first test...
            </div>
          )}

          {steps.map((step, i) => (
            <div
              key={i}
              onClick={() => setSelectedStep(i)}
              style={{
                ...styles.stepCard,
                ...(selectedStep === i ? styles.stepCardActive : {}),
              }}
            >
              <div style={styles.stepNumber}>Step {step.step_number}</div>
              <div style={styles.stepName}>{step.test_name}</div>
              <div style={styles.stepRationale}>{step.test_rationale}</div>
              <div style={styles.stepResult}>{step.result_summary}</div>
              {step.eliminated?.length > 0 && (
                <div style={styles.eliminated}>
                  ❌ Eliminated: {step.eliminated.join(', ')}
                </div>
              )}
            </div>
          ))}
        </div>

        {/* Right panel: hypothesis state at selected step */}
        <div style={styles.rightPanel}>
          {currentStep && (
            <>
              <div style={styles.panelTitle}>
                Hypothesis Confidences After Step {currentStep.step_number}
                {prevStep && (
                  <span style={{ fontSize: 10, color: '#718096', fontWeight: 400, marginLeft: 8 }}>
                    (arrows show change from step {prevStep.step_number})
                  </span>
                )}
              </div>
              <HypothesisChart
                hypotheses={currentStep.hypotheses_after}
                prevHypotheses={prevStep ? prevStep.hypotheses_after : null}
              />

              {/* Confidence change summary */}
              {prevStep && currentStep.hypotheses_after && (
                <ConfidenceDeltaSummary
                  current={currentStep.hypotheses_after}
                  prev={prevStep.hypotheses_after}
                />
              )}

              {/* LLM Hypothesis Reasoning */}
              <HypothesisReasoningPanel hypotheses={currentStep.hypotheses_after} />

              {/* Evidence details */}
              <div style={{ ...styles.panelTitle, marginTop: 16 }}>Evidence</div>
              <EvidenceBlock evidence={currentStep.evidence} />

              {/* Per-step intermediate conclusion */}
              {currentStep.intermediate_conclusion && (
                <div style={styles.intermediateCard}>
                  <div style={styles.panelTitle}>🔎 Current Assessment (Step {currentStep.step_number})</div>
                  <p style={styles.intermediateText}>{currentStep.intermediate_conclusion}</p>
                </div>
              )}
            </>
          )}

          {/* Initial hypotheses (before any step) — only shown when step 0 selected and no prev */}
          {!currentStep && steps.length === 0 && !isRunning && (
            <div style={{ color: '#718096', fontSize: 13 }}>No steps recorded.</div>
          )}

          {/* Final Gemini conclusion — only shown when viewing the last step or no step selected */}
          {investigation.status === 'completed' && (!currentStep || selectedStep === steps.length - 1) && (
            <div style={styles.conclusionCard}>
              <div style={styles.panelTitle}>🎯 Final Conclusion</div>
              <p style={styles.conclusionText}>{investigation.conclusion}</p>
              <div style={{ ...styles.panelTitle, marginTop: 12 }}>💡 Recommendation</div>
              <p style={styles.recommendationText}>{investigation.recommendation}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function StatusBadge({ status }) {
  const colors = {
    running: { bg: '#2d3748', color: '#f6ad55' },
    completed: { bg: '#1a4731', color: '#68d391' },
    failed: { bg: '#742a2a', color: '#fc8181' },
  };
  const c = colors[status] || colors.running;
  return (
    <span style={{ ...styles.badge, background: c.bg, color: c.color }}>
      {status === 'running' ? '⟳ ' : status === 'completed' ? '✓ ' : '✗ '}
      {status}
    </span>
  );
}

/**
 * Shows the LLM's reasoning behind each hypothesis (description field).
 * Collapsible so it doesn't clutter the default view.
 */
function HypothesisReasoningPanel({ hypotheses }) {
  const [open, setOpen] = React.useState(false);
  if (!hypotheses || hypotheses.length === 0) return null;

  return (
    <div style={{ marginTop: 14 }}>
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          background: 'none', border: '1px solid #2d3748', borderRadius: 4,
          color: '#63b3ed', cursor: 'pointer', fontSize: 11, padding: '4px 10px',
          display: 'flex', alignItems: 'center', gap: 6,
        }}
      >
        🤖 {open ? '▲' : '▼'} LLM Hypothesis Reasoning
      </button>
      {open && (
        <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 8 }}>
          {[...hypotheses].sort((a, b) => b.confidence - a.confidence).map(h => (
            <div key={h.id} style={{
              background: '#151822', border: `1px solid ${h.active ? '#2d3748' : '#1a1f2e'}`,
              borderRadius: 6, padding: '8px 12px',
              opacity: h.active ? 1 : 0.5,
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                <span style={{ fontSize: 12, fontWeight: 600, color: h.active ? '#e2e8f0' : '#718096' }}>
                  {h.label}
                </span>
                <span style={{ fontSize: 11, color: '#a0aec0' }}>
                  {h.active ? `${Math.round(h.confidence * 100)}%` : 'eliminated'}
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


/**
 * Shows a small +/- delta summary below the chart so small changes are always visible.
 */
function ConfidenceDeltaSummary({ current, prev }) {
  if (!current || !prev) return null;

  const prevMap = {};
  prev.forEach(h => { prevMap[h.id] = h.confidence; });

  const deltas = current
    .map(h => ({
      label: h.label.split(' ').slice(0, 3).join(' '),
      delta: h.confidence - (prevMap[h.id] || h.confidence),
      active: h.active,
    }))
    .filter(d => Math.abs(d.delta) > 0.001)
    .sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta));

  if (deltas.length === 0) return (
    <div style={{ fontSize: 11, color: '#4a5568', marginTop: 6, marginBottom: 4 }}>
      No significant confidence change from previous step.
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
          {d.delta > 0 ? '▲' : '▼'} {d.label}: {(Math.abs(d.delta) * 100).toFixed(1)}%
        </span>
      ))}
    </div>
  );
}

function HypothesisChart({ hypotheses, prevHypotheses }) {
  if (!hypotheses || hypotheses.length === 0) return (
    <div style={{ color: '#718096', fontSize: 12, padding: '12px 0' }}>No hypothesis data for this step.</div>
  );

  const prevMap = {};
  if (prevHypotheses) {
    prevHypotheses.forEach(h => { prevMap[h.id] = h.confidence; });
  }

  const data = [...hypotheses]
    .sort((a, b) => b.confidence - a.confidence)
    .map(h => ({
      id: h.id,
      name: h.label.split(' ').slice(0, 2).join(' '),
      confidence: Math.round(h.confidence * 100),
      prev: prevMap[h.id] !== undefined ? Math.round(prevMap[h.id] * 100) : null,
      active: h.active,
      delta: prevMap[h.id] !== undefined ? h.confidence - prevMap[h.id] : 0,
    }));

  return (
    <div>
      <ResponsiveContainer width="100%" height={180}>
        <BarChart data={data} layout="vertical" margin={{ top: 0, right: 40, bottom: 0, left: 80 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#2d3748" horizontal={false} />
          <XAxis type="number" domain={[0, 100]} tick={{ fill: '#718096', fontSize: 10 }} tickFormatter={v => `${v}%`} />
          <YAxis type="category" dataKey="name" tick={{ fill: '#a0aec0', fontSize: 11 }} width={80} />
          <Tooltip
            contentStyle={{ background: '#1a1f2e', border: '1px solid #2d3748', color: '#e2e8f0' }}
            formatter={(v, name, props) => {
              const d = props.payload;
              const deltaStr = d.delta !== 0
                ? ` (${d.delta > 0 ? '+' : ''}${(d.delta * 100).toFixed(1)}% from prev step)`
                : '';
              return [`${v}%${deltaStr}`, 'Confidence'];
            }}
          />
          <Bar dataKey="confidence" radius={[0, 4, 4, 0]} label={<DeltaLabel prevMap={prevMap} />}>
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
        🟢 gained confidence · 🔴 lost confidence · 🔵 leading (unchanged) · ⬛ eliminated
      </div>
    </div>
  );
}

/**
 * Custom label that shows Δ% next to each bar when there's a meaningful change.
 */
function DeltaLabel({ prevMap, x, y, width, height, value, name }) {
  // `name` is the display name (2 words), we can't look up prevMap directly.
  // The delta is shown in the ConfidenceDeltaSummary instead.
  return null;
}

function EvidenceBlock({ evidence }) {
  if (!evidence) return null;

  // Render segments if present (K-O decomposition)
  if (evidence.segments) {
    return (
      <div style={styles.evidenceBlock}>
        {evidence.composition_share_pct !== undefined && (
          <div style={styles.evidenceRow}>
            <span style={styles.evidenceKey}>Composition Effect</span>
            <span style={{ color: '#f6ad55' }}>{evidence.composition_share_pct}%</span>
          </div>
        )}
        {evidence.rate_share_pct !== undefined && (
          <div style={styles.evidenceRow}>
            <span style={styles.evidenceKey}>Rate Effect</span>
            <span style={{ color: '#63b3ed' }}>{evidence.rate_share_pct}%</span>
          </div>
        )}
        <div style={{ marginTop: 8, fontSize: 11, color: '#718096' }}>By segment:</div>
        {evidence.segments.map((s, i) => (
          <div key={i} style={styles.segmentRow}>
            <span style={{ color: '#e2e8f0', fontWeight: 500 }}>{s.channel}</span>
            <span style={{ color: '#a0aec0' }}>
              {(s.baseline_rate * 100).toFixed(0)}% → {(s.current_rate * 100).toFixed(0)}%
            </span>
            <span style={{ color: '#718096' }}>
              w: {(s.weight_baseline * 100).toFixed(0)}% → {(s.weight_current * 100).toFixed(0)}%
            </span>
          </div>
        ))}
      </div>
    );
  }

  // Generic evidence rendering
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
  invId: { fontSize: 16, fontWeight: 700, color: '#e2e8f0' },
  runningDots: { fontSize: 12, color: '#f6ad55', fontStyle: 'italic' },
  invStats: { display: 'flex', gap: 20, alignItems: 'center' },
  metricDrop: { textAlign: 'center' },
  metricName: { fontSize: 11, color: '#718096', display: 'block' },
  metricChange: { fontSize: 22, fontWeight: 700, color: '#fc8181' },
  testCount: { textAlign: 'center' },
  testCountNum: { fontSize: 22, fontWeight: 700, color: '#63b3ed', display: 'block' },
  testCountLabel: { fontSize: 11, color: '#718096' },
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
    fontSize: 12, fontWeight: 700, color: '#a0aec0',
    textTransform: 'uppercase', letterSpacing: 0.5,
    marginBottom: 10, display: 'flex', alignItems: 'center', gap: 8,
  },
  noveltyTag: {
    background: '#2d3748', color: '#63b3ed',
    borderRadius: 4, padding: '2px 6px', fontSize: 10,
  },
  stepCard: {
    background: '#151822', border: '1px solid #2d3748',
    borderRadius: 6, padding: '10px 12px', cursor: 'pointer',
    transition: 'border-color 0.15s',
  },
  stepCardActive: {
    border: '1px solid #63b3ed',
    background: '#1a2744',
  },
  stepNumber: { fontSize: 10, color: '#718096', textTransform: 'uppercase', letterSpacing: 1 },
  stepName: { fontSize: 13, fontWeight: 600, color: '#e2e8f0', marginTop: 2 },
  stepRationale: { fontSize: 11, color: '#718096', marginTop: 4, fontStyle: 'italic' },
  stepResult: { fontSize: 12, color: '#a0aec0', marginTop: 6 },
  eliminated: { fontSize: 11, color: '#fc8181', marginTop: 4 },
  loadingSteps: { color: '#718096', fontSize: 13, padding: '12px 0', display: 'flex', gap: 8, alignItems: 'center' },
  spinner: {
    width: 14, height: 14, border: '2px solid #2d3748',
    borderTop: '2px solid #63b3ed', borderRadius: '50%',
    animation: 'spin 0.8s linear infinite',
  },
  evidenceBlock: {
    background: '#151822', borderRadius: 6, padding: '10px 12px',
    fontSize: 12, display: 'flex', flexDirection: 'column', gap: 4,
  },
  evidenceRow: {
    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
  },
  evidenceKey: { color: '#718096', textTransform: 'capitalize' },
  segmentRow: {
    display: 'flex', justifyContent: 'space-between',
    padding: '2px 0', borderTop: '1px solid #2d3748',
    fontSize: 11,
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
