import { useEffect, useRef, useState } from 'react';
import { buildBaseUrl, getConnection, type SampleRodConnection } from '@/lib/connectionStorage';
import { fetchStatus, type RecordStatus } from '@/lib/samplerodApi';

type RemoteState = {
  status: RecordStatus | null;
  connected: boolean;
  error: string | null;
};

// Ouvre un flux SSE vers /events et met a jour le statut en temps reel.
// Reconnexion automatique apres 3s si la connexion se coupe.
export function useRemoteStatus(connection: SampleRodConnection | null) {
  const [state, setState] = useState<RemoteState>({ status: null, connected: false, error: null });
  const esRef = useRef<EventSource | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!connection) {
      setState({ status: null, connected: false, error: null });
      return;
    }

    let cancelled = false;

    function connect() {
      if (cancelled) return;

      const url = buildBaseUrl(connection!) + '/events'
        + (connection!.token ? `?token=${encodeURIComponent(connection!.token)}` : '');

      const es = new EventSource(url);
      esRef.current = es;

      es.addEventListener('status', (e: MessageEvent) => {
        try {
          const data = JSON.parse(e.data) as RecordStatus;
          setState({ status: data, connected: true, error: null });
        } catch { /* ignore */ }
      });

      es.onerror = () => {
        es.close();
        esRef.current = null;
        setState(prev => ({ ...prev, connected: false, error: 'Connexion perdue' }));
        // Reconnexion apres 3s
        if (!cancelled) timerRef.current = setTimeout(connect, 3000);
      };
    }

    // Snapshot initial avant d'ouvrir SSE
    fetchStatus()
      .then(s => setState({ status: s, connected: true, error: null }))
      .catch(() => setState(prev => ({ ...prev, error: 'Serveur inaccessible' })));

    connect();

    return () => {
      cancelled = true;
      if (timerRef.current) clearTimeout(timerRef.current);
      esRef.current?.close();
    };
  }, [connection]);

  return state;
}
