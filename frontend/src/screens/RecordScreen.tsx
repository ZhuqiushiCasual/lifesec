import React, { useState, useCallback } from 'react';
import {
  View, Text, TextInput, TouchableOpacity, FlatList, StyleSheet, Alert, ActivityIndicator,
  KeyboardAvoidingView, Platform, Modal, ScrollView,
} from 'react-native';
import { useFocusEffect } from '@react-navigation/native';
import { Ionicons } from '@expo/vector-icons';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { events as eventsApi, board as boardApi } from '../services/api';
import { EventItem, TodayBoard } from '../types';
import { useAppStore } from '../store';
import { colors } from '../theme/colors';

const TYPE_ICONS: Record<string, keyof typeof Ionicons.glyphMap> = {
  dietary: 'fast-food', sport: 'fitness', health: 'medkit', mood: 'happy', invest: 'trending-up',
};

const CAT_ICONS: Record<string, string> = {
  ai: '🤖', finance: '📈', industry: '🏭',
};

export default function RecordScreen() {
  const insets = useSafeAreaInsets();
  const user = useAppStore((s) => s.user);
  const [input, setInput] = useState('');
  const [eventList, setEventList] = useState<EventItem[]>([]);
  const [todayBoard, setTodayBoard] = useState<TodayBoard | null>(null);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [showProfile, setShowProfile] = useState(false);

  const loadData = useCallback(async (p = 1) => {
    setLoading(true);
    try {
      const [evRes, brRes] = await Promise.all([eventsApi.list(p), boardApi.today()]);
      if (p === 1) setEventList(evRes.data.items);
      else setEventList((prev) => [...prev, ...evRes.data.items]);
      setPage(p);
      setTodayBoard(brRes.data);
    } catch (_) {
    } finally {
      setLoading(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { loadData(); }, [loadData]));

  const handleSend = async () => {
    if (!input.trim()) return;
    setSending(true);
    try {
      await eventsApi.create({ content: input.trim() });
      setInput('');
      loadData(1);
    } catch (err: any) {
      const detail = err?.response?.data?.detail || err?.message || JSON.stringify(err);
      Alert.alert('错误', detail);
    } finally {
      setSending(false);
    }
  };

  const suggestions = [
    { label: '🍳 早餐', text: '早餐吃了' },
    { label: '🤕 身体状态', text: '下午有点' },
    { label: '🏃 运动', text: '晚上健身' },
    { label: '😊 情绪', text: '今天心情' },
  ];

  const renderEvent = ({ item }: { item: EventItem }) => (
    <View style={styles.eventCard}>
      <View style={styles.eventHeader}>
        <Ionicons name={TYPE_ICONS[item.type] || 'ellipse'} size={16} color={colors.primary} />
        <Text style={styles.eventType}>{item.type}</Text>
        <Text style={styles.eventTime}>
          {new Date(item.recorded_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}
        </Text>
      </View>
      <Text style={styles.eventContent}>{item.content}</Text>
      {item.sentiment && (
        <Text style={styles.sentiment}>
          {item.sentiment === 'positive' ? '😊' : item.sentiment === 'negative' ? '😟' : '😐'} {item.sentiment}
        </Text>
      )}
    </View>
  );

  const renderHeader = () => (
    <View>
      <View style={styles.greetingRow}>
        <View style={styles.greetingLeft}>
          <Text style={styles.greetingWave}>
            {todayBoard?.greeting || '下午好'} 🌿
          </Text>
          <Text style={styles.greetingName}>Hi, {user.name || '用户'}</Text>
          <Text style={styles.greetingDate}>{todayBoard?.date || ''}</Text>
        </View>
        <TouchableOpacity style={styles.avatarBtn} onPress={() => setShowProfile(true)}>
          <View style={styles.avatar}>
            <Ionicons name="person" size={22} color={colors.textWhite} />
          </View>
        </TouchableOpacity>
      </View>

      {todayBoard && todayBoard.latest_insights.length > 0 && (
        <View style={styles.quickSection}>
          <Text style={styles.quickLabel}>📡 核心动态</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.quickScroll}>
            {todayBoard.latest_insights.map((i) => (
              <TouchableOpacity key={i.id} style={styles.quickCard}>
                <Text style={styles.quickCat}>
                  {CAT_ICONS[i.category] || '📌'} {i.category}
                </Text>
                <Text style={styles.quickTitle} numberOfLines={2}>{i.title}</Text>
                <Text style={styles.quickSummary} numberOfLines={2}>{i.summary}</Text>
              </TouchableOpacity>
            ))}
          </ScrollView>
        </View>
      )}

      <View style={styles.chatDialog}>
        <Text style={styles.chatHint}>💬 记录今天发生了什么</Text>
        <View style={styles.suggestionRow}>
          {suggestions.map((s, i) => (
            <TouchableOpacity key={i} style={styles.suggestionChip} onPress={() => { setInput(s.text); }}>
              <Text style={styles.suggestionText}>{s.label}</Text>
            </TouchableOpacity>
          ))}
        </View>
      </View>

      {todayBoard && (
        <TouchableOpacity style={styles.summaryCard}>
          <View style={styles.summaryLeft}>
            <View style={styles.summaryIcon}>
              <Ionicons name="list" size={18} color={colors.primary} />
            </View>
            <View>
              <Text style={styles.summaryTitle}>今日已记录 {todayBoard.today_event_count} 条</Text>
              <Text style={styles.summarySub}>
                {todayBoard.recent_events.map((e) => e.type).filter((v, i, a) => a.indexOf(v) === i).join(' · ') || '暂无'}
              </Text>
            </View>
          </View>
          <Text style={styles.summaryArrow}>→</Text>
        </TouchableOpacity>
      )}
    </View>
  );

  return (
    <KeyboardAvoidingView style={[styles.container, { paddingTop: insets.top }]} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <FlatList
        data={eventList}
        keyExtractor={(e) => e.id}
        renderItem={renderEvent}
        ListHeaderComponent={renderHeader}
        contentContainerStyle={styles.list}
        onRefresh={() => loadData(1)}
        refreshing={loading && page === 1}
        onEndReached={() => !loading && loadData(page + 1)}
        onEndReachedThreshold={0.5}
        ListEmptyComponent={!loading ? <Text style={styles.empty}>还没有记录</Text> : null}
      />

      <View style={styles.inputBar}>
        <TouchableOpacity style={styles.addBtn}>
          <Text style={styles.addBtnText}>+</Text>
        </TouchableOpacity>
        <TextInput
          style={styles.input}
          placeholder="随便说说，我会帮你整理..."
          placeholderTextColor={colors.textMuted}
          value={input}
          onChangeText={setInput}
          multiline
          maxLength={1000}
        />
        <TouchableOpacity style={styles.voiceBtn}>
          <Text style={styles.voiceBtnText}>🎤</Text>
        </TouchableOpacity>
        <TouchableOpacity style={styles.sendBtn} onPress={handleSend} disabled={sending || !input.trim()}>
          {sending ? (
            <ActivityIndicator color={colors.textWhite} size="small" />
          ) : (
            <Ionicons name="send" size={16} color={colors.textWhite} />
          )}
        </TouchableOpacity>
      </View>

      <Modal visible={showProfile} transparent animationType="fade" onRequestClose={() => setShowProfile(false)}>
        <TouchableOpacity style={styles.modalOverlay} activeOpacity={1} onPress={() => setShowProfile(false)}>
          <TouchableOpacity activeOpacity={1} style={styles.profileSheet} onPress={(e) => e.stopPropagation()}>
            <View style={styles.profileHeader}>
              <View style={styles.profileAvatar}>
                <Ionicons name="person" size={36} color={colors.textWhite} />
              </View>
              <Text style={styles.profileName}>{user.name || '用户'}</Text>
              <Text style={styles.profileEmail}>{user.email}</Text>
            </View>
            <View style={styles.profileMenu}>
              <TouchableOpacity style={styles.profileMenuItem}>
                <Ionicons name="settings-outline" size={20} color={colors.textSecondary} />
                <Text style={styles.profileMenuText}>偏好设置</Text>
                <Ionicons name="chevron-forward" size={18} color={colors.textMuted} />
              </TouchableOpacity>
              <TouchableOpacity style={styles.profileMenuItem}>
                <Ionicons name="download-outline" size={20} color={colors.textSecondary} />
                <Text style={styles.profileMenuText}>导出数据</Text>
                <Ionicons name="chevron-forward" size={18} color={colors.textMuted} />
              </TouchableOpacity>
              <TouchableOpacity style={styles.profileMenuItem}>
                <Ionicons name="trash-outline" size={20} color={colors.danger} />
                <Text style={[styles.profileMenuText, { color: colors.danger }]}>删除所有数据</Text>
                <Ionicons name="chevron-forward" size={18} color={colors.textMuted} />
              </TouchableOpacity>
            </View>
          </TouchableOpacity>
        </TouchableOpacity>
      </Modal>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  list: { paddingHorizontal: 20, paddingBottom: 80 },

  greetingRow: {
    flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start',
    paddingTop: 8, paddingBottom: 2,
  },
  greetingLeft: {},
  greetingWave: { fontSize: 14, color: colors.textSecondary, marginBottom: 2 },
  greetingName: { fontSize: 26, fontWeight: '700', color: colors.text, letterSpacing: -0.3 },
  greetingDate: { fontSize: 12, color: colors.textMuted, marginTop: 2 },
  avatarBtn: { marginTop: 4 },
  avatar: {
    width: 44, height: 44, borderRadius: 22,
    backgroundColor: colors.primary, justifyContent: 'center', alignItems: 'center',
  },

  quickSection: { marginVertical: 14 },
  quickLabel: { fontSize: 11, textTransform: 'uppercase', letterSpacing: 1.2, color: colors.textMuted, fontWeight: '500', marginBottom: 10 },
  quickScroll: { marginHorizontal: -20, paddingHorizontal: 20 },
  quickCard: {
    minWidth: 210, maxWidth: 210,
    backgroundColor: colors.card, borderRadius: 16, padding: 14,
    borderWidth: 1, borderColor: colors.border,
    marginRight: 10, flexShrink: 0,
  },
  quickCat: { fontSize: 10, textTransform: 'uppercase', letterSpacing: 1, color: colors.primary, fontWeight: '600', marginBottom: 6 },
  quickTitle: { fontSize: 14, fontWeight: '600', color: colors.text, lineHeight: 19, marginBottom: 4 },
  quickSummary: { fontSize: 11, color: colors.textSecondary, lineHeight: 16 },

  chatDialog: { backgroundColor: colors.card, borderRadius: 20, padding: 18, borderWidth: 1, borderColor: colors.border, marginVertical: 6 },
  chatHint: { fontSize: 12, color: colors.textMuted, marginBottom: 12, textAlign: 'center' },
  suggestionRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginBottom: 4 },
  suggestionChip: {
    fontSize: 12, color: colors.textSecondary,
    backgroundColor: colors.headerBg, borderWidth: 1, borderColor: colors.border,
    borderRadius: 16, paddingHorizontal: 14, paddingVertical: 7,
  },
  suggestionText: { fontSize: 12, color: colors.textSecondary },

  summaryCard: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    padding: 14, backgroundColor: colors.card, borderRadius: 16,
    borderWidth: 1, borderColor: colors.border, marginBottom: 8,
  },
  summaryLeft: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  summaryIcon: {
    width: 36, height: 36, borderRadius: 12,
    backgroundColor: 'rgba(138,171,138,0.10)', justifyContent: 'center', alignItems: 'center',
  },
  summaryTitle: { fontSize: 13, color: colors.text, fontWeight: '500' },
  summarySub: { fontSize: 11, color: colors.textMuted, marginTop: 1 },
  summaryArrow: { color: colors.textMuted },

  eventCard: {
    backgroundColor: colors.card, borderRadius: 14, padding: 14, marginBottom: 10,
    borderWidth: 1, borderColor: colors.border,
  },
  eventHeader: { flexDirection: 'row', alignItems: 'center', gap: 6, marginBottom: 6 },
  eventType: { fontSize: 12, fontWeight: '600', color: colors.primary, textTransform: 'capitalize' },
  eventTime: { fontSize: 11, color: colors.textMuted, marginLeft: 'auto' },
  eventContent: { fontSize: 15, color: colors.text, lineHeight: 22 },
  sentiment: { fontSize: 12, marginTop: 4, color: colors.textSecondary },
  empty: { textAlign: 'center', color: colors.textMuted, marginTop: 40, fontSize: 14 },

  inputBar: {
    flexDirection: 'row', alignItems: 'center', gap: 8,
    paddingHorizontal: 8, paddingVertical: 8,
    backgroundColor: colors.inputBg, borderRadius: 20,
    borderWidth: 1, borderColor: colors.borderLight,
    marginHorizontal: 12, marginBottom: 8,
  },
  addBtn: {
    width: 32, height: 32, borderRadius: 16,
    backgroundColor: colors.headerBg, borderWidth: 1, borderColor: colors.border,
    justifyContent: 'center', alignItems: 'center',
  },
  addBtnText: { fontSize: 18, color: colors.textSecondary },
  input: { flex: 1, fontSize: 14, color: colors.text, paddingVertical: 8, maxHeight: 80 },
  voiceBtn: {
    width: 32, height: 32, borderRadius: 16,
    backgroundColor: colors.headerBg, borderWidth: 1, borderColor: colors.border,
    justifyContent: 'center', alignItems: 'center',
  },
  voiceBtnText: { fontSize: 16 },
  sendBtn: {
    width: 38, height: 38, borderRadius: 19,
    backgroundColor: colors.primary, justifyContent: 'center', alignItems: 'center',
  },

  modalOverlay: {
    flex: 1, backgroundColor: 'rgba(0,0,0,0.3)',
    justifyContent: 'flex-end',
  },
  profileSheet: {
    backgroundColor: colors.bg,
    borderTopLeftRadius: 24, borderTopRightRadius: 24,
    paddingBottom: 40,
  },
  profileHeader: { alignItems: 'center', padding: 24 },
  profileAvatar: {
    width: 64, height: 64, borderRadius: 32,
    backgroundColor: colors.primary, justifyContent: 'center', alignItems: 'center',
    marginBottom: 12,
  },
  profileName: { fontSize: 18, fontWeight: '600', color: colors.text },
  profileEmail: { fontSize: 13, color: colors.textSecondary, marginTop: 2 },
  profileMenu: { backgroundColor: colors.card, marginHorizontal: 16, borderRadius: 14, overflow: 'hidden' },
  profileMenuItem: {
    flexDirection: 'row', alignItems: 'center',
    paddingHorizontal: 20, paddingVertical: 16,
    borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  profileMenuText: { fontSize: 15, color: colors.textSecondary, marginLeft: 12, flex: 1 },
});
