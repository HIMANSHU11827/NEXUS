import React, { useState, useEffect, useRef } from 'react'
import HolisticVision from './HolisticVision'
import {
   Menu, Search, Edit2, Trash2, X, Eye, EyeOff, PlusCircle,
   Shield, Cpu, Activity, Clock, User, Palette, Settings2,
   Monitor, Bell, ShieldAlert, Mic, LayoutDashboard,
   Database, GraduationCap, Wrench, BrainCircuit, HeartPulse, Send, ChevronDown
} from 'lucide-react'

interface NexusState {
   hive: { id: string; persona: string; status: string; finished?: string }[];
   skills: { name: string; description: string }[];
   tools: { name: string; description: string }[];
   providers: { name: string; status: string; description: string }[];
   provider_instances: { id: string; parent: string; model: string; api_key?: string }[];
   mcp: { connected: number; total: number; servers?: any[] };
   health: { cpu: string; ram: string; status: string };
   session: { active: boolean; turns: number };
   reminders: { text: string; time: string }[];
   audit?: {
      unified_graph?: { nodes: number; edges: number; by_source?: Record<string, number>; by_kind?: Record<string, number> };
      roadmap?: { total: number; counts: Record<string, number>; completion_ratio: number; remaining_top?: any[] };
      evidence?: { total: number; by_status: Record<string, number>; unsupported_claims?: any[] };
      mission_replay?: any[];
      tool_economy?: any[];
   };
}

