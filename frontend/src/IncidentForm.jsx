import { useState } from 'react'

export default function IncidentForm({ onInvestigate, loading }) {
  const [service, setService] = useState('Payment API')
  const [severity, setSeverity] = useState('Critical')
  const [errorLogs, setErrorLogs] = useState(
    'HTTP 503 errors\nDB connection timeout\nconnection pool exhausted'
  )

  return (
    <div className="card">
      <h2>INCIDENT RESPONSE AGENT</h2>
      <label>Service</label>
      <input value={service} onChange={(e) => setService(e.target.value)} />

      <label>Severity</label>
      <select value={severity} onChange={(e) => setSeverity(e.target.value)}>
        <option>Critical</option>
        <option>High</option>
        <option>Medium</option>
        <option>Low</option>
      </select>

      <label>Error / Logs</label>
      <textarea
        rows={5}
        value={errorLogs}
        onChange={(e) => setErrorLogs(e.target.value)}
      />

      <button disabled={loading} onClick={() => onInvestigate({ service, severity, errorLogs })}>
        {loading ? 'Investigating…' : 'Investigate Incident'}
      </button>
    </div>
  )
}
