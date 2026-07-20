import AsyncStorage from '@react-native-async-storage/async-storage';

const KEY = 'samplerod_connection';

export type SampleRodConnection = {
  host: string;
  port: number;
  token: string;
};

let _cached: SampleRodConnection | null = null;

export async function loadConnection(): Promise<SampleRodConnection | null> {
  const raw = await AsyncStorage.getItem(KEY);
  if (!raw) return null;
  try {
    _cached = JSON.parse(raw) as SampleRodConnection;
    return _cached;
  } catch {
    return null;
  }
}

export function getConnection(): SampleRodConnection | null {
  return _cached;
}

export async function saveConnection(conn: SampleRodConnection): Promise<void> {
  _cached = conn;
  await AsyncStorage.setItem(KEY, JSON.stringify(conn));
}

export async function clearConnection(): Promise<void> {
  _cached = null;
  await AsyncStorage.removeItem(KEY);
}

export function buildBaseUrl(conn: SampleRodConnection): string {
  return `http://${conn.host}:${conn.port}`;
}
