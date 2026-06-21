import React from 'react';
import { NavigationContainer } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { Ionicons } from '@expo/vector-icons';

import RecordScreen from '../screens/RecordScreen';
import SecretaryScreen from '../screens/SecretaryScreen';
import InsightScreen from '../screens/InsightScreen';
import { colors } from '../theme/colors';

const Stack = createNativeStackNavigator();
const Tab = createBottomTabNavigator();

function MainTabs() {
  return (
    <Tab.Navigator
      screenOptions={({ route }) => ({
        tabBarIcon: ({ focused, color, size }) => {
          const icons: Record<string, keyof typeof Ionicons.glyphMap> = {
            Record: focused ? 'create' : 'create-outline',
            Secretary: focused ? 'person' : 'person-outline',
            Insight: focused ? 'compass' : 'compass-outline',
          };
          return <Ionicons name={icons[route.name]} size={size} color={color} />;
        },
        tabBarActiveTintColor: colors.primary,
        tabBarInactiveTintColor: colors.textMuted,
        headerShown: false,
        tabBarStyle: {
          backgroundColor: colors.bg,
          borderTopColor: colors.border,
          paddingTop: 6,
          height: 70,
        },
        tabBarLabelStyle: {
          fontSize: 10,
          fontWeight: '500',
          letterSpacing: 0.3,
          marginBottom: 6,
        },
      })}
    >
      <Tab.Screen name="Record" component={RecordScreen} options={{ title: '记录' }} />
      <Tab.Screen name="Secretary" component={SecretaryScreen} options={{ title: '秘书' }} />
      <Tab.Screen name="Insight" component={InsightScreen} options={{ title: '洞察' }} />
    </Tab.Navigator>
  );
}

export default function AppNavigator() {
  return (
    <NavigationContainer>
      <Stack.Navigator screenOptions={{ headerShown: false }}>
        <Stack.Screen name="Main" component={MainTabs} />
      </Stack.Navigator>
    </NavigationContainer>
  );
}
