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
  onOpenSettings?: () => void;
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
  onOpenSettings,
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
          fontSize: '1.1rem',
          fontWeight: 800,
          letterSpacing: '4px',
          marginBottom: '22px',
          whiteSpace: 'nowrap',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: '12px',
          cursor: 'pointer',
          color: '#f4f4f5',
        }}
      >
        {showLogoMark && (
          <span style={{ fontSize: '1rem', color: '#f59e0b', display: 'inline-flex', width: '28px', height: '28px', alignItems: 'center', justifyContent: 'center', borderRadius: '8px', background: '#15161a', border: '1px solid #262830' }}>
            {brandMark}
          </span>
        )}
        <span>{(brandName.trim() || 'NEXUS').toUpperCase()}</span>
      </div>

      <button className="lemon-new-btn" onClick={newChat} title="Create new session">
        <span style={{ fontSize: '1.25rem', fontWeight: 600, display: 'inline-flex', alignItems: 'center' }}>+</span>
        <span style={{ marginTop: '-1px' }}>New</span>
      </button>

      <style>{`
            :root { --accent-cyan: #22d3ee; --bg-deep: #050505; }
            
            .lemon-new-btn {
              display: flex;
              align-items: center;
              justify-content: center;
              gap: 8px;
              width: calc(100% - 30px);
              margin: 0 15px 20px 15px;
              padding: 12px 14px;
              background-color: #18191d;
              border: 1px solid #2a2c34;
              border-radius: 12px;
              color: #f4f4f5;
              font-size: 0.92rem;
              font-weight: 700;
              cursor: pointer;
              transition: all 0.15s ease-in-out;
            }
            .lemon-new-btn:hover {
              background-color: #1d1f24;
              border-color: #3a3d46;
            }
            .lemon-new-btn:active {
              transform: translateY(1px);
            }
            .hover-menu-item:hover {
              background-color: #27272a !important;
              color: #fff !important;
            }
            .hover-menu-item-delete:hover {
              background-color: #3f1515 !important;
              color: #f87171 !important;
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
            style={{ width: '100%', background: '#15161a', border: '1px solid #262830', borderRadius: '10px', padding: '10px 12px 10px 30px', color: '#e4e4e7', fontSize: '0.8rem', outline: 'none' }}
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
                padding: '8px 10px 8px 12px',
                borderRadius: '10px',
                fontSize: '0.8rem',
                color: currentSessionId === session.id ? '#fff' : '#a1a1aa',
                background: currentSessionId === session.id ? '#17191f' : 'transparent',
                border: currentSessionId === session.id ? '1px solid #2e3340' : '1px solid transparent',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                transition: 'all 0.15s',
                fontWeight: currentSessionId === session.id ? 600 : 400,
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
                      background: 'transparent',
                      border: 'none',
                      borderRadius: '4px',
                      color: '#a1a1aa',
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
                      border: '1px solid #2a2c34',
                      borderRadius: '10px',
                      padding: '4px',
                      width: '100px',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '2px',
                      boxShadow: '0 4px 12px rgba(0, 0, 0, 0.5)',
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
        <button
          type="button"
          className={`nav-item hover-white ${settingsOpen ? 'active' : ''}`}
          aria-label="Open admin settings"
          onClick={(event) => {
            event.preventDefault();
            event.stopPropagation();
            if (onOpenSettings) {
              onOpenSettings();
              return;
            }
            setSettingsOpen(true);
            setActiveTab('session');
          }}
          style={{
            background: 'transparent',
            borderRadius: '6px',
            border: '1px solid transparent',
            padding: '8px 10px',
            display: 'flex',
            alignItems: 'center',
            width: '100%',
            textAlign: 'left',
            cursor: 'pointer',
            position: 'relative',
            zIndex: 2,
            transition: 'background 0.15s'
          }}
        >
          <div style={{
            width: '32px',
            height: '32px',
            borderRadius: '50%',
            background: '#17191f',
            border: '1px solid #2e3340',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#e4e4e7',
            fontWeight: 600,
            fontSize: '0.9rem',
            flexShrink: 0,
          }}>
            {operatorName.charAt(0).toUpperCase() || 'H'}
          </div>
          <div style={{ display: sidebarVisible ? 'flex' : 'none', flexDirection: 'column', marginLeft: '12px', alignItems: 'flex-start', gap: '2px' }}>
            <span style={{ fontSize: '0.85rem', fontWeight: 500, color: '#e4e4e7' }}>
              {operatorName}
            </span>
            <span style={{ fontSize: '0.7rem', color: '#a1a1aa' }}>
              Operator
            </span>
          </div>
        </button>
      </div>
    </div>
  );
}
