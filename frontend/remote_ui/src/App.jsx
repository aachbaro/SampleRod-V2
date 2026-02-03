import { useEffect, useRef, useState } from "react";

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
  const [retroTime, setRetroTime] = useState(10);
  const retroInitializedRef = useRef(false);
  const retroTouchedRef = useRef(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [history, setHistory] = useState([]);
  const [renameId, setRenameId] = useState(null);
  const [renameValue, setRenameValue] = useState("");
  const [busyId, setBusyId] = useState(null);

  const applyStatus = (data) => {
    setStatus(data);
    if (
      !retroInitializedRef.current &&
      !retroTouchedRef.current &&
      typeof data.pre_seconds === "number"
    ) {
      setRetroTime(data.pre_seconds);
      retroInitializedRef.current = true;
    } else if (!retroInitializedRef.current) {
      retroInitializedRef.current = true;
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

  const loadHistory = async () => {
    try {
      const data = await fetchJson("/samples/history");
      const items = data.samples || [];
      setHistory(items);
    } catch (err) {
      setError(err.message);
    }
  };

  const formatDate = (value) => {
    if (!value) return "";
    try {
      return new Date(value).toLocaleString();
    } catch {
      return value;
    }
  };

  const formatDuration = (value) => {
    if (value === null || value === undefined) return "";
    return `${Number(value).toFixed(1)}s`;
  };

  useEffect(() => {
    loadLibraries();
    loadHistory();

    const es = new EventSource("/events");
    const onStatus = (ev) => {
      try {
        const data = JSON.parse(ev.data);
        applyStatus(data);
      } catch (err) {
        setError(err.message);
      }
    };
    es.addEventListener("status", onStatus);
    es.addEventListener("sample_added", (ev) => {
      try {
        const data = JSON.parse(ev.data);
        setHistory((prev) => [data, ...prev.filter((s) => s.id !== data.id)]);
      } catch (err) {
        setError(err.message);
      }
    });
    es.addEventListener("sample_renamed", (ev) => {
      try {
        const data = JSON.parse(ev.data);
        setHistory((prev) =>
          prev.map((s) => (s.id === data.id ? data : s))
        );
      } catch (err) {
        setError(err.message);
      }
    });
    es.addEventListener("sample_deleted", (ev) => {
      try {
        const data = JSON.parse(ev.data);
        setHistory((prev) => prev.filter((s) => s.id !== data.id));
      } catch (err) {
        setError(err.message);
      }
    });
    es.onerror = () => {
      setError("SSE connection lost");
    };
    return () => {
      es.removeEventListener("status", onStatus);
      es.close();
    };
  }, []);

  const toggleRecording = async () => {
    setLoading(true);
    setError("");
    try {
      if (status.is_recording) {
        await fetchJson("/record/stop", { method: "POST" });
      } else {
        if (!selectedId) {
          setError("Select a library first.");
          return;
        }
        await fetchJson("/record/start", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            library_id: Number(selectedId),
            retro_time: Number(retroTime) || 0,
          }),
        });
      }
      // status mis a jour via SSE
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const startRename = (sample) => {
    setRenameId(sample.id);
    setRenameValue(sample.name || "");
  };

  const cancelRename = () => {
    setRenameId(null);
    setRenameValue("");
  };

  const saveRename = async (sampleId) => {
    if (!renameValue.trim()) return;
    setBusyId(sampleId);
    setError("");
    try {
      const res = await fetchJson(`/samples/${sampleId}/rename`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: renameValue.trim() }),
      });
      if (res.sample) {
        setHistory((prev) =>
          prev.map((s) => (s.id === sampleId ? res.sample : s))
        );
      }
      cancelRename();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusyId(null);
    }
  };

  const deleteSample = async (sampleId) => {
    setBusyId(sampleId);
    setError("");
    try {
      await fetchJson(`/samples/${sampleId}/delete`, { method: "POST" });
      setHistory((prev) => prev.filter((s) => s.id !== sampleId));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="page">
      <div className="card">
        <header className="header">
          <div>
            <h1>Remote Control</h1>
            <p className="subtitle">Control from your phone.</p>
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

        <section className="section">
          <label className="label">Retro time</label>
          <div className="chips">
            {[0, 10, 20].map((value) => (
              <button
                key={value}
                className={`chip ${retroTime === value ? "active" : ""}`}
                onClick={() => {
                  retroTouchedRef.current = true;
                  setRetroTime(value);
                }}
                type="button"
              >
                {value}s
              </button>
            ))}
          </div>
        </section>

        <section className="section actions">
          <button
            className={`btn toggle ${status.is_recording ? "stop" : "start"}`}
            onClick={toggleRecording}
            disabled={loading || (!selectedId && !status.is_recording)}
          >
            {status.is_recording ? "Stop" : "Start"}
          </button>
        </section>

        <section className="section status">
          <div className="stat">
            <span>Retro</span>
            <strong>{status.retro_enabled ? "Enabled" : "Disabled"}</strong>
          </div>
          <div className="stat">
            <span>Retro selection</span>
            <strong>{retroTime}s</strong>
          </div>
          <div className="stat">
            <span>Buffer max</span>
            <strong>{status.pre_seconds}s</strong>
          </div>
        </section>

        <section className="section history">
          <div className="history-header">
            <h2>History</h2>
            <span className="history-count">{history.length}</span>
          </div>
          {history.length === 0 && (
            <div className="history-empty">No samples yet.</div>
          )}
          {history.map((samp) => (
            <div className="history-item" key={samp.id}>
              <div className="history-main">
                {renameId === samp.id ? (
                  <div className="history-inline-rename">
                    <input
                      className="rename-input"
                      value={renameValue}
                      onChange={(e) => setRenameValue(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          saveRename(samp.id);
                        } else if (e.key === "Escape") {
                          cancelRename();
                        }
                      }}
                      autoFocus
                    />
                  </div>
                ) : (
                  <div
                    className="history-title"
                    onDoubleClick={() => startRename(samp)}
                    title="Double click to rename"
                  >
                    {samp.name}
                  </div>
                )}
                <div className="history-meta">
                  {formatDuration(samp.duration)} · {formatDate(samp.created_at)}
                </div>
              </div>
              <audio
                className="history-audio"
                controls
                preload="none"
                src={`/samples/${samp.id}/audio`}
              />
              {renameId === samp.id ? (
                <div className="history-rename">
                  <button
                    className="btn small"
                    onClick={() => saveRename(samp.id)}
                    disabled={busyId === samp.id}
                  >
                    Save
                  </button>
                  <button className="btn small ghost" onClick={cancelRename}>
                    Cancel
                  </button>
                </div>
              ) : (
                <div className="history-actions">
                  <button
                    className="btn small ghost"
                    onClick={() => startRename(samp)}
                  >
                    Rename
                  </button>
                  <button
                    className="btn small danger"
                    onClick={() => deleteSample(samp.id)}
                    disabled={busyId === samp.id}
                  >
                    Delete
                  </button>
                </div>
              )}
            </div>
          ))}
        </section>

        {error && <div className="error">Error: {error}</div>}
      </div>
    </div>
  );
}
