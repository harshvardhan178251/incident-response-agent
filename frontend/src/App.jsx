import { useEffect, useState } from 'react'
import IncidentForm from './IncidentForm.jsx'
import Investigation from './Investigation.jsx'

const API = ''; // same-origin via vite proxy; set VITE_API_URL for prod

export default function App() {
  const [incident, setIncident] = useState(null)
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [resolving, setResolving] = useState(false)
  const [resolved, setResolved] = useState(null)
  const [health, setHealth] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    fetch(`${API}/api/health`).then((r) => r.json()).then(setHealth).catch(() => {})
  }, [])

  async function investigate(data) {
    setLoading(true)
    setError('')
    setResolved(null)
    try {
      const r = await fetch(`${API}/api/investigate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          service: data.service,
          severity: data.severity,
          error_logs: data.errorLogs
        })
      })
      if (!r.ok) throw new Error(`Backend ${r.status}`)
      const json = await r.json()
      setIncident(data)
      setResult(json)
    } catch (e) {
      setError('Investigation failed — is the FastAPI backend running on :8010?')
    } finally {
      setLoading(false)
    }
  }

  async function resolve({ resolution, outcome }) {
    setResolving(true)
    try {
      const r = await fetch(`${API}/api/resolve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          service: incident.service,
          severity: incident.severity,
          error_logs: incident.errorLogs,
          root_cause: result.root_cause,
          resolution,
          outcome
        })
      })
      const json = await r.json()
      setResolved(json)
    } finally {
      setResolving(false)
    }
  }

  return (
    <div className="page">
      <header>
        <h1>🚨 Incident Response Agent</h1>
        <p className="muted">
          Create → Investigate → Hindsight Recall → Recommend → Resolve → Retain
          {health && (
            <> · memory: <b>{health.memory_backend}</b> · llm: <b>{health.llm}</b> · stored: <b>{health.incidents_stored}</b></>
          )}
        </p>
      </header>
      {error && <div className="error">{error}</div>}
      <div className="grid">
        <IncidentForm onInvestigate={investigate} loading={loading} />
        <Investigation
          result={result}
          incident={incident}
          onResolve={resolve}
          resolving={resolving}
          resolved={resolved}
        />
      </div>
      <footer className="muted">
        Demo: Payment API / Critical / HTTP 503 + DB connection timeout + pool exhausted →
        expect INC-001 (pool increase ✓) vs INC-002 (restart ✗).
      </footer>
    </div>
  )
}
