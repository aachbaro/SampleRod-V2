import { CameraView, useCameraPermissions } from 'expo-camera';
import { useCallback, useState } from 'react';
import { ActivityIndicator, Alert, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useC } from '@/constants/ThemeContext';
import { Spacing, Radius } from '@/constants/theme';
import { useConnection } from '@/hooks/useConnection';
import { useRetroRecorder } from '@/hooks/useRetroRecorder';
import { useTransfer } from '@/hooks/useTransfer';
import type { SampleRodConnection } from '@/lib/connectionStorage';

type QRPayload = { host: string; port: number; token: string };

function isValidPayload(v: unknown): v is QRPayload {
  if (typeof v !== 'object' || v === null) return false;
  const o = v as Record<string, unknown>;
  return typeof o.host === 'string' && typeof o.port === 'number';
}

export default function TransferScreen() {
  const C = useC();
  const [permission, requestPermission] = useCameraPermissions();
  const [scanning, setScanning] = useState(false);
  const { connection, connect, disconnect } = useConnection();
  const { recordings, markSynced } = useRetroRecorder();
  const { uploading, current, progress, done, total, errors, transferAll } = useTransfer(recordings, markSynced);

  const pendingCount = recordings.filter(r => !r.synced).length;

  const handleBarcode = useCallback(async ({ data }: { data: string }) => {
    if (!scanning) return;
    setScanning(false);
    try {
      const payload = JSON.parse(data) as unknown;
      if (!isValidPayload(payload)) throw new Error('QR invalide');
      const conn: SampleRodConnection = {
        host: payload.host,
        port: payload.port,
        token: payload.token ?? '',
      };
      await connect(conn);
      Alert.alert('Connecte !', `${conn.host}:${conn.port}`);
    } catch {
      Alert.alert('QR invalide', 'Ce QR code ne vient pas de SampleRod.');
      setScanning(true);
    }
  }, [scanning, connect]);

  const handleTransfer = useCallback(async () => {
    try {
      await transferAll();
      if (errors.length === 0) {
        Alert.alert('Transfert termine', `${done} fichier(s) envoye(s).`);
      }
    } catch (e) {
      Alert.alert('Erreur', e instanceof Error ? e.message : String(e));
    }
  }, [transferAll, done, errors]);

  return (
    <SafeAreaView style={[styles.safe, { backgroundColor: C.bgA }]}>
      <View style={styles.header}>
        <Text style={[styles.title, { color: C.textMain }]}>Transferer</Text>
      </View>

      {/* Statut connexion */}
      <View style={[styles.card, { backgroundColor: C.cardBg, borderColor: C.border }]}>
        {connection ? (
          <View style={styles.connRow}>
            <View>
              <Text style={[styles.cardLabel, { color: C.textMuted }]}>Serveur</Text>
              <Text style={[styles.cardValue, { color: C.textMain }]}>
                {connection.host}:{connection.port}
              </Text>
            </View>
            <TouchableOpacity onPress={() => void disconnect()} hitSlop={8}>
              <Text style={{ color: C.error, fontSize: 13 }}>Deconnecter</Text>
            </TouchableOpacity>
          </View>
        ) : (
          <Text style={[styles.cardValue, { color: C.textMuted }]}>Non connecte</Text>
        )}
      </View>

      {/* Scanner QR */}
      {!connection && (
        <View style={styles.section}>
          <Text style={[styles.sectionTitle, { color: C.textMuted }]}>
            Scanne le QR code dans Parametres › Controle distant de SampleRod
          </Text>

          {scanning ? (
            <View style={[styles.scanner, { borderColor: C.border }]}>
              <CameraView
                style={StyleSheet.absoluteFill}
                facing="back"
                barcodeScannerSettings={{ barcodeTypes: ['qr'] }}
                onBarcodeScanned={handleBarcode}
              />
              <TouchableOpacity
                style={[styles.cancelScan, { backgroundColor: C.cardBg }]}
                onPress={() => setScanning(false)}
              >
                <Text style={{ color: C.textMain }}>Annuler</Text>
              </TouchableOpacity>
            </View>
          ) : (
            <TouchableOpacity
              style={[styles.scanBtn, { backgroundColor: C.accent }]}
              onPress={async () => {
                if (!permission?.granted) {
                  const { granted } = await requestPermission();
                  if (!granted) {
                    Alert.alert('Camera refusee', 'Active la camera dans les parametres.');
                    return;
                  }
                }
                setScanning(true);
              }}
            >
              <Text style={styles.scanBtnLabel}>Scanner le QR code</Text>
            </TouchableOpacity>
          )}
        </View>
      )}

      {/* Bouton transfert */}
      {connection && (
        <View style={styles.section}>
          <Text style={[styles.sectionTitle, { color: C.textMuted }]}>
            {pendingCount === 0
              ? 'Tous tes enregistrements sont synchronises.'
              : `${pendingCount} enregistrement(s) en attente de transfert.`}
          </Text>

          {uploading ? (
            <View style={styles.progressBlock}>
              <ActivityIndicator color={C.accent} />
              <Text style={[styles.progressText, { color: C.textMuted }]}>
                {current ?? '...'} ({done}/{total})
              </Text>
              <View style={[styles.progressBar, { backgroundColor: C.border }]}>
                <View
                  style={[
                    styles.progressFill,
                    { backgroundColor: C.accent, width: `${progress}%` as `${number}%` },
                  ]}
                />
              </View>
            </View>
          ) : (
            <TouchableOpacity
              style={[
                styles.transferBtn,
                { backgroundColor: pendingCount === 0 ? C.cardSoft : C.accent },
              ]}
              onPress={() => void handleTransfer()}
              disabled={pendingCount === 0}
            >
              <Text style={[styles.transferBtnLabel, { color: pendingCount === 0 ? C.textMuted : '#fff' }]}>
                Transferer vers SampleRod
              </Text>
            </TouchableOpacity>
          )}

          {errors.length > 0 && (
            <View style={styles.errorBlock}>
              {errors.map((e, i) => (
                <Text key={i} style={[styles.errorItem, { color: C.error }]}>{e}</Text>
              ))}
            </View>
          )}
        </View>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1 },
  header: { paddingHorizontal: Spacing.lg, paddingTop: Spacing.lg, paddingBottom: Spacing.sm },
  title: { fontSize: 22, fontWeight: '700' },
  card: {
    marginHorizontal: Spacing.lg, marginBottom: Spacing.md,
    padding: Spacing.md, borderRadius: Radius.md, borderWidth: 1,
  },
  cardLabel: { fontSize: 11, fontWeight: '600', textTransform: 'uppercase', letterSpacing: 0.6, marginBottom: 2 },
  cardValue: { fontSize: 15, fontWeight: '500' },
  connRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  section: { paddingHorizontal: Spacing.lg, gap: Spacing.md },
  sectionTitle: { fontSize: 13, lineHeight: 20 },
  scanBtn: {
    paddingVertical: Spacing.lg, borderRadius: Radius.lg, alignItems: 'center',
  },
  scanBtnLabel: { color: '#fff', fontWeight: '700', fontSize: 16 },
  scanner: {
    height: 260, borderRadius: Radius.lg, overflow: 'hidden',
    borderWidth: 1, position: 'relative',
  },
  cancelScan: {
    position: 'absolute', bottom: Spacing.md, alignSelf: 'center',
    paddingHorizontal: Spacing.lg, paddingVertical: Spacing.sm,
    borderRadius: Radius.md,
  },
  transferBtn: {
    paddingVertical: Spacing.lg, borderRadius: Radius.lg, alignItems: 'center',
  },
  transferBtnLabel: { fontWeight: '700', fontSize: 16 },
  progressBlock: { gap: Spacing.sm, alignItems: 'center' },
  progressText: { fontSize: 13 },
  progressBar: { width: '100%', height: 4, borderRadius: 2, overflow: 'hidden' },
  progressFill: { height: '100%', borderRadius: 2 },
  errorBlock: { gap: 4 },
  errorItem: { fontSize: 12 },
});
