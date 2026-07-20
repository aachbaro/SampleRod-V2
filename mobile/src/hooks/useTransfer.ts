import { useCallback, useState } from 'react';
import { uploadRecording } from '@/lib/samplerodApi';
import { getConnection } from '@/lib/connectionStorage';
import type { LocalRecording } from './useRetroRecorder';

type TransferState = {
  uploading: boolean;
  current: string | null;
  progress: number;
  done: number;
  total: number;
  errors: string[];
};

// Upload sequentiel de tous les recordings non synchronises vers SampleRod.
export function useTransfer(
  recordings: LocalRecording[],
  onSynced: (id: string) => Promise<void>,
) {
  const [state, setState] = useState<TransferState>({
    uploading: false, current: null, progress: 0, done: 0, total: 0, errors: [],
  });

  const transferAll = useCallback(async (libraryId?: number) => {
    const conn = getConnection();
    if (!conn) throw new Error('Non connecte — scanne le QR code d\'abord');

    const pending = recordings.filter(r => !r.synced);
    if (pending.length === 0) return;

    setState({ uploading: true, current: null, progress: 0, done: 0, total: pending.length, errors: [] });

    const errors: string[] = [];
    let done = 0;

    for (const rec of pending) {
      setState(prev => ({ ...prev, current: rec.filename, progress: 0 }));
      try {
        await uploadRecording(
          rec.uri,
          rec.filename,
          libraryId,
          (pct) => setState(prev => ({ ...prev, progress: pct })),
        );
        await onSynced(rec.id);
        done++;
        setState(prev => ({ ...prev, done }));
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        errors.push(`${rec.filename}: ${msg}`);
      }
    }

    setState(prev => ({ ...prev, uploading: false, current: null, errors }));
  }, [recordings, onSynced]);

  return { ...state, transferAll };
}
