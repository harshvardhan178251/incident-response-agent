import { useState } from 'react'

export default function Investigation({ result, incident, onResolve, resolving, resolved }) {
  const [fix, setFix] = useState('Increased pool from 50 → 100')
  const [outcome, setOutcome] = useState('SUCCESS')

  if (!result) return null

  return (
    <div className="card">
      <h2>AI INVESTIGATION</h2>

      <div className="section">
        <h3>🔎 LIKELY ROOT CAUSE</h3>
        <p className="cause">{result.root_cause}</p>
        <strong>Evidence</strong>
        <ul>
          {(result.evidence || []).map((e, i) => (
            <li key={i}>{e}</li>
          ))}
        </ul>
      </div>

      <div className="section">
        <h3>🧠 HINDSIGHT MEMORY</h3>
        {(result.similar || []).map((m) => (
          <div key={m.id} className="memory">
            <div className="mem-head">
              <strong>{m.id}</strong>
              <span>Similarity: {m.similarity}%</span>
            </div>
            <div className={m.outcome === 'SUCCESS' ? 'ok' : 'bad'}>
              {m.outcome === 'SUCCESS' ? '✓' : '✗'} {m.resolution} → {m.outcome}
            </div>
            <div className="muted">{m.service} · {m.root_cause}</div>
          </div>
        ))}
      </div>

      <div className="section">
        <h3>🤖 RECOMMENDATION</h3>
        <p>{result.recommendation}</p>
      </div>

      {!resolved ? (
        <div className="section resolve-box">
          <h3>ENGINEER RESOLUTION</h3>
          <label>Actual fix</label>
          <input value={fix} onChange={(e) => setFix(e.target.value)} />
          <label>Outcome</label>
          <select value={outcome} onChange={(e) => setOutcome(e.target.value)}>
            <option>SUCCESS</option>
            <option>FAILED</option>
          </select>
          <button
            disabled={resolving}
            onClick={() => onResolve({ resolution: fix, outcome })}
          >
            {resolving ? 'Saving…' : 'Resolve & Remember → Save to Hindsight'}
          </button>
          <p className="muted">
            Service: {incident.service} · Root cause: {result.root_cause}
          </p>
        </div>
      ) : (
        <div className="section saved">
          <h3>✅ SAVED TO HINDSIGHT</h3>
          <p><strong>Root cause:</strong> {resolved.saved.root_cause}</p>
          <p><strong>Actual fix:</strong> {resolved.saved.resolution}</p>
          <p><strong>Outcome:</strong> {resolved.saved.outcome}</p>
          <p className="muted">{resolved.message}</p>
        </div>
      )}
    </div>
  )
}
