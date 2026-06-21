import React, { useEffect, useState } from 'react';
import { View, Text, StyleSheet, ScrollView, RefreshControl, ActivityIndicator } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import * as api from '../services/api';
import { Digest } from '../types';
import { colors } from '../theme/colors';

export default function DigestScreen() {
  const insets = useSafeAreaInsets();
  const [digest, setDigest] = useState<Digest | null>(null);
  const [loading, setLoading] = useState(true);

  const loadDigest = async () => {
    try {
      const res = await api.digests.latest();
      setDigest(res.data);
    } catch (_) {
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadDigest(); }, []);

  if (loading) {
    return (
      <View style={[styles.centered, { paddingTop: insets.top }]}>
        <ActivityIndicator size="large" color={colors.primary} />
      </View>
    );
  }

  if (!digest) {
    return (
      <View style={[styles.centered, { paddingTop: insets.top }]}>
        <Text style={styles.empty}>还没有日报</Text>
      </View>
    );
  }

  return (
    <ScrollView style={[styles.container, { paddingTop: insets.top }]} refreshControl={<RefreshControl refreshing={loading} onRefresh={loadDigest} />}>
      <View style={styles.header}>
        <Text style={styles.date}>📅 {digest.date}</Text>
        {digest.score && (
          <View style={styles.scoreRow}>
            <Text style={styles.scoreLabel}>今日评分</Text>
            <Text style={styles.scoreValue}>{digest.score}/100</Text>
          </View>
        )}
      </View>

      {digest.highlights && (
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>✨ 今日亮点</Text>
          {Object.entries(digest.highlights).map(([k, v], i) => (
            <Text key={i} style={styles.listItem}>• {v}</Text>
          ))}
        </View>
      )}

      {digest.problems && (
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>⚠️ 今日问题</Text>
          {Object.entries(digest.problems).map(([k, v], i) => (
            <Text key={i} style={styles.listItem}>• {v}</Text>
          ))}
        </View>
      )}

      {digest.suggestions && (
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>💡 明日建议</Text>
          {Object.entries(digest.suggestions).map(([k, v], i) => (
            <Text key={i} style={styles.listItem}>• {v}</Text>
          ))}
        </View>
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  centered: { flex: 1, justifyContent: 'center', alignItems: 'center' },
  header: { backgroundColor: colors.headerBg, padding: 24 },
  date: { fontSize: 18, fontWeight: '600', color: colors.text, marginBottom: 12 },
  scoreRow: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  scoreLabel: { fontSize: 14, color: colors.textSecondary },
  scoreValue: { fontSize: 28, fontWeight: '700', color: colors.primary },
  section: { backgroundColor: colors.card, margin: 16, marginBottom: 0, padding: 16, borderRadius: 14, shadowColor: colors.text, shadowOffset: { width: 0, height: 1 }, shadowOpacity: 0.05, shadowRadius: 3, elevation: 1 },
  sectionTitle: { fontSize: 15, fontWeight: '600', color: colors.text, marginBottom: 8 },
  listItem: { fontSize: 14, color: colors.textSecondary, lineHeight: 22, marginBottom: 4 },
  empty: { color: colors.textMuted, fontSize: 14 },
});
