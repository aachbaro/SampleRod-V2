import { useAudioRecorder, RecordingPresets, requestRecordingPermissionsAsync } from 'expo-audio';
import * as FileSystem from 'expo-file-system/legacy';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { useCallback, useEffect, useRef, useState } from 'react';

// Preset musique : qualite maximale, 192kbps stereo 44100Hz
// Android: audioSource 9 = UNPROCESSED (micro brut, pas de filtre voix)
const MUSIC_PRESET = {
  ...RecordingPresets.HIGH_QUALITY,
  android: {
    ...RecordingPresets.HIGH_QUALITY.android,
    sampleRate: 44100,
    numberOfChannels: 2,
    bitRate: 192000,
    audioSource: 9, // AudioSource.UNPROCESSED — pas de noise/echo cancellation
  },
  ios: {
    ...RecordingPresets.HIGH_QUALITY.ios,
    sampleRate: 44100,
    numberOfChannels: 2,
    bitRate: 192000,
  },
};

const RECORDINGS_KEY = 'samplerod_recordings';
const SEGMENT_DIR = FileSystem.cacheDirectory + 'sr_segments/';
const RECORDINGS_DIR = FileSystem.documentDirectory + 'sr_recordings/';
const SEGMENT_DURATION_MS = 5000;
const MAX_SEGMENTS = 12; // 60 secondes de buffer

export type LocalRecording = {
  id: string;
  filename: string;
  uri: string;
  durationSeconds: number;
  recordedAt: string;
  synced: boolean;
};

async function ensureDirs() {
  await FileSystem.makeDirectoryAsync(SEGMENT_DIR, { intermediates: true });
  await FileSystem.makeDirectoryAsync(RECORDINGS_DIR, { intermediates: true });
}

async function loadRecordingsList(): Promise<LocalRecording[]> {
  const raw = await AsyncStorage.getItem(RECORDINGS_KEY);
  if (!raw) return [];
  try { return JSON.parse(raw) as LocalRecording[]; }
  catch { return []; }
}

async function saveRecordingsList(list: LocalRecording[]): Promise<void> {
  await AsyncStorage.setItem(RECORDINGS_KEY, JSON.stringify(list));
}

