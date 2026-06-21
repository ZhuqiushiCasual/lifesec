import React, { useCallback, useEffect, useState } from 'react';
import { View, Text, FlatList, StyleSheet, RefreshControl, ActivityIndicator } from 'react-native';
import { useFocusEffect } from '@react-navigation/native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import * as api from '../services/api';
import { FinanceTxn } from '../types';
import { colors } from '../theme/colors';

export default function FinanceScreen() {
  const insets = useSafeAreaInsets();
  const [txns, setTxns] = useState<FinanceTxn[]>([]);
  const [loading, setLoading] = useState(true);

  const loadTxns = async () => {
    try {
      const res = await api.finance.listTxns();
      setTxns(res.data.items);
    } catch (_) {
    } finally {
      setLoading(false);
    }
  };

  useFocusEffect(useCallback(() => { loadTxns(); }, []));

  const renderItem = ({ item }: { item: FinanceTxn }) => (
    <View style={styles.txnCard}>
      <View style={styles.txnHeader}>
        <Text style={[styles.txnType, { color: item.type === 'income' ? colors.success : item.type === 'expense' ? colors.danger : colors.primary }]}>
          {item.type === 'income' ? '📈' : item.type === 'expense' ? '📉' : '🏦'} {item.type}
        </Text>
        <Text style={styles.txnAmount}>
          {item.type === 'income' ? '+' : item.type === 'expense' ? '-' : ''}
                    ¥{Number(item.amount).toLocaleString()}
        </Text>
      </View>
      <View style={styles.txnMeta}>
        <Text style={styles.txnCategory}>{item.category}</Text>
        {item.counterparty && <Text style={styles.txnCounterparty}>{item.counterparty}</Text>}
        {item.account && <Text style={styles.txnAccount}>{item.account}</Text>}
      </View>
      <Text style={styles.txnTime}>
        {new Date(item.recorded_at).toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })}
      </Text>
    </View>
  );

  return (
    <View style={[styles.container, { paddingTop: insets.top }]}>
      {loading ? (
        <ActivityIndicator style={styles.loading} size="large" color={colors.primary} />
      ) : (
        <FlatList
          data={txns}
          keyExtractor={(t) => t.id}
          renderItem={renderItem}
          contentContainerStyle={styles.list}
          refreshControl={<RefreshControl refreshing={loading} onRefresh={loadTxns} />}
          ListEmptyComponent={<Text style={styles.empty}>暂无财务记录</Text>}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  list: { padding: 16 },
  loading: { flex: 1, justifyContent: 'center' },
  txnCard: { backgroundColor: colors.card, borderRadius: 14, padding: 14, marginBottom: 10, shadowColor: colors.text, shadowOffset: { width: 0, height: 1 }, shadowOpacity: 0.05, shadowRadius: 3, elevation: 1 },
  txnHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 },
  txnType: { fontSize: 13, fontWeight: '600', textTransform: 'capitalize' },
  txnAmount: { fontSize: 16, fontWeight: '700' },
  txnMeta: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginBottom: 4 },
  txnCategory: { fontSize: 12, color: colors.textSecondary, backgroundColor: colors.borderLight, paddingHorizontal: 8, paddingVertical: 2, borderRadius: 8 },
  txnCounterparty: { fontSize: 12, color: colors.textSecondary },
  txnAccount: { fontSize: 12, color: colors.textMuted },
  txnTime: { fontSize: 11, color: colors.textMuted },
  empty: { textAlign: 'center', color: colors.textMuted, marginTop: 40, fontSize: 14 },
});
