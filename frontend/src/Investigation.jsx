import { useState } from 'react'

function scoreLabel(m) {
  const s = m.scores || {}
  if (typeof s.final === 'number') return `Hindsight score: ${s.final.toFixed(2)}`
  return 'Relevant memory'
}

function memField(m, name) {
  if (m[name]) return m[name]
  if (m.metadata && m.metadata[name]) return m.metadata[name]
  return null
}

function Bar({ label, pct }) {
  const w = Math.max(0, Math.min(100, pct * 10))
  return (
    <div className="muted">{label} <span className="bar"><span style={{ width: `${w}%` }} /></span> {pct}%</div>
  )
}

export default function Investigation({ result, incident, onResolve, resolving, resolveState, onNew }) {
  const [fix, setFix] = useState('')
  const [outcome, setOutcome] = useState('SUCCESS')

  if (!result) return null
  const saved = resolveState && resolveState.ok
  const rec = result.recommendation_structured || null
  const conf = result.confidence || null
  const fp = result.fingerprint || null
  const impact = result.memory_impact || null
  const timeline = result.timeline || []
  const failedFixes = result.failed_fixes || []
  const okFixes = result.successful_fixes || []
  const runbooks = result.runbooks || []
  const breakdown = (conf && conf.breakdown) || null

  return (
    <div className="card">
      <h2>AI INVESTIGATION {incident && <span className="muted">· {incident.id}</span>}</h2>

      {fp && (
        <div className="section">
          <h3>🧩 INCIDENT FINGERPRINT</h3>
          <div className="muted">
            Service: <b>{fp.service}</b> · Severity: <b>{fp.severity}</b> · Error: <b>{fp.error_class}</b>
          </div>
          <div className="muted">
            Dependency: <b>{fp.dependency}</b> · Failure mode: <b>{fp.failure_mode}</b> · Pattern: <b>{fp.pattern}</b>
          </div>
        </div>
      )}

      <div className="section">
        <h3>🔎 LIKELY ROOT CAUSE vs SYMPTOM</h3>
        <p className="cause">{result.root_cause}</p>
        {fp && <p className="muted">Symptom: {fp.symptom} · Root cause ≠ symptom — recall ranked by cause pattern.</p>}
        {result.multi_cause_warning && (
          <p className="muted">⚠️ Same symptom does not mean same cause — memories below span different root causes.</p>
        )}
        <strong>Evidence</strong>
        <ul>
          {(result.evidence || []).map((e, i) => (
            <li key={i}>✓ {e}</li>
          ))}
        </ul>
      </div>

      {impact && (
        <div className="section">
          <h3>🧠 MEMORY IMPACT</h3>
          <p className="muted">
            Without memory: {impact.without_memory} → With Hindsight: {impact.with_memory} ·
            {' '}{impact.n} incidents · {impact.successful}✅ {impact.failed}❌
            {impact.rec_changed ? ' · Recommendation changed because of memory.' : ''}
          </p>
        </div>
      )}

      <div className="section">
        <h3>🧠 HINDSIGHT MEMORY</h3>
        {!result.memory_available && (
          <div className="error">
            Hindsight is unavailable{result.memory_error ? `: ${result.memory_error}` : ''} —
            recommendation below is based on the current incident only.
          </div>
        )}
        {result.memory_available && (result.memories || []).length === 0 && (
          <p className="muted">No relevant memories found in Hindsight.</p>
        )}
        {(result.memories || []).slice(0, 6).map((m) => (
          <div key={m.rank} className="memory">
            <div className="mem-head">
              <strong>Rank #{m.rank}{m.incident_id ? ` · ${m.incident_id}` : ''}{m.age ? ` · ${m.age}` : ''}</strong>
              <span>{scoreLabel(m)}</span>
            </div>
            {(memField(m, 'service') || memField(m, 'outcome') || memField(m, 'resolution')) ? (
              <div className="mem-fields">
                {memField(m, 'service') && <div><strong>Service:</strong> {memField(m, 'service')}</div>}
                {memField(m, 'resolution') && <div><strong>Resolution:</strong> {memField(m, 'resolution')}</div>}
                {memField(m, 'outcome') && <div><strong>Outcome:</strong> {memField(m, 'outcome')}</div>}
              </div>
            ) : null}
            <details>
              <summary className="muted">Similar incident text</summary>
              <div>{m.text}</div>
            </details>
          </div>
        ))}
      </div>

      {timeline.length > 0 && (
        <div className="section">
          <h3>📈 INCIDENT LEARNING TIMELINE</h3>
          {timeline.map((t, i) => (
            <div key={i} className="muted">
              {t.incident_id || `rank #${t.rank}`} · {t.resolution || '—'} · {t.outcome || '?'} {t.outcome === 'SUCCESS' ? '✅' : t.outcome === 'FAILED' ? '❌' : ''}{t.age ? ` · ${t.age}` : ''}
              {i < timeline.length - 1 && <div>↓ learned</div>}
            </div>
          ))}
        </div>
      )}

      <div className="section">
        <h3>🤖 RECOMMENDATION</h3>
        {rec ? (
          <>
            <h4>Recommended Action</h4>
            <p style={{ whiteSpace: 'pre-wrap' }}>{rec.recommended_action}</p>
            {rec.why && rec.why.length > 0 && (
              <>
                <h4>Why</h4>
                <ul>{rec.why.map((w, i) => <li key={i}>{w}</li>)}</ul>
              </>
            )}
            {rec.resembles_incident_id && (
              <p className="muted">Resembles {rec.resembles_incident_id}</p>
            )}
          </>
        ) : (
          <p style={{ whiteSpace: 'pre-wrap' }}>{result.recommendation}</p>
        )}
        {rec && (
          <div className="section">
            <h4>🔄 WHY I CHANGED MY MIND</h4>
            <p className="muted">Initial hypothesis: {rec.initial_hypothesis || result.root_cause}</p>
            <p className="muted">
              After recall: {impact ? `${impact.n} similar (${impact.successful}✅ ${impact.failed}❌)` : 'no history'} ·
              {' '}{rec.followed_memory === false ? 'overrode history' : 'followed history'}
            </p>
            {rec.reason_for_change && <p className="muted">Reason: {rec.reason_for_change}</p>}
          </div>
        )}
        {(failedFixes.length > 0 || (rec && rec.historical_failures && rec.historical_failures.length > 0)) && (
          <div className="section">
            <h4>⚠️ AVOID THESE PREVIOUS FIXES</h4>
            <ul>
              {failedFixes.map((f, i) => (
                <li key={i}>{f.resolution || 'past fix'} ❌ {f.incident_id ? `in ${f.incident_id}` : ''}</li>
              ))}
              {rec && (rec.historical_failures || []).map((w, i) => (
                <li key={`h${i}`}>{w}</li>
              ))}
            </ul>
          </div>
        )}
        {rec && rec.alternative && (
          <div className="section">
            <h4>🧪 What if we tried the alternative?</h4>
            <p className="muted">Alternative: {rec.alternative} — expected: {rec.alternative_evidence}</p>
          </div>
        )}
        {conf && conf.confidence != null && (
          <div className="muted">
            Confidence: <strong>{conf.confidence}%</strong>
            <span title={conf.basis ? `top final ${conf.basis.top_final}, mean rest ${conf.basis.mean_rest}, n=${conf.basis.n}` : ''}>
              {' '}(retrieval — derived from Hindsight scores, not a guess)
            </span>
          </div>
        )}
        {breakdown && (
          <div>
            <Bar label="Current evidence" pct={breakdown.current_evidence} />
            <Bar label="Successful history" pct={breakdown.successful_history} />
            <Bar label="Failed alternatives" pct={breakdown.failed_alternatives} />
            <Bar label="Incident similarity" pct={breakdown.incident_similarity} />
          </div>
        )}
        {runbooks.length > 0 && (
          <div className="section">
            <h4>📚 RUNBOOK</h4>
            {runbooks.map((r, i) => <p key={i} className="muted">{r.text}</p>)}
          </div>
        )}
        <details>
          <summary className="muted">Model details</summary>
          <div className="muted">analysis: {result.meta && result.meta.analysis_llm} · recommendation: {result.meta && result.meta.recommendation_llm}</div>
        </details>
      </div>

      {!saved ? (
        <div className="section resolve-box">
          <h3>ENGINEER RESOLUTION</h3>
          <label>Actual fix</label>
          <input
            value={fix}
            placeholder="e.g. Increased Redis pool 20 → 50 and added health probes"
            onChange={(e) => setFix(e.target.value)}
          />
          <label>Outcome</label>
          <select value={outcome} onChange={(e) => setOutcome(e.target.value)}>
            <option>SUCCESS</option>
            <option>FAILED</option>
          </select>
          <button
            disabled={resolving || !fix.trim()}
            onClick={() => onResolve({ resolution: fix.trim(), outcome })}
          >
            {resolving ? 'Saving…' : 'Resolve & Remember → Save to Hindsight'}
          </button>
          {resolveState && !resolveState.ok && (
            <div className="error">❌ {resolveState.message}</div>
          )}
          <p className="muted">
            Incident: {incident.id} · Service: {incident.service} · Root cause: {result.root_cause}
          </p>
        </div>
      ) : (
        <div className="section saved">
          <h3>✅ Memory Updated</h3>
          <p><strong>{resolveState.incident_id}</strong> has been stored in Hindsight.</p>
          <p><strong>Actual fix:</strong> {resolveState.saved.resolution}</p>
          <p><strong>Outcome:</strong> {resolveState.saved.outcome}</p>
          {resolveState.runbook && <p className="muted">📚 Runbook generated from this incident.</p>}
          <p className="muted">{resolveState.message}</p>
          <button onClick={onNew}>Create another similar incident →</button>
        </div>
      )}
    </div>
  )
}
