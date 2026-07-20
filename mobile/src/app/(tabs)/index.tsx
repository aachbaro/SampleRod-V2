import { useState } from 'react';
import { Alert, FlatList, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useC } from '@/constants/ThemeContext';
import { Spacing, Radius } from '@/constants/theme';
import { useRetroRecorder, type LocalRecording } from '@/hooks/useRetroRecorder';

function fmt(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

function RecordingRow({ rec, onDelete, C }: { rec: LocalRecording; onDelete: () => void; C: ReturnType<typeof useC> }) {
  const date = new Date(rec.recordedAt).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' });
  return (
    <View style={[styles.row, { backgroundColor: C.cardBg, borderColor: C.border }]}>
      <View style={styles.rowLeft}>
        <Text style={[styles.rowName, { color: C.textMain }]} numberOfLines={1}>{rec.filename}</Text>
        <Text style={[styles.rowMeta, { color: C.textMuted }]}>{date} · {fmt(rec.durationSeconds)}</Text>
      </View>
      <View style={styles.rowRight}>
        {rec.synced && <Text style={[styles.badge, { backgroundColor: C.accentSoft, color: C.accent }]}>sync</Text>}
        <TouchableOpacity onPress={onDelete} hitSlop={8}>
          <Text style={{ color: C.error, fontSize: 16 }}>🗑</Text>
        </TouchableOpacity>
      </View>
    </View>
  );
}

export default function RecorderScreen() {
  const C = useC();
  const {
    recordings, isRecording, bufferSeconds,
    startRetroBuffer, stopAndSave, stopBuffer, deleteRecording,
  } = useRetroRecorder();

  const [keepSecs, setKeepSecs] = useState(30);

  async function handleSave() {
    const rec = await stopAndSave(keepSecs);
    if (rec) Alert.alert('Enregistrement sauvegarde', `${rec.filename}\n${fmt(rec.durationSeconds)} garde`);
  }

  return (
    <SafeAreaView style={[styles.safe, { backgroundColor: C.bgA }]}>
      {/* Header */}
      <View style={styles.header}>
        <Text style={[styles.title, { color: C.textMain }]}>Enregistrer</Text>
      </View>

      {/* Bouton principal */}
      <View style={styles.center}>
        {!isRecording ? (
          <TouchableOpacity
            style={[styles.bigBtn, { backgroundColor: C.recRed }]}
            onPress={() => void startRetroBuffer()}
          >
            <Text style={styles.bigBtnIcon}>🎙</Text>
            <Text style={styles.bigBtnLabel}>Demarrer le buffer</Text>
          </TouchableOpacity>
        ) : (
          <View style={styles.recordingBlock}>
            <View style={[styles.indicator, { backgroundColor: C.recRed }]} />
            <Text style={[styles.bufferLabel, { color: C.textMuted }]}>
              Buffer: {fmt(bufferSeconds)}
            </Text>

            {/* Choix duree a garder */}
            <View style={styles.keepRow}>
              {[15, 30, 60].map(s => (
                <TouchableOpacity
                  key={s}
                  onPress={() => setKeepSecs(s)}
                  style={[
                    styles.keepBtn,
                    {
                      backgroundColor: keepSecs === s ? C.accent : C.cardSoft,
                      borderColor: C.border,
                    },
                  ]}
                >
                  <Text style={{ color: keepSecs === s ? '#fff' : C.textMuted, fontWeight: '600' }}>
                    {s}s
                  </Text>
                </TouchableOpacity>
              ))}
            </View>

            <TouchableOpacity
              style={[styles.saveBtn, { backgroundColor: C.accent }]}
              onPress={() => void handleSave()}
            >
              <Text style={styles.saveBtnLabel}>Sauvegarder les {keepSecs}s</Text>
            </TouchableOpacity>

            <TouchableOpacity onPress={stopBuffer}>
              <Text style={[styles.cancelLabel, { color: C.textMuted }]}>Annuler le buffer</Text>
            </TouchableOpacity>
          </View>
        )}
      </View>

      {/* Liste des enregistrements */}
      <FlatList
        data={recordings}
        keyExtractor={r => r.id}
        contentContainerStyle={styles.list}
        ListHeaderComponent={
          recordings.length > 0
            ? <Text style={[styles.listTitle, { color: C.textMuted }]}>Enregistrements locaux</Text>
            : null
        }
        renderItem={({ item }) => (
          <RecordingRow rec={item} C={C} onDelete={() => void deleteRecording(item.id)} />
        )}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1 },
  header: { paddingHorizontal: Spacing.lg, paddingTop: Spacing.lg, paddingBottom: Spacing.sm },
  title: { fontSize: 22, fontWeight: '700' },
  center: { alignItems: 'center', paddingVertical: Spacing.xxl },
  bigBtn: {
    width: 160, height: 160, borderRadius: 80,
    alignItems: 'center', justifyContent: 'center', gap: Spacing.sm,
  },
  bigBtnIcon: { fontSize: 48 },
  bigBtnLabel: { color: '#fff', fontWeight: '700', fontSize: 13 },
  recordingBlock: { alignItems: 'center', gap: Spacing.lg },
  indicator: { width: 14, height: 14, borderRadius: 7 },
  bufferLabel: { fontSize: 14 },
  keepRow: { flexDirection: 'row', gap: Spacing.sm },
  keepBtn: {
    paddingHorizontal: Spacing.lg, paddingVertical: Spacing.sm,
    borderRadius: Radius.md, borderWidth: 1,
  },
  saveBtn: {
    paddingHorizontal: Spacing.xl, paddingVertical: Spacing.md,
    borderRadius: Radius.lg,
  },
  saveBtnLabel: { color: '#fff', fontWeight: '700', fontSize: 16 },
  cancelLabel: { fontSize: 13, textDecorationLine: 'underline' },
  list: { paddingHorizontal: Spacing.lg, paddingBottom: Spacing.xxl },
  listTitle: { fontSize: 12, fontWeight: '600', marginBottom: Spacing.sm, textTransform: 'uppercase', letterSpacing: 0.8 },
  row: {
    flexDirection: 'row', alignItems: 'center', padding: Spacing.md,
    borderRadius: Radius.md, borderWidth: 1, marginBottom: Spacing.sm,
  },
  rowLeft: { flex: 1, marginRight: Spacing.sm },
  rowName: { fontSize: 13, fontWeight: '600' },
  rowMeta: { fontSize: 11, marginTop: 2 },
  rowRight: { flexDirection: 'row', alignItems: 'center', gap: Spacing.sm },
  badge: {
    fontSize: 10, fontWeight: '700', paddingHorizontal: 6, paddingVertical: 2,
    borderRadius: 4, textTransform: 'uppercase',
  },
});
