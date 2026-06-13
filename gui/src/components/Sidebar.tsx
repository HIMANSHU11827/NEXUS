import { useState, useEffect } from 'react';
import type { CSSProperties } from 'react';
import { Edit2, Search, Trash2, MoreHorizontal, Bot } from 'lucide-react';
import type { SessionNotice, SessionSummary } from '../types';
import { cleanUserMessage } from '../textUtils';

type SidebarProps = {
  brandName: string;
  brandMark: string;
  showLogoMark: boolean;
  currentSessionId: string;
  editTitle: string;
  editingId: string | null;
  historySearch: string;
  hoveredSessionId: string | null;
  isSidebarResizing: boolean;
  operatorName: string;
  sessionList: SessionSummary[];
  sessionNotice: SessionNotice | null;
  settingsOpen: boolean;
  sidebarVisible: boolean;
  sidebarWidth: number;
  deleteSession: (id: string) => void;
  loadSession: (id: string) => void;
  renameSession: (id: string, title: string) => void;
  setActiveTab: (tab: string) => void;
  setEditTitle: (title: string) => void;
  setEditingId: (id: string | null) => void;
  setHistorySearch: (value: string) => void;
  setHoveredSessionId: (id: string | null) => void;
  setIsSidebarResizing: (value: boolean) => void;
  setSettingsOpen: (value: boolean) => void;
  newChat?: () => void;
};

const sidebarStyle = (sidebarWidth: number): CSSProperties => ({
  ['--sidebar-width' as string]: `${sidebarWidth}px`,
});

