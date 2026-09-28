import { useEffect, useState } from 'react'
import IncidentForm from './IncidentForm.jsx'
import Investigation from './Investigation.jsx'

const API = ''; // same-origin via vite proxy; set VITE_API_URL for prod

export default function App() {
  const [incident, setIncident] = useState(null)
  const [result, setResult] = useState(null)
  const [working, setWorking] = useState(false)
  const [resolving, setResolving] = useState(false)
  const [resolveState, setResolveState] = useState(null) // {ok:true,...} | {ok:false,...}
  const [health, setHealth] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    fetch(`${API}/api/health`).then((r) => r.json()).then(setHealth).catch(() => {})
  }, [])

  function post(path, body) {
    return fetch(`${API}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    })
  }

  // Create Incident → Investigate (LLM + Hindsight recall + recommendation)
  async function investigate(data) {
    setWorking(true)
    setError('')
    setResult(null)
    setResolveState(null)
    try {
      const c = await post('/api/incidents', {
        service: data.service,
        severity: data.severity,
        error_logs: data.errorLogs
      })
      if (!c.ok) throw new Error(`create failed (${c.status})`)
      const created = await c.json()
      setIncident({ ...data, id: created.id })

      const r = await post(`/api/incidents/${created.id}/investigate`, {})
      if (!r.ok) throw new Error(`investigate failed (${r.status})`)
      setResult(await r.json())
    } catch (e) {
      setError(`Investigation failed (${e.message}) — is the FastAPI backend running on :8010?`)
    } finally {
      setWorking(false)
    }
  }

  // Engineer resolution → Hindsight retain (honest success / failure)
  async function resolve({ resolution, outcome }) {
    setResolving(true)
    setResolveState(null)
    try {
      const r = await post(`/api/incidents/${incident.id}/resolve`, { resolution, outcome })
      const json = await r.json().catch(() => ({}))
      if (!r.ok) {
        setResolveState({ ok: false, message: json.detail || `Save failed (${r.status})` })
      } else {
        setResolveState({ ok: true, ...json })
      }
    } catch (e) {
      setResolveState({ ok: false, message: `Could not save memory. Hindsight is unavailable. (${e.message})` })
    } finally {
      setResolving(false)
    }
  }

  function newIncident() {
    setIncident(null)
    setResult(null)
    setResolveState(null)
    setError('')
  }

  return (
    <div className="page">
      <header>
        <h1>🚨 Incident Response Agent</h1>
        <p className="muted">
          Create → Investigate → Hindsight Recall → Recommend → Resolve → Retain
          {health && (
            <> · <span title={health.memory_backend === 'hindsight' ? 'Hindsight Cloud reachable' : 'Hindsight unavailable — recommendations use current incident only'}>
              {health.memory_backend === 'hindsight' ? '🟢 Hindsight connected' : '🔴 Hindsight disconnected'}
            </span> · llm: <b>{health.llm}</b> · stored: <b>{health.incidents_stored}</b></>
          )}
          {incident && <> · incident: <b>{incident.id}</b></>}
        </p>
      </header>
      {error && <div className="error">{error}</div>}
      <div className="grid">
        <IncidentForm onInvestigate={investigate} loading={working} />
        <Investigation
          result={result}
          incident={incident}
          onResolve={resolve}
          resolving={resolving}
          resolveState={resolveState}
          onNew={newIncident}
        />
      </div>
      <footer className="muted">
        Enter any service + logs → Investigate → Resolve &amp; Remember → create a similar
        incident to see Hindsight recall what you saved.
      </footer>
    </div>
  )
}
