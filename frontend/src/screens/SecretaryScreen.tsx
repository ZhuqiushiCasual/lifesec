import React, { useCallback, useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, RefreshControl, ActivityIndicator,
} from 'react-native';
import { useFocusEffect } from '@react-navigation/native';
import { Ionicons } from '@expo/vector-icons';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import * as api from '../services/api';
import { TodayBoard, Digest, FinanceTxn, WeeklyTrendResponse } from '../types';
import { colors } from '../theme/colors';
import LineChart from '../components/LineChart';

const TYPE_ICONS: Record<string, string> = {
  dietary: 'fast-food', sport: 'fitness', health: 'medkit', mood: 'happy', sleep: 'moon', event: 'calendar',
};

const TYPE_EMOJI: Record<string, string> = {
  dietary: '🍽️', sport: '🏃', health: '🏥', mood: '😊', sleep: '😴', event: '📝',
};

function accentFor(type: string): string {
  switch (type) {
    case 'sport': return colors.primary;
    case 'dietary': return colors.accentWheat;
    case 'health': return colors.accentCoral;
    case 'mood': return colors.accentPeach;
    case 'sleep': return colors.accentLavender;
    case 'event': return colors.accentSky;
    default: return colors.textMuted;
  }
}

function BarChart({
  data, labels, color, target,
}: { data: number[]; labels: string[]; color: string; target?: number }) {
  const maxVal = Math.max(...data, target || 0, 1);
  return (
    <View style={styles.barChart}>
      {data.map((v, i) => (
        <View key={i} style={styles.barCol}>
          <View style={[styles.barFillDynamic, {
            height: v > 0 ? Math.max((v / maxVal) * 50, 4) : 0,
            backgroundColor: color,
          }]} />
          <Text style={styles.barLabel}>{labels[i]}</Text>
        </View>
      ))}
    </View>
  );
}

const COLOR_MAP: Record<string, string> = {
  primary: colors.primary,
  accentLavender: colors.accentLavender,
  accentWheat: colors.accentWheat,
  accentPeach: colors.accentPeach,
  accentCoral: colors.accentCoral,
  accentSky: colors.accentSky,
};