export function Sidebar({
  brandName,
  brandMark,
  showLogoMark,
  currentSessionId,
  editTitle,
  editingId,
  historySearch,
  hoveredSessionId,
  isSidebarResizing,
  operatorName,
  sessionList,
  sessionNotice,
  settingsOpen,
  sidebarVisible,
  sidebarWidth,
  deleteSession,
  loadSession,
  renameSession,
  setActiveTab,
  setEditTitle,
  setEditingId,
  setHistorySearch,
  setHoveredSessionId,
  setIsSidebarResizing,
  setSettingsOpen,
  newChat,
}: SidebarProps) {
  const [activeMenuId, setActiveMenuId] = useState<string | null>(null);

  useEffect(() => {
    if (!activeMenuId) return;
    const handleGlobalClick = () => {
      setActiveMenuId(null);
    };
    window.addEventListener('click', handleGlobalClick);
    return () => window.removeEventListener('click', handleGlobalClick);
  }, [activeMenuId]);

  return (
    <div
      className={`sidebar ${sidebarVisible ? '' : 'hidden'} ${isSidebarResizing ? 'resizing' : ''}`}
      style={sidebarStyle(sidebarWidth)}
    >
      {sidebarVisible && (
        <button
          className="sidebar-resize-handle"
          title="Drag to resize sidebar"
          aria-label="Resize sidebar"
          onPointerDown={(event) => {
            event.preventDefault();
            setIsSidebarResizing(true);
          }}
        />
      )}
      <div
        onClick={() => setActiveTab('session')}
        style={{
          fontSize: '1.2rem',
          fontWeight: 900,
          letterSpacing: '4px',
          marginBottom: '15px',
          whiteSpace: 'nowrap',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: '8px',
          cursor: 'pointer',
          background: 'linear-gradient(to right, #fff, #999)',
          WebkitBackgroundClip: 'text',
          WebkitTextFillColor: 'transparent',
        }}
      >
        {showLogoMark && <span style={{ WebkitTextFillColor: 'initial', fontSize: '1.25rem' }}>{brandMark}</span>}
        <span>{(brandName.trim() || 'NEXUS').toUpperCase()}</span>
      </div>

      <button className="lemon-new-btn" onClick={newChat} title="Create new session">
        <span style={{ fontSize: '1.25rem', fontWeight: 600, display: 'inline-flex', alignItems: 'center' }}>+</span>
        <span style={{ marginTop: '-1px' }}>New</span>
      </button>

      <style>{`
            :root { --accent-cyan: #22d3ee; --bg-deep: #050505; }
            @keyframes pulse { 0% { opacity: 0.6; transform: scale(0.98); } 50% { opacity: 1; transform: scale(1); } 100% { opacity: 0.6; transform: scale(0.98); } }
            @keyframes glow { 0% { box-shadow: 0 0 5px rgba(59, 130, 246, 0.2); } 50% { box-shadow: 0 0 15px rgba(59, 130, 246, 0.5); } 100% { box-shadow: 0 0 5px rgba(59, 130, 246, 0.2); } }
            @keyframes slideIn { from { transform: translateY(10px); opacity: 0; } to { transform: translateY(0); opacity: 1; } }
            
            .lemon-new-btn {
              display: flex;
              align-items: center;
              justify-content: center;
              gap: 8px;
              width: calc(100% - 30px);
              margin: 0 15px 20px 15px;
              padding: 11px 16px;
              background-color: #fffdf0;
              border: 1px solid #f2e9cb;
              border-radius: 12px;
              color: #1a1a1a;
              font-size: 0.95rem;
              font-weight: 600;
              cursor: pointer;
              transition: all 0.2s ease-in-out;
              box-shadow: 0 2px 6px rgba(0, 0, 0, 0.05);
            }
            .lemon-new-btn:hover {
              background-color: #fef8e2;
              border-color: #e6dbb5;
              transform: translateY(-1px);
              box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
            }
            .lemon-new-btn:active {
              transform: translateY(1px);
            }
            .hover-menu-item:hover {
              background-color: rgba(255, 255, 255, 0.06) !important;
              color: #fff !important;
            }
            .hover-menu-item-delete:hover {
              background-color: rgba(239, 68, 68, 0.15) !important;
              color: #fca5a5 !important;
            }
      `}</style>

      {sessionNotice && (
        <div style={{
          margin: '0 15px 10px',
          padding: '8px 10px',
          borderRadius: '8px',
          fontSize: '0.68rem',
          color: sessionNotice.kind === 'error' ? '#fca5a5' : '#86efac',
          background: sessionNotice.kind === 'error' ? 'rgba(239,68,68,0.08)' : 'rgba(34,197,94,0.08)',
          border: `1px solid ${sessionNotice.kind === 'error' ? 'rgba(239,68,68,0.2)' : 'rgba(34,197,94,0.2)'}`,
        }}>
          {sessionNotice.message}
        </div>
      )}

      <div className="search-box" style={{ padding: '0 15px 15px 15px' }}>
        <div style={{ position: 'relative' }}>
          <Search size={14} style={{ position: 'absolute', left: '10px', top: '50%', transform: 'translateY(-50%)', color: '#555' }} />
          <input
            type="text"
            placeholder="Search history..."
            value={historySearch}
            onChange={(event) => setHistorySearch(event.target.value)}
            style={{ width: '100%', background: '#1e1e1e', border: '1px solid rgba(255,255,255,0.05)', borderRadius: '6px', padding: '8px 10px 8px 30px', color: '#fff', fontSize: '0.8rem', outline: 'none' }}
          />
        </div>
      </div>

      <div className="history-section" style={{ flex: 1, padding: '0 10px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '4px' }}>
        {sessionList
          .filter(session => (session.title || 'New Chat').toLowerCase().includes(historySearch.toLowerCase()))
          .map((session) => (
            <div
              key={session.id}
              onMouseEnter={() => setHoveredSessionId(session.id)}
              onMouseLeave={() => setHoveredSessionId(null)}
              style={{
                padding: '8px 9px 8px 12px',
                borderRadius: '10px',
                fontSize: '0.75rem',
                color: currentSessionId === session.id ? '#fff' : 'rgba(255,255,255,0.4)',
                background: currentSessionId === session.id ? 'rgba(59, 130, 246, 0.08)' : 'transparent',
                border: currentSessionId === session.id ? '1px solid rgba(59, 130, 246, 0.15)' : '1px solid transparent',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                transition: 'all 0.2s',
                fontWeight: currentSessionId === session.id ? 700 : 400,
                position: 'relative',
              }}
              onClick={() => loadSession(session.id)}
            >
              <div style={{ display: 'flex', alignItems: 'center', flex: 1, minWidth: 0 }}>
                <Bot size={13} style={{ marginRight: '8px', opacity: currentSessionId === session.id ? 0.9 : 0.5, flexShrink: 0 }} />
                {editingId === session.id ? (
                  <input
                    autoFocus
                    value={editTitle}
                    onChange={(event) => setEditTitle(event.target.value)}
                    onBlur={() => renameSession(session.id, editTitle)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter') renameSession(session.id, editTitle);
                    }}
                    style={{ width: '100%', background: 'transparent', border: 'none', color: '#fff', fontSize: '0.75rem', outline: 'none' }}
                  />
                ) : (
                  <span title={cleanUserMessage(session.title) || 'New Chat'} style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1, paddingRight: '8px' }}>
                    {cleanUserMessage(session.title) || 'New Chat'}
                  </span>
                )}
              </div>

              {(hoveredSessionId === session.id || activeMenuId === session.id) && (
                <div style={{ display: 'flex', alignItems: 'center', flexShrink: 0, position: 'relative' }}>
                  <button
                    title="Options"
                    onClick={(event) => {
                      event.stopPropagation();
                      setActiveMenuId(activeMenuId === session.id ? null : session.id);
                    }}
                    style={{
                      width: '24px',
                      height: '24px',
                      display: 'inline-flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      background: 'rgba(255,255,255,0.06)',
                      border: '1px solid rgba(255,255,255,0.1)',
                      borderRadius: '6px',
                      color: '#bbb',
                      cursor: 'pointer'
                    }}
                    className="hover-white"
                  >
                    <MoreHorizontal size={14} />
                  </button>

                  {activeMenuId === session.id && (
                    <div style={{
                      position: 'absolute',
                      right: '0',
                      top: '28px',
                      zIndex: 100,
                      background: '#18181b',
                      border: '1px solid rgba(255,255,255,0.08)',
                      borderRadius: '8px',
                      padding: '4px',
                      width: '100px',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '2px',
                      boxShadow: '0 4px 12px rgba(0, 0, 0, 0.4)',
                    }}>
                      <button
                        title="Rename chat"
                        onClick={(event) => {
                          event.stopPropagation();
                          setEditingId(session.id);
                          setEditTitle(cleanUserMessage(session.title) || 'New Chat');
                          setActiveMenuId(null);
                        }}
                        style={{
                          width: '100%',
                          display: 'flex',
                          alignItems: 'center',
                          gap: '6px',
                          background: 'transparent',
                          border: 'none',
                          borderRadius: '6px',
                          padding: '6px 8px',
                          color: '#d4d4d8',
                          fontSize: '0.72rem',
                          cursor: 'pointer',
                          textAlign: 'left',
                        }}
                        className="hover-menu-item"
                      >
                        <Edit2 size={11} />
                        <span>Rename</span>
                      </button>
                      <button
                        title={session.id === 'default' ? 'Clear chat history' : 'Delete chat'}
                        onClick={(event) => {
                          event.stopPropagation();
                          deleteSession(session.id);
                          setActiveMenuId(null);
                        }}
                        style={{
                          width: '100%',
                          display: 'flex',
                          alignItems: 'center',
                          gap: '6px',
                          background: 'transparent',
                          border: 'none',
                          borderRadius: '6px',
                          padding: '6px 8px',
                          color: '#f87171',
                          fontSize: '0.72rem',
                          cursor: 'pointer',
                          textAlign: 'left',
                        }}
                        className="hover-menu-item-delete"
                      >
                        <Trash2 size={11} />
                        <span>Delete</span>
                      </button>
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
      </div>



      <div className="footer-section" style={{ padding: '10px 0', borderTop: '1px solid var(--border-dim)', marginTop: 'auto' }}>
        <div
          className={`nav-item ${settingsOpen ? 'active' : ''}`}
          onClick={() => setSettingsOpen(true)}
          style={{
            background: 'rgba(255,255,255,0.02)',
            borderRadius: '12px',
            border: '1px solid var(--border-dim)',
            padding: '8px 10px',
            display: 'flex',
            alignItems: 'center',
          }}
        >
          <div style={{
            width: '36px',
            height: '36px',
            borderRadius: '10px',
            background: '#40b5d0',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#fff',
            fontWeight: 800,
            fontSize: '1.15rem',
            boxShadow: '0 2px 8px rgba(64, 181, 208, 0.2)',
            flexShrink: 0,
          }}>
            {operatorName.charAt(0).toUpperCase() || 'H'}
          </div>
          <div style={{ display: sidebarVisible ? 'flex' : 'none', flexDirection: 'column', marginLeft: '10px', alignItems: 'flex-start', gap: '3px' }}>
            <span style={{ fontSize: '0.85rem', fontWeight: 700, color: '#fff', letterSpacing: '0.2px', lineHeight: 1.2 }}>
              {operatorName}
            </span>
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: '4px',
              background: '#fef3c7',
              padding: '2px 8px',
              borderRadius: '6px',
              fontSize: '0.72rem',
              fontWeight: 700,
              color: '#b45309',
              lineHeight: 1,
            }}>
              <span style={{ color: '#d97706', fontSize: '0.75rem', display: 'inline-flex', alignItems: 'center' }}>✨</span>
              <span>0</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
