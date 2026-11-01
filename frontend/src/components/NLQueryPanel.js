/**
 * NLQueryPanel — Natural Language Query Interface
 *
 * Lets the user type a plain-English question about their product data.
 * Sends it to /api/query → Gemini generates SQL → results + plain-English answer.
 */

import React, { useState } from 'react';

const EXAMPLE_QUESTIONS = [
  'How many total users signed up?',
  'What is the breakdown of users by acquisition channel?',
  'How many users signed up in the last 7 days?',
  'What is the retention rate by channel?',
  'How many investigations have been completed?',
  'Which channel has the highest number of signups?',
  'Show me daily signups for the past 2 weeks',
  'How many users used the feature_use event today?',
];

export default function NLQueryPanel({ api }) {
  const [question, setQuestion] = useState('');
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [history, setHistory] = useState([]);

  const handleSubmit = async (q) => {
    const finalQ = (q || question).trim();
    if (!finalQ) return;
    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const res = await fetch(`${api}/api/query`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: finalQ }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Query failed');

      setResult(data);
      setHistory(prev => [{ question: finalQ, answer: data.answer, ts: new Date().toLocaleTimeString() }, ...prev.slice(0, 9)]);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const handleExample = (q) => {
    setQuestion(q);
    handleSubmit(q);
  };

  return (
    <div style={s.container}>
      <div style={s.header}>
        <h2 style={s.title}>🔎 Natural Language Query</h2>
        <p style={s.subtitle}>Ask anything about your product data in plain English — powered by Gemini text-to-SQL</p>
      </div>

      {/* Input */}
      <div style={s.inputRow}>
        <input
          style={s.input}
          value={question}
          onChange={e => setQuestion(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleSubmit()}
          placeholder="e.g. How many users signed up from Google Ads this week?"
          disabled={loading}
        />
        <button
          style={{ ...s.submitBtn, opacity: loading ? 0.6 : 1 }}
          onClick={() => handleSubmit()}
          disabled={loading || !question.trim()}
        >
          {loading ? '⏳ Querying...' : '▶ Ask'}
        </button>
      </div>

      {/* Example questions */}
      <div style={s.examples}>
        <span style={s.examplesLabel}>Try: </span>
        {EXAMPLE_QUESTIONS.slice(0, 4).map((q, i) => (
          <button key={i} style={s.exampleBtn} onClick={() => handleExample(q)}>
            {q}
          </button>
        ))}
      </div>

      {/* Error */}
      {error && (
        <div style={s.errorBox}>❌ {error}</div>
      )}

      {/* Result */}
      {result && (
        <div style={s.resultCard}>
          {/* Answer */}
          <div style={s.answerBox}>
            <span style={s.answerLabel}>💡 Answer</span>
            <p style={s.answerText}>
              {result.error
                ? <span style={{ color: '#fc8181' }}>SQL error: {result.error}</span>
                : result.answer}
            </p>
          </div>

          {/* SQL */}
          <details style={s.sqlDetails}>
            <summary style={s.sqlSummary}>🔧 Generated SQL</summary>
            <pre style={s.sqlCode}>{result.sql}</pre>
          </details>

          {/* Results table */}
          {result.columns && result.columns.length > 0 && result.rows && result.rows.length > 0 && (
            <div style={s.tableWrap}>
              <div style={s.tableLabel}>📋 Query Results ({result.rows.length} row{result.rows.length !== 1 ? 's' : ''})</div>
              <div style={s.tableScroll}>
                <table style={s.table}>
                  <thead>
                    <tr>
                      {result.columns.map((col, i) => (
                        <th key={i} style={s.th}>{col}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {result.rows.slice(0, 50).map((row, ri) => (
                      <tr key={ri} style={ri % 2 === 0 ? s.trEven : s.trOdd}>
                        {row.map((cell, ci) => (
                          <td key={ci} style={s.td}>{cell === null ? '—' : String(cell)}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {result.rows.length > 50 && (
                <p style={s.truncNote}>Showing first 50 of {result.rows.length} rows.</p>
              )}
            </div>
          )}

          {result.columns && result.columns.length > 0 && result.rows && result.rows.length === 0 && (
            <p style={s.emptyNote}>Query returned no rows.</p>
          )}
        </div>
      )}

      {/* History */}
      {history.length > 0 && (
        <div style={s.history}>
          <div style={s.historyLabel}>Recent queries</div>
          {history.map((h, i) => (
            <div key={i} style={s.historyItem}>
              <button style={s.historyQ} onClick={() => handleExample(h.question)}>
                {h.question}
              </button>
              <span style={s.historyA}>{h.answer?.slice(0, 100)}{h.answer?.length > 100 ? '…' : ''}</span>
              <span style={s.historyTs}>{h.ts}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

const s = {
  container: { maxWidth: 900, margin: '0 auto' },
  header: { marginBottom: 24 },
  title: { fontSize: 22, fontWeight: 700, color: '#e2e8f0', marginBottom: 6, margin: '0 0 6px 0' },
  subtitle: { fontSize: 13, color: '#718096', margin: 0 },
  inputRow: { display: 'flex', gap: 10, marginBottom: 12 },
  input: {
    flex: 1,
    background: '#1a1f2e',
    border: '1px solid #4a5568',
    borderRadius: 8,
    color: '#e2e8f0',
    fontSize: 14,
    padding: '10px 14px',
    outline: 'none',
  },
  submitBtn: {
    background: '#3182ce',
    color: '#fff',
    border: 'none',
    borderRadius: 8,
    padding: '10px 20px',
    fontWeight: 700,
    fontSize: 14,
    cursor: 'pointer',
    whiteSpace: 'nowrap',
  },
  examples: { display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 24, alignItems: 'center' },
  examplesLabel: { fontSize: 12, color: '#718096' },
  exampleBtn: {
    background: '#2d3748',
    color: '#a0aec0',
    border: '1px solid #4a5568',
    borderRadius: 20,
    padding: '4px 12px',
    fontSize: 12,
    cursor: 'pointer',
  },
  errorBox: {
    background: '#2d1515',
    border: '1px solid #c53030',
    borderRadius: 8,
    color: '#fc8181',
    padding: '12px 16px',
    fontSize: 13,
    marginBottom: 16,
  },
  resultCard: {
    background: '#1a1f2e',
    border: '1px solid #2d3748',
    borderRadius: 12,
    padding: 20,
    marginBottom: 24,
  },
  answerBox: { marginBottom: 16 },
  answerLabel: { fontSize: 11, color: '#68d391', fontWeight: 700, textTransform: 'uppercase', letterSpacing: 1 },
  answerText: { fontSize: 16, color: '#e2e8f0', marginTop: 6, lineHeight: 1.5 },
  sqlDetails: { marginBottom: 16 },
  sqlSummary: { fontSize: 12, color: '#718096', cursor: 'pointer', marginBottom: 8 },
  sqlCode: {
    background: '#0f1117',
    border: '1px solid #2d3748',
    borderRadius: 6,
    padding: '10px 14px',
    fontSize: 12,
    color: '#68d391',
    overflowX: 'auto',
    whiteSpace: 'pre-wrap',
    marginTop: 8,
  },
  tableWrap: {},
  tableLabel: { fontSize: 12, color: '#a0aec0', marginBottom: 8, fontWeight: 600 },
  tableScroll: { overflowX: 'auto' },
  table: { width: '100%', borderCollapse: 'collapse', fontSize: 13 },
  th: {
    background: '#2d3748',
    color: '#a0aec0',
    padding: '8px 12px',
    textAlign: 'left',
    fontWeight: 600,
    borderBottom: '1px solid #4a5568',
    whiteSpace: 'nowrap',
  },
  trEven: { background: '#0f1117' },
  trOdd: { background: '#141820' },
  td: { color: '#e2e8f0', padding: '7px 12px', borderBottom: '1px solid #1e2433' },
  truncNote: { fontSize: 11, color: '#718096', marginTop: 6 },
  emptyNote: { fontSize: 13, color: '#718096', marginTop: 8 },
  history: { marginTop: 8 },
  historyLabel: { fontSize: 11, color: '#4a5568', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 8 },
  historyItem: {
    display: 'flex',
    alignItems: 'flex-start',
    gap: 10,
    padding: '8px 0',
    borderBottom: '1px solid #1e2433',
    flexWrap: 'wrap',
  },
  historyQ: {
    background: 'none',
    border: 'none',
    color: '#63b3ed',
    cursor: 'pointer',
    fontSize: 13,
    padding: 0,
    textDecoration: 'underline',
    whiteSpace: 'nowrap',
  },
  historyA: { fontSize: 12, color: '#718096', flex: 1 },
  historyTs: { fontSize: 11, color: '#4a5568', whiteSpace: 'nowrap' },
};
