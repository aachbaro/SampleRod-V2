import AsyncStorage from '@react-native-async-storage/async-storage';
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';
import { useColorScheme } from 'react-native';
import { DARK, LIGHT, type ThemePalette } from './theme';

export type ThemeMode = 'light' | 'dark' | 'system';

type ThemeContextValue = {
  C: ThemePalette;
  theme: ThemeMode;
  isDark: boolean;
  setTheme: (mode: ThemeMode) => void;
};

const ThemeContext = createContext<ThemeContextValue>({
  C: DARK,
  theme: 'dark',
  isDark: true,
  setTheme: () => {},
});

const STORAGE_KEY = 'samplerod_theme_mode';

export function ThemeProvider({ children }: { children: ReactNode }) {
  const systemScheme = useColorScheme();
  const [theme, setThemeState] = useState<ThemeMode>('dark');

  useEffect(() => {
    AsyncStorage.getItem(STORAGE_KEY)
      .then(v => { if (v === 'light' || v === 'dark' || v === 'system') setThemeState(v); })
      .catch(() => {});
  }, []);

  const setTheme = useCallback((mode: ThemeMode) => {
    setThemeState(mode);
    AsyncStorage.setItem(STORAGE_KEY, mode).catch(() => {});
  }, []);

  const resolvedScheme = theme === 'system' ? (systemScheme ?? 'dark') : theme;
  const isDark = resolvedScheme === 'dark';
  const C = isDark ? DARK : LIGHT;

  return (
    <ThemeContext.Provider value={{ C, theme, isDark, setTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useC(): ThemePalette {
  return useContext(ThemeContext).C;
}

export function useTheme() {
  const { theme, isDark, setTheme } = useContext(ThemeContext);
  return { theme, isDark, setTheme };
}
