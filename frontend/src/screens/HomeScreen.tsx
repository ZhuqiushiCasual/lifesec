import React, { useCallback, useEffect, useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, RefreshControl, ActivityIndicator,
} from 'react-native';
import { useFocusEffect } from '@react-navigation/native';
import { Ionicons } from '@expo/vector-icons';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import * as api from '../services/api';
import { TodayBoard } from '../types';
import { colors } from '../theme/colors';

const TYPE_ICONS: Record<string, keyof typeof Ionicons.glyphMap> = {
  dietary: 'fast-food', sport: 'fitness', health: 'medkit', mood: 'happy', invest: 'trending-up', event: 'ellipse',
};

export default function HomeScreen() {
  const insets = useSafeAreaInsets();
  const [board, setBoard] = useState<TodayBoard | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const loadBoard = async () => {
    try {
      const res = await api.board.today();
      setBoard(res.data);
    } catch (_) {
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useFocusEffect(useCallback(() => { loadBoard(); }, []));

  if (loading) {
    return (
      <View style={[styles.centered, { paddingTop: insets.top }]}>
        <ActivityIndicator size="large" color={colors.primary} />
      </View>
    );
  }

  return (
    <ScrollView
      style={[styles.container, { paddingTop: insets.top }]}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); loadBoard(); }} />}
    >
      {board && (
        <>
          <View style={styles.greetingCard}>
            <Text style={styles.greeting}>{board.greeting}</Text>
            <Text style={styles.date}>{board.date}</Text>
          </View>

          <View style={styles.statusCard}>
            <Text style={styles.sectionTitle}>今日状态</Text>
            <View style={styles.statusRow}>
              <StatusBadge icon="checkbox" label={`已记录 ${board.today_event_count} 条`} />
              <StatusBadge icon="fitness" label="运动" done={board.sport_done} />
              <StatusBadge icon="happy" label="情绪" value={board.mood || '-'} />
              <StatusBadge icon="water" label="喝水" warning={board.water_warning} />
            </View>
          </View>

          <View style={styles.section}>
            <Text style={styles.sectionTitle}>今日记录</Text>
            {board.recent_events.length === 0 ? (
              <Text style={styles.emptyText}>还没有记录，开始聊点什么吧</Text>
            ) : (
              board.recent_events.map((e) => (
                <View key={e.id} style={styles.eventItem}>
                  <Ionicons name={TYPE_ICONS[e.type] || 'ellipse'} size={18} color={colors.primary} />
                  <Text style={styles.eventTime}>
                    {new Date(e.recorded_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}
                  </Text>
                  <Text style={styles.eventContent} numberOfLines={2}>{e.content}</Text>
                </View>
              ))
            )}
          </View>

          <View style={styles.section}>
            <Text style={styles.sectionTitle}>洞察看板</Text>
            <ScrollView horizontal showsHorizontalScrollIndicator={false}>
              {board.latest_insights.map((i) => (
                <TouchableOpacity key={i.id} style={styles.insightCard}>
                  <Text style={styles.insightCategory}>
                    {i.category === 'ai' ? '🤖 AI' : i.category === 'finance' ? '📈 金融' : '🏭 行业'}
                  </Text>
                  <Text style={styles.insightTitle} numberOfLines={2}>{i.title}</Text>
                  <Text style={styles.insightSummary} numberOfLines={2}>{i.summary}</Text>
                </TouchableOpacity>
              ))}
            </ScrollView>
          </View>

          {board.has_latest_digest && (
            <TouchableOpacity style={styles.digestEntry}>
              <Ionicons name="newspaper" size={20} color={colors.primary} />
              <Text style={styles.digestText}>昨日日报已生成</Text>
              <Ionicons name="chevron-forward" size={18} color={colors.textMuted} />
            </TouchableOpacity>
          )}
        </>
      )}
    </ScrollView>
  );
}

function StatusBadge({ icon, label, done, warning, value }: any) {
  const color = done !== undefined ? (done ? colors.success : colors.textMuted) : warning !== undefined ? (warning ? colors.warning : colors.success) : colors.primary;
  return (
    <View style={[styles.badge, { borderColor: color }]}>
      <Ionicons name={icon} size={14} color={color} />
      <Text style={[styles.badgeText, { color }]}>{value || label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  centered: { flex: 1, justifyContent: 'center', alignItems: 'center' },
  greetingCard: { padding: 20, backgroundColor: colors.headerBg },
  greeting: { fontSize: 22, fontWeight: '700', color: colors.text },
  date: { fontSize: 14, color: colors.textSecondary, marginTop: 4 },
  statusCard: { backgroundColor: colors.card, margin: 16, padding: 16, borderRadius: 16, shadowColor: colors.text, shadowOffset: { width: 0, height: 1 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 },
  sectionTitle: { fontSize: 16, fontWeight: '600', color: colors.text, marginBottom: 12 },
  statusRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  badge: { flexDirection: 'row', alignItems: 'center', gap: 4, paddingHorizontal: 10, paddingVertical: 6, borderRadius: 20, borderWidth: 1 },
  badgeText: { fontSize: 12, fontWeight: '500' },
  section: { marginHorizontal: 16, marginBottom: 16, backgroundColor: colors.card, borderRadius: 16, padding: 16, shadowColor: colors.text, shadowOffset: { width: 0, height: 1 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 },
  emptyText: { color: colors.textMuted, fontSize: 14, textAlign: 'center', paddingVertical: 20 },
  eventItem: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: colors.borderLight },
  eventTime: { fontSize: 12, color: colors.textMuted, minWidth: 40 },
  eventContent: { flex: 1, fontSize: 14, color: colors.textSecondary },
  insightCard: { width: 240, backgroundColor: colors.inputBg, borderRadius: 12, padding: 14, marginRight: 12, borderWidth: 1, borderColor: colors.border },
  insightCategory: { fontSize: 11, fontWeight: '600', color: colors.primary, marginBottom: 4 },
  insightTitle: { fontSize: 14, fontWeight: '600', color: colors.text, marginBottom: 4 },
  insightSummary: { fontSize: 12, color: colors.textSecondary },
  digestEntry: { flexDirection: 'row', alignItems: 'center', gap: 8, marginHorizontal: 16, marginBottom: 24, backgroundColor: colors.tagBg, borderRadius: 12, padding: 14 },
  digestText: { flex: 1, fontSize: 14, color: colors.primary, fontWeight: '500' },
});
