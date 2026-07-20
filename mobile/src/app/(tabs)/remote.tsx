import { useCallback, useState } from 'react';
import { Alert, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useC } from '@/constants/ThemeContext';
import { Spacing, Radius } from '@/constants/theme';
import { useConnection } from '@/hooks/useConnection';
import { useRemoteStatus } from '@/hooks/useRemoteStatus';
import { startRecording, stopRecording } from '@/lib/samplerodApi';

export default function RemoteScreen() {
  const C = useC();
  const { connection } = useConnection();
  const { status, connected, error } = useRemoteStatus(connection);
  const [busy, setBusy] = useState(false);

  const handleStart = useCallback(async () => {
    setBusy(true);
    try {
      await startRecording();
    } catch (e) {
      Alert.alert('Erreur', e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, []);

  const handleStop = useCallback(async () => {
    setBusy(true);
    try {
      await stopRecording();
    } catch (e) {
      Alert.alert('Erreur', e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, []);

  if (!connection) {
    return (
      <SafeAreaView style={[styles.safe, { backgroundColor: C.bgA }]}>
        <View style={styles.empty}>
          <Text style={[styles.emptyIcon]}>🔗</Text>
          <Text style={[styles.emptyText, { color: C.textMuted }]}>
            Scanne le QR code dans l'onglet Transferer pour te connecter a SampleRod.
          </Text>
        </View>
      </SafeAreaView>
    );
  }

  const isRecording = status?.is_recording ?? false;

  return (
    <SafeAreaView style={[styles.safe, { backgroundColor: C.bgA }]}>
      <View style={styles.header}>
        <Text style={[styles.title, { color: C.textMain }]}>Remote</Text>
        <View style={[styles.dot, { backgroundColor: connected ? C.success : C.error }]} />
      </View>

      {/* Infos serveur */}
      <View style={[styles.card, { backgroundColor: C.cardBg, borderColor: C.border }]}>
        <Text style={[styles.cardLabel, { color: C.textMuted }]}>Connecte a</Text>
        <Text style={[styles.cardValue, { color: C.textMain }]}>
          {connection.host}:{connection.port}
        </Text>
        {error && <Text style={[styles.errorText, { color: C.error }]}>{error}</Text>}
      </View>

      {/* Statut enregistrement */}
      <View style={[styles.card, { backgroundColor: C.cardBg, borderColor: C.border }]}>
        <Text style={[styles.cardLabel, { color: C.textMuted }]}>Etat</Text>
        <Text style={[styles.statusText, { color: isRecording ? C.recRed : C.textMuted }]}>
          {status === null ? '—' : isRecording ? '● Enregistrement en cours' : '○ En attente'}
        </Text>
        {status?.retro_enabled && (
          <Text style={[styles.retroLabel, { color: C.textMuted }]}>
            Retro: {status.pre_seconds}s
          </Text>
        )}
      </View>

      {/* Boutons */}
      <View style={styles.btnRow}>
        <TouchableOpacity
          style={[
            styles.btn,
            { backgroundColor: isRecording ? C.cardSoft : C.recRed, opacity: busy ? 0.5 : 1 },
          ]}
          onPress={() => void handleStart()}
          disabled={busy || isRecording}
        >
          <Text style={[styles.btnLabel, { color: isRecording ? C.textMuted : '#fff' }]}>
            Demarrer
          </Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={[
            styles.btn,
            { backgroundColor: isRecording ? C.accent : C.cardSoft, opacity: busy ? 0.5 : 1 },
          ]}
          onPress={() => void handleStop()}
          disabled={busy || !isRecording}
        >
          <Text style={[styles.btnLabel, { color: isRecording ? '#fff' : C.textMuted }]}>
            Arreter
          </Text>
        </TouchableOpacity>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1 },
  header: {
    flexDirection: 'row', alignItems: 'center', gap: Spacing.sm,
    paddingHorizontal: Spacing.lg, paddingTop: Spacing.lg, paddingBottom: Spacing.sm,
  },
  title: { fontSize: 22, fontWeight: '700', flex: 1 },
  dot: { width: 10, height: 10, borderRadius: 5 },
  card: {
    marginHorizontal: Spacing.lg, marginBottom: Spacing.md,
    padding: Spacing.md, borderRadius: Radius.md, borderWidth: 1,
  },
  cardLabel: { fontSize: 11, fontWeight: '600', textTransform: 'uppercase', letterSpacing: 0.6, marginBottom: 4 },
  cardValue: { fontSize: 15, fontWeight: '500' },
  errorText: { fontSize: 12, marginTop: 4 },
  statusText: { fontSize: 16, fontWeight: '600' },
  retroLabel: { fontSize: 12, marginTop: 4 },
  btnRow: { flexDirection: 'row', gap: Spacing.md, paddingHorizontal: Spacing.lg, marginTop: Spacing.lg },
  btn: { flex: 1, paddingVertical: Spacing.lg, borderRadius: Radius.lg, alignItems: 'center' },
  btnLabel: { fontSize: 16, fontWeight: '700' },
  empty: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: Spacing.xxl, gap: Spacing.lg },
  emptyIcon: { fontSize: 48 },
  emptyText: { textAlign: 'center', fontSize: 14, lineHeight: 22 },
});
