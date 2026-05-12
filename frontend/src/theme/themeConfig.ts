import type { ThemeConfig } from 'antd';
import { theme } from 'antd';
import type { ThemeMode } from './themeStorage';

export type ResolvedThemeMode = Exclude<ThemeMode, 'system'>;

const brandPrimary = '#3F7A82';
const brandPrimaryAccent = '#9D5B7B';

const fontFamily = [
  '"Inter"',
  '"PingFang SC"',
  '"HarmonyOS Sans"',
  '"Microsoft YaHei UI"',
  '"Microsoft YaHei"',
  '"Heiti SC"',
  '-apple-system',
  'BlinkMacSystemFont',
  '"Segoe UI"',
  'Roboto',
  '"Helvetica Neue"',
  'Arial',
  'sans-serif',
].join(', ');

const sharedToken: ThemeConfig['token'] = {
  colorPrimary: brandPrimary,
  colorInfo: brandPrimary,
  borderRadius: 10,
  borderRadiusLG: 14,
  borderRadiusSM: 6,
  wireframe: false,
  fontFamily,
  fontSize: 14,
  motionDurationMid: '0.22s',
  motionEaseInOut: 'cubic-bezier(0.22, 1, 0.36, 1)',
};

const sharedComponents: ThemeConfig['components'] = {
  Button: {
    borderRadius: 10,
    controlHeight: 36,
    fontWeight: 500,
    primaryShadow: '0 6px 16px -4px color-mix(in srgb, var(--ant-color-primary) 38%, transparent)',
    defaultShadow: 'none',
  },
  Card: {
    borderRadiusLG: 16,
    paddingLG: 20,
  },
  Modal: {
    borderRadiusLG: 16,
  },
  Drawer: {
    paddingLG: 20,
  },
  Tooltip: {
    colorBgSpotlight: brandPrimary,
  },
  Menu: {
    itemBorderRadius: 8,
    itemMarginInline: 8,
    itemHeight: 38,
    iconSize: 16,
    fontSize: 14,
  },
  Tabs: {
    titleFontSize: 15,
    titleFontSizeLG: 16,
    horizontalItemPadding: '10px 16px',
    inkBarColor: brandPrimary,
  },
  Input: {
    borderRadius: 10,
    controlHeight: 38,
    activeShadow: '0 0 0 3px color-mix(in srgb, var(--ant-color-primary) 22%, transparent)',
  },
  Select: {
    borderRadius: 10,
    controlHeight: 38,
  },
  Tag: {
    borderRadiusSM: 6,
  },
};

const lightThemeConfig: ThemeConfig = {
  algorithm: theme.defaultAlgorithm,
  token: {
    ...sharedToken,
    colorBgBase: '#F6F4EE',
    colorTextBase: '#1F2933',
    colorBgLayout: '#F4F1EA',
    colorBgContainer: '#FFFFFF',
    colorBgElevated: '#FFFFFF',
    colorBorder: '#E5DED1',
    colorBorderSecondary: '#EFEAE0',
    colorTextSecondary: '#4D5560',
    colorTextTertiary: '#7C8693',
    colorFillTertiary: '#F0EBE0',
    colorFillSecondary: '#EAE3D4',
    boxShadow: '0 6px 20px -8px rgba(31, 41, 51, 0.12), 0 2px 6px -4px rgba(31, 41, 51, 0.08)',
    boxShadowSecondary: '0 12px 30px -12px rgba(31, 41, 51, 0.18), 0 4px 10px -6px rgba(31, 41, 51, 0.08)',
  },
  components: {
    ...sharedComponents,
    Layout: {
      bodyBg: '#F4F1EA',
      headerBg: '#FFFFFF',
      siderBg: '#FFFFFF',
    },
    Menu: {
      ...sharedComponents?.Menu,
      itemSelectedBg: 'color-mix(in srgb, ' + brandPrimary + ' 12%, transparent)',
      itemSelectedColor: brandPrimary,
      itemHoverBg: 'color-mix(in srgb, ' + brandPrimary + ' 7%, transparent)',
    },
  },
};

const darkThemeConfig: ThemeConfig = {
  algorithm: theme.darkAlgorithm,
  token: {
    ...sharedToken,
    colorPrimary: '#5FA0A8',
    colorInfo: '#5FA0A8',
    colorBgBase: '#0E141B',
    colorTextBase: '#E8ECF2',
    colorBgLayout: '#0B1118',
    colorBgContainer: '#141B24',
    colorBgElevated: '#1A222D',
    colorBorder: '#28323F',
    colorBorderSecondary: '#1E2731',
    colorTextSecondary: '#B6BFCB',
    colorTextTertiary: '#7C8693',
    boxShadow: '0 8px 24px -10px rgba(0, 0, 0, 0.55), 0 2px 8px -4px rgba(0, 0, 0, 0.45)',
    boxShadowSecondary: '0 14px 36px -12px rgba(0, 0, 0, 0.65), 0 4px 12px -6px rgba(0, 0, 0, 0.4)',
  },
  components: {
    ...sharedComponents,
    Layout: {
      bodyBg: '#0B1118',
      headerBg: '#141B24',
      siderBg: '#141B24',
    },
    Menu: {
      ...sharedComponents?.Menu,
      itemSelectedBg: 'color-mix(in srgb, #5FA0A8 22%, transparent)',
      itemSelectedColor: '#7DC2CB',
      itemHoverBg: 'color-mix(in srgb, #5FA0A8 12%, transparent)',
    },
  },
};

export const getThemeConfig = (mode: ResolvedThemeMode): ThemeConfig => {
  return mode === 'dark' ? darkThemeConfig : lightThemeConfig;
};

export const brandGradient = (mode: ResolvedThemeMode): string => {
  if (mode === 'dark') {
    return `linear-gradient(135deg, #2E5A60 0%, #3F7A82 45%, #6B4660 100%)`;
  }
  return `linear-gradient(135deg, ${brandPrimary} 0%, #4D8088 45%, ${brandPrimaryAccent} 100%)`;
};

export const brandPrimaryHex = brandPrimary;
export const brandAccentHex = brandPrimaryAccent;
