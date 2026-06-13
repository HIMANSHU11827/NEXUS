import { Menu, PlusCircle } from 'lucide-react';

type LoadingScreenProps = {
  label: string;
  subtext?: string;
  reconnecting?: boolean;
};

export function LoadingScreen({ label, subtext, reconnecting = false }: LoadingScreenProps) {
  if (reconnecting) {
    return (
      <div style={{ width: '100vw', height: '100vh', background: '#0a0a0a', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', fontFamily: 'monospace', gap: '18px' }}>
        <div className="spinner" style={{ width: '34px', height: '34px', border: '3px solid #111827', borderTopColor: '#60a5fa', borderRadius: '50%', animation: 'spin 1s linear infinite' }} />
        <div style={{ fontSize: '0.95rem', fontWeight: 900, color: '#dbeafe', letterSpacing: '3px' }}>{label}</div>
        {subtext && (
          <div style={{ fontSize: '0.72rem', color: '#64748b', maxWidth: '380px', textAlign: 'center', lineHeight: 1.8 }}>
            {subtext}
          </div>
        )}
        <div style={{ fontSize: '0.62rem', color: '#334155', marginTop: '4px' }}>Auto-retrying every 3 s</div>
        <style>{`@keyframes spin  { to { transform: rotate(360deg); } }`}</style>
      </div>
    );
  }

  return (
    <div style={{ width: '100vw', height: '100vh', background: '#0f0f0f', color: '#3b82f6', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', fontFamily: 'monospace', gap: '20px' }}>
      <div className="spinner" style={{ width: '40px', height: '40px', border: '4px solid #111', borderTopColor: '#3b82f6', borderRadius: '50%', animation: 'spin 1s linear infinite' }} />
      {label}
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}

export function BackendOfflineBanner() {
  return (
    <div style={{
      position: 'fixed',
      top: 14,
      left: '50%',
      transform: 'translateX(-50%)',
      zIndex: 7000,
      display: 'inline-flex',
      alignItems: 'center',
      gap: '8px',
      padding: '7px 12px',
      borderRadius: '999px',
      background: 'rgba(15,23,42,0.86)',
      border: '1px solid rgba(96,165,250,0.24)',
      color: '#dbeafe',
      fontSize: '0.68rem',
      fontWeight: 800,
      letterSpacing: '0.3px',
      boxShadow: '0 10px 30px rgba(0,0,0,0.25)',
      backdropFilter: 'blur(12px)',
    }}>
      <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#60a5fa', animation: 'pulse 1.2s infinite' }} />
      Reconnecting to NEXUS
    </div>
  );
}

type FloatingNavControlsProps = {
  chatScrolled: boolean;
  isSidebarResizing: boolean;
  sidebarVisible: boolean;
  sidebarWidth: number;
  handleNewChat: () => void;
  setSidebarVisible: (visible: boolean) => void;
};

export function FloatingNavControls({
  chatScrolled,
  handleNewChat,
  isSidebarResizing,
  setSidebarVisible,
  sidebarVisible,
  sidebarWidth,
}: FloatingNavControlsProps) {
  void isSidebarResizing;
  void sidebarWidth;
  if (sidebarVisible) {
    // Sidebar is open — no need for floating controls, they'd overlap content
    return null;
  }
  return (
    <div style={{ position: 'fixed', top: 14, left: 18, display: 'flex', gap: '8px', zIndex: 5000, opacity: chatScrolled ? 0.18 : 1, pointerEvents: chatScrolled ? 'none' : 'auto', transform: chatScrolled ? 'translateY(-10px)' : 'translateY(0)', transition: 'opacity 0.18s ease, transform 0.18s ease' }}>
      <button
        className="toggle-sidebar-btn"
        style={{ position: 'static', width: '34px', height: '34px', background: 'rgba(255,255,255,0.88)', backdropFilter: 'blur(12px)', border: '1px solid rgba(0,0,0,0.10)', color: '#374151', boxShadow: '0 2px 8px rgba(0,0,0,0.08)', borderRadius: '10px' }}
        onClick={() => setSidebarVisible(true)}
      >
        <Menu size={17} />
      </button>
      <button
        className="toggle-sidebar-btn"
        style={{ position: 'static', height: '34px', padding: '0 12px', background: 'rgba(59,130,246,0.10)', color: '#2563eb', border: '1px solid rgba(59,130,246,0.22)', backdropFilter: 'blur(12px)', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px', boxShadow: '0 2px 8px rgba(59,130,246,0.08)', borderRadius: '10px' }}
        onClick={handleNewChat}
      >
        <PlusCircle size={15} />
        <span style={{ fontSize: '0.65rem', fontWeight: 800, letterSpacing: '1.5px', whiteSpace: 'nowrap' }}>NEW CHAT</span>
      </button>
    </div>
  );
}

type HeaderStatusRailProps = {
  chatScrolled: boolean;
  drawerType: string;
  healthClass: string;
  hiveCount: number;
  reminderCount: number;
  setDrawerType: (drawer: 'none' | 'hive' | 'reminders' | 'health' | 'canvas') => void;
};

export function HeaderStatusRail({
  chatScrolled,
  drawerType,
  healthClass,
  hiveCount,
  reminderCount,
  setDrawerType,
}: HeaderStatusRailProps) {
  return (
    <div className={`drawer-switcher-width ${drawerType === 'canvas' ? 'canvas' : ''}`}>
      <div className="header-minimal" style={{ opacity: chatScrolled ? 0.16 : 1, pointerEvents: chatScrolled ? 'none' : 'auto', transform: chatScrolled ? 'translateY(-10px)' : 'translateY(0)' }}>
        <div className={`status-indicator clickable-indicator ${healthClass}`} onClick={() => setDrawerType('health')}>
          HEALTH
        </div>
        <div
          className="status-indicator clickable-indicator"
          style={{
            background: hiveCount > 0 ? 'rgba(34, 197, 94, 0.1)' : 'rgba(239, 68, 68, 0.1)',
            color: hiveCount > 0 ? '#4ade80' : '#f87171',
          }}
          onClick={() => setDrawerType('hive')}
        >
          HIVE: {hiveCount}
        </div>
        <div
          className="status-indicator clickable-indicator"
          style={{ background: 'rgba(251, 191, 36, 0.1)', color: '#fbbf24' }}
          onClick={() => setDrawerType('reminders')}
        >
          REMINDERS: {reminderCount}
        </div>
        <div
          className="status-indicator clickable-indicator"
          style={{ background: 'rgba(59, 130, 246, 0.1)', color: '#93c5fd' }}
          onClick={() => setDrawerType('canvas')}
        >
          CANVAS
        </div>
      </div>
    </div>
  );
}
