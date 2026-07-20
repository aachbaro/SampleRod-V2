import { Platform } from 'react-native';

export const DARK = {
  bgA: '#121318',
  bgB: '#1a1c22',
  cardBg: '#22242c',
  cardSoft: '#2a2d38',
  textMain: '#e8e9ee',
  textMuted: '#8890a4',
  textSub: '#b0b4c4',
  accent: '#7c6af7',
  accentSoft: '#2d2660',
  border: '#323544',
  recRed: '#e84040',
  recRedSoft: '#4a1010',
  success: '#22c55e',
  error: '#ef4444',
  warning: '#f59e0b',
} as const;

export const LIGHT = {
  bgA: '#f4f4f7',
  bgB: '#ffffff',
  cardBg: '#ffffff',
  cardSoft: '#f0f0f5',
  textMain: '#1a1c22',
  textMuted: '#8890a4',
  textSub: '#44475a',
  accent: '#5b44e8',
  accentSoft: '#dddaff',
  border: '#d4d6e4',
  recRed: '#d63030',
  recRedSoft: '#fde8e8',
  success: '#16a34a',
  error: '#dc2626',
  warning: '#d97706',
} as const;

export type ThemePalette = { readonly [K in keyof typeof DARK]: string };

export const C = DARK;

export const Fonts = Platform.select({
  ios: { sans: 'system-ui', mono: 'ui-monospace' },
  default: { sans: 'normal', mono: 'monospace' },
});

export const Spacing = {
  xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32,
} as const;

export const Radius = {
  sm: 6, md: 10, lg: 14,
} as const;
