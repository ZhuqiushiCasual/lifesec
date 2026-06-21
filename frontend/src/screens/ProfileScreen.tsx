import React from 'react';
import { View, Text, TouchableOpacity, StyleSheet } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useAppStore } from '../store';
import { colors } from '../theme/colors';

export default function ProfileScreen() {
  const insets = useSafeAreaInsets();
  const user = useAppStore((s) => s.user);

  return (
    <View style={[styles.container, { paddingTop: insets.top }]}>
      <View style={styles.profileCard}>
        <View style={styles.avatar}>
          <Ionicons name="person" size={40} color={colors.textWhite} />
        </View>
        <Text style={styles.name}>{user.name || '用户'}</Text>
        <Text style={styles.email}>{user.email}</Text>
      </View>

      <View style={styles.menu}>
        <TouchableOpacity style={styles.menuItem}>
          <Ionicons name="settings-outline" size={20} color={colors.textSecondary} />
          <Text style={styles.menuText}>偏好设置</Text>
          <Ionicons name="chevron-forward" size={18} color={colors.textMuted} style={styles.menuArrow} />
        </TouchableOpacity>
        <TouchableOpacity style={styles.menuItem}>
          <Ionicons name="download-outline" size={20} color={colors.textSecondary} />
          <Text style={styles.menuText}>导出数据</Text>
          <Ionicons name="chevron-forward" size={18} color={colors.textMuted} style={styles.menuArrow} />
        </TouchableOpacity>
        <TouchableOpacity style={styles.menuItem}>
          <Ionicons name="trash-outline" size={20} color={colors.danger} />
          <Text style={[styles.menuText, { color: colors.danger }]}>删除所有数据</Text>
          <Ionicons name="chevron-forward" size={18} color={colors.textMuted} style={styles.menuArrow} />
        </TouchableOpacity>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  profileCard: { alignItems: 'center', padding: 24, backgroundColor: colors.card, marginBottom: 1 },
  avatar: { width: 72, height: 72, borderRadius: 36, backgroundColor: colors.primary, justifyContent: 'center', alignItems: 'center', marginBottom: 12 },
  name: { fontSize: 18, fontWeight: '600', color: colors.text },
  email: { fontSize: 13, color: colors.textSecondary, marginTop: 2 },
  menu: { backgroundColor: colors.card, marginTop: 12 },
  menuItem: { flexDirection: 'row', alignItems: 'center', paddingHorizontal: 20, paddingVertical: 16, borderBottomWidth: 1, borderBottomColor: colors.borderLight },
  menuText: { fontSize: 15, color: colors.textSecondary, marginLeft: 12, flex: 1 },
  menuArrow: { marginLeft: 'auto' },
});
