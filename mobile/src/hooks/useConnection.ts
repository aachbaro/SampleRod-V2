import { useCallback, useEffect, useState } from 'react';
import {
  clearConnection,
  getConnection,
  loadConnection,
  saveConnection,
  type SampleRodConnection,
} from '@/lib/connectionStorage';

export function useConnection() {
  const [connection, setConnection] = useState<SampleRodConnection | null>(getConnection());
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadConnection().then(c => {
      setConnection(c);
      setLoading(false);
    });
  }, []);

  const connect = useCallback(async (conn: SampleRodConnection) => {
    await saveConnection(conn);
    setConnection(conn);
  }, []);

  const disconnect = useCallback(async () => {
    await clearConnection();
    setConnection(null);
  }, []);

  return { connection, loading, connect, disconnect };
}