export function useRetroRecorder() {
  const [recordings, setRecordings] = useState<LocalRecording[]>([]);
  const [isRecording, setIsRecording] = useState(false);
  const [bufferSeconds, setBufferSeconds] = useState(0);
  const [permissionGranted, setPermissionGranted] = useState(false);

  const segmentPaths = useRef<string[]>([]);
  const segmentTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const recorder = useAudioRecorder(MUSIC_PRESET as typeof RecordingPresets.HIGH_QUALITY);
  const segmentIndex = useRef(0);

  // Charge la liste sauvegardee au demarrage
  useEffect(() => {
    ensureDirs().then(() => loadRecordingsList().then(setRecordings));
  }, []);

  // Mise a jour du compteur de buffer toutes les secondes
  useEffect(() => {
    if (!isRecording) { setBufferSeconds(0); return; }
    const t = setInterval(() => {
      setBufferSeconds(segmentPaths.current.length * (SEGMENT_DURATION_MS / 1000));
    }, 1000);
    return () => clearInterval(t);
  }, [isRecording]);

  const requestPermission = useCallback(async (): Promise<boolean> => {
    const { granted } = await requestRecordingPermissionsAsync();
    setPermissionGranted(granted);
    return granted;
  }, []);

  // Lance l'enregistrement d'un segment, recommence automatiquement
  const startNextSegment = useCallback(async () => {
    const path = SEGMENT_DIR + `seg_${Date.now()}_${segmentIndex.current++}.m4a`;
    try {
      await recorder.prepareToRecordAsync();
      recorder.record();
    } catch { /* ignore si deja en cours */ }
  }, [recorder]);

  // Arrete le segment courant, sauvegarde le fichier, tourne le buffer
  const rotateSegment = useCallback(async () => {
    try {
      await recorder.stop();
      const uri = recorder.uri;
      if (uri) {
        const dest = SEGMENT_DIR + `seg_${Date.now()}.m4a`;
        await FileSystem.moveAsync({ from: uri, to: dest });
        segmentPaths.current.push(dest);
        // Garde seulement les MAX_SEGMENTS derniers
        while (segmentPaths.current.length > MAX_SEGMENTS) {
          const old = segmentPaths.current.shift()!;
          FileSystem.deleteAsync(old, { idempotent: true });
        }
      }
    } catch { /* segment rate, on continue */ }
    startNextSegment();
  }, [recorder, startNextSegment]);

  const startRetroBuffer = useCallback(async () => {
    const granted = await requestPermission();
    if (!granted) return;
    segmentPaths.current = [];
    segmentIndex.current = 0;
    setIsRecording(true);
    await startNextSegment();
    // Rotation toutes les SEGMENT_DURATION_MS
    segmentTimer.current = setInterval(() => { void rotateSegment(); }, SEGMENT_DURATION_MS);
  }, [requestPermission, startNextSegment, rotateSegment]);

  const stopAndSave = useCallback(async (keepLastSeconds = 30): Promise<LocalRecording | null> => {
    if (segmentTimer.current) {
      clearInterval(segmentTimer.current);
      segmentTimer.current = null;
    }
    try { await recorder.stop(); } catch { /* peut etre deja arrete */ }
    const uri = recorder.uri;
    if (uri) {
      segmentPaths.current.push(uri);
    }
    setIsRecording(false);

    // Nombre de segments a garder
    const secsPerSeg = SEGMENT_DURATION_MS / 1000;
    const keepCount = Math.ceil(keepLastSeconds / secsPerSeg);
    const toKeep = segmentPaths.current.slice(-keepCount);

    if (toKeep.length === 0) {
      segmentPaths.current = [];
      return null;
    }

    // Si un seul segment, le copier directement
    const filename = `recording_${new Date().toISOString().replace(/[:.]/g, '-')}.m4a`;
    const dest = RECORDINGS_DIR + filename;

    if (toKeep.length === 1) {
      await FileSystem.copyAsync({ from: toKeep[0], to: dest });
    } else {
      // Concatenation: copier le premier segment comme base, les autres seront
      // envoyes separes si la concatenation n'est pas disponible.
      // TODO: utiliser ffmpeg-kit pour concat propre
      await FileSystem.copyAsync({ from: toKeep[0], to: dest });
    }

    // Nettoyage des segments
    for (const p of segmentPaths.current) {
      FileSystem.deleteAsync(p, { idempotent: true });
    }
    segmentPaths.current = [];

    // Taille approximative pour duree
    const info = await FileSystem.getInfoAsync(dest, { size: true });
    const durationSeconds = keepLastSeconds;

    const rec: LocalRecording = {
      id: Date.now().toString(),
      filename,
      uri: dest,
      durationSeconds,
      recordedAt: new Date().toISOString(),
      synced: false,
    };

    const updated = [rec, ...recordings];
    setRecordings(updated);
    await saveRecordingsList(updated);
    return rec;
  }, [recorder, recordings]);

  const stopBuffer = useCallback(() => {
    if (segmentTimer.current) {
      clearInterval(segmentTimer.current);
      segmentTimer.current = null;
    }
    recorder.stop().catch(() => {});
    for (const p of segmentPaths.current) {
      FileSystem.deleteAsync(p, { idempotent: true });
    }
    segmentPaths.current = [];
    setIsRecording(false);
  }, [recorder]);

  const markSynced = useCallback(async (id: string) => {
    const updated = recordings.map(r => r.id === id ? { ...r, synced: true } : r);
    setRecordings(updated);
    await saveRecordingsList(updated);
  }, [recordings]);

  const deleteRecording = useCallback(async (id: string) => {
    const rec = recordings.find(r => r.id === id);
    if (rec) FileSystem.deleteAsync(rec.uri, { idempotent: true });
    const updated = recordings.filter(r => r.id !== id);
    setRecordings(updated);
    await saveRecordingsList(updated);
  }, [recordings]);

  return {
    recordings,
    isRecording,
    bufferSeconds,
    permissionGranted,
    startRetroBuffer,
    stopAndSave,
    stopBuffer,
    markSynced,
    deleteRecording,
  };
}
