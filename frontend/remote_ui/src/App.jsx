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
  const SHOT_LIMIT = 20;
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
  const [screens, setScreens] = useState([]);
  const [shots, setShots] = useState([]);
  const [shotRenameId, setShotRenameId] = useState(null);
  const [shotRenameValue, setShotRenameValue] = useState("");
  const [shotBusyId, setShotBusyId] = useState(null);
  const [viewerShot, setViewerShot] = useState(null);
  const [renameId, setRenameId] = useState(null);
  const [renameValue, setRenameValue] = useState("");
  const [busyId, setBusyId] = useState(null);
  const [playingId, setPlayingId] = useState(null);
  const [audioState, setAudioState] = useState({});
  const audioRefs = useRef({});
  const [isFullscreen, setIsFullscreen] = useState(false);

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

  const loadScreens = async () => {
    try {
      const data = await fetchJson("/screenshots/screens");
      setScreens(data.screens || []);
    } catch (err) {
      setError(err.message);
    }
  };

  const loadShots = async () => {
    try {
      const data = await fetchJson(`/screenshots/list?limit=${SHOT_LIMIT}`);
      setShots((data.items || []).slice(0, SHOT_LIMIT));
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

  const formatClock = (seconds) => {
    if (!isFinite(seconds)) return "0:00";
    const s = Math.max(0, Math.floor(seconds));
    const m = Math.floor(s / 60);
    const r = s % 60;
    return `${m}:${String(r).padStart(2, "0")}`;
  };

  const updateAudioState = (id, patch) => {
    setAudioState((prev) => ({
      ...prev,
      [id]: {
        current: 0,
        duration: 0,
        ...(prev[id] || {}),
        ...patch,
      },
    }));
  };

  useEffect(() => {
    loadLibraries();
    loadHistory();
    loadScreens();

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
    es.addEventListener("screenshot_added", (ev) => {
      try {
        const data = JSON.parse(ev.data);
        setShots((prev) =>
          [data, ...prev.filter((s) => s.id !== data.id)].slice(0, SHOT_LIMIT)
        );
      } catch (err) {
        setError(err.message);
      }
    });
    es.addEventListener("screenshot_deleted", (ev) => {
      try {
        const data = JSON.parse(ev.data);
        setShots((prev) => prev.filter((s) => s.id !== data.id));
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

  useEffect(() => {
    const onChange = () => {
      setIsFullscreen(Boolean(document.fullscreenElement));
    };
    document.addEventListener("fullscreenchange", onChange);
    return () => document.removeEventListener("fullscreenchange", onChange);
  }, []);

  useEffect(() => {
    if (!viewerShot) return;
    const onKey = (ev) => {
      if (ev.key === "Escape") {
        setViewerShot(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [viewerShot]);

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

  const startShotRename = (shot) => {
    setShotRenameId(shot.id);
    setShotRenameValue((shot.filename || "").replace(/\.png$/i, ""));
  };

  const cancelRename = () => {
    setRenameId(null);
    setRenameValue("");
  };

  const cancelShotRename = () => {
    setShotRenameId(null);
    setShotRenameValue("");
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

  const saveShotRename = async (shotId) => {
    if (!shotRenameValue.trim()) return;
    setShotBusyId(shotId);
    setError("");
    try {
      const res = await fetchJson(`/screenshots/rename`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: shotId, name: shotRenameValue.trim() }),
      });
      if (res.item) {
        setShots((prev) =>
          prev.map((s) => (s.id === shotId ? res.item : s))
        );
      }
      cancelShotRename();
    } catch (err) {
      setError(err.message);
    } finally {
      setShotBusyId(null);
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

  const deleteShot = async (shotId) => {
    setShotBusyId(shotId);
    setError("");
    try {
      await fetchJson(`/screenshots/delete`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: shotId }),
      });
      setShots((prev) => prev.filter((s) => s.id !== shotId));
    } catch (err) {
      setError(err.message);
    } finally {
      setShotBusyId(null);
    }
  };

  const captureScreen = async (screenIndex) => {
    setShotBusyId(`capture-${screenIndex}`);
    setError("");
    try {
      const res = await fetchJson(`/screenshots/capture`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ screen_index: screenIndex }),
      });
      if (res.item) {
        setShots((prev) => [res.item, ...prev.filter((s) => s.id !== res.item.id)]);
      } else {
        loadShots();
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setShotBusyId(null);
    }
  };

  const togglePlay = async (sampleId) => {
    const audio = audioRefs.current[sampleId];
    if (!audio) return;

    if (playingId && playingId !== sampleId) {
      const prev = audioRefs.current[playingId];
      if (prev) {
        prev.pause();
        prev.currentTime = 0;
        updateAudioState(playingId, { current: 0 });
      }
    }

    if (audio.paused) {
      try {
        await audio.play();
        setPlayingId(sampleId);
      } catch (err) {
        setError(err.message || "Playback failed");
      }
    } else {
      audio.pause();
      setPlayingId(null);
    }
  };

  const toggleFullscreen = async () => {
    try {
      if (!document.fullscreenElement) {
        await document.documentElement.requestFullscreen();
      } else {
        await document.exitFullscreen();
      }
    } catch (err) {
      setError(err.message || "Fullscreen not supported");
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
          <button
            className={`icon-btn ghost fullscreen ${isFullscreen ? "active" : ""}`}
            onClick={toggleFullscreen}
            aria-label="Toggle fullscreen"
          >
            {isFullscreen ? (
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M8 3H3v5h2V5h3V3zm13 0h-5v2h3v3h2V3zM5 16H3v5h5v-2H5v-3zm16 0h-2v3h-3v2h5v-5z" />
              </svg>
            ) : (
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M3 3h8v2H5v6H3V3zm18 0v8h-2V5h-6V3h8zM5 13v6h6v2H3v-8h2zm14 0h2v8h-8v-2h6v-6z" />
              </svg>
            )}
          </button>
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
            {[0, 5, 10, 20].map((value) => (
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
              <div className="history-audio-row">
                <button
                  className={`play-btn ${
                    playingId === samp.id ? "pause" : "play"
                  }`}
                  onClick={() => togglePlay(samp.id)}
                  aria-label={playingId === samp.id ? "Pause" : "Play"}
                >
                  {playingId === samp.id ? (
                    <svg viewBox="0 0 24 24" aria-hidden="true">
                      <rect x="5" y="4" width="5" height="16" rx="1.5" />
                      <rect x="14" y="4" width="5" height="16" rx="1.5" />
                    </svg>
                  ) : (
                    <svg viewBox="0 0 24 24" aria-hidden="true">
                      <path d="M7 5v14l11-7z" />
                    </svg>
                  )}
                </button>
                <input
                  className="progress"
                  type="range"
                  min="0"
                  max={audioState[samp.id]?.duration || samp.duration || 1}
                  step="0.01"
                  value={audioState[samp.id]?.current || 0}
                  onChange={(e) => {
                    const audio = audioRefs.current[samp.id];
                    const next = Number(e.target.value);
                    if (audio) {
                      audio.currentTime = next;
                    }
                    updateAudioState(samp.id, { current: next });
                  }}
                />
                <div className="time">
                  {formatClock(audioState[samp.id]?.current || 0)} /{" "}
                  {formatClock(
                    audioState[samp.id]?.duration || samp.duration || 0
                  )}
                </div>
                <audio
                  ref={(el) => {
                    if (el) {
                      audioRefs.current[samp.id] = el;
                    }
                  }}
                  preload="metadata"
                  src={`/samples/${samp.id}/audio`}
                  onLoadedMetadata={(e) => {
                    updateAudioState(samp.id, {
                      duration: e.currentTarget.duration || 0,
                    });
                  }}
                  onTimeUpdate={(e) => {
                    updateAudioState(samp.id, {
                      current: e.currentTarget.currentTime || 0,
                    });
                  }}
                  onEnded={() => {
                    setPlayingId(null);
                    updateAudioState(samp.id, { current: 0 });
                  }}
                />
              </div>
              {renameId === samp.id ? (
                <div className="history-rename">
                  <button
                    className="icon-btn"
                    onClick={() => saveRename(samp.id)}
                    disabled={busyId === samp.id}
                    aria-label="Save"
                  >
                    <svg viewBox="0 0 24 24" aria-hidden="true">
                      <path d="M9.2 16.2 5.5 12.5l-1.4 1.4 5.1 5.1L20 8.2l-1.4-1.4z" />
                    </svg>
                  </button>
                  <button
                    className="icon-btn ghost"
                    onClick={cancelRename}
                    aria-label="Cancel"
                  >
                    <svg viewBox="0 0 24 24" aria-hidden="true">
                      <path d="M18.3 5.7 12 12l6.3 6.3-1.4 1.4L10.6 13.4 4.3 19.7 2.9 18.3 9.2 12 2.9 5.7 4.3 4.3l6.3 6.3 6.3-6.3z" />
                    </svg>
                  </button>
                </div>
              ) : (
                <div className="history-actions">
                  <button
                    className="icon-btn ghost"
                    onClick={() => startRename(samp)}
                    aria-label="Rename"
                  >
                    <svg viewBox="0 0 24 24" aria-hidden="true">
                      <path d="M3 17.3V21h3.7l10.9-10.9-3.7-3.7L3 17.3zm17.7-10.6c.4-.4.4-1 0-1.4L18.7 3.3c-.4-.4-1-.4-1.4 0l-2 2 3.7 3.7 2-2z" />
                    </svg>
                  </button>
                  <a
                    className="icon-btn ghost"
                    href={`/samples/${samp.id}/download`}
                    download
                    aria-label="Download"
                  >
                    <svg viewBox="0 0 24 24" aria-hidden="true">
                      <path d="M12 3v10.2l3.3-3.3 1.4 1.4-5.7 5.7-5.7-5.7 1.4-1.4 3.3 3.3V3h2zm-7 15h14v2H5v-2z" />
                    </svg>
                  </a>
                  <button
                    className="icon-btn danger"
                    onClick={() => deleteSample(samp.id)}
                    disabled={busyId === samp.id}
                    aria-label="Delete"
                  >
                    <svg viewBox="0 0 24 24" aria-hidden="true">
                      <path d="M6 7h12l-1 14H7L6 7zm3-3h6l1 2H8l1-2z" />
                    </svg>
                  </button>
                </div>
              )}
            </div>
          ))}
        </section>

        <section className="section screenshots">
          <div className="history-header">
            <h2>Screenshots</h2>
            <span className="history-count">{shots.length}</span>
          </div>
          <div className="screen-buttons">
            {screens.length === 0 && (
              <div className="history-empty">No screens detected.</div>
            )}
            {screens.map((screen) => (
              <button
                key={screen.index}
                className="chip"
                onClick={() => captureScreen(screen.index)}
                disabled={shotBusyId === `capture-${screen.index}`}
                type="button"
              >
                {screen.name || `Screen ${screen.index + 1}`}
              </button>
            ))}
          </div>
          {shots.length === 0 && (
            <div className="history-empty">No screenshots yet.</div>
          )}
          {shots.map((shot) => (
            <div className="shot-item" key={shot.id}>
              <div className="shot-preview">
                <img
                  src={`/screenshots/file/${shot.id}`}
                  alt={shot.filename}
                  loading="lazy"
                  onClick={() => setViewerShot(shot)}
                />
              </div>
              <div className="shot-body">
                {shotRenameId === shot.id ? (
                  <input
                    className="rename-input"
                    value={shotRenameValue}
                    onChange={(e) => setShotRenameValue(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        saveShotRename(shot.id);
                      } else if (e.key === "Escape") {
                        cancelShotRename();
                      }
                    }}
                    autoFocus
                  />
                ) : (
                  <div
                    className="history-title"
                    onDoubleClick={() => startShotRename(shot)}
                    title="Double click to rename"
                  >
                    {shot.filename}
                  </div>
                )}
                <div className="history-meta">
                  {formatDate(shot.created_at)} · Screen {Number(shot.screen_index) + 1} ·{" "}
                  {shot.width}x{shot.height}
                </div>
                <div className="shot-actions">
                  {shotRenameId === shot.id ? (
                    <>
                      <button
                        className="icon-btn"
                        onClick={() => saveShotRename(shot.id)}
                        disabled={shotBusyId === shot.id}
                        aria-label="Save"
                      >
                        <svg viewBox="0 0 24 24" aria-hidden="true">
                          <path d="M9.2 16.2 5.5 12.5l-1.4 1.4 5.1 5.1L20 8.2l-1.4-1.4z" />
                        </svg>
                      </button>
                      <button
                        className="icon-btn ghost"
                        onClick={cancelShotRename}
                        aria-label="Cancel"
                      >
                        <svg viewBox="0 0 24 24" aria-hidden="true">
                          <path d="M18.3 5.7 12 12l6.3 6.3-1.4 1.4L10.6 13.4 4.3 19.7 2.9 18.3 9.2 12 2.9 5.7 4.3 4.3l6.3 6.3 6.3-6.3z" />
                        </svg>
                      </button>
                    </>
                  ) : (
                    <>
                      <button
                        className="icon-btn ghost"
                        onClick={() => startShotRename(shot)}
                        aria-label="Rename"
                      >
                        <svg viewBox="0 0 24 24" aria-hidden="true">
                          <path d="M3 17.3V21h3.7l10.9-10.9-3.7-3.7L3 17.3zm17.7-10.6c.4-.4.4-1 0-1.4L18.7 3.3c-.4-.4-1-.4-1.4 0l-2 2 3.7 3.7 2-2z" />
                        </svg>
                      </button>
                      <a
                        className="icon-btn ghost"
                        href={`/screenshots/file/${shot.id}`}
                        download
                        aria-label="Download"
                      >
                        <svg viewBox="0 0 24 24" aria-hidden="true">
                          <path d="M12 3v10.2l3.3-3.3 1.4 1.4-5.7 5.7-5.7-5.7 1.4-1.4 3.3 3.3V3h2zm-7 15h14v2H5v-2z" />
                        </svg>
                      </a>
                      <button
                        className="icon-btn danger"
                        onClick={() => deleteShot(shot.id)}
                        disabled={shotBusyId === shot.id}
                        aria-label="Delete"
                      >
                        <svg viewBox="0 0 24 24" aria-hidden="true">
                          <path d="M6 7h12l-1 14H7L6 7zm3-3h6l1 2H8l1-2z" />
                        </svg>
                      </button>
                    </>
                  )}
                </div>
              </div>
            </div>
          ))}
        </section>

        {error && <div className="error">Error: {error}</div>}
      </div>
      {viewerShot && (
        <div className="viewer-overlay" onClick={() => setViewerShot(null)}>
          <div className="viewer-card" onClick={(e) => e.stopPropagation()}>
            <div className="viewer-header">
              <div className="viewer-title">{viewerShot.filename}</div>
              <button
                className="icon-btn ghost viewer-close"
                onClick={() => setViewerShot(null)}
                aria-label="Close"
              >
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M18.3 5.7 12 12l6.3 6.3-1.4 1.4L10.6 13.4 4.3 19.7 2.9 18.3 9.2 12 2.9 5.7 4.3 4.3l6.3 6.3 6.3-6.3z" />
                </svg>
              </button>
            </div>
            <img
              className="viewer-image"
              src={`/screenshots/file/${viewerShot.id}`}
              alt={viewerShot.filename}
            />
          </div>
        </div>
      )}
    </div>
  );
}
