import { useEffect, useState } from "react";

const apiUrl = (path) => `${path}`;

async function fetchJson(path, options) {
  const res = await fetch(apiUrl(path), options);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`HTTP ${res.status}: ${text}`);
  }
  return res.json();
}

export default function App() {
  const [status, setStatus] = useState({
    is_recording: false,
    retro_enabled: false,
    pre_seconds: 0,
  });
  const [libraries, setLibraries] = useState([]);
  const [selectedId, setSelectedId] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const loadStatus = async () => {
    try {
      const data = await fetchJson("/record/status");
      setStatus(data);
    } catch (err) {
      setError(err.message);
    }
  };

  const loadLibraries = async () => {
    try {
      const data = await fetchJson("/libraries");
      const libs = data.libraries || [];
      setLibraries(libs);
      if (libs.length && !selectedId) {
        setSelectedId(String(libs[0].id));
      }
    } catch (err) {
      setError(err.message);
    }
  };

  useEffect(() => {
    loadStatus();
    loadLibraries();
    const timer = setInterval(loadStatus, 1000);
    return () => clearInterval(timer);
  }, []);

  const startRecording = async () => {
    if (!selectedId) return;
    setLoading(true);
    setError("");
    try {
      await fetchJson("/record/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ library_id: Number(selectedId) }),
      });
      await loadStatus();
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const stopRecording = async () => {
    setLoading(true);
    setError("");
    try {
      await fetchJson("/record/stop", { method: "POST" });
      await loadStatus();
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="page">
      <div className="card">
        <header className="header">
          <div>
            <h1>Remote Control</h1>
            <p className="subtitle">Control the recorder from your phone.</p>
          </div>
          <div className={`pill ${status.is_recording ? "on" : "off"}`}>
            {status.is_recording ? "Recording" : "Idle"}
          </div>
        </header>

        <section className="section">
          <label className="label">Library</label>
          <select
            className="select"
            value={selectedId}
            onChange={(e) => setSelectedId(e.target.value)}
          >
            {libraries.length === 0 && <option value="">No library</option>}
            {libraries.map((lib) => (
              <option key={lib.id} value={lib.id}>
                {lib.path}
              </option>
            ))}
          </select>
        </section>

        <section className="section actions">
          <button
            className="btn primary"
            onClick={startRecording}
            disabled={loading || !selectedId}
          >
            Start
          </button>
          <button className="btn ghost" onClick={stopRecording} disabled={loading}>
            Stop
          </button>
        </section>

        <section className="section status">
          <div className="stat">
            <span>Retro</span>
            <strong>{status.retro_enabled ? "Enabled" : "Disabled"}</strong>
          </div>
          <div className="stat">
            <span>Pre seconds</span>
            <strong>{status.pre_seconds}</strong>
          </div>
        </section>

        {error && <div className="error">Error: {error}</div>}
      </div>
    </div>
  );
}
