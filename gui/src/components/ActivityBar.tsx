import { useState } from 'react';
import {
  MessageSquare,
  FileCode2,
  Terminal,
  Settings,
  PanelLeftOpen,
  PanelLeftClose,
  Database,
  Braces,
  Sparkles,
} from 'lucide-react';

export type ActivityTab = 'chat' | 'explorer' | 'terminal' | 'canvas' | 'settings' | 'mcp';

interface ActivityBarProps {
  activeTab: ActivityTab;
  onTabChange: (tab: ActivityTab) => void;
  sidebarVisible: boolean;
  onToggleSidebar: () => void;
  agentLite?: boolean;
}

const tabs: { id: ActivityTab; icon: React.ReactNode; label: string }[] = [
  { id: 'chat', icon: <MessageSquare size={20} />, label: 'Chat' },
  { id: 'explorer', icon: <FileCode2 size={20} />, label: 'Explorer' },
  { id: 'canvas', icon: <Braces size={20} />, label: 'Canvas' },
  { id: 'terminal', icon: <Terminal size={20} />, label: 'Terminal' },
  { id: 'mcp', icon: <Database size={20} />, label: 'MCP' },
  { id: 'settings', icon: <Settings size={20} />, label: 'Settings' },
];

export function ActivityBar({
  activeTab,
  onTabChange,
  sidebarVisible,
  onToggleSidebar,
  agentLite = false,
}: ActivityBarProps) {
  return (
    <div
      style={{
        width: '48px',
        minWidth: '48px',
        height: '100vh',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        background: agentLite ? '#f0efec' : '#111113',
        borderRight: agentLite ? '1px solid #d4d0c8' : '1px solid rgba(255,255,255,0.06)',
        padding: '8px 0',
        gap: '2px',
        zIndex: 20,
        userSelect: 'none',
      }}
    >
      {/* Top icon - app brand */}
      <div
        style={{
          width: '36px',
          height: '36px',
          borderRadius: '10px',
          background: 'linear-gradient(135deg, #3b82f6, #6366f1)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: '#fff',
          fontWeight: 900,
          fontSize: '1.1rem',
          marginBottom: '12px',
          cursor: 'pointer',
          boxShadow: '0 2px 8px rgba(59,130,246,0.3)',
        }}
        onClick={onToggleSidebar}
        title={sidebarVisible ? 'Collapse sidebar' : 'Expand sidebar'}
      >
        <Sparkles size={16} />
      </div>

      {/* Navigation tabs */}
      <div
        style={{
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          gap: '2px',
        }}
      >
        {tabs.map((tab) => {
          const isActive = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => onTabChange(tab.id)}
              title={tab.label}
              style={{
                width: '36px',
                height: '36px',
                borderRadius: '10px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                background: isActive
                  ? agentLite
                    ? 'rgba(59,130,246,0.12)'
                    : 'rgba(59,130,246,0.15)'
                  : 'transparent',
                border: 'none',
                color: isActive ? '#3b82f6' : agentLite ? '#6b7280' : 'rgba(255,255,255,0.35)',
                cursor: 'pointer',
                transition: 'all 0.15s ease',
                position: 'relative',
              }}
              onMouseEnter={(e) => {
                if (!isActive) {
                  e.currentTarget.style.background = agentLite
                    ? 'rgba(0,0,0,0.04)'
                    : 'rgba(255,255,255,0.06)';
                  e.currentTarget.style.color = agentLite ? '#374151' : 'rgba(255,255,255,0.7)';
                }
              }}
              onMouseLeave={(e) => {
                if (!isActive) {
                  e.currentTarget.style.background = 'transparent';
                  e.currentTarget.style.color = agentLite ? '#6b7280' : 'rgba(255,255,255,0.35)';
                }
              }}
            >
              {isActive && (
                <div
                  style={{
                    position: 'absolute',
                    left: '-8px',
                    top: '50%',
                    transform: 'translateY(-50%)',
                    width: '3px',
                    height: '20px',
                    borderRadius: '0 3px 3px 0',
                    background: '#3b82f6',
                  }}
                />
              )}
              {tab.icon}
            </button>
          );
        })}
      </div>

      {/* Bottom - toggle sidebar */}
      <button
        onClick={onToggleSidebar}
        title={sidebarVisible ? 'Collapse sidebar' : 'Expand sidebar'}
        style={{
          width: '36px',
          height: '36px',
          borderRadius: '10px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: 'transparent',
          border: 'none',
          color: agentLite ? '#6b7280' : 'rgba(255,255,255,0.3)',
          cursor: 'pointer',
          transition: 'all 0.15s ease',
          marginTop: 'auto',
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.background = agentLite
            ? 'rgba(0,0,0,0.04)'
            : 'rgba(255,255,255,0.06)';
          e.currentTarget.style.color = agentLite ? '#374151' : 'rgba(255,255,255,0.7)';
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.background = 'transparent';
          e.currentTarget.style.color = agentLite ? '#6b7280' : 'rgba(255,255,255,0.3)';
        }}
      >
        {sidebarVisible ? <PanelLeftClose size={18} /> : <PanelLeftOpen size={18} />}
      </button>
    </div>
  );
}
