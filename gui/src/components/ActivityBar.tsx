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
        width: '58px',
        minWidth: '58px',
        height: '100vh',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        background: agentLite ? '#f4f1ea' : '#0f1014',
        borderRight: agentLite ? '1px solid #d4d0c8' : '1px solid #1d1f26',
        padding: '12px 0 10px',
        gap: '6px',
        zIndex: 20,
        userSelect: 'none',
      }}
    >
      {/* Top icon - app brand */}
      <div
        style={{
          width: '40px',
          height: '40px',
          borderRadius: '12px',
          background: agentLite ? '#ffffff' : '#16181e',
          border: agentLite ? '1px solid #d6d3d1' : '1px solid #2a2d36',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: agentLite ? '#2563eb' : '#60a5fa',
          fontWeight: 900,
          fontSize: '1.1rem',
          marginBottom: '14px',
          cursor: 'pointer',
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
                borderRadius: '12px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                background: isActive
                  ? agentLite
                    ? '#ffffff'
                    : '#171a20'
                  : 'transparent',
                border: isActive ? (agentLite ? '1px solid #d6d3d1' : '1px solid #2a2d36') : '1px solid transparent',
                color: isActive ? '#60a5fa' : agentLite ? '#6b7280' : '#6b7280',
                cursor: 'pointer',
                transition: 'all 0.15s ease',
                position: 'relative',
              }}
              onMouseEnter={(e) => {
                if (!isActive) {
                  e.currentTarget.style.background = agentLite
                    ? '#ffffff'
                    : '#171a20';
                  e.currentTarget.style.color = agentLite ? '#374151' : '#d4d4d8';
                }
              }}
              onMouseLeave={(e) => {
                if (!isActive) {
                  e.currentTarget.style.background = 'transparent';
                  e.currentTarget.style.color = agentLite ? '#6b7280' : '#6b7280';
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
                    height: '16px',
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
          borderRadius: '12px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: 'transparent',
          border: 'none',
          color: agentLite ? '#6b7280' : '#6b7280',
          cursor: 'pointer',
          transition: 'all 0.15s ease',
          marginTop: 'auto',
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.background = agentLite
            ? '#ffffff'
            : '#171a20';
          e.currentTarget.style.color = agentLite ? '#374151' : '#d4d4d8';
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.background = 'transparent';
          e.currentTarget.style.color = agentLite ? '#6b7280' : '#6b7280';
        }}
      >
        {sidebarVisible ? <PanelLeftClose size={18} /> : <PanelLeftOpen size={18} />}
      </button>
    </div>
  );
}
