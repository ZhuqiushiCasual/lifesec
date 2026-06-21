import React, { useCallback, useState } from 'react';
import { View, Text, FlatList, StyleSheet, TouchableOpacity, ActivityIndicator, RefreshControl } from 'react-native';
import { useFocusEffect } from '@react-navigation/native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import * as api from '../services/api';
import { Insight } from '../types';
import { colors } from '../theme/colors';

const CATEGORIES = ['all', 'ai', 'finance', 'industry'];
const CAT_NAMES: Record<string, string> = { all: '全部', ai: '🤖 AI', finance: '📈 金融', industry: '🏭 行业' };
const CAT_STYLES: Record<string, string> = { ai: 'ai', finance: 'finance', industry: 'industry' };

export default function InsightScreen() {
  const insets = useSafeAreaInsets();
  const [insights, setInsights] = useState<Insight[]>([]);
  const [category, setCategory] = useState('all');
  const [loading, setLoading] = useState(true);

  const loadInsights = useCallback(async (cat = category) => {
    setLoading(true);
    try {
      const res = await api.insights.list(cat === 'all' ? undefined : cat);
      setInsights(res.data.items);
    } catch (_) {
    } finally {
      setLoading(false);
    }
  }, [category]);

  useFocusEffect(useCallback(() => { loadInsights(); }, [loadInsights]));

  const renderItem = ({ item }: { item: Insight }) => (
    <View style={[styles.card, item.importance && item.importance >= 4 ? styles.cardImportant : null]}>
      <View style={styles.cardHeader}>
        <View style={[styles.catBadge, item.category === 'ai' ? styles.catAi : item.category === 'finance' ? styles.catFinance : styles.catIndustry]}>
          <Text style={[styles.catText, item.category === 'ai' ? styles.catAiText : item.category === 'finance' ? styles.catFinanceText : styles.catIndustryText]}>
            {CAT_NAMES[item.category] || item.category}
          </Text>
        </View>
        {item.importance && item.importance >= 4 && (
          <View style={styles.importanceBadge}>
            <Text style={styles.importanceText}>重要</Text>
          </View>
        )}
      </View>
      <Text style={styles.cardTitle}>{item.title}</Text>
      <Text style={styles.cardSummary}>{item.summary}</Text>
      {item.impact && (
        <View style={styles.impactBox}>
          <Text style={styles.impactText}>💡 影响：{item.impact}</Text>
        </View>
      )}
      <View style={styles.cardFooter}>
        <View style={styles.topicsRow}>
          {(item.topics || []).slice(0, 3).map((t, i) => (
            <Text key={i} style={styles.topic}>{t}</Text>
          ))}
        </View>
        <Text style={styles.cardTime}>
          {item.published_at
            ? (() => {
                const diff = Date.now() - new Date(item.published_at).getTime();
                const h = Math.floor(diff / 3600000);
                if (h < 1) return '刚刚';
                if (h < 24) return `${h} 小时前`;
                return `${Math.floor(h / 24)} 天前`;
              })()
            : item.source_name || ''}
        </Text>
      </View>
    </View>
  );

  return (
    <View style={[styles.container, { paddingTop: insets.top }]}>
      <View style={styles.headerArea}>
        <Text style={styles.headerTitle}>洞察看板</Text>
        <Text style={styles.headerSub}>AI 为你筛选的外部世界变化</Text>
      </View>

      <View style={styles.filterBar}>
        {CATEGORIES.map((c) => (
          <TouchableOpacity
            key={c}
            style={[styles.filterChip, category === c && styles.filterChipActive]}
            onPress={() => { setCategory(c); loadInsights(c); }}
          >
            <Text style={[styles.filterText, category === c && styles.filterTextActive]}>
              {CAT_NAMES[c]}
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      {loading ? (
        <ActivityIndicator style={styles.loading} size="large" color={colors.primary} />
      ) : (
        <FlatList
          data={insights}
          keyExtractor={(i) => i.id}
          renderItem={renderItem}
          contentContainerStyle={styles.list}
          refreshControl={<RefreshControl refreshing={loading} onRefresh={() => loadInsights()} />}
          ListEmptyComponent={<Text style={styles.empty}>暂无洞察</Text>}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  headerArea: { paddingHorizontal: 20, paddingTop: 8, paddingBottom: 12 },
  headerTitle: { fontSize: 24, fontWeight: '700', color: colors.text },
  headerSub: { fontSize: 13, color: colors.textSecondary, marginTop: 2 },

  filterBar: {
    flexDirection: 'row', gap: 8, paddingHorizontal: 20, marginBottom: 16,
  },
  filterChip: {
    fontSize: 12, fontWeight: '500', paddingVertical: 8, paddingHorizontal: 16,
    borderRadius: 20, borderWidth: 1, borderColor: colors.borderLight,
    backgroundColor: colors.card, flexShrink: 0,
  },
  filterChipActive: {
    backgroundColor: 'rgba(138,171,138,0.10)',
    borderColor: colors.primaryLight,
  },
  filterText: { fontSize: 12, color: colors.textSecondary, fontWeight: '500' },
  filterTextActive: { color: colors.primary },

  list: { paddingHorizontal: 20, paddingBottom: 20 },
  card: {
    backgroundColor: colors.card, borderRadius: 16, padding: 16,
    borderWidth: 1, borderColor: colors.border, marginBottom: 10,
    overflow: 'hidden',
  },
  cardImportant: { borderLeftWidth: 3, borderLeftColor: colors.accentCoral },

  cardHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 },
  catBadge: { paddingVertical: 4, paddingHorizontal: 9, borderRadius: 6 },
  catAi: { backgroundColor: 'rgba(138,171,138,0.10)' },
  catFinance: { backgroundColor: 'rgba(224,180,158,0.12)' },
  catIndustry: { backgroundColor: 'rgba(160,188,200,0.12)' },
  catText: { fontSize: 10, fontWeight: '600', textTransform: 'uppercase', letterSpacing: 1.2 },
  catAiText: { color: colors.primary },
  catFinanceText: { color: '#c08870' },
  catIndustryText: { color: '#7a9aa8' },

  importanceBadge: { paddingVertical: 4, paddingHorizontal: 9, borderRadius: 6, backgroundColor: 'rgba(212,145,122,0.10)' },
  importanceText: { fontSize: 10, fontWeight: '600', color: colors.accentCoral, letterSpacing: 0.5 },

  cardTitle: { fontSize: 15, fontWeight: '600', color: colors.text, lineHeight: 21, marginBottom: 6 },
  cardSummary: { fontSize: 12, color: colors.textSecondary, lineHeight: 18, marginBottom: 8 },
  impactBox: {
    paddingVertical: 8, paddingHorizontal: 12,
    backgroundColor: 'rgba(138,171,138,0.06)',
    borderRadius: 10, borderLeftWidth: 2, borderLeftColor: 'rgba(138,171,138,0.3)',
    marginBottom: 8,
  },
  impactText: { fontSize: 11, color: '#6b8a6b', lineHeight: 16 },

  cardFooter: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  topicsRow: { flexDirection: 'row', gap: 4, flexWrap: 'wrap' },
  topic: { fontSize: 10, color: colors.textMuted, backgroundColor: colors.headerBg, paddingVertical: 2, paddingHorizontal: 8, borderRadius: 4 },
  cardTime: { fontSize: 10, color: colors.textMuted, flexShrink: 0 },

  loading: { flex: 1, justifyContent: 'center' },
  empty: { textAlign: 'center', color: colors.textMuted, marginTop: 40, fontSize: 14 },
});