function App() {
   const [activeTab, setActiveTab] = useState('session');
   const [sidebarVisible, setSidebarVisible] = useState(true);
   const [settingsOpen, setSettingsOpen] = useState(false);
   const [settingsTab, setSettingsTab] = useState('profile');
   const [accentColor, setAccentColor] = useState('#3b82f6');
   const [operatorName, setOperatorName] = useState('Admin Operator');
   const [interfaceMode, setInterfaceMode] = useState('dark'); // dark, light, grey, night, white
   const [drawerType, setDrawerType] = useState<'none' | 'hive' | 'reminders' | 'health'>('none');
   const [currentSessionId, setCurrentSessionId] = useState('default');
   const [sessionList, setSessionList] = useState<{id: string, title: string}[]>([]);
   const [historySearch, setHistorySearch] = useState('');
   const [editingId, setEditingId] = useState<number | null>(null);
   const [editTitle, setEditTitle] = useState('');
   const [inputValue, setInputValue] = useState('');
   const [state, setState] = useState<NexusState | null>(null);
   const [loading, setLoading] = useState(true);
   const [backendOffline, setBackendOffline] = useState(false);
   const [messages, setMessages] = useState<{ role: string, content: string }[]>([]);
   const [isStreaming, setIsStreaming] = useState(false);
   const [expandedBlocks, setExpandedBlocks] = useState<Set<string>>(new Set());
   const [copiedMsgId, setCopiedMsgId] = useState<number | null>(null);
   const [hoveredMsgId, setHoveredMsgId] = useState<number | null>(null);
   const messagesEndRef = useRef<HTMLDivElement>(null);

   useEffect(() => {
      messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
   }, [messages, isStreaming]);

   const handleSend = async () => {
      if (!inputValue.trim() && uploadedFiles.length === 0) return;

      const prompt = inputValue;
      const userMsg = { role: 'user', content: prompt };
      setMessages(prev => [...prev, userMsg]);
      setInputValue('');
      setIsStreaming(true);

      try {
         // 1. Handle File Uploads
         if (uploadedFiles.length > 0) {
            const formData = new FormData();
            uploadedFiles.forEach(file => formData.append('files', file));
            
            await fetch('/api/upload', {
               method: 'POST',
               body: formData
            });
            setUploadedFiles([]); // Clear after upload
         }

         // 2. Send Chat Request
         const response = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
               prompt,
               session_id: currentSessionId,
               provider: selectedSessionProvider || instanceName || 'openrouter'
            })
         });

         if (!response.body) return;
         const reader = response.body.getReader();
         const decoder = new TextDecoder();

         let assistantContent = '';
         setMessages(prev => [...prev, { role: 'assistant', content: '' }]);

         while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            const chunk = decoder.decode(value);
            assistantContent += chunk;

            setMessages(prev => {
               const newMsgs = [...prev];
               newMsgs[newMsgs.length - 1] = { role: 'assistant', content: assistantContent };
               return newMsgs;
            });
         }
      } catch (err) {
         console.error("Chat error:", err);
         setMessages(prev => [...prev, { role: 'assistant', content: 'SYSTEM_ERROR: Connection to NEXUS brain lost.' }]);
      } finally {
         setIsStreaming(false);
         fetchSessions(); // Refresh list to update titles/mtime
      }
   };

   const handleNewChat = async () => {
       try {
           const res = await fetch('/api/sessions/new', { method: 'POST' });
           const data = await res.json();
           setCurrentSessionId(data.id);
           setMessages([]);
           setInputValue('');
           setActiveTab('session');
           fetchSessions();
       } catch (err) {
           console.error("New chat error:", err);
       }
   };

    const loadSession = async (id: string) => {
        try {
            const res = await fetch('/api/sessions/load', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ id })
            });
            const data = await res.json();
            if (data.status === 'success') {
                setCurrentSessionId(data.id);
                setMessages(data.history || []);
                setActiveTab('session');
                setInputValue('');
            }
        } catch (err) {
            console.error("Load session error:", err);
        }
    };

    const deleteSession = async (id: string) => {
        setConfirmModal({
           show: true,
           title: "PURGE SESSION",
           message: "Are you sure you want to permanently erase this session from memory?",
           onConfirm: async () => {
              try {
                  const res = await fetch(`/api/sessions/${id}`, { method: 'DELETE' });
                  if (res.ok) {
                      if (currentSessionId === id) {
                          setMessages([]);
                          setCurrentSessionId('default');
                      }
                      fetchSessions();
                  }
              } catch (err) { console.error("Delete session error:", err); }
              setConfirmModal(null);
           }
        });
    };

    const renameSession = async (id: string, title: string) => {
        try {
            await fetch('/api/sessions/rename', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ id, title })
            });
            setEditingId(null);
            fetchSessions();
        } catch (err) { console.error("Rename session error:", err); }
    };

   // MCP Registration State
   const [showAddMcpModal, setShowAddMcpModal] = useState(false);
   const [newMcpName, setNewMcpName] = useState('');
   const [newMcpConfig, setNewMcpConfig] = useState('{\n  \n}');

   const [showProviderPanel, setShowProviderPanel] = useState(false);
   const [selectedProv, setSelectedProv] = useState<any>(null);
   const [instanceName, setInstanceName] = useState('');
   const [apiKey, setApiKey] = useState('');
   const [targetModel, setTargetModel] = useState('');
   const [showApiKey, setShowApiKey] = useState(false);
   const [editingInstanceId, setEditingInstanceId] = useState<string | null>(null);

   const [uploadedFiles, setUploadedFiles] = useState<File[]>([]);
   const [selectedSessionProvider, setSelectedSessionProvider] = useState<string>('openrouter');
   const [isDragging, setIsDragging] = useState(false);
   const [showModelMenu, setShowModelMenu] = useState(false);
   const modelMenuRef = useRef<HTMLDivElement>(null);
   const [confirmModal, setConfirmModal] = useState<{ show: boolean, title: string, message: string, onConfirm: () => void } | null>(null);

   useEffect(() => {
      function handleClickOutside(event: MouseEvent) {
         if (modelMenuRef.current && !modelMenuRef.current.contains(event.target as Node)) {
            setShowModelMenu(false);
         }
      }
      document.addEventListener("mousedown", handleClickOutside);
      return () => document.removeEventListener("mousedown", handleClickOutside);
   }, []);

   async function fetchHistory() {
      try {
         const res = await fetch('/api/history');
         const data = await res.json();
         if (Array.isArray(data)) {
            setMessages(data);
         }
      } catch (err) {
         console.error("Failed to fetch history:", err);
      }
   }

   async function fetchSessions() {
      try {
         const res = await fetch('http://127.0.0.1:8000/api/sessions');
         const data = await res.json();
         if (Array.isArray(data)) {
            setSessionList(data);
         }
      } catch (err) {
         console.error("Failed to fetch sessions:", err);
      }
   }

   useEffect(() => {
      const fetchData = async () => {
         try {
            const res = await fetch('/api/state', { signal: AbortSignal.timeout(8000) });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            setState(data);
            setBackendOffline(false);
            setLoading(false);
         } catch (err) {
            console.error("Failed to fetch state:", err);
            setBackendOffline(true);
            setLoading(false);
         }
      };

      fetchData();
      fetchHistory();
      fetchSessions();
      const interval = setInterval(fetchData, 3000);
      return () => clearInterval(interval);
   }, []);


   const navItems = [
      { id: 'session', label: 'Dashboard', icon: <LayoutDashboard size={18} /> },
      { id: 'hive', label: 'Hive', icon: <Activity size={18} /> },
      { id: 'mcp', label: 'MCP', icon: <Database size={18} /> },
      { id: 'audit', label: 'Audit', icon: <ShieldAlert size={18} /> },
      { id: 'skills', label: 'Skills', icon: <GraduationCap size={18} /> },
      { id: 'tools', label: 'Tools', icon: <Wrench size={18} /> },
      { id: 'providers', label: 'Providers', icon: <BrainCircuit size={18} /> },
      { id: 'reminders', label: 'Reminders', icon: <Bell size={18} /> },
      { id: 'vision', label: 'Vision', icon: <Eye size={18} /> },
      { id: 'health', label: 'Health', icon: <HeartPulse size={18} /> }
   ];

   if (loading) return (
      <div style={{ width: '100vw', height: '100vh', background: '#0f0f0f', color: '#3b82f6', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', fontFamily: 'monospace', gap: '20px' }}>
         <div className="spinner" style={{ width: '40px', height: '40px', border: '4px solid #111', borderTopColor: '#3b82f6', borderRadius: '50%', animation: 'spin 1s linear infinite' }}></div>
         [ SOVEREIGN_SYNCHRONIZING ]
         <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      </div>
   );

   if (backendOffline || !state) return (
      <div style={{ width: '100vw', height: '100vh', background: '#0a0a0a', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', fontFamily: 'monospace', gap: '18px' }}>
         <div style={{ fontSize: '2.5rem' }}>⚠️</div>
         <div style={{ fontSize: '1rem', fontWeight: 900, color: '#f87171', letterSpacing: '3px' }}>BACKEND OFFLINE</div>
         <div style={{ fontSize: '0.72rem', color: '#444', maxWidth: '380px', textAlign: 'center', lineHeight: 1.8 }}>
            Cannot reach <span style={{ color: '#3b82f6' }}>/api/state</span>.<br/>
            Start the FastAPI server:<br/>
            <span style={{ color: '#4ade80', fontSize: '0.65rem' }}>python -m uvicorn dashboard.api:app --port 8000</span>
         </div>
         <div style={{ fontSize: '0.62rem', color: '#333', marginTop: '4px' }}>Auto-retrying every 3 s…</div>
         <div style={{ width: '6px', height: '6px', borderRadius: '50%', background: '#f87171', animation: 'blink 1.5s infinite' }} />
         <style>{`
            @keyframes spin  { to { transform: rotate(360deg); } }
            @keyframes blink { 0%,100%{opacity:1} 50%{opacity:0.2} }
         `}</style>
      </div>
   );

   const cpuVal = parseInt(state.health?.cpu?.replace('%', '') || '0');
   const healthClass = cpuVal > 60 ? 'red' : 'green';

   return (
      <>
         <div className={`sidebar ${sidebarVisible ? '' : 'hidden'}`}>
            <div
               className="logo-section"
               onClick={() => setActiveTab('session')}
               style={{ 
                  fontSize: '1.25rem', 
                  fontWeight: 900,
                  letterSpacing: '2px',
                  color: '#fff', 
                  paddingBottom: '24px', 
                  whiteSpace: 'nowrap', 
                  display: 'flex', 
                  justifyContent: 'space-between', 
                  cursor: 'pointer',
                  background: 'linear-gradient(to right, #fff, #666)',
                  WebkitBackgroundClip: 'text',
                  WebkitTextFillColor: 'transparent'
               }}
            >
               SOVEREIGN
            </div>

            <div className="nav-section" style={{ paddingBottom: '20px' }}>
               <div
                  className={`nav-item ${activeTab === 'session' ? 'active' : ''}`}
                  onClick={() => setActiveTab('session')}
                  style={{ display: 'flex', alignItems: 'center' }}
               >
                  <div style={{ color: activeTab === 'session' ? 'var(--accent-blue)' : '#555' }}>
                     <style>{`
                  :root { --accent-cyan: #22d3ee; --bg-deep: #050505; }
                  @keyframes pulse { 0% { opacity: 0.6; transform: scale(0.98); } 50% { opacity: 1; transform: scale(1); } 100% { opacity: 0.6; transform: scale(0.98); } }
                  @keyframes glow { 0% { box-shadow: 0 0 5px rgba(59, 130, 246, 0.2); } 50% { box-shadow: 0 0 15px rgba(59, 130, 246, 0.5); } 100% { box-shadow: 0 0 5px rgba(59, 130, 246, 0.2); } }
                  @keyframes slideIn { from { transform: translateY(10px); opacity: 0; } to { transform: translateY(0); opacity: 1; } }
                `}</style>
                     <LayoutDashboard size={18} />
                  </div>
                  <span style={{ display: sidebarVisible ? 'inline' : 'none', marginLeft: '12px' }}>Dashboard</span>
               </div>
            </div>

            <div className="search-box" style={{ padding: '0 15px 15px 15px' }}>
               <div style={{ position: 'relative' }}>
                  <Search size={14} style={{ position: 'absolute', left: '10px', top: '50%', transform: 'translateY(-50%)', color: '#555' }} />
                  <input
                     type="text"
                     placeholder="Search history..."
                     value={historySearch}
                     onChange={(e) => setHistorySearch(e.target.value)}
                     style={{ width: '100%', background: '#1e1e1e', border: '1px solid rgba(255,255,255,0.05)', borderRadius: '6px', padding: '8px 10px 8px 30px', color: '#fff', fontSize: '0.8rem', outline: 'none' }}
                  />
               </div>
            </div>

            <div className="history-section" style={{ flex: 1, padding: '0 10px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                {sessionList
                  .filter(s => s.title.toLowerCase().includes(historySearch.toLowerCase()))
                  .map((s) => (
                    <div 
                      key={s.id} 
                      onMouseEnter={() => setHoveredMsgId(s.id as any)}
                      onMouseLeave={() => setHoveredMsgId(null)}
                      style={{
                        padding: '8px 12px',
                        borderRadius: '10px',
                        fontSize: '0.75rem',
                        color: currentSessionId === s.id ? '#fff' : 'rgba(255,255,255,0.4)',
                        background: currentSessionId === s.id ? 'rgba(59, 130, 246, 0.08)' : 'transparent',
                        border: currentSessionId === s.id ? '1px solid rgba(59, 130, 246, 0.15)' : '1px solid transparent',
                        cursor: 'pointer',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        transition: 'all 0.2s',
                        fontWeight: currentSessionId === s.id ? 700 : 400
                      }}
                      onClick={() => loadSession(s.id)}
                    >
                      {editingId === s.id as any ? (
                        <input 
                           autoFocus
                           value={editTitle}
                           onChange={(e) => setEditTitle(e.target.value)}
                           onBlur={() => renameSession(s.id, editTitle)}
                           onKeyDown={(e) => e.key === 'Enter' && renameSession(s.id, editTitle)}
                           style={{ width: '100%', background: 'transparent', border: 'none', color: '#fff', fontSize: '0.75rem', outline: 'none' }}
                        />
                      ) : (
                        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>
                           {s.title || 'New Chat'}
                        </span>
                      )}
                      
                      <div style={{ display: 'flex', gap: '5px', opacity: hoveredMsgId === s.id as any ? 1 : 0, transition: 'opacity 0.2s' }}>
                         <Edit2 size={12} onClick={(e) => { e.stopPropagation(); setEditingId(s.id as any); setEditTitle(s.title); }} style={{ color: '#555' }} className="hover-white" />
                         <Trash2 size={12} onClick={(e) => { e.stopPropagation(); deleteSession(s.id); }} style={{ color: '#555' }} className="hover-white" />
                      </div>
                    </div>
                  ))}
            </div>

            <div className="nav-section" style={{ borderTop: '1px solid rgba(255,255,255,0.05)', padding: '15px 10px' }}>
               <div style={{ fontSize: '0.65rem', color: '#555', paddingBottom: '10px', textTransform: 'uppercase', letterSpacing: '1px', fontWeight: '700' }}>Operational Nodes</div>
               <div className="nav-grid">
                  {navItems.filter(i => ['mcp', 'audit', 'skills', 'tools', 'providers', 'vision'].includes(i.id)).map(item => (
                     <div
                        key={item.id}
                        className={`nav-grid-item ${activeTab === item.id ? 'active' : ''}`}
                        onClick={() => setActiveTab(activeTab === item.id ? 'session' : item.id)}
                     >
                        <div style={{ color: activeTab === item.id ? 'var(--accent-blue)' : '#555', transition: 'all 0.2s', display: 'flex', alignItems: 'center' }}>
                           {item.icon}
                        </div>
                        <span style={{ fontSize: '0.6rem', marginTop: '5px', textAlign: 'center' }}>{item.label}</span>
                     </div>
                  ))}
               </div>
            </div>

            <div className="footer-section" style={{ padding: '20px 0', borderTop: '1px solid var(--border-dim)', marginTop: 'auto' }}>
               <div
                  className={`nav-item ${settingsOpen ? 'active' : ''}`}
                  onClick={() => setSettingsOpen(true)}
                  style={{ 
                     background: 'rgba(255,255,255,0.02)', 
                     borderRadius: '16px', 
                     border: '1px solid var(--border-dim)',
                     padding: '12px'
                  }}
               >
                  <div style={{ 
                     width: '36px', 
                     height: '36px', 
                     borderRadius: '12px', 
                     background: 'linear-gradient(135deg, var(--accent-blue), var(--accent-indigo))', 
                     display: 'flex', 
                     alignItems: 'center', 
                     justifyContent: 'center', 
                     color: '#fff',
                     boxShadow: '0 4px 12px rgba(59, 130, 246, 0.3)'
                  }}>
                     <User size={20} />
                  </div>
                  <div style={{ display: sidebarVisible ? 'flex' : 'none', flexDirection: 'column', marginLeft: '12px' }}>
                     <span style={{ fontSize: '0.85rem', fontWeight: 800, color: '#fff', letterSpacing: '0.5px' }}>{operatorName.toUpperCase()}</span>
                     <span style={{ fontSize: '0.6rem', color: 'var(--text-muted)', letterSpacing: '1.5px', fontWeight: 600 }}>SYSTEM OPERATOR</span>
                  </div>
               </div>
            </div>
         </div>

         <div className="main-content">
            {/* FIXED NAVIGATION CONTROLS */}
            <div style={{ position: 'fixed', top: 25, left: sidebarVisible ? 220 : 25, display: 'flex', gap: '10px', zIndex: 5000, transition: 'left 0.4s cubic-bezier(0.4, 0, 0.2, 1)' }}>
               <button
                  className="toggle-sidebar-btn"
                  style={{ position: 'static', width: '42px', height: '42px', background: 'rgba(10,10,10,0.8)', backdropFilter: 'blur(10px)', border: '1px solid rgba(255,255,255,0.1)' }}
                  onClick={() => setSidebarVisible(!sidebarVisible)}
               >
                  <Menu size={20} />
               </button>
               <button
                  className="toggle-sidebar-btn"
                  style={{ position: 'static', width: sidebarVisible ? '42px' : 'auto', height: '42px', padding: sidebarVisible ? '0' : '0 15px', background: 'rgba(59, 130, 246, 0.1)', color: 'var(--accent-blue)', border: '1px solid rgba(59, 130, 246, 0.2)', backdropFilter: 'blur(10px)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
                  onClick={handleNewChat}
               >
                  <PlusCircle size={20} />
                  {!sidebarVisible && (
                     <span style={{ fontSize: '0.65rem', fontWeight: 800, marginLeft: '10px', letterSpacing: '1.5px', whiteSpace: 'nowrap' }}>NEW CHAT</span>
                  )}
               </button>
            </div>

            <div className="header-minimal">
               <div className={`status-indicator clickable-indicator ${healthClass}`} onClick={() => setDrawerType(drawerType === 'health' ? 'none' : 'health')}>
                  HEALTH
               </div>
               <div className="status-indicator clickable-indicator"
                  style={{
                     background: (state.hive?.length || 0) > 0 ? 'rgba(34, 197, 94, 0.1)' : 'rgba(239, 68, 68, 0.1)',
                     color: (state.hive?.length || 0) > 0 ? '#4ade80' : '#f87171'
                  }}
                  onClick={() => setDrawerType(drawerType === 'hive' ? 'none' : 'hive')}>
                  HIVE: {state.hive?.length || 0}
               </div>
               <div className="status-indicator clickable-indicator"
                  style={{ background: 'rgba(251, 191, 36, 0.1)', color: '#fbbf24' }}
                  onClick={() => setDrawerType(drawerType === 'reminders' ? 'none' : 'reminders')}>
                  REMINDERS: {state.reminders?.length || 0}
               </div>
            </div>

            {/* DETAILS DRAWER */}
            <div className={`details-drawer ${drawerType !== 'none' ? 'open' : ''}`}>
               <div className="drawer-header">
                  <span>{drawerType.toUpperCase()} INTELLIGENCE</span>
                  <X size={18} style={{ cursor: 'pointer' }} onClick={() => setDrawerType('none')} />
               </div>

               <div className="drawer-content">
                  {drawerType === 'hive' && (
                     <div style={{ display: 'flex', flexDirection: 'column', gap: '15px' }}>
                        {state.hive && state.hive.length > 0 ? state.hive.map((a, i) => (
                           <div key={i} className="drawer-item" style={{ background: 'rgba(255,255,255,0.02)', padding: '15px', borderRadius: '12px', border: '1px solid rgba(255,255,255,0.05)' }}>
                              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '5px' }}>
                                 <span style={{ fontSize: '0.8rem', fontWeight: 800, color: '#fff' }}>{a.persona} Node</span>
                                 <span style={{ fontSize: '0.6rem', background: a.status === 'idle' ? 'rgba(74, 222, 128, 0.1)' : 'rgba(59, 130, 246, 0.1)', color: a.status === 'idle' ? '#4ade80' : '#3b82f6', padding: '2px 8px', borderRadius: '10px', textTransform: 'uppercase' }}>{a.status}</span>
                              </div>
                              <div style={{ fontSize: '0.7rem', color: '#555', fontFamily: 'monospace' }}>{a.id}</div>
                           </div>
                        )) : (
                           <div style={{ textAlign: 'center', padding: '40px 20px', color: '#333', fontSize: '0.75rem' }}>No active hive entities detected.</div>
                        )}
                     </div>
                  )}

                  {drawerType === 'health' && (
                     <div style={{ display: 'flex', flexDirection: 'column', gap: '15px' }}>
                        <div className="drawer-item" style={{ background: 'rgba(255,255,255,0.02)', padding: '20px', borderRadius: '12px', border: '1px solid rgba(255,255,255,0.05)', display: 'flex', alignItems: 'center', gap: '15px' }}>
                           <Cpu size={20} color="var(--accent-blue)" />
                           <div>
                              <div style={{ fontSize: '0.8rem', fontWeight: 800, color: '#fff' }}>CPU LOAD</div>
                              <div style={{ fontSize: '0.75rem', color: '#4ade80', marginTop: '4px' }}>{state.health?.cpu} - OPTIMIZED</div>
                           </div>
                        </div>
                        <div className="drawer-item" style={{ background: 'rgba(255,255,255,0.02)', padding: '20px', borderRadius: '12px', border: '1px solid rgba(255,255,255,0.05)', display: 'flex', alignItems: 'center', gap: '15px' }}>
                           <Activity size={20} color="var(--accent-blue)" />
                           <div>
                              <div style={{ fontSize: '0.8rem', fontWeight: 800, color: '#fff' }}>MEMORY MESH</div>
                              <div style={{ fontSize: '0.75rem', color: '#4ade80', marginTop: '4px' }}>{state.health?.ram} - SECURE</div>
                           </div>
                        </div>
                        <div className="drawer-item" style={{ background: 'rgba(255,255,255,0.02)', padding: '20px', borderRadius: '12px', border: '1px solid rgba(255,255,255,0.05)', display: 'flex', alignItems: 'center', gap: '15px' }}>
                           <Shield size={20} color="#4ade80" />
                           <div>
                              <div style={{ fontSize: '0.8rem', fontWeight: 800, color: '#fff' }}>SYSTEM STATUS</div>
                              <div style={{ fontSize: '0.75rem', color: '#4ade80', marginTop: '4px' }}>{state.health?.status || 'STABLE'}</div>
                           </div>
                        </div>
                     </div>
                  )}

                  {drawerType === 'reminders' && (
                     <div style={{ display: 'flex', flexDirection: 'column', gap: '15px' }}>
                        {state.reminders && state.reminders.length > 0 ? state.reminders.map((r, i) => (
                           <div key={i} className="drawer-item" style={{ background: 'rgba(251, 191, 36, 0.05)', padding: '15px', borderRadius: '12px', border: '1px solid rgba(251, 191, 36, 0.1)', display: 'flex', gap: '15px', alignItems: 'start' }}>
                              <Clock size={16} color="#fbbf24" style={{ marginTop: '2px' }} />
                              <div>
                                 <div style={{ fontSize: '0.8rem', fontWeight: 700, color: '#fff' }}>{r.text}</div>
                                 <div style={{ fontSize: '0.65rem', color: '#fbbf24', marginTop: '5px', opacity: 0.7 }}>{r.time}</div>
                              </div>
                           </div>
                        )) : (
                           <div style={{ textAlign: 'center', padding: '40px 20px', color: '#333', fontSize: '0.75rem' }}>Zero cognitive pendings.</div>
                        )}
                     </div>
                  )}
               </div>
            </div>

            {activeTab === 'session' ? (
               <div style={{ display: 'flex', flexDirection: 'column', width: '100%', height: '100%', alignItems: 'center', justifyContent: messages.length === 0 ? 'center' : 'flex-start', overflow: 'hidden' }}>
                  {messages.length === 0 ? (
                     <h1 className="hero-text" style={{ fontSize: '3.5rem', fontWeight: 900, letterSpacing: '-2px', marginBottom: '40px', background: 'linear-gradient(to bottom, #fff, #555)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>SOVEREIGN AI</h1>
                  ) : (
                     <div className="messages-container" style={{ flex: 1, width: '100%', maxWidth: '800px', display: 'flex', flexDirection: 'column', gap: '16px', padding: '100px 15px 140px 15px', overflowY: 'auto', scrollbarWidth: 'none' }}>
                        {messages.map((m, i) => {
                           const isUser = m.role === 'user';

                           const toggleBlock = (key: string) => {
                              setExpandedBlocks(prev => {
                                 const next = new Set(prev);
                                 if (next.has(key)) next.delete(key);
                  else next.add(key);
                                 return next;
                              });
                           };

                           const getCleanText = (text: string) => {
                              return text.split('\n')
                                 .filter(line => {
                                    const trim = line.trim();
                                    const markerMatch = trim.match(/^\[(THINKING|TOOL|SKILL|MCP|HIVE|SYSTEM|Executing|Wait|Hive|TODO|FILE|BASH)[^\]]*\](.*)/i);
                                    if (markerMatch && markerMatch[2].trim()) return true;
                                    if (markerMatch) return false;
                                    const jsonKeys = ['"command":', '"params":', '"path":', '"action":', '"summary":', '"old":', '"new":', '"arguments":', '"intent":', '"brain":', '"error":', '"message":', '"type":'];
                                    const codeKeys = ['def ', 'self.', 'import ', 'class ', 'return ', 'try:', 'except ', 'def:'];
                                    const isTrash = trim.startsWith('{') || trim.startsWith('}') || trim.startsWith(']') || trim.startsWith('],') || trim.startsWith('```json') || trim.startsWith('```') || trim.includes('": "') || trim.includes('": {') || jsonKeys.some(key => trim.includes(key)) || codeKeys.some(key => trim.startsWith(key));
                                    return !isTrash && trim !== '';
                                 })
                                 .map(line => {
                                    const trim = line.trim();
                                    const markerMatch = trim.match(/^\[(THINKING|TOOL|SKILL|MCP|HIVE|SYSTEM|Executing|Wait|Hive|TODO|FILE|BASH)[^\]]*\](.*)/i);
                                    return markerMatch ? markerMatch[2].trim() : line;
                                 })
                                 .join('\n');
                           };

                           const renderContent = (content: string, msgIndex: number) => {
                              const lines = content.split('\n');
                              const rendered: React.ReactNode[] = [];
                              let processBuffer: string[] = [];
                              let blockCounter = 0;

                              const flushBuffer = (key: string) => {
                                 if (processBuffer.length === 0) return;
                                 const bufferCopy = [...processBuffer];
                                 const isExpanded = expandedBlocks.has(key);

                                 rendered.push(
                                    <div key={key} style={{ marginTop: '12px', marginBottom: '8px', animation: 'slideIn 0.3s ease-out' }}>
                                       <div
                                          onClick={() => toggleBlock(key)}
                                          style={{
                                             fontSize: '0.62rem',
                                             fontWeight: 800,
                                             color: isExpanded ? '#fff' : '#3b82f6',
                                             background: isExpanded ? '#3b82f6' : 'rgba(59, 130, 246, 0.04)',
                                             border: '1px solid rgba(59, 130, 246, 0.15)',
                                             padding: '5px 12px',
                                             borderRadius: '6px',
                                             display: 'inline-flex',
                                             alignItems: 'center',
                                             gap: '8px',
                                             cursor: 'pointer',
                                             letterSpacing: '1px',
                                             textTransform: 'uppercase',
                                             fontFamily: '"JetBrains Mono", monospace',
                                             transition: 'all 0.2s cubic-bezier(0.4, 0, 0.2, 1)',
                                             backdropFilter: 'blur(10px)'
                                          }}>
                                          <div style={{ width: '6px', height: '6px', borderRadius: '50%', background: isExpanded ? '#fff' : '#3b82f6', animation: 'pulse 2s infinite' }}></div>
                                          {isExpanded ? 'DISMISS COGNITION' : `INSPECT PROCESS (${bufferCopy.length} UNITS)`}
                                       </div>
                                       {isExpanded && (
                                          <div style={{
                                             marginTop: '10px',
                                             background: 'rgba(255,255,255,0.02)',
                                             border: '1px solid rgba(255,255,255,0.04)',
                                             borderRadius: '12px',
                                             padding: '12px',
                                             fontSize: '0.72rem',
                                             fontFamily: '"JetBrains Mono", monospace',
                                             color: '#a1a1aa',
                                             overflowX: 'auto',
                                             animation: 'fadeIn 0.3s ease-out',
                                             lineHeight: '1.6'
                                          }}>
                                             {bufferCopy.map((l, idx) => (
                                                <div key={idx} style={{ marginBottom: '6px', whiteSpace: 'pre-wrap', borderLeft: '2px solid rgba(255,255,255,0.05)', paddingLeft: '12px' }}>{l}</div>
                                             ))}
                                          </div>
                                       )}
                                    </div>
                                 );
                                 processBuffer = [];
                              };

                              lines.forEach((line, idx) => {
                                 const trim = line.trim();

                                 // 🛡️ [MARKER PURGE]: BUG FIX — use [^\]]* to match any chars in tag (e.g. TURN 1, STEP 2)
                                 const markerMatch = trim.match(/^\[(THINKING|TOOL|SKILL|MCP|HIVE|SYSTEM|Executing|Wait|Hive|TODO|FILE|BASH)[^\]]*\](.*)/i);

                                 if (markerMatch) {
                                    const rest = markerMatch[2].trim();

                                    if (rest) {
                                       // Tag has inline content = this IS the actual response clean text.
                                       // Silently discard buffered internal process lines, show only the response.
                                       processBuffer = [];
                                       rendered.push(<div key={`l-${idx}`} style={{ marginTop: '10px', color: 'rgba(255,255,255,0.95)', lineHeight: '1.8', fontSize: '1.05rem' }}>{rest}</div>);
                                    } else {
                                       // Pure diagnostic marker (no response text after tag) — buffer silently
                                       processBuffer.push(line);
                                    }
                                    return;
                                 }

                                 // 🛡️ [JSON/CODE PURGE]: Enhanced trash filter
                                 // Note: startsWith('[') removed — valid bracketed lines are caught above by markerMatch
                                 const jsonKeys = ['"command":', '"params":', '"path":', '"action":', '"summary":', '"old":', '"new":', '"arguments":', '"intent":', '"brain":', '"error":', '"message":', '"type":'];
                                 const codeKeys = ['def ', 'self.', 'import ', 'class ', 'return ', 'try:', 'except ', 'def:'];
                                 const isTrash = trim.startsWith('{') || trim.startsWith('}') ||
                                    trim.startsWith(']') || trim.startsWith('],') ||
                                    trim.startsWith('```json') || trim.startsWith('```') ||
                                    trim.includes('": "') || trim.includes('": {') ||
                                    jsonKeys.some(key => trim.includes(key)) ||
                                    codeKeys.some(key => trim.startsWith(key));

                                 if (isTrash) {
                                    processBuffer.push(line);
                                 } else if (trim) {
                                    flushBuffer(`${msgIndex}-${blockCounter++}`);
                                    rendered.push(<div key={`l-${idx}`} style={{ marginTop: '10px', color: 'rgba(255,255,255,0.95)', lineHeight: '1.8', fontSize: '1.05rem' }}>{line}</div>);
                                 }
                              });

                              flushBuffer(`${msgIndex}-${blockCounter++}`);
                              return rendered;
                           };

                           return (
                               <div
                                  key={i}
                                  onMouseEnter={() => setHoveredMsgId(i)}
                                  onMouseLeave={() => setHoveredMsgId(null)}
                                  style={{ alignSelf: isUser ? 'flex-end' : 'flex-start', maxWidth: isUser ? '65%' : '85%', display: 'flex', flexDirection: 'column', gap: '4px', animation: 'fadeIn 0.5s cubic-bezier(0.16, 1, 0.3, 1)', marginBottom: '10px' }}
                               >
                                  {/* Bubble */}
                                  <div style={{
                                      background: isUser
                                         ? 'linear-gradient(135deg, rgba(59,130,246,0.12) 0%, rgba(59,130,246,0.05) 100%)'
                                         : 'rgba(255, 255, 255, 0.02)',
                                      borderTop: isUser ? '1px solid rgba(59,130,246,0.3)' : '1px solid rgba(255,255,255,0.08)',
                                      borderRight: isUser ? '1px solid rgba(59,130,246,0.3)' : '1px solid rgba(255,255,255,0.08)',
                                      borderBottom: isUser ? '1px solid rgba(59,130,246,0.3)' : '1px solid rgba(255,255,255,0.08)',
                                      borderLeft: isUser 
                                         ? '1px solid rgba(59,130,246,0.3)' 
                                         : '3px solid var(--accent-blue)',
                                      padding: isUser ? '8px 14px' : '12px 18px',
                                      borderRadius: isUser ? '20px 20px 4px 20px' : '4px 20px 20px 20px',
                                      color: isUser ? '#fff' : 'rgba(255,255,255,0.95)',
                                      fontSize: '0.88rem',
                                      lineHeight: '1.6',
                                      whiteSpace: 'pre-wrap',
                                      fontWeight: isUser ? 500 : 400,
                                      letterSpacing: '-0.01em',
                                      backdropFilter: 'blur(12px)',
                                      boxShadow: isUser
                                         ? '0 4px 15px -4px rgba(59,130,246,0.1)'
                                         : '0 4px 25px -10px rgba(0,0,0,0.5)',
                                      transition: 'all 0.3s cubic-bezier(0.4, 0, 0.2, 1)'
                                   }}>
                                      {isUser
                                         ? m.content
                                         : (m.content.trim() === '' && isStreaming && i === messages.length - 1)
                                            ? (
                                               <div style={{ display: 'flex', gap: '6px', alignItems: 'center', padding: '4px 0' }}>
                                                  <div style={{ width: '4px', height: '4px', borderRadius: '50%', background: 'var(--accent-blue)', animation: 'pulse 1s infinite 0.0s' }}/>
                                                  <div style={{ width: '4px', height: '4px', borderRadius: '50%', background: 'var(--accent-blue)', animation: 'pulse 1s infinite 0.2s' }}/>
                                                  <div style={{ width: '4px', height: '4px', borderRadius: '50%', background: 'var(--accent-blue)', animation: 'pulse 1s infinite 0.4s' }}/>
                                               </div>
                                            )
                                            : renderContent(m.content, i)
                                      }
                                   </div>

                                  {/* Footer: timestamp + copy */}
                                  <div style={{
                                     display: 'flex',
                                     alignItems: 'center',
                                     justifyContent: isUser ? 'flex-end' : 'flex-start',
                                     gap: '10px',
                                     paddingLeft: isUser ? '0' : '6px',
                                     paddingRight: isUser ? '6px' : '0',
                                     opacity: hoveredMsgId === i ? 1 : 0.3,
                                     transition: 'opacity 0.2s ease'
                                  }}>
                                     {m.content && (
                                        <div style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                                           <button title="Copy" onClick={() => { navigator.clipboard.writeText(isUser ? m.content : getCleanText(m.content)); setCopiedMsgId(i); setTimeout(() => setCopiedMsgId(null), 2000); }} style={{ background: copiedMsgId === i ? 'rgba(74,222,128,0.10)' : 'transparent', border: 'none', borderRadius: '6px', cursor: 'pointer', padding: '4px 6px', display: 'inline-flex', alignItems: 'center', color: copiedMsgId === i ? '#4ade80' : '#555', transition: 'all 0.2s', outline: 'none' }}>
                                              {copiedMsgId === i
                                                 ? <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3"><polyline points="20 6 9 17 4 12"/></svg>
                                                 : <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>
                                              }
                                           </button>
                                           {!isUser && <button title="Good response" style={{ background: 'transparent', border: 'none', borderRadius: '6px', cursor: 'pointer', padding: '4px 6px', display: 'inline-flex', alignItems: 'center', color: '#555', transition: 'color 0.2s', outline: 'none' }} onMouseEnter={e => (e.currentTarget.style.color='#4ade80')} onMouseLeave={e => (e.currentTarget.style.color='#555')}><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M14 9V5a3 3 0 00-3-3l-4 9v11h11.28a2 2 0 002-1.7l1.38-9a2 2 0 00-2-2.3H14z"/><path d="M7 22H4a2 2 0 01-2-2v-7a2 2 0 012-2h3"/></svg></button>}
                                           {!isUser && <button title="Bad response" style={{ background: 'transparent', border: 'none', borderRadius: '6px', cursor: 'pointer', padding: '4px 6px', display: 'inline-flex', alignItems: 'center', color: '#555', transition: 'color 0.2s', outline: 'none' }} onMouseEnter={e => (e.currentTarget.style.color='#f87171')} onMouseLeave={e => (e.currentTarget.style.color='#555')}><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M10 15v4a3 3 0 003 3l4-9V2H5.72a2 2 0 00-2 1.7l-1.38 9a2 2 0 002 2.3H10z"/><path d="M17 2h2.67A2.31 2.31 0 0122 4v7a2.31 2.31 0 01-2.33 2H17"/></svg></button>}
                                           {!isUser && !isStreaming && <button title="Regenerate" onClick={() => { const lastUser = [...messages].reverse().find(x => x.role==='user'); if(lastUser){ setMessages(prev => prev.slice(0,-1)); setInputValue(lastUser.content); setTimeout(handleSend, 50); } }} style={{ background: 'transparent', border: 'none', borderRadius: '6px', cursor: 'pointer', padding: '4px 6px', display: 'inline-flex', alignItems: 'center', color: '#555', transition: 'color 0.2s', outline: 'none' }} onMouseEnter={e => (e.currentTarget.style.color='#3b82f6')} onMouseLeave={e => (e.currentTarget.style.color='#555')}><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 102.13-9.36L1 10"/></svg></button>}
                                        </div>
                                     )}
                                  </div>
                               </div>
                           );
                        })}
                        <div ref={messagesEndRef} />
                        <style>{`
                  @keyframes fadeIn { from { opacity: 0; transform: translateY(20px); } to { opacity: 1; transform: translateY(0); } }
                  @keyframes pulse { 0% { opacity: 0.3; } 50% { opacity: 0.8; } 100% { opacity: 0.3; } }
                  .messages-container::-webkit-scrollbar { display: none; }
                `}</style>
                     </div>
                  )}

                  <div className="search-container"
                     onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
                     onDragLeave={() => setIsDragging(false)}
                     onDrop={(e) => {
                        e.preventDefault();
                        setIsDragging(false);
                        if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
                           setUploadedFiles(prev => [...prev, ...Array.from(e.dataTransfer.files)]);
                        }
                     }}
                  >
                     <div className={`search-bar-wrap ${isDragging ? 'dragging' : ''}`} style={isDragging ? { border: '1px dashed var(--accent-blue)', background: 'rgba(59, 130, 246, 0.05)' } : {}}>
                        {uploadedFiles.length > 0 && (
                           <div style={{ display: 'flex', gap: '10px', padding: '15px 15px 0 15px', flexWrap: 'wrap' }}>
                              {uploadedFiles.map((f, i) => (
                                 <div key={i} style={{ background: 'rgba(255,255,255,0.1)', padding: '5px 10px', borderRadius: '8px', fontSize: '0.7rem', display: 'flex', alignItems: 'center', gap: '5px', color: '#fff' }}>
                                    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '100px' }}>{f.name}</span>
                                    <X size={12} style={{ cursor: 'pointer' }} onClick={() => setUploadedFiles(prev => prev.filter((_, idx) => idx !== i))} />
                                 </div>
                              ))}
                           </div>
                        )}

                        <textarea
                           className="main-input"
                           placeholder="Type to NEXUS..."
                           rows={1}
                           value={inputValue}
                           onChange={(e) => {
                              setInputValue(e.target.value);
                              e.target.style.height = 'auto';
                              e.target.style.height = e.target.scrollHeight + 'px';
                           }}
                           onKeyDown={(e) => {
                              if (e.key === 'Enter' && !e.shiftKey) {
                                 e.preventDefault();
                                 handleSend();
                                 (e.target as any).style.height = 'auto';
                              }
                           }}
                           onPaste={(e) => {
                              if (e.clipboardData.files && e.clipboardData.files.length > 0) {
                                 setUploadedFiles(prev => [...prev, ...Array.from(e.clipboardData.files)]);
                              }
                           }}
                           style={{ resize: 'none', overflowY: 'hidden', minHeight: '40px', maxHeight: '200px', lineHeight: '1.6' }}
                        />

                        <div className="input-footer">
                           <div className="action-icons" style={{ display: 'flex', alignItems: 'center', gap: '18px' }}>
                              <label className="icon-btn" style={{ cursor: 'pointer', color: '#888', transition: 'all 0.2s' }}>
                                 <input type="file" multiple style={{ display: 'none' }} onChange={(e) => {
                                    if (e.target.files && e.target.files.length > 0) {
                                       setUploadedFiles(prev => [...prev, ...Array.from(e.target.files!)]);
                                    }
                                 }} />
                                 <PlusCircle size={20} className="hover-white" />
                              </label>
                              <span className="icon-btn" style={{ color: '#888', cursor: 'pointer', transition: 'all 0.2s' }}><Mic size={20} className="hover-white" /></span>
                              <span className="icon-btn" style={{ color: '#888', cursor: 'pointer', transition: 'all 0.2s' }}><Monitor size={20} className="hover-white" /></span>
                              <div style={{ position: 'relative' }} ref={modelMenuRef}>
                               <div 
                                  onClick={() => setShowModelMenu(!showModelMenu)}
                                  style={{
                                     background: 'rgba(255, 255, 255, 0.05)',
                                     color: '#fff',
                                     padding: '8px 16px',
                                     borderRadius: '12px',
                                     border: '1px solid rgba(255, 255, 255, 0.1)',
                                     fontSize: '0.8rem',
                                     fontWeight: 600,
                                     cursor: 'pointer',
                                     display: 'flex',
                                     alignItems: 'center',
                                     gap: '12px',
                                     minWidth: '200px',
                                     justifyContent: 'space-between',
                                     transition: 'all 0.3s'
                                  }}
                                  className="hover-bright"
                               >
                                  <span style={{ opacity: selectedSessionProvider ? 1 : 0.5 }}>
                                     {selectedSessionProvider || 'Select Model'}
                                  </span>
                                  <ChevronDown size={14} style={{ opacity: 0.4, transform: showModelMenu ? 'rotate(180deg)' : 'rotate(0deg)', transition: 'transform 0.3s cubic-bezier(0.4, 0, 0.2, 1)' }} />
                               </div>

                               {showModelMenu && (
                                  <div style={{
                                     position: 'absolute',
                                     bottom: 'calc(100% + 12px)',
                                     left: 0,
                                     width: '100%',
                                     background: 'rgba(13, 13, 13, 0.98)',
                                     backdropFilter: 'blur(20px)',
                                     border: '1px solid rgba(255, 255, 255, 0.1)',
                                     borderRadius: '14px',
                                     padding: '6px',
                                     zIndex: 9000,
                                     boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.7)',
                                     maxHeight: '280px',
                                     overflowY: 'auto'
                                  }} className="custom-scrollbar fade-in">
                                     {state?.provider_instances?.length === 0 ? (
                                        <div style={{ padding: '20px', fontSize: '0.7rem', color: '#444', textAlign: 'center', fontWeight: 800, letterSpacing: '1px' }}>
                                           NO MODELS ACTIVE
                                        </div>
                                     ) : (
                                        state?.provider_instances?.map((inst, idx) => (
                                           <div 
                                              key={idx}
                                              onClick={() => {
                                                 setSelectedSessionProvider(inst.id);
                                                 setShowModelMenu(false);
                                              }}
                                              style={{
                                                 padding: '10px 14px',
                                                 borderRadius: '10px',
                                                 fontSize: '0.8rem',
                                                 cursor: 'pointer',
                                                 transition: 'all 0.2s',
                                                 marginBottom: '2px',
                                                 background: selectedSessionProvider === inst.id ? 'rgba(59, 130, 246, 0.15)' : 'transparent',
                                                 color: selectedSessionProvider === inst.id ? 'var(--accent-blue)' : '#999',
                                                 fontWeight: selectedSessionProvider === inst.id ? 700 : 500
                                              }}
                                              className="dropdown-item-hover"
                                           >
                                              {inst.id}
                                           </div>
                                        ))
                                     )}
                                  </div>
                               )}
                            </div>
                           </div>
                           <div
                              className={`send-arrow ${(inputValue || uploadedFiles.length > 0) ? 'active' : ''}`}
                              style={{ width: '42px', height: '42px', borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: (inputValue || uploadedFiles.length > 0) ? 'pointer' : 'default' }}
                              onClick={handleSend}
                           >
                              <Send size={18} />
                           </div>
                        </div>
                     </div>
                  </div>
               </div>
            ) : (
               <div className="tab-view" style={{ padding: activeTab === 'vision' ? '20px 40px' : '80px 40px', maxWidth: activeTab === 'vision' ? 'none' : '1200px', margin: '0 auto', width: '100%', height: activeTab === 'vision' ? '100vh' : 'auto', overflowY: activeTab === 'vision' ? 'hidden' : 'auto', overflowX: 'hidden' }}>
                  <div style={{ display: activeTab === 'vision' ? 'block' : 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: activeTab === 'vision' ? 0 : '30px', height: activeTab === 'vision' ? '100%' : 'auto' }}>
                     <h1 style={{ display: activeTab === 'vision' ? 'none' : 'block', fontSize: '2.2rem', textTransform: 'uppercase', letterSpacing: '3px', fontWeight: 900, color: '#fff', margin: 0 }}>{activeTab}</h1>
                  
                  
                  {activeTab === 'vision' && <HolisticVision />}
                     {activeTab === 'mcp' && (
                        <button
                           onClick={() => setShowAddMcpModal(true)}
                           style={{ background: 'rgba(59, 130, 246, 0.1)', border: '1px solid var(--accent-blue)', color: 'var(--accent-blue)', padding: '8px 16px', borderRadius: '8px', fontSize: '0.7rem', fontWeight: 900, cursor: 'pointer', letterSpacing: '1px' }}
                        >
                           + ADD MCP
                        </button>
                     )}
                  </div>

                  {activeTab === 'skills' && (
                     <div className="grid-list" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: '25px' }}>
                        {state.skills?.map((s, i) => (
                           <div key={i} className="asset-card" style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.05)', padding: '30px', borderRadius: '20px' }}>
                              <div style={{ fontSize: '1.3rem', fontWeight: '800', marginBottom: '12px', color: '#fff', letterSpacing: '-0.5px' }}>{s.name}</div>
                              <div style={{ fontSize: '0.85rem', color: '#666', lineHeight: '1.5' }}>{s.description}</div>
                           </div>
                        ))}
                     </div>
                  )}

                  {activeTab === 'tools' && (
                     <div className="grid-list" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: '25px' }}>
                        {state.tools?.map((t, i) => (
                           <div key={i} className="asset-card" style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.05)', padding: '30px', borderRadius: '20px' }}>
                              <div style={{ fontSize: '1.3rem', fontWeight: '800', marginBottom: '12px', color: '#fff' }}>{t.name}</div>
                              <div style={{ fontSize: '0.85rem', color: '#666', lineHeight: '1.5' }}>{t.description}</div>
                           </div>
                        ))}
                     </div>
                  )}

                  {activeTab === 'mcp' && (
                     <div className="grid-list" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: '25px' }}>
                        {state.mcp?.servers?.map((srv: any, i: number) => (
                           <div key={i} className="asset-card" style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.1)', padding: '30px', borderRadius: '20px', position: 'relative', overflow: 'hidden' }}>
                              <div style={{ position: 'absolute', top: 0, left: 0, width: '3px', height: '100%', background: 'var(--accent-blue)' }}></div>
                              <div style={{ fontSize: '1.1rem', fontWeight: '800', color: '#fff', letterSpacing: '1px' }}>{srv.name.toUpperCase()}</div>
                           </div>
                        ))}
                     </div>
                  )}

                  {activeTab === 'audit' && (
                     <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '18px', alignItems: 'start' }}>
                        <div className="asset-card" style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.05)', padding: '24px', borderRadius: '12px' }}>
                           <div style={{ fontSize: '0.7rem', color: '#555', fontWeight: 900, letterSpacing: '1.5px', textTransform: 'uppercase', marginBottom: '12px' }}>Unified Graph</div>
                           <div style={{ fontSize: '2rem', color: '#fff', fontWeight: 900 }}>{state.audit?.unified_graph?.nodes || 0}</div>
                           <div style={{ fontSize: '0.8rem', color: '#777' }}>{state.audit?.unified_graph?.edges || 0} edges across runtime stores</div>
                           <div style={{ marginTop: '18px', display: 'grid', gap: '8px' }}>
                              {Object.entries(state.audit?.unified_graph?.by_source || {}).slice(0, 8).map(([key, value]) => (
                                 <div key={key} style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', color: '#888' }}>
                                    <span>{key}</span><span style={{ color: '#fff', fontWeight: 800 }}>{value as number}</span>
                                 </div>
                              ))}
                           </div>
                        </div>

                        <div className="asset-card" style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.05)', padding: '24px', borderRadius: '12px' }}>
                           <div style={{ fontSize: '0.7rem', color: '#555', fontWeight: 900, letterSpacing: '1.5px', textTransform: 'uppercase', marginBottom: '12px' }}>Roadmap</div>
                           <div style={{ fontSize: '2rem', color: '#fff', fontWeight: 900 }}>{Math.round((state.audit?.roadmap?.completion_ratio || 0) * 100)}%</div>
                           <div style={{ fontSize: '0.8rem', color: '#777' }}>
                              {state.audit?.roadmap?.counts?.done || 0} done / {state.audit?.roadmap?.counts?.partial || 0} partial / {state.audit?.roadmap?.counts?.missing || 0} missing
                           </div>
                           <div style={{ marginTop: '18px', display: 'grid', gap: '10px' }}>
                              {(state.audit?.roadmap?.remaining_top || []).slice(0, 4).map((item: any, i: number) => (
                                 <div key={i} style={{ fontSize: '0.75rem', color: '#999', lineHeight: 1.35 }}>
                                    <span style={{ color: 'var(--accent-blue)', fontWeight: 800 }}>{item.status}</span> {item.item}
                                 </div>
                              ))}
                           </div>
                        </div>

                        <div className="asset-card" style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.05)', padding: '24px', borderRadius: '12px' }}>
                           <div style={{ fontSize: '0.7rem', color: '#555', fontWeight: 900, letterSpacing: '1.5px', textTransform: 'uppercase', marginBottom: '12px' }}>Evidence</div>
                           <div style={{ fontSize: '2rem', color: '#fff', fontWeight: 900 }}>{state.audit?.evidence?.total || 0}</div>
                           <div style={{ fontSize: '0.8rem', color: '#777' }}>claims recorded</div>
                           <div style={{ marginTop: '18px', display: 'grid', gap: '8px' }}>
                              {Object.entries(state.audit?.evidence?.by_status || {}).map(([key, value]) => (
                                 <div key={key} style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', color: '#888' }}>
                                    <span>{key}</span><span style={{ color: '#fff', fontWeight: 800 }}>{value as number}</span>
                                 </div>
                              ))}
                           </div>
                        </div>

                        <div className="asset-card" style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.05)', padding: '24px', borderRadius: '12px' }}>
                           <div style={{ fontSize: '0.7rem', color: '#555', fontWeight: 900, letterSpacing: '1.5px', textTransform: 'uppercase', marginBottom: '12px' }}>Tool Economy</div>
                           <div style={{ display: 'grid', gap: '9px' }}>
                              {(state.audit?.tool_economy || []).slice(0, 8).map((tool: any) => (
                                 <div key={tool.tool} style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: '12px', alignItems: 'center', fontSize: '0.75rem' }}>
                                    <span style={{ color: '#ddd', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{tool.tool}</span>
                                    <span style={{ color: tool.success_rate >= 0.9 ? '#4ade80' : '#facc15', fontWeight: 900 }}>{Math.round((tool.success_rate || 0) * 100)}%</span>
                                 </div>
                              ))}
                           </div>
                        </div>

                        <div className="asset-card" style={{ gridColumn: '1 / -1', background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.05)', padding: '24px', borderRadius: '12px' }}>
                           <div style={{ fontSize: '0.7rem', color: '#555', fontWeight: 900, letterSpacing: '1.5px', textTransform: 'uppercase', marginBottom: '16px' }}>Recent Mission Replay</div>
                           <div style={{ display: 'grid', gap: '10px' }}>
                              {(state.audit?.mission_replay || []).slice(0, 10).map((event: any, i: number) => (
                                 <div key={i} style={{ display: 'grid', gridTemplateColumns: '160px 1fr', gap: '14px', fontSize: '0.75rem', color: '#888', borderTop: i === 0 ? 'none' : '1px solid rgba(255,255,255,0.05)', paddingTop: i === 0 ? 0 : '10px' }}>
                                    <span style={{ color: '#fff', fontWeight: 800 }}>{event.event_type}</span>
                                    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{event.data?.tool || event.data?.note || event.mission_id || 'event'}</span>
                                 </div>
                              ))}
                           </div>
                        </div>
                     </div>
                  )}

                  {activeTab === 'providers' && (
                     <div className="grid-list" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: '25px', alignItems: 'start' }}>
                        {state.providers?.map((p, i) => {
                           const instances = state.provider_instances?.filter(pi => pi.parent === p.name) || [];

                           return (
                              <div
                                 key={i}
                                 className="asset-card"
                                 onClick={(e) => {
                                    // If they clicked the main card and not an instance box, open "Add New"
                                    if ((e.target as any).closest('.instance-box')) return;
                                    setSelectedProv(p);
                                    setShowProviderPanel(true);
                                    setApiKey('');
                                    setTargetModel('');
                                    setInstanceName('');
                                 }}
                                 style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.05)', padding: '30px', borderRadius: '20px', cursor: 'pointer', transition: 'all 0.3s ease', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}
                              >
                                 <div style={{ fontSize: '1.3rem', fontWeight: 900, color: '#fff', letterSpacing: '-0.5px' }}>{p.name}</div>

                                 {instances.length > 0 && (
                                    <div style={{ marginTop: '20px', display: 'flex', flexDirection: 'column', gap: '10px', width: '100%' }}>
                                       {instances.map((ins, idx) => (
                                          <div
                                             key={idx}
                                             className="instance-box"
                                             onClick={(e) => {
                                                e.stopPropagation();
                                                setSelectedProv(p);
                                                setInstanceName(ins.id);
                                                setEditingInstanceId(ins.id);
                                                setApiKey(ins.api_key || '');
                                                setTargetModel(ins.model || '');
                                                setShowProviderPanel(true);
                                             }}
                                             style={{ background: 'rgba(59, 130, 246, 0.1)', border: '1px solid rgba(59, 130, 246, 0.3)', padding: '10px 15px', borderRadius: '10px', display: 'flex', flexDirection: 'column', alignItems: 'center' }}
                                          >
                                             <div style={{ fontSize: '0.75rem', fontWeight: 800, color: '#fff' }}>{ins.id}</div>
                                             <div style={{ fontSize: '0.6rem', color: 'var(--accent-blue)', marginTop: '4px' }}>{ins.model || 'No Model Set'}</div>
                                          </div>
                                       ))}
                                    </div>
                                 )}
                              </div>
                           );
                        })}
                     </div>
                  )}
               </div>
            )}

         </div>

         {settingsOpen && (
            <div className="settings-overlay" onClick={() => setSettingsOpen(false)}>
               <div className="settings-modal" onClick={e => e.stopPropagation()} style={{ padding: 0, width: '700px', maxWidth: '95vw', display: 'flex', overflow: 'hidden', borderRadius: '24px', height: '500px' }}>
                  <div style={{ width: '200px', background: 'rgba(255,255,255,0.02)', borderRight: '1px solid rgba(255,255,255,0.05)', padding: '40px 10px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
                     <div style={{ fontSize: '0.65rem', fontWeight: 900, color: '#444', letterSpacing: '2px', padding: '0 20px 15px 20px', textTransform: 'uppercase' }}>Enclave Settings</div>
                     {[
                        { id: 'profile', icon: <User size={16} />, label: 'Account Profile' },
                        { id: 'appearance', icon: <Palette size={16} />, label: 'Interface GUI' },
                        { id: 'security', icon: <Shield size={16} />, label: 'Security & Gates' },
                        { id: 'advanced', icon: <Settings2 size={16} />, label: 'Advanced Orchestration' }
                     ].map(t => (
                        <div
                           key={t.id}
                           onClick={() => setSettingsTab(t.id)}
                           style={{
                              display: 'flex', alignItems: 'center', gap: '15px', padding: '12px 20px', borderRadius: '12px', cursor: 'pointer',
                              background: settingsTab === t.id ? 'rgba(59, 130, 246, 0.1)' : 'transparent',
                              color: settingsTab === t.id ? 'var(--accent-blue)' : '#888',
                              transition: 'all 0.2s', fontWeight: settingsTab === t.id ? 700 : 500
                           }}
                        >
                           {t.icon} <span style={{ fontSize: '0.85rem' }}>{t.label}</span>
                        </div>
                     ))}
                  </div>
                  {/* Main Workspace */}
                  <div style={{ flex: 1, background: '#0d0d0d', padding: '30px', overflowY: 'auto', position: 'relative' }}>
                     <X
                        className="close-btn"
                        onClick={() => setSettingsOpen(false)}
                        style={{ position: 'absolute', top: '30px', right: '30px', color: '#444' }}
                     />

                     {settingsTab === 'profile' && (
                        <div className="fade-in">
                           <h2 style={{ fontSize: '1.8rem', fontWeight: 900, marginBottom: '30px' }}>Account Profile</h2>
                           <div style={{ display: 'flex', alignItems: 'center', gap: '30px', background: 'rgba(255,255,255,0.02)', padding: '30px', borderRadius: '20px', border: '1px solid rgba(255,255,255,0.05)' }}>
                              <div style={{ width: '80px', height: '80px', borderRadius: '24px', background: 'var(--accent-blue)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '2.2rem', color: '#fff', fontWeight: 900 }}>{operatorName.charAt(0)}</div>
                              <div style={{ flex: 1 }}>
                                 <label style={{ display: 'block', fontSize: '0.65rem', fontWeight: 900, color: '#444', letterSpacing: '1.5px', marginBottom: '10px', textTransform: 'uppercase' }}>Identity Label</label>
                                 <input
                                    type="text"
                                    value={operatorName}
                                    onChange={(e) => setOperatorName(e.target.value)}
                                    style={{ width: '100%', background: 'transparent', border: 'none', borderBottom: '1px solid var(--accent-blue)', color: '#fff', fontSize: '1.2rem', fontWeight: 800, outline: 'none', paddingBottom: '5px' }}
                                 />
                                 <div style={{ fontSize: '0.75rem', color: '#555', marginTop: '10px' }}>Sovereign Tier Access • UID-77291</div>
                              </div>
                           </div>
                        </div>
                     )}

                     {settingsTab === 'appearance' && (
                        <div className="fade-in">
                           <h2 style={{ fontSize: '1.8rem', fontWeight: 900, marginBottom: '30px' }}>Interface GUI</h2>

                           <div style={{ marginBottom: '40px' }}>
                              <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 900, color: '#444', letterSpacing: '1.5px', marginBottom: '15px', textTransform: 'uppercase' }}>Theme Matrix</label>
                              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: '10px' }}>
                                 {[
                                    { id: 'dark', label: 'Dark', bg: '#0d0d0d', text: '#fff' },
                                    { id: 'light', label: 'Light', bg: '#f9f9f9', text: '#111' },
                                    { id: 'grey', label: 'Grey', bg: '#222', text: '#bbb' },
                                    { id: 'night', label: 'Night', bg: '#050510', text: '#4ade80' },
                                    { id: 'white', label: 'White', bg: '#ffffff', text: '#000' }
                                 ].map(m => (
                                    <button
                                       key={m.id}
                                       onClick={() => setInterfaceMode(m.id)}
                                       className={`mode-pill ${interfaceMode === m.id ? 'active' : ''}`}
                                       style={{
                                          padding: '15px 10px', fontSize: '0.65rem', fontWeight: 800,
                                          border: interfaceMode === m.id ? '1px solid var(--accent-blue)' : '1px solid rgba(255,255,255,0.05)',
                                          background: m.bg, color: m.text
                                       }}
                                    >
                                       {m.label.toUpperCase()}
                                    </button>
                                 ))}
                              </div>
                           </div>

                           <div>
                              <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 900, color: '#444', letterSpacing: '1.5px', marginBottom: '15px', textTransform: 'uppercase' }}>Accent Core Color</label>
                              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '15px' }}>
                                 {['#3b82f6', '#10b981', '#f59e0b', '#8b5cf6', '#ef4444', '#ec4899', '#06b6d4', '#f97316', '#a855f7'].map(c => (
                                    <div
                                       key={c}
                                       onClick={() => {
                                          setAccentColor(c);
                                          document.documentElement.style.setProperty('--accent-blue', c);
                                       }}
                                       style={{
                                          width: '42px', height: '42px', borderRadius: '12px', background: c, cursor: 'pointer',
                                          border: accentColor === c ? '3px solid #fff' : 'none',
                                          boxShadow: accentColor === c ? `0 0 20px ${c}` : 'none',
                                          transition: 'all 0.2s'
                                       }}
                                    />
                                 ))}
                              </div>
                           </div>
                        </div>
                     )}

                     {settingsTab === 'security' && (
                        <div className="fade-in">
                           <h2 style={{ fontSize: '1.8rem', fontWeight: 900, marginBottom: '30px' }}>Security & Gates</h2>
                           <div style={{ display: 'flex', flexDirection: 'column', gap: '15px' }}>
                              {[
                                 { title: 'Neural Encryption Shield', desc: 'Secure AES-256 wrapping for cognitive weights.', active: true, icon: <Shield size={18} /> },
                                 { title: 'Biometric Handshake', desc: 'Sovereign machine auth for config changes.', active: true, icon: <User size={18} /> },
                                 { title: 'Emergency Killswitch', desc: 'Immediate hive shutdown on threat detection.', active: true, icon: <ShieldAlert size={18} /> }
                              ].map((s, i) => (
                                 <div key={i} style={{ background: 'rgba(255,255,255,0.02)', padding: '22px', borderRadius: '18px', border: '1px solid rgba(255,255,255,0.05)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                    <div style={{ display: 'flex', gap: '20px', alignItems: 'center' }}>
                                       <div style={{ color: s.active ? 'var(--accent-blue)' : '#333' }}>{s.icon}</div>
                                       <div>
                                          <div style={{ fontSize: '0.9rem', fontWeight: 800 }}>{s.title}</div>
                                          <div style={{ fontSize: '0.7rem', color: '#555', marginTop: '2px' }}>{s.desc}</div>
                                       </div>
                                    </div>
                                    <div style={{ width: '40px', height: '22px', background: s.active ? 'var(--accent-blue)' : '#222', borderRadius: '20px', position: 'relative', cursor: 'pointer' }}>
                                       <div style={{ position: 'absolute', right: s.active ? '4px' : '22px', top: '4px', width: '14px', height: '14px', background: '#fff', borderRadius: '50%', transition: 'all 0.3s' }} />
                                    </div>
                                 </div>
                              ))}
                           </div>
                        </div>
                     )}

                     {settingsTab === 'advanced' && (
                        <div className="fade-in">
                           <h2 style={{ fontSize: '1.8rem', fontWeight: 900, marginBottom: '30px' }}>Advanced Orchestration</h2>
                           <div style={{ display: 'flex', flexDirection: 'column', gap: '25px' }}>
                              <div style={{ background: 'rgba(255,255,255,0.02)', padding: '25px', borderRadius: '20px', border: '1px solid rgba(255,255,255,0.05)' }}>
                                 <label style={{ display: 'block', fontSize: '0.65rem', fontWeight: 900, color: '#444', marginBottom: '15px', textTransform: 'uppercase' }}>Neural Frontier Kernel</label>
                                 <select style={{ width: '100%', background: '#111', border: '1px solid #222', padding: '18px', borderRadius: '15px', color: '#fff', outline: 'none', appearance: 'none', fontSize: '0.85rem', fontWeight: 700 }}>
                                    <option>Recursive Inference v1.0.4 [STABLE]</option>
                                    <option>Quantum Branching v1.0.5-beta</option>
                                 </select>
                              </div>
                              <button className="hover-white" style={{ width: '100%', background: 'white', color: '#000', border: 'none', padding: '22px', borderRadius: '18px', fontWeight: 900, letterSpacing: '3px', textTransform: 'uppercase', cursor: 'pointer' }}>
                                 RESTART SYSTEM CORE
                              </button>
                           </div>
                        </div>
                     )}
                  </div>
               </div>
            </div>
         )}

         {/* RIGHT-SIDE MCP REGISTRATION PANEL */}
         <div style={{
            position: 'fixed', top: 0, right: showAddMcpModal ? 0 : '-400px',
            width: '380px', height: '100%',
            background: '#0a0a0a', borderLeft: '1px solid rgba(255,255,255,0.1)',
            zIndex: 7000, padding: '80px 30px 40px 30px',
            transition: 'right 0.4s cubic-bezier(0.4, 0, 0.2, 1)',
            boxShadow: '-20px 0 50px rgba(0,0,0,0.5)',
            display: 'flex', flexDirection: 'column'
         }}>
            <div
               style={{ position: 'absolute', top: 25, right: 25, display: 'flex', alignItems: 'center', gap: '10px', cursor: 'pointer', color: 'rgba(255,255,255,0.4)', transition: 'color 0.2s' }}
               className="hover-white"
               onClick={() => setShowAddMcpModal(false)}
            >
               <span style={{ fontSize: '0.6rem', fontWeight: 800, letterSpacing: '2px' }}>DISMISS</span>
               <X size={18} />
            </div>

            <h2 style={{ fontSize: '1.6rem', fontWeight: 900, marginBottom: '10px', color: '#fff', letterSpacing: '-1px' }}>ADD MCP SERVER</h2>
            <p style={{ fontSize: '0.8rem', color: '#555', marginBottom: '40px' }}>Define satellite architectural parameters.</p>

            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '25px' }}>
               <div>
                  <label style={{ display: 'block', fontSize: '0.65rem', fontWeight: 900, color: 'var(--accent-blue)', letterSpacing: '2px', marginBottom: '10px', textTransform: 'uppercase' }}>MCP NAME</label>
                  <input
                     type="text"
                     placeholder="ID_IDENTIFIER"
                     value={newMcpName}
                     onChange={(e) => setNewMcpName(e.target.value)}
                     style={{ width: '100%', background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.1)', padding: '15px', borderRadius: '12px', color: '#fff', outline: 'none', fontSize: '0.9rem' }}
                  />
               </div>

               <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
                     <label style={{ display: 'block', fontSize: '0.65rem', fontWeight: 900, color: 'var(--accent-blue)', letterSpacing: '2px', textTransform: 'uppercase' }}>JSON Definition</label>
                     <button
                        onClick={() => {
                           try {
                              const formatted = JSON.stringify(JSON.parse(newMcpConfig), null, 2);
                              setNewMcpConfig(formatted);
                           } catch (e) { alert("Invalid Structure Detected"); }
                        }}
                        style={{ background: 'transparent', border: '1px solid rgba(255,255,255,0.1)', color: '#555', fontSize: '0.6rem', padding: '4px 8px', borderRadius: '4px', cursor: 'pointer' }}
                     >
                        FORMAT
                     </button>
                  </div>
                  <textarea
                     value={newMcpConfig}
                     onChange={(e) => setNewMcpConfig(e.target.value)}
                     style={{ flex: 1, width: '100%', background: '#000', border: '1px solid rgba(255,255,255,0.1)', padding: '20px', borderRadius: '12px', color: '#4ade80', outline: 'none', fontSize: '0.8rem', fontFamily: 'monospace', resize: 'none', lineHeight: 1.6 }}
                     placeholder="{ ... }"
                  />
               </div>

               <button
                  onClick={() => {
                     setShowAddMcpModal(false);
                     setNewMcpName('');
                  }}
                  style={{ background: 'var(--accent-blue)', border: 'none', padding: '20px', borderRadius: '16px', color: '#fff', cursor: 'pointer', fontWeight: 800, fontSize: '0.85rem', letterSpacing: '2px', textTransform: 'uppercase', marginTop: '20px', boxShadow: '0 10px 30px -5px rgba(59, 130, 246, 0.4)' }}
               >
                  SAVE MCP
               </button>
            </div>
         </div>

         {/* PROVIDER CONFIG PANEL */}
         <div style={{
            position: 'fixed', top: 0, right: showProviderPanel ? 0 : '-400px',
            width: '380px', height: '100%',
            background: '#0a0a0a', borderLeft: '1px solid rgba(255,255,255,0.1)',
            zIndex: 7000, padding: '80px 30px 40px 30px',
            transition: 'right 0.4s cubic-bezier(0.4, 0, 0.2, 1)',
            boxShadow: '-20px 0 50px rgba(0,0,0,0.5)',
            display: 'flex', flexDirection: 'column'
         }}>
            <div
               style={{ position: 'absolute', top: 25, right: 25, display: 'flex', alignItems: 'center', gap: '10px', cursor: 'pointer', color: 'rgba(255,255,255,0.4)', transition: 'color 0.2s' }}
               className="hover-white"
               onClick={() => setShowProviderPanel(false)}
            >
               <span style={{ fontSize: '0.6rem', fontWeight: 800, letterSpacing: '2px' }}>DISMISS</span>
               <X size={18} />
            </div>

            <h2 style={{ fontSize: '1.6rem', fontWeight: 900, marginBottom: '10px', color: '#fff', letterSpacing: '-1px' }}>{selectedProv?.name || 'PROVIDER'}</h2>
            <p style={{ fontSize: '0.8rem', color: '#555', marginBottom: '40px' }}>Configure authentication and model routing.</p>

            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '25px' }}>
               <div>
                  <label style={{ display: 'block', fontSize: '0.65rem', fontWeight: 900, color: 'var(--accent-blue)', letterSpacing: '2px', marginBottom: '10px', textTransform: 'uppercase' }}>CONFIG IDENTIFIER</label>
                  <input
                     type="text"
                     placeholder="e.g. anthropic-primary"
                     value={instanceName}
                     onChange={(e) => setInstanceName(e.target.value)}
                     style={{ width: '100%', background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.1)', padding: '15px', borderRadius: '12px', color: '#fff', outline: 'none', fontSize: '0.9rem' }}
                  />
               </div>

               <div>
                  <label style={{ display: 'block', fontSize: '0.65rem', fontWeight: 900, color: 'var(--accent-blue)', letterSpacing: '2px', marginBottom: '10px', textTransform: 'uppercase' }}>API KEY</label>
                  <div style={{ position: 'relative' }}>
                     <input
                        type={showApiKey ? "text" : "password"}
                        placeholder="sk-..."
                        value={apiKey}
                        onChange={(e) => setApiKey(e.target.value)}
                        style={{ width: '100%', background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.1)', padding: '15px', paddingRight: '45px', borderRadius: '12px', color: '#fff', outline: 'none', fontSize: '0.9rem' }}
                     />
                     <div
                        onClick={() => setShowApiKey(!showApiKey)}
                        style={{ position: 'absolute', right: '15px', top: '50%', transform: 'translateY(-50%)', cursor: 'pointer', color: 'rgba(255,255,255,0.3)' }}
                     >
                        {showApiKey ? <EyeOff size={16} /> : <Eye size={16} />}
                     </div>
                  </div>
               </div>

               <div>
                  <label style={{ display: 'block', fontSize: '0.65rem', fontWeight: 900, color: 'var(--accent-blue)', letterSpacing: '2px', marginBottom: '10px', textTransform: 'uppercase' }}>MODEL NAME</label>
                  <input
                     type="text"
                     placeholder="e.g. gpt-4o"
                     value={targetModel}
                     onChange={(e) => setTargetModel(e.target.value)}
                     style={{ width: '100%', background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.1)', padding: '15px', borderRadius: '12px', color: '#fff', outline: 'none', fontSize: '0.9rem' }}
                  />
               </div>

               <div style={{ display: 'flex', gap: '15px', marginTop: '10px' }}>
                  <button
                     onClick={() => alert(`Testing API connection for ${selectedProv?.name}... (Mock)`)}
                     className="hover-white"
                     style={{ flex: 1, background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)', padding: '15px', borderRadius: '12px', color: '#fff', cursor: 'pointer', fontWeight: 800, fontSize: '0.75rem', letterSpacing: '1px', textTransform: 'uppercase' }}
                  >
                     TEST API
                  </button>
                  <button
                     onClick={() => alert(`Ping sent to ${selectedProv?.name} endpoint... OK`)}
                     className="hover-white"
                     style={{ flex: 1, background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)', padding: '15px', borderRadius: '12px', color: '#fff', cursor: 'pointer', fontWeight: 800, fontSize: '0.75rem', letterSpacing: '1px', textTransform: 'uppercase' }}
                  >
                     TEST CONNECTION
                  </button>
               </div>

               <div style={{ display: 'flex', gap: '15px', marginTop: '20px' }}>
                  <button
                     onClick={async () => {
                        if (!selectedProv) return;
                        try {
                           if (editingInstanceId && editingInstanceId !== instanceName) {
                              await fetch(`http://localhost:8000/api/providers/instance/${editingInstanceId}`, { method: 'DELETE' });
                           }
                           const res = await fetch('http://localhost:8000/api/providers/configure', {
                              method: 'POST',
                              headers: { 'Content-Type': 'application/json' },
                              body: JSON.stringify({
                                 name: selectedProv.name,
                                 instance_id: instanceName || selectedProv.name.toLowerCase(),
                                 api_key: apiKey,
                                 model: targetModel
                              })
                           });
                           const data = await res.json();
                           if (data.status === 'success') {
                              setShowProviderPanel(false);
                              setApiKey('');
                              setTargetModel('');
                              setInstanceName('');
                              setEditingInstanceId(null);
                           }
                        } catch (e) {
                           alert("Configuration failed.");
                        }
                     }}
                     style={{ flex: 2, background: 'var(--accent-blue)', border: 'none', padding: '20px', borderRadius: '16px', color: '#fff', cursor: 'pointer', fontWeight: 800, fontSize: '0.85rem', letterSpacing: '2px', textTransform: 'uppercase', boxShadow: '0 10px 30px -5px rgba(59, 130, 246, 0.4)' }}
                  >
                     SAVE PROVIDER
                  </button>

                  {editingInstanceId && (
                     <button
                        onClick={async () => {
                           if (!window.confirm("Delete this instance?")) return;
                           try {
                              const res = await fetch(`http://localhost:8000/api/providers/instance/${editingInstanceId}`, { method: 'DELETE' });
                              const data = await res.json();
                              if (data.status === 'success') {
                                 setShowProviderPanel(false);
                                 setEditingInstanceId(null);
                                 setInstanceName('');
                                 setApiKey('');
                                 setTargetModel('');
                              }
                           } catch (e) { alert("Deletion failed."); }
                        }}
                        style={{ flex: 1, background: 'rgba(239, 68, 68, 0.1)', border: '1px solid rgba(239, 68, 68, 0.2)', padding: '20px', borderRadius: '16px', color: '#f87171', cursor: 'pointer', fontWeight: 800, fontSize: '0.7rem', letterSpacing: '1px', textTransform: 'uppercase' }}
                     >
                        DELETE
                     </button>
                  )}
               </div>
            </div>
         </div>
         {confirmModal?.show && (
            <div className="settings-overlay" style={{ zIndex: 10000 }}>
               <div className="settings-modal" style={{ maxWidth: '450px', textAlign: 'center', animation: 'slideIn 0.3s cubic-bezier(0.16, 1, 0.3, 1)', padding: '40px 30px' }}>
                  <div style={{ width: '50px', height: '50px', borderRadius: '50%', background: 'rgba(239, 68, 68, 0.1)', display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 20px auto', color: '#ef4444' }}>
                     <ShieldAlert size={24} />
                  </div>
                  <h2 style={{ fontSize: '1.1rem', fontWeight: 800, marginBottom: '12px', letterSpacing: '1px' }}>{confirmModal.title}</h2>
                  <p style={{ color: 'var(--text-muted)', fontSize: '0.85rem', lineHeight: '1.6', marginBottom: '30px' }}>{confirmModal.message}</p>
                  <div style={{ display: 'flex', gap: '12px', justifyContent: 'center' }}>
                     <button 
                        onClick={() => setConfirmModal(null)} 
                        className="chip" 
                        style={{ padding: '10px 25px', fontWeight: 700 }}
                     >
                        CANCEL
                     </button>
                     <button 
                        onClick={confirmModal.onConfirm} 
                        className="chip active" 
                        style={{ padding: '10px 25px', background: '#ef4444', color: '#fff', border: '1px solid #ef4444', fontWeight: 700 }}
                     >
                        PURGE
                     </button>
                  </div>
               </div>
            </div>
         )}
      </>
   );
}

export default App;
