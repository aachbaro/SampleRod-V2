import { Tabs } from 'expo-router';
import { Text } from 'react-native';
import { useC } from '@/constants/ThemeContext';

function TabIcon({ emoji }: { emoji: string }) {
  return <Text style={{ fontSize: 20 }}>{emoji}</Text>;
}

export default function TabLayout() {
  const C = useC();
  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarStyle: {
          backgroundColor: C.bgB,
          borderTopColor: C.border,
          borderTopWidth: 1,
          height: 62,
          paddingBottom: 10,
        },
        tabBarActiveTintColor: C.accent,
        tabBarInactiveTintColor: C.textMuted,
        tabBarLabelStyle: { fontSize: 10, fontWeight: '600' },
      }}
    >
      <Tabs.Screen
        name="index"
        options={{
          title: 'Enregistrer',
          tabBarIcon: () => <TabIcon emoji="🎙" />,
        }}
      />
      <Tabs.Screen
        name="remote"
        options={{
          title: 'Remote',
          tabBarIcon: () => <TabIcon emoji="🎛" />,
        }}
      />
      <Tabs.Screen
        name="transfer"
        options={{
          title: 'Transferer',
          tabBarIcon: () => <TabIcon emoji="📤" />,
        }}
      />
    </Tabs>
  );
}
