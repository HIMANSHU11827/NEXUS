import { useState, useEffect, useCallback } from 'react';

type NexusSettings = {
  sidebarWidth: number;
  drawerWidth: number;
  canvasWidth: number;
  showChatAvatars: boolean;
  showLogoInHeader: boolean;
  showLogoMark: boolean;
  accentColor: string;
  operatorName: string;
  brandName: string;
  brandMark: string;
  assistantAvatar: string;
  userAvatar: string;
  interfaceMode: string;
};

const defaults: NexusSettings = {
  sidebarWidth: 236,
  drawerWidth: 390,
  canvasWidth: 768,
  showChatAvatars: true,
  showLogoInHeader: true,
  showLogoMark: true,
  accentColor: '#3b82f6',
  operatorName: 'Operator',
  brandName: 'NEXUS',
  brandMark: '⚡',
  assistantAvatar: '🧠',
  userAvatar: '👤',
  interfaceMode: 'dark',
};

function loadFromStorage(): Partial<NexusSettings> {
  const stored: Partial<NexusSettings> = {};
  const sidebar = Number(localStorage.getItem('nexus.sidebarWidth'));
  if (Number.isFinite(sidebar) && sidebar > 0) stored.sidebarWidth = sidebar;
  const drawer = Number(localStorage.getItem('nexus.drawerWidth'));
  if (Number.isFinite(drawer) && drawer > 0) stored.drawerWidth = drawer;
  const canvas = Number(localStorage.getItem('nexus.canvasWidth'));
  if (Number.isFinite(canvas) && canvas > 0) stored.canvasWidth = canvas;
  stored.showChatAvatars = localStorage.getItem('nexus.showChatAvatars') !== 'false';
  stored.showLogoInHeader = localStorage.getItem('nexus.showLogoInHeader') !== 'false';
  stored.showLogoMark = localStorage.getItem('nexus.showLogoMark') !== 'false';
  stored.accentColor = localStorage.getItem('nexus.accentColor') || defaults.accentColor;
  stored.operatorName = localStorage.getItem('nexus.operatorName') || defaults.operatorName;
  stored.brandName = localStorage.getItem('nexus.brandName') || defaults.brandName;
  stored.brandMark = localStorage.getItem('nexus.brandMark') || defaults.brandMark;
  stored.assistantAvatar = localStorage.getItem('nexus.assistantAvatar') || defaults.assistantAvatar;
  stored.userAvatar = localStorage.getItem('nexus.userAvatar') || defaults.userAvatar;
  return stored;
}

export function useSettings() {
  const [settings, setSettings] = useState<NexusSettings>(() => ({
    ...defaults,
    ...loadFromStorage(),
  }));

  const updateSetting = useCallback(<K extends keyof NexusSettings>(
    key: K,
    value: NexusSettings[K],
  ) => {
    setSettings(prev => ({ ...prev, [key]: value }));
  }, []);

  useEffect(() => {
    if (settings.accentColor) {
      localStorage.setItem('nexus.accentColor', settings.accentColor);
    }
  }, [settings.accentColor]);

  useEffect(() => {
    localStorage.setItem('nexus.showChatAvatars', String(settings.showChatAvatars));
  }, [settings.showChatAvatars]);

  useEffect(() => {
    localStorage.setItem('nexus.showLogoInHeader', String(settings.showLogoInHeader));
  }, [settings.showLogoInHeader]);

  useEffect(() => {
    localStorage.setItem('nexus.showLogoMark', String(settings.showLogoMark));
  }, [settings.showLogoMark]);

  useEffect(() => {
    localStorage.setItem('nexus.operatorName', settings.operatorName);
  }, [settings.operatorName]);

  useEffect(() => {
    localStorage.setItem('nexus.brandName', settings.brandName);
  }, [settings.brandName]);

  useEffect(() => {
    localStorage.setItem('nexus.brandMark', settings.brandMark);
  }, [settings.brandMark]);

  useEffect(() => {
    localStorage.setItem('nexus.assistantAvatar', settings.assistantAvatar);
  }, [settings.assistantAvatar]);

  useEffect(() => {
    localStorage.setItem('nexus.userAvatar', settings.userAvatar);
  }, [settings.userAvatar]);

  return { settings, updateSetting };
}
