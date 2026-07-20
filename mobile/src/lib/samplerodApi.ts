import { buildBaseUrl, getConnection, type SampleRodConnection } from './connectionStorage';

function authHeaders(conn: SampleRodConnection): Record<string, string> {
  const h: Record<string, string> = {};
  if (conn.token) h['Authorization'] = `Bearer ${conn.token}`;
  return h;
}

export type RecordStatus = {
  is_recording: boolean;
  retro_enabled: boolean;
  pre_seconds: number;
};

export async function fetchStatus(): Promise<RecordStatus> {
  const conn = getConnection();
  if (!conn) throw new Error('Non connecte');
  const res = await fetch(`${buildBaseUrl(conn)}/record/status`, {
    headers: authHeaders(conn),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json() as Promise<RecordStatus>;
}

export async function startRecording(libraryId?: number): Promise<void> {
  const conn = getConnection();
  if (!conn) throw new Error('Non connecte');
  const body: Record<string, unknown> = {};
  if (libraryId !== undefined) body.library_id = libraryId;
  const res = await fetch(`${buildBaseUrl(conn)}/record/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders(conn) },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
}

export async function stopRecording(): Promise<void> {
  const conn = getConnection();
  if (!conn) throw new Error('Non connecte');
  const res = await fetch(`${buildBaseUrl(conn)}/record/stop`, {
    method: 'POST',
    headers: authHeaders(conn),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
}

// Upload d'un fichier audio via XHR (fetch + FormData bugge sur RN 0.85)
export function uploadRecording(
  fileUri: string,
  filename: string,
  libraryId?: number,
  onProgress?: (pct: number) => void,
): Promise<{ filename: string; path: string; sample_id: number | null }> {
  return new Promise((resolve, reject) => {
    const conn = getConnection();
    if (!conn) { reject(new Error('Non connecte')); return; }

    const url = libraryId !== undefined
      ? `${buildBaseUrl(conn)}/mobile/upload?library_id=${libraryId}`
      : `${buildBaseUrl(conn)}/mobile/upload`;

    const xhr = new XMLHttpRequest();
    xhr.open('POST', url);
    if (conn.token) xhr.setRequestHeader('Authorization', `Bearer ${conn.token}`);
    xhr.setRequestHeader('X-Filename', filename);

    if (onProgress && xhr.upload) {
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100));
      };
    }

    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try { resolve(JSON.parse(xhr.responseText)); }
        catch { resolve({ filename, path: '', sample_id: null }); }
      } else {
        reject(new Error(`Upload echoue: HTTP ${xhr.status}`));
      }
    };
    xhr.onerror = () => reject(new Error('Erreur reseau'));

    // Envoie le fichier comme body binaire brut
    xhr.send({ uri: fileUri, type: 'audio/m4a', name: filename } as unknown as Document);
  });
}