export default function SecretaryScreen() {
  const insets = useSafeAreaInsets();
  const [board, setBoard] = useState<TodayBoard | null>(null);
  const [digest, setDigest] = useState<Digest | null>(null);
  const [txns, setTxns] = useState<FinanceTxn[]>([]);
  const [weekly, setWeekly] = useState<WeeklyTrendResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const loadAll = useCallback(async () => {
    try {
      const [brRes, diRes, txRes, wkRes] = await Promise.allSettled([
        api.board.today(),
        api.digests.latest(),
        api.finance.listTxns(),
        api.memory.weekly(),
      ]);
      if (brRes.status === 'fulfilled') setBoard(brRes.value.data);
      if (diRes.status === 'fulfilled') setDigest(diRes.value.data);
      if (txRes.status === 'fulfilled') setTxns(txRes.value.data.items);
      if (wkRes.status === 'fulfilled') setWeekly(wkRes.value.data);
    } catch (_) {
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { loadAll(); }, [loadAll]));

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
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); loadAll(); }} />}
    >
      <View style={styles.header}>
        <Text style={styles.headerGreeting}>你的个人秘书</Text>
        <Text style={styles.headerTitle}>今日看板</Text>
      </View>

      <View style={styles.statusCard}>
        <View style={styles.statusHeader}>
          <Text style={styles.statusLabel}>今日评分</Text>
          <Text style={styles.statusScore}>{digest?.score ?? '-'}</Text>
        </View>
        <View style={styles.statusPills}>
          <View style={styles.pill}>
            <Ionicons name="list" size={14} color={colors.primary} />
            <Text style={styles.pillText}>记录</Text>
            <Text style={styles.pillValue}>{board?.today_event_count ?? 0} 条</Text>
          </View>
          <View style={styles.pill}>
            <Ionicons name="happy" size={14} color={colors.primary} />
            <Text style={styles.pillText}>情绪</Text>
            <Text style={styles.pillValue}>{board?.mood || '-'}</Text>
          </View>
          <View style={[styles.pill, board?.sport_done ? null : styles.pillWarn]}>
            <Ionicons name="fitness" size={14} color={board?.sport_done ? colors.primary : colors.accentCoral} />
            <Text style={styles.pillText}>运动</Text>
            <Text style={styles.pillValue}>{board?.sport_done ? '已完成' : '未完成'}</Text>
          </View>
          <View style={[styles.pill, board?.water_warning ? styles.pillWarn : null]}>
            <Ionicons name="water" size={14} color={board?.water_warning ? colors.accentCoral : colors.primary} />
            <Text style={styles.pillText}>饮水</Text>
            <Text style={styles.pillValue}>{board?.water_warning ? '不足' : '充足'}</Text>
          </View>
        </View>
      </View>

      <View style={styles.secLabel}>
        <Text style={styles.secLabelText}>今日时间轴</Text>
      </View>
      {(board?.recent_events ?? []).length === 0 ? (
        <View style={styles.emptyCard}>
          <Text style={styles.emptyText}>还没有记录</Text>
        </View>
      ) : (
        <View style={styles.timelineWrap}>
          {(board?.recent_events ?? []).map((e, i) => {
            const isLast = i === (board?.recent_events ?? []).length - 1;
            const accent = accentFor(e.type);
            return (
              <View key={e.id || i} style={[styles.tlRow, isLast && styles.tlRowLast]}>
                <View style={styles.tlRailCol}>
                  <View style={[styles.tlNode, { backgroundColor: accent }]} />
                  {!isLast && <View style={[styles.tlRail, { backgroundColor: accent + '40' }]} />}
                </View>
                <View style={styles.tlContent}>
                  <Text style={styles.tlTime}>
                    {new Date(e.recorded_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}
                  </Text>
                  <View style={[styles.tlCard, { borderLeftColor: accent }]}>
                    <View style={styles.tlTypeRow}>
                      <Text style={styles.tlTypeEmoji}>{TYPE_EMOJI[e.type] || '•'}</Text>
                      <Text style={styles.tlType}>{e.type}</Text>
                    </View>
                    <Text style={styles.tlText} numberOfLines={3}>{e.content}</Text>
                  </View>
                </View>
              </View>
            );
          })}
        </View>
      )}

      <View style={styles.secLabel}>
        <Text style={styles.secLabelText}>本周健康记录</Text>
        {weekly && <Text style={styles.secLabelSub}>{weekly.week_start.slice(5)} 起</Text>}
      </View>
      {(weekly?.health_events ?? []).length === 0 ? (
        <View style={styles.emptyCard}>
          <Text style={styles.emptyText}>本周暂无健康记录</Text>
        </View>
      ) : (
        <View style={styles.timelineWrap}>
          {(weekly?.health_events ?? []).map((e, i) => {
            const isLast = i === (weekly?.health_events ?? []).length - 1;
            const accent = accentFor(e.type);
            return (
              <View key={e.id || i} style={[styles.tlRow, isLast && styles.tlRowLast]}>
                <View style={styles.tlRailCol}>
                  <View style={[styles.tlNode, { backgroundColor: accent }]} />
                  {!isLast && <View style={[styles.tlRail, { backgroundColor: accent + '40' }]} />}
                </View>
                <View style={styles.tlContent}>
                  <Text style={styles.tlTime}>
                    {new Date(e.recorded_at).toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })}
                    {'  '}
                    {new Date(e.recorded_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}
                  </Text>
                  <View style={[styles.tlCard, { borderLeftColor: accent }]}>
                    <View style={styles.tlTypeRow}>
                      <Text style={styles.tlTypeEmoji}>{TYPE_EMOJI[e.type] || '•'}</Text>
                      <Text style={styles.tlType}>{e.type === 'sleep' ? '睡眠' : '健康'}</Text>
                    </View>
                    <Text style={styles.tlText} numberOfLines={3}>{e.content}</Text>
                  </View>
                </View>
              </View>
            );
          })}
        </View>
      )}

      <View style={styles.secLabel}>
        <Text style={styles.secLabelText}>本周趋势</Text>
        {weekly && <Text style={styles.secLabelSub}>{weekly.week_start.slice(5)} 起</Text>}
      </View>
      {(weekly?.charts ?? []).length === 0 ? (
        <View style={styles.emptyCard}>
          <Text style={styles.emptyText}>本周暂无趋势数据</Text>
        </View>
      ) : (
        (weekly?.charts ?? []).map((chart) => {
          const lineColor = COLOR_MAP[chart.color] || colors.primary;
          const labels = weekly?.day_labels ?? ['一','二','三','四','五','六','日'];
          const renderLine = chart.type === 'sleep' || chart.type === 'mood';
          return (
            <View key={chart.type} style={styles.trendCard}>
              <View style={styles.trendHeader}>
                <Text style={styles.trendTitle}>{chart.title}</Text>
                <View style={[styles.trendBadge, { backgroundColor: lineColor + '20' }]}>
                  <Text style={[styles.trendBadgeText, { color: lineColor }]}>{chart.summary}</Text>
                </View>
              </View>
              {renderLine ? (
                <LineChart
                  data={chart.data}
                  labels={labels}
                  color={lineColor}
                  target={chart.target}
                  unit={chart.unit}
                  height={96}
                />
              ) : (
                <BarChart data={chart.data} labels={labels} color={lineColor} target={chart.target} />
              )}
              {chart.target ? (
                <Text style={styles.trendTarget}>目标 {chart.target}{chart.unit}</Text>
              ) : null}
            </View>
          );
        })
      )}

      <View style={styles.secLabel}>
        <Text style={styles.secLabelText}>财务看板</Text>
      </View>
      <View style={styles.financeCard}>
        <View style={styles.finSummaryRow}>
          <View style={styles.finSummaryItem}>
            <Text style={styles.finAmount}>¥520,000</Text>
            <Text style={styles.finLabel}>总资产</Text>
          </View>
          <View style={styles.finSummaryItem}>
            <Text style={styles.finAmount}>¥420,000</Text>
            <Text style={styles.finLabel}>净资产</Text>
          </View>
          <View style={styles.finSummaryItem}>
            <Text style={[styles.finAmount, { color: colors.primary }]}>+¥6,800</Text>
            <Text style={styles.finLabel}>本月净额</Text>
          </View>
        </View>

        <View style={styles.assetSection}>
          <View style={styles.assetRow}>
            <Text style={styles.assetIcon}>📈</Text>
            <Text style={styles.assetName}>股票</Text>
            <View style={styles.assetTrack}>
              <View style={[styles.assetFill, { width: '42%', backgroundColor: colors.primary }]} />
            </View>
            <Text style={styles.assetPct}>42%</Text>
          </View>
          <View style={styles.assetRow}>
            <Text style={styles.assetIcon}>🏠</Text>
            <Text style={styles.assetName}>房产</Text>
            <View style={styles.assetTrack}>
              <View style={[styles.assetFill, { width: '30%', backgroundColor: colors.accentLavender }]} />
            </View>
            <Text style={styles.assetPct}>30%</Text>
          </View>
          <View style={styles.assetRow}>
            <Text style={styles.assetIcon}>💰</Text>
            <Text style={styles.assetName}>基金</Text>
            <View style={styles.assetTrack}>
              <View style={[styles.assetFill, { width: '22%', backgroundColor: colors.accentPeach }]} />
            </View>
            <Text style={styles.assetPct}>22%</Text>
          </View>
          <View style={styles.assetRow}>
            <Text style={styles.assetIcon}>💵</Text>
            <Text style={styles.assetName}>现金</Text>
            <View style={styles.assetTrack}>
              <View style={[styles.assetFill, { width: '6%', backgroundColor: colors.accentSky }]} />
            </View>
            <Text style={styles.assetPct}>6%</Text>
          </View>
        </View>

        {txns.length > 0 && (
          <View style={styles.txnSection}>
            {txns.slice(0, 3).map((t) => (
              <View key={t.id} style={styles.txnItem}>
                <Text style={styles.txnDate}>
                  {new Date(t.recorded_at).toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })}
                </Text>
                <Text style={styles.txnIcon}>{t.type === 'income' ? '📈' : t.type === 'expense' ? '🛒' : '🏦'}</Text>
                <Text style={styles.txnText} numberOfLines={1}>{t.counterparty || t.category}</Text>
                <Text style={[styles.txnAmount, { color: t.type === 'income' ? colors.primary : colors.danger }]}>
                  {t.type === 'income' ? '+' : '-'}¥{Number(t.amount).toLocaleString()}
                </Text>
              </View>
            ))}
          </View>
        )}
      </View>

      {digest && (
        <>
          <View style={styles.secLabel}>
            <Text style={styles.secLabelText}>总结 & 回顾</Text>
          </View>
          <TouchableOpacity style={styles.navEntry}>
            <View style={styles.navEntryLeft}>
              <View style={styles.navEntryIcon}>
                <Ionicons name="newspaper" size={20} color={colors.primary} />
              </View>
              <View>
                <Text style={styles.navEntryTitle}>昨日日报</Text>
                <Text style={styles.navEntrySub}>{digest.date} · 评分 {digest.score} </Text>
              </View>
            </View>
            <Text style={styles.navEntryArrow}>→</Text>
          </TouchableOpacity>
          <TouchableOpacity style={styles.navEntry}>
            <View style={styles.navEntryLeft}>
              <View style={styles.navEntryIcon}>
                <Ionicons name="trending-up" size={20} color={colors.primary} />
              </View>
              <View>
                <Text style={styles.navEntryTitle}>过去 30 天变化</Text>
                <Text style={styles.navEntrySub}>运动 ↑ · 情绪 ↑ · 饮水量 →</Text>
              </View>
            </View>
            <Text style={styles.navEntryArrow}>→</Text>
          </TouchableOpacity>
          <TouchableOpacity style={[styles.navEntry, { marginBottom: 4 }]}>
            <View style={styles.navEntryLeft}>
              <View style={styles.navEntryIcon}>
                <Ionicons name="time" size={20} color={colors.primary} />
              </View>
              <View>
                <Text style={styles.navEntryTitle}>一年前的今天</Text>
                <Text style={styles.navEntrySub}>你在做什么？</Text>
              </View>
            </View>
            <Text style={styles.navEntryArrow}>→</Text>
          </TouchableOpacity>
        </>
      )}

      <View style={{ height: 12 }} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  centered: { flex: 1, justifyContent: 'center', alignItems: 'center' },

  header: { paddingHorizontal: 20, paddingTop: 8, paddingBottom: 14 },
  headerGreeting: { fontSize: 14, color: colors.textSecondary },
  headerTitle: { fontSize: 24, fontWeight: '700', color: colors.text },

  statusCard: {
    backgroundColor: colors.card, borderRadius: 20, padding: 18,
    borderWidth: 1, borderColor: colors.border, marginHorizontal: 20, marginBottom: 16,
    overflow: 'hidden',
  },
  statusHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 },
  statusLabel: { fontSize: 11, textTransform: 'uppercase', letterSpacing: 1.2, color: colors.textMuted, fontWeight: '500' },
  statusScore: { fontSize: 36, fontWeight: '700', color: colors.primary },
  statusPills: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  pill: {
    flexDirection: 'row', alignItems: 'center', gap: 6,
    paddingVertical: 9, paddingHorizontal: 12,
    backgroundColor: colors.headerBg, borderRadius: 12,
    borderWidth: 1, borderColor: colors.border, minWidth: '47%',
  },
  pillWarn: { borderColor: 'rgba(212,145,122,0.2)', backgroundColor: 'rgba(212,145,122,0.05)' },
  pillText: { fontSize: 12, color: colors.textSecondary },
  pillValue: { fontWeight: '600', color: colors.text, fontSize: 13, marginLeft: 'auto' },

  secLabel: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginHorizontal: 20, marginTop: 16, marginBottom: 10 },
  secLabelText: { fontSize: 11, textTransform: 'uppercase', letterSpacing: 1.2, color: colors.textMuted, fontWeight: '500' },
  secLabelSub: { fontSize: 11, color: colors.textMuted },

  timelineWrap: {
    marginHorizontal: 20, marginBottom: 12, backgroundColor: colors.card,
    borderRadius: 16, padding: 16, borderWidth: 1, borderColor: colors.border,
  },
  tlRow: { flexDirection: 'row', minHeight: 56 },
  tlRowLast: { minHeight: 0 },
  tlRailCol: { width: 16, alignItems: 'center', marginRight: 10 },
  tlNode: { width: 10, height: 10, borderRadius: 5, marginTop: 2, borderWidth: 2, borderColor: '#fff' },
  tlRail: { flex: 1, width: 2, marginTop: 2, marginBottom: 6 },
  tlContent: { flex: 1, paddingBottom: 14 },
  tlTime: { fontSize: 10, color: colors.textMuted, marginBottom: 4, fontWeight: '500' },
  tlCard: {
    paddingVertical: 8, paddingHorizontal: 12, backgroundColor: colors.headerBg,
    borderRadius: 10, borderLeftWidth: 3,
  },
  tlTypeRow: { flexDirection: 'row', alignItems: 'center', gap: 4, marginBottom: 2 },
  tlTypeEmoji: { fontSize: 11 },
  tlType: { fontSize: 9, textTransform: 'uppercase', letterSpacing: 1, color: colors.textMuted },
  tlText: { fontSize: 12.5, color: colors.text, lineHeight: 17 },
  emptyCard: { backgroundColor: colors.card, borderRadius: 14, padding: 20, marginHorizontal: 20, alignItems: 'center' },
  emptyText: { color: colors.textMuted, fontSize: 13 },

  trendCard: {
    backgroundColor: colors.card, borderRadius: 16, padding: 16,
    borderWidth: 1, borderColor: colors.border, marginHorizontal: 20, marginBottom: 10,
  },
  trendHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 },
  trendTitle: { fontSize: 13, color: colors.text, fontWeight: '500' },
  trendBadge: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: 8 },
  trendBadgeText: { fontSize: 12, fontWeight: '600' },
  barChart: { flexDirection: 'row', alignItems: 'flex-end', gap: 6, height: 64 },
  barCol: { flex: 1, alignItems: 'center', gap: 4 },
  barFillDynamic: { width: '100%', borderRadius: 4 },
  barLabel: { fontSize: 10, color: colors.textMuted },
  trendTarget: { fontSize: 10, color: colors.textMuted, marginTop: 8, textAlign: 'center' },

  financeCard: {
    backgroundColor: colors.card, borderRadius: 16, padding: 16,
    borderWidth: 1, borderColor: colors.border, marginHorizontal: 20, marginBottom: 10,
  },
  finSummaryRow: { flexDirection: 'row', gap: 10, marginBottom: 12 },
  finSummaryItem: {
    flex: 1, padding: 12, backgroundColor: colors.headerBg, borderRadius: 12, alignItems: 'center',
  },
  finAmount: { fontSize: 16, fontWeight: '600', color: colors.text },
  finLabel: { fontSize: 10, color: colors.textMuted, marginTop: 2 },

  assetSection: { marginBottom: 6 },
  assetRow: { flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 6 },
  assetIcon: { fontSize: 16, width: 24, textAlign: 'center' },
  assetName: { fontSize: 12, color: colors.textSecondary, width: 38 },
  assetTrack: { flex: 1, height: 8, backgroundColor: colors.headerBg, borderRadius: 4, overflow: 'hidden' },
  assetFill: { height: '100%', borderRadius: 4 },
  assetPct: { fontSize: 11, color: colors.textMuted, width: 34, textAlign: 'right' },

  txnSection: { marginTop: 8 },
  txnItem: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: colors.border },
  txnDate: { fontSize: 11, color: colors.textMuted, width: 36 },
  txnIcon: { fontSize: 14, width: 22, textAlign: 'center' },
  txnText: { flex: 1, fontSize: 13, color: colors.text },
  txnAmount: { fontWeight: '600', fontSize: 12 },

  navEntry: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    padding: 14, backgroundColor: colors.card, borderRadius: 16,
    borderWidth: 1, borderColor: colors.border, marginHorizontal: 20, marginBottom: 8,
  },
  navEntryLeft: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  navEntryIcon: {
    width: 38, height: 38, borderRadius: 12,
    backgroundColor: 'rgba(138,171,138,0.08)', justifyContent: 'center', alignItems: 'center',
  },
  navEntryTitle: { fontSize: 13, color: colors.text, fontWeight: '500' },
  navEntrySub: { fontSize: 11, color: colors.textMuted, marginTop: 1 },
  navEntryArrow: { color: colors.textMuted, fontSize: 13 },
});
