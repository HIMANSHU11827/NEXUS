import React, { useState, useEffect, useRef } from 'react'
import {
   Search, Edit2, Trash2, X, Eye, EyeOff, PlusCircle,
   Shield, Cpu, Activity, User, Palette, Settings2,
   Monitor, Bell, ShieldAlert, Mic, LayoutDashboard, Sparkles,
   Database, GraduationCap, Wrench, BrainCircuit, HeartPulse, Send, ChevronDown, Power,
   CheckCircle2, TerminalSquare, Puzzle, FileText, Globe, FileSearch, 
   MoreVertical, RefreshCw, ShieldCheck, Download, Link2, MoreHorizontal
} from 'lucide-react'
import { BackendOfflineBanner, FloatingNavControls, HeaderStatusRail, LoadingScreen } from './components/AppChrome'
import { CanvasPanel } from './components/CanvasPanel'
import { ConfigPanel } from './components/ConfigPanel'
import { HealthDrawer, HiveDrawer, RemindersDrawer } from './components/DrawerPanels'
import { Sidebar } from './components/Sidebar'
import { ActivityBar } from './components/ActivityBar'
import { cleanAssistantText, cleanUserMessage } from './textUtils'
import { WorkActivityTimeline } from './components/WorkActivityTimeline'
import type { ChatMessage, NexusState, SessionNotice, SessionSummary, WorkEvent } from './types'
import type { ActivityTab } from './components/ActivityBar'

import { cleanAssistantText, cleanUserMessage } from './textUtils'
type SourceItem = {
   id: string;
   name: string;
   type: 'File' | 'Website';
   checked: boolean;
   path?: string;
   url?: string;
};

type TaskFileItem = SourceItem & {
   kind: 'Document' | 'Image' | 'Code file' | 'Link';
   subtitle: string;
   sourceLabel: string;
   downloadable: boolean;
};

const ThreeLineMenu = ({ color = 'currentColor' }: { color?: string }) => (
   <span style={{ width: '16px', height: '14px', display: 'grid', gap: '3px', alignContent: 'center', justifyItems: 'start' }} aria-hidden="true">
      {[16, 12, 7].map((width, line) => (
         <span
            key={line}
            style={{
               display: 'block',
               width: `${width}px`,
               height: '2px',
               borderRadius: '2px',
               background: color,
            }}
         />
      ))}
   </span>
);

const getJsonStatus = (text: string) => {
   if (!text || !text.trim()) return null;
   try {
      const parsed = JSON.parse(text);
      if (typeof parsed !== 'object' || Array.isArray(parsed) || parsed === null) {
         return { valid: false, message: 'JSON must be an object' };
      }
      return { valid: true };
   } catch (err: any) {
      return { valid: false, message: err?.message || 'Invalid JSON' };
   }
};

function App() {
   const [activeTab, setActiveTab] = useState('session');
   const [activeActivityTab, setActiveActivityTab] = useState<ActivityTab>('chat');
   const [sidebarVisible, setSidebarVisible] = useState(true);
   const [sidebarWidth, setSidebarWidth] = useState(() => {
      const saved = Number(localStorage.getItem('nexus.sidebarWidth'));
      return Number.isFinite(saved) && saved > 0 ? saved : 250;
   });
   const [isSidebarResizing, setIsSidebarResizing] = useState(false);
   const [settingsOpen, setSettingsOpen] = useState(false);
   const [settingsTab, setSettingsTab] = useState('profile');
   const [securityStates, setSecurityStates] = useState({ shield: true, handshake: true, killswitch: false });
   const [showChatAvatars, setShowChatAvatars] = useState(() => localStorage.getItem('nexus.showChatAvatars') !== 'false');
   const [showLogoInHeader, setShowLogoInHeader] = useState(() => localStorage.getItem('nexus.showLogoInHeader') !== 'false');
   const [showLogoMark, setShowLogoMark] = useState(() => localStorage.getItem('nexus.showLogoMark') !== 'false');
   const [accentColor, setAccentColor] = useState(() => localStorage.getItem('nexus.accentColor') || '#3b82f6');
   const [operatorName, setOperatorName] = useState(() => localStorage.getItem('nexus.operatorName') || 'Himanshu Gola');
   const [brandName, setBrandName] = useState(() => localStorage.getItem('nexus.brandName') || 'NEXUS');
   const [brandMark, setBrandMark] = useState(() => localStorage.getItem('nexus.brandMark') || '⚡');
   const [assistantAvatar, setAssistantAvatar] = useState(() => localStorage.getItem('nexus.assistantAvatar') || '🧠');
   const [userAvatar, setUserAvatar] = useState(() => localStorage.getItem('nexus.userAvatar') || '👤');
   const [interfaceMode, setInterfaceMode] = useState('dark'); // dark, light, grey, night, white
   const [drawerType, setDrawerType] = useState<'none' | 'hive' | 'reminders' | 'health' | 'canvas'>('none');
   const [drawerWidth, setDrawerWidth] = useState(() => {
      const saved = Number(localStorage.getItem('nexus.drawerWidth'));
      return Number.isFinite(saved) && saved > 0 ? saved : 390;
   });
   const [isDrawerResizing, setIsDrawerResizing] = useState(false);
   const [currentSessionId, setCurrentSessionId] = useState('default');
   const [sessionList, setSessionList] = useState<SessionSummary[]>([]);
   const [sessionNotice, setSessionNotice] = useState<SessionNotice | null>(null);
   const [historySearch, setHistorySearch] = useState('');
   const [mcpSearch, setMcpSearch] = useState('');
   const [skillsSearch, setSkillsSearch] = useState('');
   const [toolsSearch, setToolsSearch] = useState('');
   const [editingId, setEditingId] = useState<string | null>(null);
   const [editTitle, setEditTitle] = useState('');
   const [sourcesPanelOpen, setSourcesPanelOpen] = useState(false);
   const [sourcesTab, setSourcesTab] = useState<'source' | 'result'>('source');
   const [sources, setSources] = useState<SourceItem[]>([]);
   const [activeSourceMenuId, setActiveSourceMenuId] = useState<string | null>(null);
   const [editingSourceId, setEditingSourceId] = useState<string | null>(null);
   const [editSourceName, setEditSourceName] = useState('');
   const sourceFileInputRef = useRef<HTMLInputElement>(null);
   const [selectedSource, setSelectedSource] = useState<SourceItem | null>(null);
   const [sourceImportOpen, setSourceImportOpen] = useState(false);
   const [sourceImportUrl, setSourceImportUrl] = useState('');
   const [sourceImportBusy, setSourceImportBusy] = useState(false);
   const [sourceImportError, setSourceImportError] = useState('');
   const [sourceSearchQuery, setSourceSearchQuery] = useState('');
   const [taskFilesOpen, setTaskFilesOpen] = useState(false);
   const [taskFilesSearch, setTaskFilesSearch] = useState('');
   const [taskFilesFilter, setTaskFilesFilter] = useState<'All' | 'Document' | 'Image' | 'Code file' | 'Link'>('All');
   const [taskMenuOpen, setTaskMenuOpen] = useState(false);
   const [hoveredSourceId, setHoveredSourceId] = useState<string | null>(null);

   useEffect(() => {
      if (!activeSourceMenuId) return;
      const handleGlobalClick = () => {
         setActiveSourceMenuId(null);
      };
      window.addEventListener('click', handleGlobalClick);
      return () => window.removeEventListener('click', handleGlobalClick);
   }, [activeSourceMenuId]);
   useEffect(() => {
      if (!taskMenuOpen) return;
      const handleGlobalClick = () => setTaskMenuOpen(false);
      window.addEventListener('click', handleGlobalClick);
      return () => window.removeEventListener('click', handleGlobalClick);
   }, [taskMenuOpen]);
   const [inputValue, setInputValue] = useState('');
   const [newReminderText, setNewReminderText] = useState('');
   const [newReminderDue, setNewReminderDue] = useState('');
   const [newHiveMission, setNewHiveMission] = useState('');
   const [hiveStarting, setHiveStarting] = useState(false);
   const [notificationPermission, setNotificationPermission] = useState(() => {
      return "Notification" in window ? Notification.permission : 'unsupported';
   });
   const notifiedReminderIds = useRef<Set<string>>(new Set());
   const [state, setState] = useState<NexusState | null>(null);
   const [loading, setLoading] = useState(true);
   const [backendOffline, setBackendOffline] = useState(false);
   const [messages, setMessages] = useState<ChatMessage[]>([]);
   const [isStreaming, setIsStreaming] = useState(false);
   const [bulkUpdating, setBulkUpdating] = useState(false);
   const [evolutionRefreshing, setEvolutionRefreshing] = useState(false);
   const [evolutionUpdatedAt, setEvolutionUpdatedAt] = useState<string>('');
   const [evolutionAction, setEvolutionAction] = useState<{ kind: 'idle' | 'plan' | 'verify' | 'error'; message: string; data?: any }>({ kind: 'idle', message: '' });
   const [evolutionWorking, setEvolutionWorking] = useState('');
   const [_collapsedBlocks, _setCollapsedBlocks] = useState<Set<string>>(new Set());
   const [copiedMsgId, setCopiedMsgId] = useState<number | null>(null);
   const [hoveredMsgId, setHoveredMsgId] = useState<number | null>(null);
   const [hoveredSessionId, setHoveredSessionId] = useState<string | null>(null);
   const [chatScrolled, _setChatScrolled] = useState(false);
   const [canvasPlaybackTime, setCanvasPlaybackTime] = useState<number | null>(null);
   const [canvasPlaybackTurnId, setCanvasPlaybackTurnId] = useState('');
   const [isPlaying, setIsPlaying] = useState(false);
   const [canvasWidth, setCanvasWidth] = useState(() => {
      const saved = Number(localStorage.getItem('nexus.canvasWidth'));
      return Number.isFinite(saved) && saved > 0 ? saved : 768;
   });
   const [isCanvasResizing, setIsCanvasResizing] = useState(false);
   const [screenSharing, setScreenSharing] = useState(false);
   const [screenShareError, setScreenShareError] = useState('');
   const [voiceListening, setVoiceListening] = useState(false);
   const [voiceError, setVoiceError] = useState('');
   const [voiceTranscript, setVoiceTranscript] = useState('');
   const [canvasPreview, setCanvasPreview] = useState<{ path: string; name: string; ext: string; content: string } | null>(null);
   const [canvasPreviewError, setCanvasPreviewError] = useState('');
   const [workEvents, setWorkEvents] = useState<WorkEvent[]>([]);
   const [commandRuns, setCommandRuns] = useState<Record<string, { status: string; command: string; stdout?: string; stderr?: string; output?: string }>>({});
   const [_workflowStartedAt, setWorkflowStartedAt] = useState(() => Date.now() / 1000);
   const [currentTurnId, setCurrentTurnId] = useState('');
   const [selectedWorkEvent, setSelectedWorkEvent] = useState<WorkEvent | null>(null);
   const [lastArtifactPath, setLastArtifactPath] = useState('');
   const [canvasViewMode, setCanvasViewMode] = useState<'source' | 'preview'>('source');
   const messagesEndRef = useRef<HTMLDivElement>(null);
   const lastMessageCountRef = useRef(0);
   const currentSessionIdRef = useRef(currentSessionId);
   const sessionMessagesCacheRef = useRef<Record<string, ChatMessage[]>>({});
   const artifactCacheRef = useRef<Record<string, any>>({});
   const artifactPathIndexRef = useRef<Record<string, string>>({});
   const composerInputRef = useRef<HTMLTextAreaElement>(null);
   const screenStreamRef = useRef<MediaStream | null>(null);
   const recognitionRef = useRef<any>(null);
   const voiceTranscriptRef = useRef('');

   useEffect(() => {
      currentSessionIdRef.current = currentSessionId;
   }, [currentSessionId]);

   const setMessagesForSession = (sessionId: string, next: ChatMessage[] | ((previous: ChatMessage[]) => ChatMessage[])) => {
      const sid = sessionId || 'default';
      const previous = sessionMessagesCacheRef.current[sid] || [];
      const resolved = typeof next === 'function' ? next(previous) : next;
      sessionMessagesCacheRef.current[sid] = resolved;
      if (currentSessionIdRef.current === sid) {
         setMessages(resolved);
      }
      return resolved;
   };

   useEffect(() => {
      if (!isSidebarResizing) return;
      const move = (event: PointerEvent) => {
         const maxWidth = Math.min(420, Math.floor(window.innerWidth * 0.42));
         const nextWidth = Math.max(210, Math.min(maxWidth, event.clientX));
         setSidebarWidth(nextWidth);
         localStorage.setItem('nexus.sidebarWidth', String(nextWidth));
      };
      const stop = () => setIsSidebarResizing(false);
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', stop, { once: true });
      window.addEventListener('pointercancel', stop, { once: true });
      document.body.classList.add('sidebar-resizing');
      return () => {
         window.removeEventListener('pointermove', move);
         window.removeEventListener('pointerup', stop);
         window.removeEventListener('pointercancel', stop);
         document.body.classList.remove('sidebar-resizing');
      };
   }, [isSidebarResizing]);

   useEffect(() => {
      if (!isDrawerResizing) return;
      const move = (event: PointerEvent) => {
         const maxWidth = Math.max(360, Math.floor(window.innerWidth * 0.62));
         const nextWidth = Math.max(320, Math.min(maxWidth, window.innerWidth - event.clientX - 16));
         setDrawerWidth(nextWidth);
         localStorage.setItem('nexus.drawerWidth', String(nextWidth));
      };
      const stop = () => setIsDrawerResizing(false);
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', stop, { once: true });
      window.addEventListener('pointercancel', stop, { once: true });
      document.body.classList.add('drawer-resizing');
      return () => {
         window.removeEventListener('pointermove', move);
         window.removeEventListener('pointerup', stop);
         window.removeEventListener('pointercancel', stop);
         document.body.classList.remove('drawer-resizing');
      };
   }, [isDrawerResizing]);

   useEffect(() => {
      if (!isCanvasResizing) return;
      const move = (event: PointerEvent) => {
         const maxWidth = Math.max(420, Math.floor(window.innerWidth * 0.78));
         const minWidth = Math.min(460, Math.floor(window.innerWidth * 0.62));
         const nextWidth = Math.max(minWidth, Math.min(maxWidth, window.innerWidth - event.clientX - 16));
         setCanvasWidth(nextWidth);
         localStorage.setItem('nexus.canvasWidth', String(nextWidth));
      };
      const stop = () => {
         setIsCanvasResizing(false);
      };
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', stop, { once: true });
      window.addEventListener('pointercancel', stop, { once: true });
      document.body.classList.add('canvas-resizing');
      return () => {
         window.removeEventListener('pointermove', move);
         window.removeEventListener('pointerup', stop);
         window.removeEventListener('pointercancel', stop);
         document.body.classList.remove('canvas-resizing');
      };
   }, [isCanvasResizing]);

   const getCanvasPreviewTargetFromMessages = () => {
      const rows: any[] = [];
      messages.forEach(message => {
         (message.content || '').split('\n').forEach(line => {
            const parsed = parseWorkActivityLine(line);
            if (parsed) rows.push(parsed);
         });
      });

      const index = (() => {
         if (canvasPlaybackTime === null || timelineWorkActivities.length === 0) return rows.length - 1;
         const stepIndex = Math.min(timelineWorkActivities.length - 1, Math.floor(canvasPlaybackTime / 5));
         const activeEvent = timelineWorkActivities[stepIndex];
         if (!activeEvent) return rows.length - 1;
         const idx = allWorkActivities.indexOf(activeEvent);
         return idx >= 0 ? idx : rows.length - 1;
      })();
      const visibleRows = rows.slice(0, Math.max(0, index) + 1);
      const latestFile = [...visibleRows]
         .reverse()
         .find(row => row?.kind === 'file' && String(row?.path || row?.target || '').trim());
      return String(latestFile?.path || latestFile?.target || '').trim();
   };

   const isRealPreviewFileEvent = (event?: WorkEvent | null) => {
      if (!event) return false;
      const kind = String(event.kind || event.type || '').toLowerCase();
      if (kind !== 'file') return false;
      const target = String(event.path || event.target || '').trim();
      return !!target && /\.[A-Za-z0-9]{1,12}(?:$|[\s?#])/.test(target);
   };

   const isWorkflowBookkeepingEvent = (event?: WorkEvent | null) => {
      if (!event) return false;
      const text = [
         event.action,
         event.title,
         event.target,
         event.phase,
      ].map(value => String(value || '').toLowerCase()).join(' ');
      return text.includes('open the created file in the ui canvas') ||
         text.includes('complete turn') ||
         text.includes('workflow finished') ||
         text.includes('generate response') ||
         text.includes('create task list') ||
         text.includes('todo list');
   };

   const commandEventKey = (event: WorkEvent) => String(event.id || event.command || event.target || event.path || '').trim();

   const runWorkCommand = async (event: WorkEvent) => {
      const key = commandEventKey(event);
      if (!key) return;
      const existing = commandRuns[key];
      if (existing?.status === 'running' || existing?.status === 'done') return;
      const command = resolveWorkActivityTarget(event);
      if (!command) return;
      setCommandRuns(prev => ({ ...prev, [key]: { status: 'running', command, stdout: '', stderr: '', output: '' } }));
      try {
         const res = await fetch('/api/work-events/run-command-stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
               session_id: currentSessionId || 'default',
               turn_id: currentTurnId,
               event_id: event.id,
               command,
               timeout: 120,
            }),
         });
         if (!res.ok || !res.body) {
            const data = await res.json().catch(() => ({}));
            throw new Error(data?.detail || `HTTP ${res.status}`);
         }
         const reader = res.body.getReader();
         const decoder = new TextDecoder();
         let sseBuffer = '';
         let stdout = '';
         let stderr = '';
         let finalStatus = 'running';
         const applyPayload = (payload: any) => {
            if (!payload || typeof payload !== 'object') return;
            if (payload.type === 'chunk') {
               const text = String(payload.text || '');
               if (payload.stream === 'stderr') stderr += text;
               else stdout += text;
               setCommandRuns(prev => ({
                  ...prev,
                  [key]: {
                     status: 'running',
                     command,
                     stdout,
                     stderr,
                     output: `${stdout}${stderr}`,
                  },
               }));
            }
            if (payload.type === 'done') {
               finalStatus = payload.status || 'done';
               stdout = String(payload.stdout ?? stdout);
               stderr = String(payload.stderr ?? stderr);
               setCommandRuns(prev => ({
                  ...prev,
                  [key]: {
                     status: finalStatus,
                     command: payload.command || command,
                     stdout,
                     stderr,
                     output: String(payload.output ?? `${stdout}${stderr}`),
                  },
               }));
               if (payload.event) {
                  const normalized = normalizeWorkEvent(payload.event);
                  setWorkEvents(prev => [...prev.filter(item => item.id !== normalized.id), normalized]);
                  setSelectedWorkEvent(current => current && commandEventKey(current) === key ? { ...current, ...normalized } : current);
               }
            }
         };
         while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            sseBuffer += decoder.decode(value, { stream: true });
            const frames = sseBuffer.split('\n\n');
            sseBuffer = frames.pop() || '';
            frames.forEach(frame => {
               const dataLine = frame.split('\n').find(line => line.startsWith('data:'));
               if (!dataLine) return;
               try {
                  applyPayload(JSON.parse(dataLine.slice(5).trim()));
               } catch {
                  // Ignore malformed partial frames; the next chunk may complete them.
               }
            });
         }
         if (sseBuffer.trim()) {
            const dataLine = sseBuffer.split('\n').find(line => line.startsWith('data:'));
            if (dataLine) {
               try {
                  applyPayload(JSON.parse(dataLine.slice(5).trim()));
               } catch {
                  // Ignore incomplete final frame.
               }
            }
         }
         await loadWorkEvents(currentSessionId, currentTurnId);
      } catch (error: any) {
         setCommandRuns(prev => ({
            ...prev,
            [key]: { status: 'error', command, stderr: String(error?.message || error), output: String(error?.message || error) },
         }));
      }
   };

   const openWorkEvent = (event: WorkEvent, playbackIndex?: number) => {
      setSelectedSource(null);
      setSelectedWorkEvent(event);
      setCanvasPlaybackTurnId(String(event?.turn_id || currentTurnId || ''));
      if (typeof playbackIndex === 'number') {
         // Convert step index to virtual seconds (each step = 5s)
         setCanvasPlaybackTime(playbackIndex * 5);
         setIsPlaying(false);
      } else {
         setCanvasPlaybackTime(null);
         setIsPlaying(false);
      }
      if (event?.lang === 'html' || String(event?.path || event?.target || '').toLowerCase().endsWith('.html')) {
         setCanvasViewMode('preview');
      } else {
         setCanvasViewMode('source');
      }
      setDrawerType('canvas');
      if (String(event?.kind || event?.type || '').toLowerCase() === 'command') {
         runWorkCommand(event);
      }
   };

   const extractGeneratedArtifact = (content: string) => {
      const text = String(content || '');
      const blocks = [...text.matchAll(/```([a-zA-Z0-9_-]*)\n([\s\S]*?)```/g)]
         .map(match => ({ lang: (match[1] || 'code').toLowerCase(), content: match[2].trim() }))
         .filter(block => block.content);
      const htmlBlock = blocks.find(block => block.lang === 'html' || /<!doctype\b|<html\b|<canvas\b|<script\b/i.test(block.content));
      if (htmlBlock) return { lang: 'html', name: 'index.html', content: htmlBlock.content };
      const codeBlock = blocks.find(block => ['tsx', 'jsx', 'js', 'ts', 'python', 'py', 'css'].includes(block.lang));
      if (codeBlock) {
         const ext = codeBlock.lang === 'python' ? 'py' : codeBlock.lang;
         return { lang: codeBlock.lang, name: `artifact.${ext}`, content: codeBlock.content };
      }
      const htmlStart = text.search(/<!doctype\b|<html\b/i);
      if (htmlStart >= 0) return { lang: 'html', name: 'index.html', content: text.slice(htmlStart).trim() };
      return null;
   };

   const buildDinoGameHtml = () => `<!doctype html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>NEXUS Dino Game</title>
<style>
  * { box-sizing: border-box; }
  body {
    margin: 0;
    min-height: 100vh;
    display: grid;
    place-items: center;
    background: linear-gradient(#dbeafe, #f8fafc 52%, #dcfce7 52%);
    font-family: system-ui, -apple-system, Segoe UI, sans-serif;
    color: #111827;
  }
  .wrap { width: min(920px, 94vw); }
  .hud {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 16px;
    margin-bottom: 12px;
    font-weight: 800;
  }
  .hint { color: #475569; font-weight: 650; }
  #game {
    position: relative;
    width: 100%;
    height: 260px;
    overflow: hidden;
    border: 3px solid #111827;
    border-radius: 16px;
    background:
      radial-gradient(circle at 80% 22%, #fde68a 0 32px, transparent 33px),
      linear-gradient(#bfdbfe 0 62%, #86efac 62% 100%);
    box-shadow: 0 18px 40px rgba(15, 23, 42, .18);
  }
  #ground {
    position: absolute;
    left: 0;
    right: 0;
    bottom: 38px;
    height: 5px;
    background: #334155;
  }
  #dino {
    position: absolute;
    left: 74px;
    bottom: 43px;
    width: 48px;
    height: 52px;
    border-radius: 13px 13px 8px 8px;
    background: #16a34a;
    box-shadow: inset -8px 0 #15803d;
  }
  #dino::before {
    content: "";
    position: absolute;
    right: 7px;
    top: 10px;
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: #fff;
    box-shadow: 2px 1px 0 #111827;
  }
  #dino::after {
    content: "";
    position: absolute;
    left: -18px;
    bottom: 11px;
    border-top: 10px solid transparent;
    border-bottom: 5px solid transparent;
    border-right: 22px solid #15803d;
  }
  #cactus {
    position: absolute;
    right: -60px;
    bottom: 43px;
    width: 34px;
    height: 62px;
    border-radius: 11px 11px 5px 5px;
    background: #0f766e;
    box-shadow: inset -6px 0 #115e59;
  }
  #cactus::before,
  #cactus::after {
    content: "";
    position: absolute;
    width: 18px;
    height: 28px;
    border-radius: 9px;
    background: #0f766e;
    top: 18px;
  }
  #cactus::before { left: -13px; }
  #cactus::after { right: -13px; top: 28px; }
  #message {
    position: absolute;
    inset: 0;
    display: grid;
    place-items: center;
    pointer-events: none;
    font-size: clamp(22px, 4vw, 42px);
    font-weight: 900;
    color: rgba(17, 24, 39, .82);
    text-align: center;
  }
</style>
</head>
<body>
  <main class="wrap">
    <div class="hud">
      <div>NEXUS Dino</div>
      <div>Score: <span id="score">0</span></div>
      <div class="hint">Space / Up / Click to jump</div>
    </div>
    <section id="game" aria-label="Dino game">
      <div id="ground"></div>
      <div id="dino"></div>
      <div id="cactus"></div>
      <div id="message"></div>
    </section>
  </main>
<script>
  const game = document.getElementById('game');
  const dino = document.getElementById('dino');
  const cactus = document.getElementById('cactus');
  const scoreEl = document.getElementById('score');
  const message = document.getElementById('message');
  let y = 0, vy = 0, cactusX = game.clientWidth + 80, score = 0, speed = 5.2, over = false;
  function jump() {
    if (over) { restart(); return; }
    if (y === 0) vy = 15;
  }
  function restart() {
    y = 0; vy = 0; cactusX = game.clientWidth + 80; score = 0; speed = 5.2; over = false; message.textContent = '';
    requestAnimationFrame(loop);
  }
  function rectsHit(a, b) {
    return a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
  }
  function loop() {
    if (over) return;
    vy -= .72;
    y = Math.max(0, y + vy);
    if (y === 0 && vy < 0) vy = 0;
    dino.style.transform = 'translateY(' + (-y) + 'px)';
    cactusX -= speed;
    if (cactusX < -90) { cactusX = game.clientWidth + Math.random() * 240; score += 1; speed += .18; }
    cactus.style.transform = 'translateX(' + cactusX + 'px)';
    scoreEl.textContent = String(score);
    if (rectsHit(dino.getBoundingClientRect(), cactus.getBoundingClientRect())) {
      over = true;
      message.innerHTML = 'Game Over<br><span style="font-size:18px">click or press Space to restart</span>';
      return;
    }
    requestAnimationFrame(loop);
  }
  addEventListener('keydown', e => { if (e.code === 'Space' || e.code === 'ArrowUp') { e.preventDefault(); jump(); } });
  game.addEventListener('pointerdown', jump);
  restart();
</script>
</body>
</html>`;

   const buildDinoGamePython = () => `import random
import tkinter as tk


WIDTH = 900
HEIGHT = 360
GROUND_Y = 285
PLAYER_X = 90


class DinoGame:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("NEXUS Dino Runner")
        self.root.resizable(False, False)

        self.canvas = tk.Canvas(self.root, width=WIDTH, height=HEIGHT, bg="#f8fafc", highlightthickness=0)
        self.canvas.pack()

        self.score = 0
        self.best = 0
        self.speed = 7
        self.gravity = 1.0
        self.jump_power = -17
        self.velocity_y = 0
        self.on_ground = True
        self.running = True
        self.obstacles = []
        self.clouds = []
        self.spawn_timer = 0

        self.player = self.canvas.create_rectangle(PLAYER_X, GROUND_Y - 46, PLAYER_X + 42, GROUND_Y, fill="#22c55e", outline="")
        self.eye = self.canvas.create_oval(PLAYER_X + 27, GROUND_Y - 38, PLAYER_X + 34, GROUND_Y - 31, fill="#052e16", outline="")
        self.canvas.create_line(0, GROUND_Y, WIDTH, GROUND_Y, fill="#334155", width=3)
        self.score_text = self.canvas.create_text(18, 18, anchor="nw", text="Score: 0", fill="#0f172a", font=("Consolas", 16, "bold"))
        self.canvas.create_text(WIDTH // 2, 28, text="SPACE / UP / CLICK to jump    R to restart", fill="#64748b", font=("Consolas", 12, "bold"))

        self.root.bind("<space>", self.jump)
        self.root.bind("<Up>", self.jump)
        self.root.bind("<Button-1>", self.jump)
        self.root.bind("r", self.restart)
        self.root.bind("R", self.restart)

        self.make_clouds()
        self.loop()

    def make_clouds(self):
        for _ in range(4):
            x = random.randint(80, WIDTH - 60)
            y = random.randint(45, 120)
            cloud = self.canvas.create_oval(x, y, x + 70, y + 24, fill="#e2e8f0", outline="")
            self.clouds.append(cloud)

    def jump(self, _event=None):
        if not self.running:
            self.restart()
            return
        if self.on_ground:
            self.velocity_y = self.jump_power
            self.on_ground = False

    def restart(self, _event=None):
        self.canvas.delete("obstacle")
        self.canvas.delete("gameover")
        self.obstacles.clear()
        self.score = 0
        self.speed = 7
        self.velocity_y = 0
        self.on_ground = True
        self.running = True
        self.spawn_timer = 0
        self.canvas.coords(self.player, PLAYER_X, GROUND_Y - 46, PLAYER_X + 42, GROUND_Y)
        self.canvas.coords(self.eye, PLAYER_X + 27, GROUND_Y - 38, PLAYER_X + 34, GROUND_Y - 31)
        self.loop()

    def spawn_obstacle(self):
        width = random.randint(22, 38)
        height = random.randint(34, 66)
        obstacle = self.canvas.create_rectangle(WIDTH + 20, GROUND_Y - height, WIDTH + 20 + width, GROUND_Y, fill="#ef4444", outline="", tags="obstacle")
        self.obstacles.append(obstacle)

    def move_player(self):
        if self.on_ground:
            return

        self.velocity_y += self.gravity
        self.canvas.move(self.player, 0, self.velocity_y)
        self.canvas.move(self.eye, 0, self.velocity_y)

        x1, _y1, x2, y2 = self.canvas.coords(self.player)
        if y2 >= GROUND_Y:
            self.canvas.coords(self.player, x1, GROUND_Y - 46, x2, GROUND_Y)
            self.canvas.coords(self.eye, PLAYER_X + 27, GROUND_Y - 38, PLAYER_X + 34, GROUND_Y - 31)
            self.velocity_y = 0
            self.on_ground = True

    def move_world(self):
        for cloud in self.clouds:
            self.canvas.move(cloud, -1.0, 0)
            _x1, _y1, x2, _y2 = self.canvas.coords(cloud)
            if x2 < 0:
                new_y = random.randint(45, 120)
                self.canvas.coords(cloud, WIDTH + 40, new_y, WIDTH + 110, new_y + 24)

        for obstacle in self.obstacles[:]:
            self.canvas.move(obstacle, -self.speed, 0)
            _x1, _y1, x2, _y2 = self.canvas.coords(obstacle)
            if x2 < -20:
                self.canvas.delete(obstacle)
                self.obstacles.remove(obstacle)

    def hit_obstacle(self):
        px1, py1, px2, py2 = self.canvas.coords(self.player)
        player_box = (px1 + 4, py1 + 4, px2 - 4, py2 - 4)
        for obstacle in self.obstacles:
            ox1, oy1, ox2, oy2 = self.canvas.coords(obstacle)
            if player_box[0] < ox2 and player_box[2] > ox1 and player_box[1] < oy2 and player_box[3] > oy1:
                return True
        return False

    def game_over(self):
        self.running = False
        self.best = max(self.best, self.score)
        self.canvas.create_rectangle(230, 105, 670, 225, fill="#0f172a", outline="", tags="gameover")
        self.canvas.create_text(WIDTH // 2, 145, text="GAME OVER", fill="#f8fafc", font=("Consolas", 28, "bold"), tags="gameover")
        self.canvas.create_text(WIDTH // 2, 185, text=f"Score {self.score}   Best {self.best}   Press R or SPACE", fill="#cbd5e1", font=("Consolas", 14, "bold"), tags="gameover")

    def loop(self):
        if not self.running:
            return

        self.spawn_timer -= 1
        if self.spawn_timer <= 0:
            self.spawn_obstacle()
            self.spawn_timer = random.randint(55, 95)

        self.move_player()
        self.move_world()

        self.score += 1
        self.speed = min(17, 7 + self.score // 450)
        self.canvas.itemconfig(self.score_text, text=f"Score: {self.score}   Best: {self.best}")

        if self.hit_obstacle():
            self.game_over()
            return

        self.root.after(16, self.loop)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    DinoGame().run()
`;

   const repairGeneratedArtifact = (artifact: { lang: string; name: string; content: string }, prompt = '') => {
      if (artifact.lang.toLowerCase() === 'html' && /\bdino\b|\bdinosaur\b/i.test(`${prompt} ${artifact.content}`)) {
         return { ...artifact, name: 'index.html', content: buildDinoGameHtml() };
      }
      if (/\bdino\b|\bdinosaur\b/i.test(`${prompt} ${artifact.content}`) && ['python', 'py'].includes(artifact.lang.toLowerCase())) {
         return { ...artifact, name: 'dino_game.py', content: buildDinoGamePython() };
      }
      return artifact;
   };

   const saveArtifactToCanvas = async (artifact: { lang: string; name: string; content: string }, sessionId = currentSessionId, title = 'Create artifact', turnId = currentTurnId) => {
      const dedupeKey = `${sessionId}:${artifact.name}:${artifact.content.length}:${artifact.content.slice(0, 80)}`;
      if (artifactCacheRef.current[dedupeKey]) {
         const cached = artifactCacheRef.current[dedupeKey];
         if (cached.event) openWorkEvent(cached.event);
         return cached;
      }
      if (lastArtifactPath === dedupeKey) return null;
      const res = await fetch('/api/artifacts', {
         method: 'POST',
         headers: { 'Content-Type': 'application/json' },
         body: JSON.stringify({
            session_id: sessionId || 'default',
            name: artifact.name,
            lang: artifact.lang,
            content: artifact.content,
            title,
            source: 'assistant-artifact',
            turn_id: turnId,
         })
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.status !== 'success') throw new Error(data?.detail || 'Could not create artifact');
      setLastArtifactPath(dedupeKey);
      artifactCacheRef.current[dedupeKey] = data;
      const artifactPath = String(data?.artifact?.path || data?.event?.path || data?.event?.target || artifact.name);
      const createFileEvent: WorkEvent = {
         ...(data.event || {}),
         id: data?.event?.id || `artifact-${Date.now()}-${artifact.name}`,
         session_id: sessionId || 'default',
         kind: 'file',
         action: 'Create file',
         title: title || `Create ${artifact.name}`,
         target: artifactPath,
         path: artifactPath,
         lang: artifact.lang,
         turn_id: turnId,
         status: data?.event?.status || 'done',
         result: `${artifact.name} created`,
      };
      const verifyCommand = ['python', 'py'].includes(artifact.lang.toLowerCase()) || artifactPath.toLowerCase().endsWith('.py')
         ? `python -m py_compile "${artifactPath}"`
         : '';
      const verifyEvent: WorkEvent | null = data?.verify_event ? normalizeWorkEvent(data.verify_event) : verifyCommand ? {
         id: `verify-${Date.now()}-${artifact.name}`,
         session_id: sessionId || 'default',
         kind: 'command',
         action: 'Run command',
         title: `Verify ${artifact.name}`,
         target: verifyCommand,
         command: verifyCommand,
         turn_id: turnId,
         status: 'ready',
      } : null;
      setWorkEvents(prev => {
         const withoutDuplicate = prev.filter(event => event.id !== createFileEvent.id && String(event.path || event.target || '') !== artifactPath);
         return verifyEvent ? [...withoutDuplicate, createFileEvent, verifyEvent] : [...withoutDuplicate, createFileEvent];
      });
      if (data?.artifact?.name && data?.artifact?.path) {
         artifactPathIndexRef.current[String(data.artifact.name)] = String(data.artifact.path);
      }
      openWorkEvent(createFileEvent);
      if (verifyEvent) {
         runWorkCommand(verifyEvent);
      }
      await loadWorkEvents(sessionId);
      return data;
   };

   const parseWorkActivityLine = (line: string): WorkEvent | null => {
      const trim = String(line || '').trim();
      if (!trim) return null;

      const normalizeEvent = (event: any, fallbackTarget = ''): WorkEvent | null => {
         if (!event || typeof event !== 'object') return null;
         const rawKind = String(event.kind || event.type || '').toLowerCase();
         const rawAction = String(event.action || event.title || '').toLowerCase();
         const rawTool = String(event.tool || event.name || '').toLowerCase();
         const target = event.target || event.path || event.command || event.query || event.tool || event.name || event.result || fallbackTarget;
         if (!target) return null;
         const targetText = String(target || '').toLowerCase();
         const role = String(event.role || '').toLowerCase();
         const isTodoPlan = role === 'planning_artifact' || targetText.endsWith('todo.md');
         const kind = isTodoPlan || rawKind.includes('todo') ? 'todo'
            : rawKind.includes('rag') || rawAction.includes('rag') || rawAction.includes('retrieval') || rawTool.includes('atlas') ? 'rag'
            : rawKind.includes('mcp') || rawAction.includes('mcp') || rawTool.includes('mcp') ? 'mcp'
            : rawKind.includes('browser') || rawAction.includes('browser') || rawTool.includes('browser') ? 'browser'
            : rawKind.includes('search') || rawKind.includes('web') || rawAction.includes('search') || rawTool.includes('search') || rawTool.includes('grep') || rawTool.includes('glob') ? 'search'
            : rawKind.includes('command') || rawKind.includes('bash') || rawKind.includes('terminal') || rawKind.includes('shell') || event.command ? 'command'
            : rawKind.includes('file') || rawAction.includes('file') || rawTool.includes('file') || event.path ? 'file'
            : rawKind.includes('skill') ? 'skill'
            : rawKind.includes('plugin') ? 'plugin'
            : rawKind.includes('provider') ? 'provider'
            : rawKind.includes('hive') || rawKind.includes('agent') || rawKind.includes('worker') ? 'hive'
            : rawKind.includes('tool') || event.tool ? 'tool'
            : 'tool';
         const action = event.action || (
            kind === 'file' ? (rawAction.includes('create') ? 'Create file' : rawAction.includes('read') ? 'Read file' : 'Edit file') :
            kind === 'search' ? 'Searching' :
            kind === 'rag' ? 'RAG' :
            kind === 'mcp' ? 'MCP' :
            kind === 'browser' ? 'Browser' :
            kind === 'command' ? 'Run command' :
            kind === 'skill' ? 'Skill' :
            kind === 'plugin' ? 'Plugin' :
            kind === 'provider' ? 'Provider' :
            kind === 'hive' ? 'Delegate task' :
            kind === 'todo' ? 'Todo' :
            'Use tool'
         );
         return {
            ...event,
            kind,
            action,
            target,
            status: event.status || (/error|fail/i.test(String(event.output || target)) ? 'error' : 'done'),
         };
      };

      const structured = trim.match(/^\[NEXUS_ACTIVITY\]:\s*(\{.*\})$/i);
      if (structured) {
         try {
            return normalizeEvent(JSON.parse(structured[1]), trim);
         } catch {
            return null;
         }
      }

      return null;
   };

   const getWorkActivityIcon = (kind = '') => {
      const normalized = String(kind || '').toLowerCase();
      return normalized === 'file' ? Edit2
         : normalized === 'search' ? Search
         : normalized === 'command' ? TerminalSquare
         : normalized === 'browser' ? Monitor
         : normalized === 'rag' ? BrainCircuit
         : normalized === 'mcp' ? Database
         : normalized === 'reflection' ? BrainCircuit
         : normalized === 'provider' ? Cpu
         : normalized === 'plugin' ? Puzzle
         : normalized === 'skill' ? GraduationCap
         : normalized === 'hive' ? Activity
         : normalized === 'todo' ? CheckCircle2
         : Wrench;
   };

   const shortWorkTarget = (value = '', maxLength = 72) => {
      const compact = String(value || '').replace(/\s+/g, ' ').trim();
      if (!compact) return '';
      return compact.length > maxLength ? `${compact.slice(0, maxLength - 3)}...` : compact;
   };

   const fileDisplayName = (value = '') => {
      const clean = String(value || '').replace(/^["']|["']$/g, '').replace(/\\/g, '/').trim();
      return clean.split('/').filter(Boolean).pop() || clean;
   };

   const getWorkActivityLabel = (row: any) => {
      const kind = String(row?.kind || row?.type || '').toLowerCase();
      const action = String(row?.action || row?.title || row?.tool || '').toLowerCase();
      const target = String(row?.path || row?.target || '').toLowerCase();
      if (kind === 'todo') return 'Planning';
      if (String(row?.role || '').toLowerCase() === 'planning_artifact' || target.endsWith('todo.md')) return 'Planning';
      if (kind === 'search') return 'Searching';
      if (kind === 'rag') return 'Reading context';
      if (kind === 'browser') return 'Browsing';
      if (kind === 'command') return 'Run command';
      if (kind === 'file') {
         if (action.includes('delete') || action.includes('remove')) return 'Delete file';
         if (action.includes('create')) return 'Create file';
         if (action.includes('read') || action.includes('view')) return 'Read file';
         if (action.includes('update')) return 'Update file';
         return 'Edit file';
      }
      if (kind === 'hive') return 'Delegating';
      if (kind === 'mcp') return 'Using MCP';
      if (kind === 'provider') return 'Checking provider';
      if (kind === 'skill') return 'Using skill';
      if (kind === 'plugin') return 'Using plugin';
      if (kind === 'tool') {
         if (action.includes('read')) return 'Reading';
         if (action.includes('list') || action.includes('glob')) return 'Listing';
         if (action.includes('grep') || action.includes('find') || action.includes('search')) return 'Searching';
         if (action.includes('run') || action.includes('execute')) return 'Running tool';
         return 'Using tool';
      }
      return 'Working';
   };

   const getWorkActivityTarget = (row: any) => {
      const kind = String(row?.kind || row?.type || '').toLowerCase();
      const role = String(row?.role || '').toLowerCase();
      if (String(row?.kind || row?.type || '').toLowerCase() === 'todo') {
         return 'todo.md';
      }
      if (role === 'planning_artifact' || String(row?.path || row?.target || '').toLowerCase().endsWith('todo.md')) {
         return 'todo.md';
      }
      if (kind === 'file') {
         return fileDisplayName(row?.path || row?.target || 'file');
      }
      if (kind === 'command') {
         return shortWorkTarget(resolveWorkActivityTarget(row), 96);
      }
      const raw = resolveWorkActivityTarget(row);
      return shortWorkTarget(raw);
   };

   const normalizeWorkEvent = (event: WorkEvent): WorkEvent => {
      const kind = String(event?.kind || event?.type || '').toLowerCase();
      const action = String(event?.action || event?.title || '').toLowerCase();
      const tool = String(event?.tool || event?.name || '').toLowerCase();
      const rawTarget = String(event?.path || event?.target || '').toLowerCase();
      const role = String(event?.role || '').toLowerCase();
      const isTodoPlan = role === 'planning_artifact' || rawTarget.endsWith('todo.md');
      const normalizedKind = isTodoPlan || kind.includes('todo') ? 'todo' :
         kind === 'artifact' ? 'file' :
         kind.includes('rag') || action.includes('rag') || action.includes('retrieval') || tool.includes('atlas') ? 'rag' :
         kind.includes('mcp') || action.includes('mcp') || tool.includes('mcp') ? 'mcp' :
         kind.includes('browser') || action.includes('browser') || tool.includes('browser') ? 'browser' :
         kind.includes('search') || kind.includes('web') || action.includes('search') || tool.includes('search') || tool.includes('grep') || tool.includes('glob') ? 'search' :
         kind.includes('command') || kind.includes('bash') || kind.includes('terminal') || kind.includes('shell') || event?.command ? 'command' :
         kind.includes('file') || action.includes('file') || tool.includes('file') || event?.path ? 'file' :
         kind.includes('skill') ? 'skill' :
         kind.includes('plugin') ? 'plugin' :
         kind.includes('provider') ? 'provider' :
         kind.includes('hive') || kind.includes('agent') || kind.includes('worker') ? 'hive' :
         kind || 'tool';
      const normalizedAction =
         normalizedKind === 'file' && (action.includes('delete') || action.includes('remove')) ? 'Delete file' :
         normalizedKind === 'file' && action.includes('artifact') ? 'Create file' :
         normalizedKind === 'file' && action.includes('create') ? 'Create file' :
         normalizedKind === 'file' && action.includes('write') ? 'Create file' :
         normalizedKind === 'file' && action.includes('read') ? 'Read file' :
         normalizedKind === 'file' && action.includes('view') ? 'Read file' :
         normalizedKind === 'file' && action.includes('update') ? 'Update file' :
         normalizedKind === 'file' && action.includes('edit') ? 'Edit file' :
         normalizedKind === 'search' ? 'Searching' :
         normalizedKind === 'rag' ? 'Read context' :
         normalizedKind === 'mcp' ? 'Use MCP' :
         normalizedKind === 'browser' ? 'Browse' :
         normalizedKind === 'command' ? 'Run command' :
         normalizedKind === 'hive' ? 'Delegate task' :
         normalizedKind === 'todo' ? 'Plan work' :
         normalizedKind === 'skill' ? 'Use skill' :
         normalizedKind === 'plugin' ? 'Use plugin' :
         normalizedKind === 'provider' ? 'Check provider' :
         normalizedKind === 'tool' ? 'Use tool' :
         event.action || event.title || (normalizedKind === 'command' ? 'Run command' : 'Use tool');
      const inferredPhaseIndex = Number(event.phase_index) || undefined;
      const phase = event.phase || event.phase_title || undefined;
      return {
         ...event,
         kind: normalizedKind,
         action: normalizedAction,
         phase,
         phase_index: inferredPhaseIndex,
         target: normalizedKind === 'todo'
            ? (event.target || (Array.isArray(event.items) ? event.items.map((item: any, index: number) => `${index + 1}. ${item}`).join('; ') : '') || event.task || '')
            : event.target || event.path || event.command || event.tool || event.title || '',
      };
   };

   const resolveWorkActivityTarget = (row: any) => {
      const raw = String(row?.target || row?.path || row?.command || row?.query || row?.result || row?.tool || 'open detail').trim();
      for (const [name, path] of Object.entries(artifactPathIndexRef.current)) {
         if (!name || !path || !raw.includes(name) || raw.includes(path)) continue;
         const safePath = path.includes(' ') ? `"${path}"` : path;
         return raw.replace(new RegExp(`(?<![\\w./\\\\-])${name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}(?![\\w./\\\\-])`, 'g'), safePath);
      }
      return raw;
   };

   const loadWorkEvents = async (sessionId = currentSessionId, turnId = currentTurnId) => {
      try {
         const turnParam = turnId ? `&turn_id=${encodeURIComponent(turnId)}` : '';
         const res = await fetch(`/api/work-events?session_id=${encodeURIComponent(sessionId || 'default')}&limit=200${turnParam}`, {
            cache: 'no-store',
            signal: AbortSignal.timeout(8000)
         });
         if (!res.ok) throw new Error(`HTTP ${res.status}`);
         const data = await res.json();
         const events = Array.isArray(data.events) ? data.events.map(normalizeWorkEvent) : [];
         events.forEach((event: any) => {
            const path = String(event?.path || event?.target || '').trim();
            const name = path.replace(/\\/g, '/').split('/').pop();
            if (String(event?.kind || '').toLowerCase() === 'file' && name && /\.[a-z0-9]+$/i.test(name)) {
               artifactPathIndexRef.current[name] = path;
            }
         });
         setWorkEvents(events);
         setSelectedWorkEvent(current => {
            if (!current) return null;
            const updated = events.find((e: any) => e.id === current.id);
            return updated ? { ...current, ...updated } : current;
         });
      } catch (err) {
         console.error("Failed to fetch work events:", err);
      }
   };

   useEffect(() => {
      if (!isStreaming) return;
      const sessionId = currentSessionId || 'default';
      const turnId = currentTurnId;
      loadWorkEvents(sessionId, turnId);
      const interval = window.setInterval(() => loadWorkEvents(sessionId, turnId), 1200);
      return () => window.clearInterval(interval);
   }, [isStreaming, currentSessionId, currentTurnId]);

   useEffect(() => {
      if (canvasPlaybackTime === null) {
         setCanvasPlaybackTurnId('');
      }
   }, [canvasPlaybackTime]);

   useEffect(() => {
      if (messages.length !== lastMessageCountRef.current) {
         lastMessageCountRef.current = messages.length;
         messagesEndRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
      }
   }, [messages.length]);

   useEffect(() => {
      if (selectedSource) {
         const targetPath = selectedSource.path || `workspace/uploads/${selectedSource.name}`;
         
         if (selectedSource.type === 'File') {
            const controller = new AbortController();
            fetch(`/api/file-preview?path=${encodeURIComponent(targetPath)}`, { signal: controller.signal })
               .then(async response => {
                  const data = await response.json().catch(() => ({}));
                  if (!response.ok) throw new Error(data?.detail || `HTTP ${response.status}`);
                  setCanvasPreview(data);
                  setCanvasPreviewError('');
               })
               .catch(error => {
                  if (error?.name === 'AbortError') return;
                  setCanvasPreview({
                     path: targetPath,
                     name: selectedSource.name,
                     ext: selectedSource.name.split('.').pop() || 'pdf',
                     content: `[Source Document]\nName: ${selectedSource.name}\nType: File\nPath: ${targetPath}\n\nThe saved source file could not be previewed in the canvas.`,
                  });
                  setCanvasPreviewError('');
               });
            return () => controller.abort();
         } else {
            const controller = new AbortController();
            fetch(`/api/file-preview?path=${encodeURIComponent(targetPath)}`, { signal: controller.signal })
               .then(async response => {
                  const data = await response.json().catch(() => ({}));
                  if (!response.ok) throw new Error(data?.detail || `HTTP ${response.status}`);
                  setCanvasPreview(data);
                  setCanvasPreviewError('');
               })
               .catch(error => {
                  if (error?.name === 'AbortError') return;
                  setCanvasPreview({
                     path: targetPath,
                     name: selectedSource.name,
                     ext: 'txt',
                     content: `[Website Source]\nName: ${selectedSource.name}\nURL: ${selectedSource.url || 'Unknown'}\n\nThe saved source file could not be previewed.`,
                  });
                  setCanvasPreviewError(error?.message || 'Could not preview website source.');
               });
            return () => controller.abort();
         }
         return;
      }

      if (selectedWorkEvent && !isRealPreviewFileEvent(selectedWorkEvent)) {
         setCanvasPreview(null);
         setCanvasPreviewError('');
         return;
      }
      const previewTarget = selectedWorkEvent
         ? resolveWorkActivityTarget(selectedWorkEvent)
         : getCanvasPreviewTargetFromMessages();
      if (!previewTarget) {
         setCanvasPreview(null);
         setCanvasPreviewError('');
         return;
      }

      const target = previewTarget.replace(/\\/g, '/').split(/\s+/)[0];
      const controller = new AbortController();
      fetch(`/api/file-preview?path=${encodeURIComponent(target)}`, { signal: controller.signal })
         .then(async response => {
            const data = await response.json().catch(() => ({}));
            if (!response.ok) throw new Error(data?.detail || `HTTP ${response.status}`);
            setCanvasPreview(data);
            setCanvasPreviewError('');
         })
         .catch(error => {
            if (error?.name === 'AbortError') return;
            setCanvasPreview(null);
            setCanvasPreviewError(String(error?.message || 'Could not preview file'));
         });

      return () => controller.abort();
    }, [messages, canvasPlaybackTime, selectedWorkEvent, selectedSource]);

   useEffect(() => {
      const targetTurnId = canvasPlaybackTurnId || String(selectedWorkEvent?.turn_id || '');
      const turnEvents = targetTurnId
         ? workEvents.filter(e => e.turn_id === targetTurnId)
         : workEvents.filter(e => !e.turn_id || e.turn_id === currentTurnId);
      const activeIndex = (() => {
         if (canvasPlaybackTime === null || turnEvents.length === 0) {
            return turnEvents.length - 1;
         }
         // Convert virtual seconds back to step index
         const stepIndex = Math.min(timelineWorkActivities.length - 1, Math.floor(canvasPlaybackTime / 5));
         const activeEvent = timelineWorkActivities[stepIndex];
         if (!activeEvent) return turnEvents.length - 1;
         const index = turnEvents.indexOf(activeEvent);
         return index >= 0 ? index : turnEvents.length - 1;
      })();
      const activeCanvasWorkEvent = canvasPlaybackTime !== null
         ? turnEvents[activeIndex] || null
         : selectedWorkEvent || turnEvents[activeIndex] || null;
      if (!activeCanvasWorkEvent) {
         setCanvasViewMode('source');
         return;
      }
      const isHtmlOrSvg = activeCanvasWorkEvent.lang === 'html' || 
                          activeCanvasWorkEvent.lang === 'svg' || 
                          String(activeCanvasWorkEvent.path || activeCanvasWorkEvent.target || '').toLowerCase().endsWith('.html') ||
                          String(activeCanvasWorkEvent.path || activeCanvasWorkEvent.target || '').toLowerCase().endsWith('.svg');
      const isRunning = String(activeCanvasWorkEvent.status || '').toLowerCase() === 'running';
      if (isHtmlOrSvg && isRunning) {
         setCanvasViewMode('preview');
      } else {
         setCanvasViewMode('source');
      }
   }, [selectedWorkEvent, workEvents, canvasPlaybackTime, canvasPlaybackTurnId, currentTurnId]);

   useEffect(() => {
      if (drawerType === 'none') return;
      const timer = window.setTimeout(() => composerInputRef.current?.focus(), 120);
      return () => window.clearTimeout(timer);
   }, [drawerType]);

   useEffect(() => {
      return () => {
         screenStreamRef.current?.getTracks().forEach(track => track.stop());
         recognitionRef.current?.abort?.();
      };
   }, []);

   useEffect(() => {
      if (!state?.reminders?.length) return;
      const now = Date.now() / 1000;
      state.reminders.forEach(reminder => {
         if (!reminder.id || reminder.done || !reminder.due_at || reminder.due_at > now) return;
         if (notifiedReminderIds.current.has(reminder.id)) return;
         notifiedReminderIds.current.add(reminder.id);
         if ("Notification" in window) {
            if (Notification.permission === "granted") {
               new Notification("NEXUS Reminder", { body: reminder.text });
            } else if (Notification.permission === "default") {
               Notification.requestPermission().then(permission => {
                  if (permission === "granted") {
                     new Notification("NEXUS Reminder", { body: reminder.text });
                  }
               });
            }
         }
      });
   }, [state?.reminders]);

   useEffect(() => {
      localStorage.setItem('nexus.brandName', brandName);
      localStorage.setItem('nexus.brandMark', brandMark);
      localStorage.setItem('nexus.assistantAvatar', assistantAvatar);
      localStorage.setItem('nexus.userAvatar', userAvatar);

      const displayName = brandName.trim() || 'NEXUS';
      const displayMark = brandMark.trim() || '⚡';
      document.title = `${displayName} AI gui`;

      const faviconSvg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" fill="#09090b"/><text x="32" y="43" text-anchor="middle" font-size="34">${displayMark}</text></svg>`;
      let favicon = document.querySelector<HTMLLinkElement>('link[rel="icon"]');
      if (!favicon) {
         favicon = document.createElement('link');
         favicon.rel = 'icon';
         document.head.appendChild(favicon);
      }
      favicon.href = `data:image/svg+xml,${encodeURIComponent(faviconSvg)}`;
   }, [brandName, brandMark, assistantAvatar, userAvatar]);

   useEffect(() => {
      localStorage.setItem('nexus.interfaceMode', interfaceMode);
      const root = document.documentElement;
      const setThemeVars = (vars: Record<string, string>) => {
         Object.entries(vars).forEach(([key, value]) => root.style.setProperty(key, value));
      };
      const lightActivity = {
         '--assistant-bubble-bg': '#ffffff',
         '--assistant-bubble-border': 'rgba(15, 23, 42, 0.08)',
         '--assistant-bubble-text': '#1f2937',
         '--user-bubble-bg': 'rgba(59, 130, 246, 0.08)',
         '--user-bubble-border': 'rgba(59, 130, 246, 0.18)',
         '--user-bubble-text': '#0f172a',
         '--avatar-user-bg': 'rgba(59, 130, 246, 0.10)',
         '--avatar-user-border': 'rgba(59, 130, 246, 0.22)',
         '--avatar-assistant-bg': 'rgba(16, 185, 129, 0.10)',
         '--avatar-assistant-border': 'rgba(16, 185, 129, 0.22)',
         '--work-bubble-bg': '#ffffff',
         '--work-bubble-bg-hover': '#f0f7ff',
         '--work-bubble-plan-bg': '#eff6ff',
         '--work-bubble-border': 'rgba(59, 130, 246, 0.16)',
         '--work-bubble-border-hover': 'rgba(59, 130, 246, 0.34)',
         '--work-bubble-text': '#1e293b',
         '--work-bubble-muted': '#64748b',
         '--work-bubble-code-bg': 'rgba(59, 130, 246, 0.07)',
         '--work-bubble-code-text': '#1d4ed8',
         '--work-bubble-code-border': 'rgba(59, 130, 246, 0.16)',
         '--work-bubble-icon-bg': 'rgba(59, 130, 246, 0.10)',
         '--work-bubble-icon-border': 'rgba(59, 130, 246, 0.22)',
         '--work-bubble-icon-text': '#3b82f6',
         '--work-bubble-shadow': '0 2px 8px rgba(15, 23, 42, 0.06)'
      };
      const darkActivity = {
         '--assistant-bubble-bg': 'rgba(255, 255, 255, 0.02)',
         '--assistant-bubble-border': 'rgba(255, 255, 255, 0.06)',
         '--assistant-bubble-text': '#f3f4f6',
         '--user-bubble-bg': 'rgba(59, 130, 246, 0.15)',
         '--user-bubble-border': 'rgba(59, 130, 246, 0.24)',
         '--user-bubble-text': '#f3f4f6',
         '--avatar-user-bg': 'rgba(59, 130, 246, 0.10)',
         '--avatar-user-border': 'rgba(59, 130, 246, 0.22)',
         '--avatar-assistant-bg': 'rgba(16, 185, 129, 0.10)',
         '--avatar-assistant-border': 'rgba(16, 185, 129, 0.22)',
         '--work-bubble-bg': 'rgba(15, 23, 42, 0.78)',
         '--work-bubble-bg-hover': 'rgba(30, 41, 59, 0.86)',
         '--work-bubble-plan-bg': 'rgba(20, 36, 61, 0.86)',
         '--work-bubble-border': 'rgba(148, 163, 184, 0.20)',
         '--work-bubble-border-hover': 'rgba(96, 165, 250, 0.44)',
         '--work-bubble-text': '#f8fafc',
         '--work-bubble-muted': '#cbd5e1',
         '--work-bubble-code-bg': 'rgba(2, 6, 23, 0.72)',
         '--work-bubble-code-text': '#bfdbfe',
         '--work-bubble-code-border': 'rgba(96, 165, 250, 0.24)',
         '--work-bubble-icon-bg': 'rgba(96, 165, 250, 0.12)',
         '--work-bubble-icon-border': 'rgba(96, 165, 250, 0.26)',
         '--work-bubble-icon-text': '#bfdbfe',
         '--work-bubble-shadow': '0 8px 24px rgba(2, 6, 23, 0.18)'
      };
      if (interfaceMode === 'light') {
         root.style.setProperty('--bg-dark', '#f8fafc');
         root.style.setProperty('--sidebar-bg', '#ffffff');
         root.style.setProperty('--card-bg', '#ffffff');
         root.style.setProperty('--card-hover-bg', '#f1f5f9');
         root.style.setProperty('--text-main', '#0f172a');
         root.style.setProperty('--text-muted', '#64748b');
         root.style.setProperty('--border-dim', '#cbd5e1');
         root.style.setProperty('--border-focus', '#94a3b8');
         setThemeVars(lightActivity);
      } else if (interfaceMode === 'white') {
         root.style.setProperty('--bg-dark', '#ffffff');
         root.style.setProperty('--sidebar-bg', '#fafafa');
         root.style.setProperty('--card-bg', '#fafafa');
         root.style.setProperty('--card-hover-bg', '#f5f5f5');
         root.style.setProperty('--text-main', '#000000');
         root.style.setProperty('--text-muted', '#737373');
         root.style.setProperty('--border-dim', '#e5e5e5');
         root.style.setProperty('--border-focus', '#d4d4d4');
         setThemeVars({
            ...lightActivity,
            '--assistant-bubble-bg': '#ffffff',
            '--work-bubble-bg': '#ffffff',
            '--work-bubble-bg-hover': '#fafafa',
            '--work-bubble-plan-bg': '#f8fafc',
            '--work-bubble-border': 'rgba(15, 23, 42, 0.12)'
         });
      } else if (interfaceMode === 'grey') {
         root.style.setProperty('--bg-dark', '#18181c');
         root.style.setProperty('--sidebar-bg', '#222226');
         root.style.setProperty('--card-bg', '#222226');
         root.style.setProperty('--card-hover-bg', '#2e2e34');
         root.style.setProperty('--text-main', '#f1f1f5');
         root.style.setProperty('--text-muted', '#9e9ea7');
         root.style.setProperty('--border-dim', '#2e2e34');
         root.style.setProperty('--border-focus', '#44444c');
         setThemeVars({
            ...darkActivity,
            '--assistant-bubble-bg': 'rgba(255, 255, 255, 0.035)',
            '--assistant-bubble-border': 'rgba(255, 255, 255, 0.08)',
            '--work-bubble-bg': 'rgba(34, 34, 38, 0.92)',
            '--work-bubble-bg-hover': 'rgba(46, 46, 52, 0.96)',
            '--work-bubble-plan-bg': 'rgba(38, 45, 58, 0.94)',
            '--work-bubble-border': 'rgba(158, 158, 167, 0.22)'
         });
      } else if (interfaceMode === 'night') {
         root.style.setProperty('--bg-dark', '#050510');
         root.style.setProperty('--sidebar-bg', '#0a0a20');
         root.style.setProperty('--card-bg', '#0a0a20');
         root.style.setProperty('--card-hover-bg', '#121235');
         root.style.setProperty('--text-main', '#4ade80');
         root.style.setProperty('--text-muted', '#50755f');
         root.style.setProperty('--border-dim', '#121235');
         root.style.setProperty('--border-focus', '#202055');
         setThemeVars({
            ...darkActivity,
            '--assistant-bubble-bg': 'rgba(10, 20, 16, 0.72)',
            '--assistant-bubble-border': 'rgba(74, 222, 128, 0.16)',
            '--assistant-bubble-text': '#d1fae5',
            '--user-bubble-bg': 'rgba(59, 130, 246, 0.10)',
            '--work-bubble-bg': 'rgba(8, 18, 26, 0.88)',
            '--work-bubble-bg-hover': 'rgba(13, 31, 39, 0.94)',
            '--work-bubble-plan-bg': 'rgba(12, 30, 31, 0.92)',
            '--work-bubble-border': 'rgba(74, 222, 128, 0.18)',
            '--work-bubble-border-hover': 'rgba(74, 222, 128, 0.34)',
            '--work-bubble-code-bg': 'rgba(5, 12, 18, 0.82)',
            '--work-bubble-code-text': '#86efac',
            '--work-bubble-code-border': 'rgba(74, 222, 128, 0.18)',
            '--work-bubble-icon-bg': 'rgba(74, 222, 128, 0.10)',
            '--work-bubble-icon-border': 'rgba(74, 222, 128, 0.20)',
            '--work-bubble-icon-text': '#4ade80'
         });
      } else { // dark
         root.style.setProperty('--bg-dark', '#09090b');
         root.style.setProperty('--sidebar-bg', '#18181b');
         root.style.setProperty('--card-bg', '#18181b');
         root.style.setProperty('--card-hover-bg', '#27272a');
         root.style.setProperty('--text-main', '#fafafa');
         root.style.setProperty('--text-muted', '#a1a1aa');
         root.style.setProperty('--border-dim', '#27272a');
         root.style.setProperty('--border-focus', '#3f3f46');
         setThemeVars(darkActivity);
      }
   }, [interfaceMode]);

   useEffect(() => {
      localStorage.setItem('nexus.accentColor', accentColor);
      document.documentElement.style.setProperty('--accent-blue', accentColor);
   }, [accentColor]);

   useEffect(() => {
      localStorage.setItem('nexus.showChatAvatars', String(showChatAvatars));
   }, [showChatAvatars]);

   useEffect(() => {
      localStorage.setItem('nexus.showLogoInHeader', String(showLogoInHeader));
   }, [showLogoInHeader]);

   useEffect(() => {
      localStorage.setItem('nexus.showLogoMark', String(showLogoMark));
   }, [showLogoMark]);

   const hasLiveScreenShare = () => {
      return !!screenStreamRef.current?.getVideoTracks().some(track => track.readyState === 'live');
   };

   const ensureScreenShare = async () => {
      setScreenShareError('');

      if (hasLiveScreenShare()) {
         setScreenSharing(true);
         composerInputRef.current?.focus();
         return;
      }

      if (!navigator.mediaDevices?.getDisplayMedia) {
         setScreenShareError('Screen share is not supported in this browser.');
         return;
      }

      try {
         const stream = await navigator.mediaDevices.getDisplayMedia({
            video: { displaySurface: 'monitor' },
            audio: false
         } as DisplayMediaStreamOptions);

         screenStreamRef.current = stream;
         setScreenSharing(true);
         stream.getTracks().forEach(track => {
            track.onended = () => {
               if (!hasLiveScreenShare()) {
                  screenStreamRef.current = null;
                  setScreenSharing(false);
               }
            };
         });
         composerInputRef.current?.focus();
      } catch (error: any) {
         const isUserCancel = error?.name === 'NotAllowedError' || error?.name === 'AbortError';
         setScreenShareError(isUserCancel ? '' : 'Could not start screen share.');
         setScreenSharing(false);
      }
   };

   const stopScreenShare = () => {
      screenStreamRef.current?.getTracks().forEach(track => track.stop());
      screenStreamRef.current = null;
      setScreenSharing(false);
      setScreenShareError('');
   };

   const speakAssistantReply = (text: string) => {
      if (!('speechSynthesis' in window)) return;
      const clean = cleanAssistantText(text).replace(/\s+/g, ' ').trim();
      if (!clean) return;
      window.speechSynthesis.cancel();
      const utterance = new SpeechSynthesisUtterance(clean.slice(0, 700));
      utterance.rate = 1.05;
      utterance.pitch = 1;
      window.speechSynthesis.speak(utterance);
   };

   const handleSend = async (overridePrompt?: string, options?: { voiceMode?: boolean }) => {
      const prompt = (overridePrompt ?? inputValue).trim();
      if (!prompt && uploadedFiles.length === 0) return;

      const sessionId = currentSessionId || `session_${Date.now()}`;
      if (!currentSessionId) {
         currentSessionIdRef.current = sessionId;
         setCurrentSessionId(sessionId);
      }
      const turnStartedAt = Date.now() / 1000;
      const turnId = `${sessionId}-${Math.round(turnStartedAt * 1000)}-${Math.random().toString(36).slice(2, 8)}`;
      setWorkflowStartedAt(turnStartedAt);
      setCurrentTurnId(turnId);
      setWorkEvents([]);
      setCommandRuns({});
      setSelectedSource(null);
      setSelectedWorkEvent(null);
      setCanvasPlaybackTime(null);
      setIsPlaying(false);
      setSessionList(prev => {
         if (prev.some(s => s.id === sessionId)) return prev;
         return [{ id: sessionId, title: cleanUserMessage(prompt) || 'New Chat', updated_at: Date.now() / 1000 }, ...prev];
      });
      const userMsg = { role: 'user', content: prompt };
      const assistantPlaceholder = { role: 'assistant', content: '' };
      setMessagesForSession(sessionId, prev => [...prev, userMsg, assistantPlaceholder]);
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
               session_id: sessionId,
               turn_id: turnId,
               source: 'gui',
               provider: selectedSessionProvider || instanceName || 'openrouter',
               voice_mode: !!options?.voiceMode
            })
         });

         if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            const message = errorData?.message || errorData?.detail || `Chat request failed with HTTP ${response.status}`;
            setMessagesForSession(sessionId, prev => [...prev, { role: 'assistant', content: `NEXUS chat error: ${message}` }]);
            return;
         }

         if (!response.body) return;
         const reader = response.body.getReader();
         const decoder = new TextDecoder();

         let assistantContent = '';

         while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            const chunk = decoder.decode(value);
            if (!chunk.trim()) continue;
            assistantContent += chunk;
            const streamedEvents = chunk
               .split('\n')
               .map(line => parseWorkActivityLine(line))
               .filter(Boolean)
               .map(event => normalizeWorkEvent(event as WorkEvent))
               .filter(event => !isWorkflowBookkeepingEvent(event));
            if (streamedEvents.length > 0) {
               setWorkEvents(prev => {
                  const byId = new Map<string, WorkEvent>();
                  [...prev, ...streamedEvents].forEach(event => {
                     const key = event.id || `${event.kind}|${event.phase_index}|${event.target || event.path || event.command || event.action}`;
                     byId.set(key, event);
                  });
                  return Array.from(byId.values());
               });
            }

            setMessagesForSession(sessionId, prev => {
               const newMsgs = [...prev];
               const lastIndex = newMsgs.length - 1;
               if (lastIndex >= 0 && newMsgs[lastIndex]?.role === 'assistant') {
                  newMsgs[lastIndex] = { role: 'assistant', content: assistantContent };
               } else {
                  newMsgs.push({ role: 'assistant', content: assistantContent });
               }
               return newMsgs;
            });
         }
         const artifact = extractGeneratedArtifact(assistantContent);
         const wantsArtifact = /\b(code|make|create|build|game|app|website|html|canvas|run|play)\b/i.test(prompt);
         if (artifact && wantsArtifact) {
            try {
               const repairedArtifact = repairGeneratedArtifact(artifact, prompt);
               await saveArtifactToCanvas(repairedArtifact, sessionId, `Create ${repairedArtifact.name}`, turnId);
            } catch (artifactErr) {
               console.error("Artifact save error:", artifactErr);
            }
         }
         if (options?.voiceMode) speakAssistantReply(assistantContent);
      } catch (err) {
         console.error("Chat error:", err);
         setBackendOffline(true);
         setSessionNotice({ kind: 'success', message: 'Reconnecting to NEXUS… your chat stayed open.' });
         setInputValue(current => current || prompt);
      } finally {
         setIsStreaming(false);
         fetchSessions(); // Refresh list to update titles/mtime
         loadWorkEvents(sessionId, turnId);
      }
   };

   const handleSourceFileUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
      const files = event.target.files;
      if (!files || files.length === 0) return;
      
      const formData = new FormData();
      Array.from(files).forEach(f => formData.append('files', f));
      
      try {
         const res = await fetch('/api/upload', {
            method: 'POST',
            body: formData,
         });
         const data = await res.json().catch(() => ({}));
         if (res.ok && data.status === 'success') {
            const newSources = Array.isArray(data.sources) ? data.sources.map((source: any) => ({
               id: String(source.id),
               name: String(source.name),
               type: source.type === 'Website' ? 'Website' as const : 'File' as const,
               checked: source.checked !== false,
               path: source.path ? String(source.path) : undefined,
               url: source.url ? String(source.url) : undefined,
            })) : [];
            setSources(prev => [...newSources, ...prev.filter(source => !newSources.some((next: SourceItem) => next.id === source.id))]);
            setSessionNotice({ kind: 'success', message: `Uploaded ${files.length} source file(s) successfully.` });
         } else {
            throw new Error(data.detail || 'Upload failed');
         }
      } catch (err: any) {
         console.error("Upload source error:", err);
         setSessionNotice({ kind: 'error', message: err?.message || 'Upload source failed' });
      }
   };

   const importWebsiteSource = () => {
      setSourceImportUrl('');
      setSourceImportError('');
      setSourceImportOpen(true);
   };

   const submitWebsiteSource = async () => {
      const url = sourceImportUrl.trim();
      if (!url) {
         setSourceImportError('Enter a website URL.');
         return;
      }
      setSourceImportBusy(true);
      setSourceImportError('');
      try {
         const res = await fetch('/api/sources/website', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url }),
         });
         const data = await res.json().catch(() => ({}));
         if (!res.ok || data.status !== 'success') throw new Error(data?.detail || 'Website import failed');
         const source = data.source;
         const newSource: SourceItem = {
            id: String(source.id),
            name: String(source.name),
            type: source.type === 'Website' ? 'Website' : 'File',
            checked: source.checked !== false,
            path: source.path ? String(source.path) : undefined,
            url: source.url ? String(source.url) : undefined,
         };
         setSources(prev => [newSource, ...prev.filter(item => item.id !== newSource.id)]);
         setSelectedSource(newSource);
         setSelectedWorkEvent(null);
         setDrawerType('canvas');
         setSourceImportOpen(false);
         setSourceImportUrl('');
         setSessionNotice({ kind: 'success', message: 'Website source imported and saved to Library.' });
      } catch (err: any) {
         setSourceImportError(err?.message || 'Website import failed.');
      } finally {
         setSourceImportBusy(false);
      }
   };

   const handleSourceAction = async (action: 'reparse' | 'deep-reparse' | 'delete', id: string, name: string) => {
      if (action === 'delete') {
         try {
            const res = await fetch(`/api/sources/${encodeURIComponent(id)}`, { method: 'DELETE' });
            if (!res.ok) {
               const data = await res.json().catch(() => ({}));
               throw new Error(data?.detail || `HTTP ${res.status}`);
            }
            setSources(prev => prev.filter(s => s.id !== id));
            if (selectedSource?.id === id) {
               setSelectedSource(null);
               setCanvasPreview(null);
            }
            setSessionNotice({ kind: 'success', message: `Source "${name}" removed.` });
         } catch (err: any) {
            setSessionNotice({ kind: 'error', message: err?.message || `Could not remove "${name}".` });
         }
      } else if (action === 'reparse') {
         setSessionNotice({ kind: 'success', message: `Reparse is queued for "${name}".` });
      } else if (action === 'deep-reparse') {
         setSessionNotice({ kind: 'success', message: `Deep reparse is queued for "${name}".` });
      }
   };

   const renameSource = async (id: string, newName: string) => {
      if (!newName.trim()) return;
      try {
         const res = await fetch(`/api/sources/${encodeURIComponent(id)}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: newName }),
         });
         const data = await res.json().catch(() => ({}));
         if (!res.ok) throw new Error(data?.detail || `HTTP ${res.status}`);
         const updatedSource = data.source;
         setSources(prev => prev.map(s => s.id === id ? { ...s, name: String(updatedSource?.name || newName) } : s));
         if (selectedSource?.id === id) {
            setSelectedSource(prev => prev ? { ...prev, name: String(updatedSource?.name || newName) } : null);
         }
         setSessionNotice({ kind: 'success', message: `Source renamed to "${newName}".` });
      } catch (err: any) {
         setSessionNotice({ kind: 'error', message: err?.message || 'Could not rename source.' });
      }
      setEditingSourceId(null);
   };

   const handleNewChat = async () => {
       try {
           const res = await fetch('/api/sessions/new', { method: 'POST' });
           const data = await res.json();
           currentSessionIdRef.current = data.id;
           setCurrentSessionId(data.id);
           sessionMessagesCacheRef.current[data.id] = [];
           setMessages([]);
           setWorkEvents([]);
           setCommandRuns({});
           setWorkflowStartedAt(Date.now() / 1000);
           setCurrentTurnId('');
           setSelectedWorkEvent(null);
           setLastArtifactPath('');
           artifactCacheRef.current = {};
           artifactPathIndexRef.current = {};
           setCanvasViewMode('source');
           setInputValue('');
           setActiveTab('session');
           setSessionList(prev => prev.some(s => s.id === data.id) ? prev : [{ id: data.id, title: data.title || 'New Chat', updated_at: Date.now() / 1000 }, ...prev]);
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
                const sid = data.id || id;
                const loadedHistory = Array.isArray(data.history) ? data.history : [];
                const cachedHistory = sessionMessagesCacheRef.current[sid] || [];
                const nextHistory = loadedHistory.length > 0 ? loadedHistory : cachedHistory;
                currentSessionIdRef.current = sid;
                setCurrentSessionId(sid);
                sessionMessagesCacheRef.current[sid] = nextHistory;
                setMessages(nextHistory);
                setWorkflowStartedAt(Date.now() / 1000);
                setCurrentTurnId('');
                setCommandRuns({});
                setSelectedWorkEvent(null);
                setLastArtifactPath('');
                artifactCacheRef.current = {};
                artifactPathIndexRef.current = {};
                setCanvasViewMode('source');
                loadWorkEvents(data.id);
                setActiveTab('session');
                setInputValue('');
            }
        } catch (err) {
            console.error("Load session error:", err);
        }
    };

    const deleteSession = async (id: string) => {
        try {
            const res = await fetch(`/api/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' });
            const data = await res.json().catch(() => ({}));
            if (!res.ok || data.status === 'error') {
               setSessionNotice({
                  kind: 'error',
                  message: data.detail || data.message || `Could not delete chat (HTTP ${res.status})`,
               });
               return;
            }

            if (data.cleared) {
               setSessionList(prev => prev.map(s => (
                  s.id === id ? { ...s, title: 'New Chat', updated_at: Date.now() / 1000 } : s
               )));
               if (currentSessionId === id) {
                  sessionMessagesCacheRef.current[id] = [];
                  setMessages([]);
                  setInputValue('');
                  setActiveTab('session');
               }
               setSessionNotice({ kind: 'success', message: 'Chat cleared.' });
            } else {
               const remainingSessions = sessionList.filter(s => s.id !== id);
               setSessionList(remainingSessions);
               if (currentSessionId === id) {
                  const nextSession = remainingSessions[0];
                  if (nextSession) {
                     await loadSession(nextSession.id);
                  } else {
                     currentSessionIdRef.current = 'default';
                     sessionMessagesCacheRef.current.default = [];
                     setMessages([]);
                     setCurrentSessionId('default');
                     setInputValue('');
                     setActiveTab('session');
                  }
               }
               setSessionNotice({ kind: 'success', message: 'Chat deleted.' });
            }
            await fetchSessions();
        } catch (err) {
           console.error("Delete session error:", err);
           setSessionNotice({ kind: 'error', message: 'Delete failed — is the API running on port 8000?' });
        }
    };

    const renameSession = async (id: string, title: string) => {
        const cleanTitle = title.trim() || 'New Chat';
        setSessionList(prev => prev.map(s => s.id === id ? { ...s, title: cleanTitle } : s));
        try {
            const res = await fetch('/api/sessions/rename', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ id, title: cleanTitle })
            });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            setEditingId(null);
            fetchSessions();
        } catch (err) {
            console.error("Rename session error:", err);
            fetchSessions();
        }
    };

   // MCP Registration State
   const [showAddMcpModal, setShowAddMcpModal] = useState(false);
   const [newMcpName, setNewMcpName] = useState('');
   const [newMcpConfig, setNewMcpConfig] = useState('{\n  \n}');
   const [mcpPanelMode, setMcpPanelMode] = useState<'add' | 'edit'>('add');
   const [mcpPanelError, setMcpPanelError] = useState('');

   const [showProviderPanel, setShowProviderPanel] = useState(false);
   const [selectedProv, setSelectedProv] = useState<any>(null);
   const [providerFamilyName, setProviderFamilyName] = useState('');
   const [instanceName, setInstanceName] = useState('');
   const [apiKey, setApiKey] = useState('');
   const [targetModel, setTargetModel] = useState('');
   const [providerEndpoint, setProviderEndpoint] = useState('');
   const [showApiKey, setShowApiKey] = useState(false);
   const [editingInstanceId, setEditingInstanceId] = useState<string | null>(null);
   const [providerCheck, setProviderCheck] = useState<any>(null);
   const [assetPanel, setAssetPanel] = useState<{
      open: boolean;
      kind: 'skills' | 'tools' | 'plugins';
      mode: 'add' | 'edit';
      id?: string;
      name: string;
      description: string;
      active: boolean;
      configText: string;
      error?: string;
   } | null>(null);
   const [configData, setConfigData] = useState<Record<string, any> | null>(null);
   const [configDraft, setConfigDraft] = useState<Record<string, any> | null>(null);
   const [configSection, setConfigSection] = useState('system');
   const [configSearch, setConfigSearch] = useState('');
   const [configMode, setConfigMode] = useState<'form' | 'json'>('form');
   const [configJsonText, setConfigJsonText] = useState('');
   const [configStatus, setConfigStatus] = useState<{ kind: 'idle' | 'valid' | 'error' | 'saving'; message: string }>({ kind: 'idle', message: 'Not loaded' });
   const [pluginSearch, setPluginSearch] = useState('');
   const [pluginInstallUrl, setPluginInstallUrl] = useState('');
   const [pluginForceInstall, setPluginForceInstall] = useState(false);
   const [pluginEnableAfterInstall, setPluginEnableAfterInstall] = useState(true);
   const [pluginBusy, setPluginBusy] = useState('');
   const [pluginStatus, setPluginStatus] = useState<{ kind: 'idle' | 'valid' | 'error' | 'saving'; message: string }>({ kind: 'idle', message: 'Ready' });

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

   useEffect(() => {
       if (state?.provider_instances && state.provider_instances.length > 0) {
          const hasCurrent = state.provider_instances.some((inst: any) => inst.id === selectedSessionProvider && inst.status === 'ACTIVE');
          if (!hasCurrent) {
             const hasOpenRouter = state.provider_instances.some((inst: any) => inst.id === 'openrouter' && inst.status === 'ACTIVE');
             if (hasOpenRouter) {
                setSelectedSessionProvider('openrouter');
             } else {
                const activeInst = state.provider_instances.find((inst: any) => inst.status === 'ACTIVE');
                if (activeInst) {
                   setSelectedSessionProvider(activeInst.id);
                }
             }
          }
       }
    }, [state?.provider_instances, selectedSessionProvider]);

   async function fetchHistory(sessionId = currentSessionId) {
      try {
         const res = await fetch(`/api/history?session_id=${encodeURIComponent(sessionId || 'default')}`);
         if (!res.ok) throw new Error(`HTTP ${res.status}`);
         const data = await res.json();
         if (Array.isArray(data)) {
            const sid = sessionId || 'default';
            sessionMessagesCacheRef.current[sid] = data;
            if (currentSessionIdRef.current === sid) {
               setMessages(data);
            }
         }
         setBackendOffline(false);
         loadWorkEvents(sessionId);
      } catch (err) {
         setBackendOffline(true);
      }
   }

   async function fetchSessions() {
      try {
         const res = await fetch('/api/sessions');
         if (!res.ok) throw new Error(`HTTP ${res.status}`);
         const data = await res.json();
         if (Array.isArray(data)) {
            setSessionList(data);
         }
         setBackendOffline(false);
      } catch (err) {
         setBackendOffline(true);
      }
   }

   async function syncActiveSession() {
      try {
         const res = await fetch('/api/sessions/active');
         if (!res.ok) return;
         const data = await res.json();
         const activeId = data.session_id || 'default';
         if (activeId && activeId !== currentSessionIdRef.current) {
            currentSessionIdRef.current = activeId;
            setCurrentSessionId(activeId);
            if (Array.isArray(data.history)) {
               sessionMessagesCacheRef.current[activeId] = data.history;
               setMessages(data.history);
            }
            await loadWorkEvents(activeId);
         } else if (Array.isArray(data.history) && activeId === currentSessionIdRef.current) {
            const cached = sessionMessagesCacheRef.current[activeId] || [];
            if (data.history.length > cached.length) {
               sessionMessagesCacheRef.current[activeId] = data.history;
               setMessages(data.history);
               await loadWorkEvents(activeId);
            }
         }
      } catch {
         /* backend may be starting */
      }
   }

   async function refreshEvolutionAudit() {
      setEvolutionRefreshing(true);
      try {
         const res = await fetch(`/api/audit?refresh=true&t=${Date.now()}`, {
            cache: 'no-store',
            signal: AbortSignal.timeout(12000)
         });
         if (!res.ok) throw new Error(`HTTP ${res.status}`);
         const audit = await res.json();
         setState(prev => prev ? { ...prev, audit } : prev);
         setEvolutionUpdatedAt(new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }));
      } catch (err) {
         console.error("Failed to refresh evolution audit:", err);
      } finally {
         setEvolutionRefreshing(false);
      }
   }

   async function runEvolutionControl(action: 'plan' | 'verify') {
      setEvolutionWorking(action);
      setEvolutionAction({ kind: action, message: action === 'plan' ? 'Generating real evolution plan...' : 'Running real verification gates...' });
      try {
         const res = await fetch(`/api/evolution/${action}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: '{}',
            signal: AbortSignal.timeout(action === 'verify' ? 260000 : 45000)
         });
         const data = await res.json().catch(() => ({}));
         if (!res.ok) throw new Error(data?.detail || data?.message || `HTTP ${res.status}`);
         setEvolutionAction({
            kind: action,
            message: data?.message || (action === 'plan' ? 'Evolution plan generated.' : 'Evolution verification completed.'),
            data
         });
         await refreshEvolutionAudit();
      } catch (err: any) {
         setEvolutionAction({ kind: 'error', message: err?.message || `${action} failed.` });
      } finally {
         setEvolutionWorking('');
      }
   }

   const cloneConfig = (value: any) => JSON.parse(JSON.stringify(value ?? {}));
   const configDirty = JSON.stringify(configDraft || {}) !== JSON.stringify(configData || {});
   const hiddenConfigSections = new Set([
      'providers',
      'mcp_servers',
      'custom_tool_configs',
      'custom_tool_descriptions',
      'custom_skill_configs',
      'custom_skill_descriptions',
      'disabled_tools',
      'deleted_tools',
      'disabled_skills',
      'deleted_skills',
      'disabled_plugins',
      'deleted_plugins',
      'voice',
   ]);
   const configSections = configDraft ? Object.keys(configDraft).filter(section => !hiddenConfigSections.has(section)).sort((a, b) => {
      const order = ['system', 'gui', 'vision', 'security', 'memory', 'autonomy', 'context', 'diagnostics', 'storage'];
      const ia = order.indexOf(a);
      const ib = order.indexOf(b);
      if (ia !== -1 || ib !== -1) return (ia === -1 ? 999 : ia) - (ib === -1 ? 999 : ib);
      return a.localeCompare(b);
   }) : [];
   const filteredConfigSections = configSections.filter(section => {
      const needle = configSearch.trim().toLowerCase();
      if (!needle) return true;
      return section.toLowerCase().includes(needle) || JSON.stringify(configDraft?.[section] || {}).toLowerCase().includes(needle);
   });
   const selectedConfigValue = configDraft?.[configSection];

   const currentDashboardConfig = () => ({
      brand_name: brandName,
      brand_mark: brandMark,
      assistant_avatar: assistantAvatar,
      user_avatar: userAvatar,
      accent_color: accentColor,
      interface_mode: interfaceMode,
      sidebar_width: sidebarWidth,
      drawer_width: drawerWidth,
      canvas_width: canvasWidth,
      animations_enabled: true,
   });

   const enrichConfigDefaults = (config: Record<string, any>) => {
      const next = cloneConfig(config || {});
      const voice = next.voice && typeof next.voice === 'object' ? next.voice : {};
      next.voice_input = {
         enabled: voice.enabled ?? false,
         microphone_device: voice.microphone_device ?? null,
         sample_rate: voice.sample_rate ?? 16000,
         record_seconds: voice.record_seconds ?? 60,
         silence_threshold: voice.silence_threshold ?? 0.008,
         min_speech_seconds: voice.min_speech_seconds ?? 0.25,
         silence_timeout_seconds: voice.silence_timeout_seconds ?? 2,
         whisper_model: voice.whisper_model ?? 'models/local/voice/distil-whisper-large-v3',
         whisper_device: voice.whisper_device ?? 'auto',
         whisper_language: voice.whisper_language ?? 'auto',
         whisper_chunk_length_s: voice.whisper_chunk_length_s ?? 15,
         whisper_batch_size: voice.whisper_batch_size ?? 1,
         push_to_talk_key: voice.push_to_talk_key ?? 'none',
         wake_word_enabled: voice.wake_word_enabled ?? false,
         wake_word: voice.wake_word ?? 'nexus',
         require_wake_word: voice.require_wake_word ?? false,
         ...(next.voice_input || {}),
      };
      next.voice_output = {
         enabled: voice.enabled ?? false,
         auto_speak: voice.auto_speak ?? true,
         speaker_device: voice.speaker_device ?? null,
         kitten_model: voice.kitten_model ?? 'KittenML/kitten-tts-micro-0.8',
         voice_name: voice.voice_name ?? 'Jasper',
         speech_speed: voice.speech_speed ?? 1.2,
         volume: voice.volume ?? 1,
         allow_text_fallback: voice.allow_text_fallback ?? true,
         keep_models_loaded: voice.keep_models_loaded ?? true,
         assistant_timeout_seconds: voice.assistant_timeout_seconds ?? 45,
         ...(next.voice_output || {}),
      };
      next.vision = {
         enabled: true,
         camera_enabled: true,
         camera_index: 0,
         default_modes: ['objects'],
         stream_fps_limit: 24,
         capture_width: 1280,
         capture_height: 720,
         backend_detection: true,
         browser_holistic: true,
         webgl_acceleration: true,
         native_acceleration: 'auto',
         model_dir: 'models/local/vision',
         yolo_detect_model: 'models/local/vision/yolo11n.pt',
         yolo_openvino_dir: 'models/local/vision/yolo11n_openvino_model',
         auto_release_camera: true,
         status_endpoint: '/api/vision/status',
         stream_endpoint: '/api/vision/stream',
         ...(next.vision || {}),
      };
      next.memory = {
         persistence: 'atomic_checkpoints',
         vault_mode: 'gravity_rag',
         short_term: {
            enabled: true,
            max_turns: 30,
            max_messages: 120,
            summarize_after_turns: 18,
            keep_recent_results: 8,
         },
         long_term: {
            enabled: true,
            store_sessions: true,
            store_failures: true,
            store_evidence: true,
            retention_days: 365,
         },
         retrieval: {
            enabled: true,
            top_k: 8,
            hybrid_weight: 0.55,
            min_score: 0.12,
         },
         ...(next.memory || {}),
      };
      next.context = {
         zero_token_packets: true,
         auto_compaction: true,
         compaction_threshold_percent: 0.72,
         max_summary_tokens: 6000,
         preserve_code_blocks: true,
         preserve_error_traces: true,
         inject_recent_failures: true,
         ...(next.context || {}),
      };
      next.autonomy = {
         enabled: true,
         max_loop_turns: 8,
         command_risk_threshold: 0.82,
         rollback_before_risky_edits: true,
         evidence_required_for_claims: true,
         auto_recover_failures: true,
         ...(next.autonomy || {}),
      };
      next.diagnostics = {
         compile_python: true,
         validate_yaml: true,
         validate_json: true,
         gui_build: true,
         run_targeted_tests: true,
         max_recent_failures: 12,
         ...(next.diagnostics || {}),
      };
      next.storage = {
         workspace_root: next.system?.workspace_root ?? './workspace',
         logs_dir: 'logs',
         uploads_dir: 'workspace/uploads',
         max_upload_mb: 10,
         cleanup_temp_on_start: false,
         ...(next.storage || {}),
      };
      return next;
   };

   const syncDerivedConfigForSave = (config: any) => {
      const next = cloneConfig(config || {});
      next.voice = {
         ...(next.voice || {}),
         enabled: Boolean(next.voice_input?.enabled || next.voice_output?.enabled),
         microphone_device: next.voice_input?.microphone_device ?? null,
         sample_rate: Number(next.voice_input?.sample_rate ?? 16000),
         record_seconds: Number(next.voice_input?.record_seconds ?? 60),
         silence_threshold: Number(next.voice_input?.silence_threshold ?? 0.008),
         min_speech_seconds: Number(next.voice_input?.min_speech_seconds ?? 0.25),
         silence_timeout_seconds: Number(next.voice_input?.silence_timeout_seconds ?? 2),
         whisper_model: String(next.voice_input?.whisper_model ?? 'models/local/voice/distil-whisper-large-v3'),
         whisper_device: String(next.voice_input?.whisper_device ?? 'auto'),
         whisper_language: String(next.voice_input?.whisper_language ?? 'auto'),
         whisper_chunk_length_s: Number(next.voice_input?.whisper_chunk_length_s ?? 15),
         whisper_batch_size: Number(next.voice_input?.whisper_batch_size ?? 1),
         push_to_talk_key: String(next.voice_input?.push_to_talk_key ?? 'none'),
         wake_word_enabled: Boolean(next.voice_input?.wake_word_enabled),
         wake_word: String(next.voice_input?.wake_word ?? 'nexus'),
         require_wake_word: Boolean(next.voice_input?.require_wake_word),
         auto_speak: Boolean(next.voice_output?.auto_speak),
         speaker_device: next.voice_output?.speaker_device ?? null,
         kitten_model: String(next.voice_output?.kitten_model ?? 'KittenML/kitten-tts-micro-0.8'),
         voice_name: String(next.voice_output?.voice_name ?? 'Jasper'),
         speech_speed: Number(next.voice_output?.speech_speed ?? 1.2),
         volume: Number(next.voice_output?.volume ?? 1),
         allow_text_fallback: Boolean(next.voice_output?.allow_text_fallback ?? true),
         keep_models_loaded: Boolean(next.voice_output?.keep_models_loaded ?? true),
         assistant_timeout_seconds: Number(next.voice_output?.assistant_timeout_seconds ?? 45),
      };
      if (next.storage?.workspace_root && next.system) {
         next.system.workspace_root = next.storage.workspace_root;
      }
      return next;
   };

   const applyDashboardConfig = (dashboardConfig: any) => {
      if (!dashboardConfig || typeof dashboardConfig !== 'object') return;
      if (typeof dashboardConfig.brand_name === 'string') setBrandName(dashboardConfig.brand_name);
      if (typeof dashboardConfig.brand_mark === 'string') setBrandMark(dashboardConfig.brand_mark);
      if (typeof dashboardConfig.assistant_avatar === 'string') setAssistantAvatar(dashboardConfig.assistant_avatar);
      if (typeof dashboardConfig.user_avatar === 'string') setUserAvatar(dashboardConfig.user_avatar);
      if (typeof dashboardConfig.accent_color === 'string') {
         setAccentColor(dashboardConfig.accent_color);
         document.documentElement.style.setProperty('--accent-blue', dashboardConfig.accent_color);
      }
      if (typeof dashboardConfig.interface_mode === 'string') setInterfaceMode(dashboardConfig.interface_mode);
      if (Number.isFinite(Number(dashboardConfig.sidebar_width))) setSidebarWidth(Number(dashboardConfig.sidebar_width));
      if (Number.isFinite(Number(dashboardConfig.drawer_width))) setDrawerWidth(Number(dashboardConfig.drawer_width));
      if (Number.isFinite(Number(dashboardConfig.canvas_width))) setCanvasWidth(Number(dashboardConfig.canvas_width));
   };

   const validateConfigDraft = (draft: any) => {
      if (!draft || typeof draft !== 'object' || Array.isArray(draft)) return 'Config must be a JSON object.';
      if (!draft.system || typeof draft.system !== 'object') return 'Missing system section.';
      if (!draft.providers || typeof draft.providers !== 'object') return 'Missing providers section.';
      if (draft.security?.safety_strictness !== undefined) {
         const strictness = Number(draft.security.safety_strictness);
         if (!Number.isFinite(strictness) || strictness < 0 || strictness > 1) return 'security.safety_strictness must be between 0 and 1.';
      }
      if (draft.gui && typeof draft.gui === 'object') {
         for (const key of ['sidebar_width', 'drawer_width', 'canvas_width']) {
            if (draft.gui[key] !== undefined) {
               const width = Number(draft.gui[key]);
               if (!Number.isFinite(width) || width < 120 || width > 2200) return `gui.${key} must be a usable pixel width.`;
            }
         }
      }
      if (draft.voice_output?.volume !== undefined) {
         const volume = Number(draft.voice_output.volume);
         if (!Number.isFinite(volume) || volume < 0 || volume > 1) return 'voice_output.volume must be between 0 and 1.';
      }
      if (draft.vision && typeof draft.vision === 'object') {
         if (draft.vision.camera_index !== undefined) {
            const cameraIndex = Number(draft.vision.camera_index);
            if (!Number.isInteger(cameraIndex) || cameraIndex < 0) return 'vision.camera_index must be 0 or greater.';
         }
         if (draft.vision.stream_fps_limit !== undefined) {
            const fps = Number(draft.vision.stream_fps_limit);
            if (!Number.isFinite(fps) || fps < 1 || fps > 120) return 'vision.stream_fps_limit must be between 1 and 120.';
         }
         for (const key of ['capture_width', 'capture_height']) {
            if (draft.vision[key] !== undefined) {
               const size = Number(draft.vision[key]);
               if (!Number.isFinite(size) || size < 120 || size > 7680) return `vision.${key} must be a valid camera size.`;
            }
         }
      }
      if (draft.context?.compaction_threshold_percent !== undefined) {
         const threshold = Number(draft.context.compaction_threshold_percent);
         if (!Number.isFinite(threshold) || threshold < 0.1 || threshold > 0.95) return 'context.compaction_threshold_percent must be between 0.1 and 0.95.';
      }
      return '';
   };

   async function loadConfig() {
      setConfigStatus({ kind: 'saving', message: 'Loading config...' });
      try {
         const res = await fetch('/api/config', { cache: 'no-store', signal: AbortSignal.timeout(10000) });
         if (!res.ok) throw new Error(`HTTP ${res.status}`);
         const data = await res.json();
         let cloned = enrichConfigDefaults(data);
         if (!cloned.gui || typeof cloned.gui !== 'object') {
            cloned.gui = currentDashboardConfig();
         } else {
            cloned.gui = { ...currentDashboardConfig(), ...cloned.gui };
         }
         const visibleSections = Object.keys(cloned).filter(section => !hiddenConfigSections.has(section));
         setConfigData(cloned);
         setConfigDraft(cloneConfig(cloned));
         setConfigJsonText(JSON.stringify(cloned, null, 2));
         setConfigSection(cloned.system ? 'system' : (visibleSections[0] || 'system'));
         applyDashboardConfig(cloned.gui);
         const validation = validateConfigDraft(cloned);
         setConfigStatus(validation ? { kind: 'error', message: validation } : { kind: 'valid', message: 'Valid active profile config loaded.' });
      } catch (err: any) {
         setConfigStatus({ kind: 'error', message: err?.message || 'Could not load config.' });
      }
   }

   async function saveConfigDraft() {
      let draft = configDraft;
      if (configMode === 'json') {
         try {
            draft = enrichConfigDefaults(JSON.parse(configJsonText));
            setConfigDraft(draft);
         } catch (err: any) {
            setConfigStatus({ kind: 'error', message: `JSON parse error: ${err?.message || err}` });
            return;
         }
      }
      draft = syncDerivedConfigForSave(enrichConfigDefaults(draft || {}));
      const validation = validateConfigDraft(draft);
      if (validation) {
         setConfigStatus({ kind: 'error', message: validation });
         return;
      }
      setConfigStatus({ kind: 'saving', message: 'Saving active profile config...' });
      try {
         const res = await fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(draft),
            signal: AbortSignal.timeout(15000)
         });
         const data = await res.json().catch(() => ({}));
         if (!res.ok) throw new Error(data?.detail || data?.message || `HTTP ${res.status}`);
         const saved = cloneConfig(draft);
         applyDashboardConfig(saved.gui);
         setConfigData(saved);
         setConfigDraft(cloneConfig(saved));
         setConfigJsonText(JSON.stringify(saved, null, 2));
         setConfigStatus({ kind: 'valid', message: data?.message || 'Configuration saved.' });
         refreshState();
      } catch (err: any) {
         setConfigStatus({ kind: 'error', message: err?.message || 'Save failed.' });
      }
   }

   const updateConfigPath = (path: string[], value: any) => {
      setConfigDraft(prev => {
         const next = cloneConfig(prev || {});
         let cursor = next;
         path.slice(0, -1).forEach(part => {
            if (!cursor[part] || typeof cursor[part] !== 'object') cursor[part] = {};
            cursor = cursor[part];
         });
         cursor[path[path.length - 1]] = value;
         setConfigJsonText(JSON.stringify(next, null, 2));
         const validation = validateConfigDraft(next);
         setConfigStatus(validation ? { kind: 'error', message: validation } : { kind: 'valid', message: 'Valid changes not saved yet.' });
         return next;
      });
   };

   async function refreshPlugins() {
      setPluginStatus({ kind: 'saving', message: 'Rescanning plugin folders...' });
      try {
         const res = await fetch('/api/plugins', { cache: 'no-store', signal: AbortSignal.timeout(10000) });
         if (!res.ok) throw new Error(`HTTP ${res.status}`);
         const data = await res.json();
         setState(prev => prev ? { ...prev, plugins: data.plugins || [] } : prev);
         setPluginStatus({ kind: 'valid', message: `Found ${(data.plugins || []).length} plugin bundles.` });
      } catch (err: any) {
         setPluginStatus({ kind: 'error', message: err?.message || 'Plugin rescan failed.' });
      }
   }

   async function installPlugin() {
      if (!pluginInstallUrl.trim()) {
         setPluginStatus({ kind: 'error', message: 'Enter a Git URL or owner/repo.' });
         return;
      }
      setPluginBusy('install');
      setPluginStatus({ kind: 'saving', message: 'Installing plugin from Git...' });
      try {
         const res = await fetch('/api/plugins/install', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: pluginInstallUrl.trim(), kind: 'plugin', force: pluginForceInstall, enable: pluginEnableAfterInstall }),
            signal: AbortSignal.timeout(130000)
         });
         const data = await res.json().catch(() => ({}));
         if (!res.ok) throw new Error(data?.detail || data?.message || `HTTP ${res.status}`);
         setPluginInstallUrl('');
         setPluginStatus({ kind: 'valid', message: data?.message || 'Plugin installed.' });
         await refreshPlugins();
         refreshState();
      } catch (err: any) {
         setPluginStatus({ kind: 'error', message: err?.message || 'Install failed.' });
      } finally {
         setPluginBusy('');
      }
   }

   async function installPluginFromCard(plugin: any) {
      const sourceUrl = String(plugin.source_url || '').trim();
      if (!sourceUrl) {
         setPluginInstallUrl('');
         setPluginStatus({ kind: 'error', message: `"${plugin.name}" has no source URL. Paste a GitHub or Git URL above to install it.` });
         return;
      }
      setPluginBusy(plugin.id);
      setPluginStatus({ kind: 'saving', message: `Installing ${formatCardName(plugin.name)}...` });
      try {
         const res = await fetch('/api/plugins/install', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
               url: sourceUrl,
               kind: 'plugin',
               force: pluginForceInstall,
               enable: pluginEnableAfterInstall
            }),
            signal: AbortSignal.timeout(130000)
         });
         const data = await res.json().catch(() => ({}));
         if (!res.ok) throw new Error(data?.detail || data?.message || `HTTP ${res.status}`);
         setPluginStatus({ kind: 'valid', message: data?.message || 'Plugin installed.' });
         await refreshPlugins();
         refreshState();
      } catch (err: any) {
         setPluginStatus({ kind: 'error', message: err?.message || 'Install failed.' });
      } finally {
         setPluginBusy('');
      }
   }

   async function togglePlugin(plugin: any) {
      const nextActive = plugin.active === false;
      setPluginBusy(plugin.id);
      setState(prev => prev ? { ...prev, plugins: (prev.plugins || []).map(item => item.id === plugin.id ? { ...item, active: nextActive } : item) } : prev);
      try {
         const res = await fetch('/api/plugins/configure', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id: plugin.id, active: nextActive }),
            signal: AbortSignal.timeout(15000)
         });
         const data = await res.json().catch(() => ({}));
         if (!res.ok) throw new Error(data?.detail || data?.message || `HTTP ${res.status}`);
         setPluginStatus({ kind: 'valid', message: data?.message || 'Plugin updated.' });
         refreshState();
      } catch (err: any) {
         setPluginStatus({ kind: 'error', message: err?.message || 'Plugin update failed.' });
         refreshPlugins();
      } finally {
         setPluginBusy('');
      }
   }

   async function removePlugin(plugin: any) {
      setConfirmModal({
         show: true,
         title: 'REMOVE PLUGIN',
         message: plugin.disk_removable
            ? `Remove plugin "${plugin.name}" from disk?`
            : `Hide "${plugin.name}" from the plugin inventory and disable its skills/tools?`,
         onConfirm: async () => {
            setPluginBusy(plugin.id);
            try {
               const res = await fetch(`/api/plugins/${encodeURIComponent(plugin.id)}`, { method: 'DELETE', signal: AbortSignal.timeout(15000) });
               const data = await res.json().catch(() => ({}));
               if (!res.ok) throw new Error(data?.detail || data?.message || `HTTP ${res.status}`);
               setPluginStatus({ kind: 'valid', message: data?.message || 'Plugin removed.' });
               await refreshPlugins();
               refreshState();
            } catch (err: any) {
               setPluginStatus({ kind: 'error', message: err?.message || 'Remove failed.' });
            } finally {
               setPluginBusy('');
            }
         }
      });
   }

   const refreshState = async () => {
      try {
         const health = await fetch('/api/health', { signal: AbortSignal.timeout(5000) });
         if (!health.ok) throw new Error(`Health HTTP ${health.status}`);
         const res = await fetch('/api/state', { signal: AbortSignal.timeout(45000) });
         if (!res.ok) throw new Error(`HTTP ${res.status}`);
         const data = await res.json();
         setState(data);
         setBackendOffline(false);
         setSessionNotice(prev => prev?.message?.includes('Reconnecting') ? null : prev);
      } catch (err) {
         setBackendOffline(true);
      }
   };

   const loadSources = async () => {
      try {
         const res = await fetch('/api/sources', { signal: AbortSignal.timeout(10000) });
         const data = await res.json().catch(() => ({}));
         if (!res.ok) throw new Error(data?.detail || `HTTP ${res.status}`);
         const loaded = Array.isArray(data.sources) ? data.sources : [];
         setSources(loaded.map((source: any) => ({
            id: String(source.id || `source-${Date.now()}`),
            name: String(source.name || 'Untitled source'),
            type: source.type === 'Website' ? 'Website' : 'File',
            checked: source.checked !== false,
            path: source.path ? String(source.path) : undefined,
            url: source.url ? String(source.url) : undefined,
         })));
      } catch (err: any) {
         setSessionNotice({ kind: 'error', message: err?.message || 'Could not load source library.' });
      }
   };

   const classifyTaskFile = (item: Pick<SourceItem, 'name' | 'type' | 'url'>): TaskFileItem['kind'] => {
      if (item.type === 'Website' || item.url) return 'Link';
      const name = item.name.toLowerCase();
      if (/\.(png|jpe?g|webp|gif|svg|bmp)$/i.test(name)) return 'Image';
      if (/\.(py|js|ts|tsx|jsx|json|md|html|css|yml|yaml|toml|rs|go|java|cpp|c|h)$/i.test(name)) return 'Code file';
      return 'Document';
   };

   const getTaskFileItems = (): TaskFileItem[] => {
      const byKey = new Map<string, TaskFileItem>();
      const addItem = (item: SourceItem, sourceLabel: string) => {
         const key = item.path || item.url || item.id;
         if (!key || byKey.has(key)) return;
         const kind = classifyTaskFile(item);
         byKey.set(key, {
            ...item,
            kind,
            subtitle: item.url || item.path || sourceLabel,
            sourceLabel,
            downloadable: item.type === 'File' && !!item.path,
         });
      };

      sources.forEach(source => addItem(source, source.type === 'Website' ? 'Link' : 'Library'));
      workEvents.forEach(event => {
         const rawPath = String(event.path || event.target || '').trim();
         const name = rawPath.replace(/\\/g, '/').split('/').pop() || '';
         if (!rawPath || !name || !/\.[A-Za-z0-9]+$/.test(name)) return;
         addItem({
            id: String(event.id || rawPath),
            name,
            type: 'File',
            checked: true,
            path: rawPath,
         }, event.source === 'assistant-artifact' ? 'Artifact' : 'Work file');
      });
      return Array.from(byKey.values());
   };

   const copyChatLink = async () => {
      const shareUrl = window.location.href;
      try {
         await navigator.clipboard.writeText(shareUrl);
         setSessionNotice({ kind: 'success', message: 'Chat link copied.' });
      } catch {
         setSessionNotice({ kind: 'error', message: 'Could not copy chat link.' });
      }
   };

   const openTaskFilesDialog = () => {
      setActiveTab('session');
      setTaskMenuOpen(false);
      setTaskFilesOpen(true);
      loadSources();
      loadWorkEvents(currentSessionId, '');
   };

   const downloadTaskFile = (file: TaskFileItem) => {
      if (file.url) {
         window.open(file.url, '_blank', 'noopener,noreferrer');
         return;
      }
      if (!file.path) {
         setSessionNotice({ kind: 'error', message: 'This file has no saved path yet.' });
         return;
      }
      window.location.href = `/api/file-download?path=${encodeURIComponent(file.path)}`;
   };

   const downloadAllTaskFiles = () => {
      const files = getTaskFileItems().filter(file => file.downloadable);
      if (files.length === 0) {
         setSessionNotice({ kind: 'error', message: 'No downloadable files in this chat yet.' });
         return;
      }
      window.location.href = `/api/session-files.zip?session_id=${encodeURIComponent(currentSessionId || 'default')}`;
      setTaskMenuOpen(false);
   };

   useEffect(() => {
      const handleToolbarClick = (event: MouseEvent) => {
         const target = event.target as HTMLElement | null;
         const button = target?.closest?.('[data-nexus-toolbar-action]') as HTMLElement | null;
         if (!button) return;

         event.preventDefault();
         event.stopPropagation();
         const action = button.dataset.nexusToolbarAction;
         if (action === 'copy-link') {
            copyChatLink();
         } else if (action === 'files') {
            openTaskFilesDialog();
         } else if (action === 'more') {
            setTaskFilesOpen(false);
            setTaskMenuOpen(open => !open);
         } else if (action === 'download-files') {
            downloadAllTaskFiles();
         } else if (action === 'task-details') {
            setTaskMenuOpen(false);
            setDrawerType('canvas');
         }
      };

      document.addEventListener('click', handleToolbarClick, true);
      return () => document.removeEventListener('click', handleToolbarClick, true);
   }, [currentSessionId, sources, workEvents]);

   const stopVoiceConversation = () => {
      recognitionRef.current?.stop?.();
      setVoiceListening(false);
   };

   const startVoiceConversation = () => {
      setVoiceError('');
      if (voiceListening) {
         stopVoiceConversation();
         return;
      }

      const SpeechRecognitionApi = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
      if (!SpeechRecognitionApi) {
         setVoiceError('Voice conversation needs Chrome or Edge speech recognition.');
         return;
      }

      window.speechSynthesis?.cancel();
      const recognition = new SpeechRecognitionApi();
      recognitionRef.current = recognition;
      voiceTranscriptRef.current = '';
      setVoiceTranscript('');
      recognition.lang = 'en-US';
      recognition.continuous = false;
      recognition.interimResults = true;
      recognition.maxAlternatives = 1;

      recognition.onstart = () => {
         setVoiceListening(true);
         composerInputRef.current?.focus();
      };

      recognition.onresult = (event: any) => {
         let finalText = '';
         let interimText = '';
         for (let i = event.resultIndex; i < event.results.length; i += 1) {
            const text = event.results[i][0]?.transcript || '';
            if (event.results[i].isFinal) finalText += text;
            else interimText += text;
         }
         if (finalText) voiceTranscriptRef.current = `${voiceTranscriptRef.current} ${finalText}`.trim();
         const visibleText = `${voiceTranscriptRef.current} ${interimText}`.trim();
         setVoiceTranscript(visibleText);
         setInputValue(visibleText);
      };

      recognition.onerror = (event: any) => {
         setVoiceListening(false);
         setVoiceError(event?.error === 'not-allowed' ? 'Microphone permission was blocked.' : 'Voice capture stopped.');
      };

      recognition.onend = () => {
         setVoiceListening(false);
         const text = voiceTranscriptRef.current.trim();
         if (text) {
            setVoiceTranscript('');
            handleSend(text, { voiceMode: true });
         }
      };

      recognition.start();
   };

   const createReminder = async () => {
      const text = newReminderText.trim();
      if (!text) return;
      const dueAt = newReminderDue ? Math.floor(new Date(newReminderDue).getTime() / 1000) : 0;
      const optimisticReminder = {
         id: `pending_${Date.now()}`,
         text,
         time: dueAt ? new Date(dueAt * 1000).toLocaleString() : new Date().toLocaleString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
         due_at: dueAt,
         created_at: Date.now() / 1000
      };
      setNewReminderText('');
      setNewReminderDue('');
      setState(prev => prev ? { ...prev, reminders: [optimisticReminder, ...(prev.reminders || [])] } : prev);
      try {
         const res = await fetch('/api/reminders', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text, due_at: dueAt, time: optimisticReminder.time })
         });
         if (!res.ok) throw new Error(`HTTP ${res.status}`);
         const data = await res.json();
         if (Array.isArray(data.reminders)) {
            setState(prev => prev ? { ...prev, reminders: data.reminders } : prev);
         }
      } catch (err) {
         console.error("Failed to create reminder:", err);
         refreshState();
      }
   };

   const deleteReminder = async (id?: string) => {
      if (!id) return;
      setState(prev => prev ? { ...prev, reminders: (prev.reminders || []).filter(r => r.id !== id) } : prev);
      try {
         const res = await fetch(`/api/reminders/${encodeURIComponent(id)}`, { method: 'DELETE' });
         if (!res.ok) throw new Error(`HTTP ${res.status}`);
         const data = await res.json();
         if (Array.isArray(data.reminders)) {
            setState(prev => prev ? { ...prev, reminders: data.reminders } : prev);
         }
      } catch (err) {
         console.error("Failed to delete reminder:", err);
         refreshState();
      }
   };

   const requestReminderNotifications = async () => {
      if (!("Notification" in window)) {
         setNotificationPermission('unsupported');
         return;
      }
      const permission = await Notification.requestPermission();
      setNotificationPermission(permission);
   };

   const startHiveMission = async (missionOverride?: string) => {
      const mission = (missionOverride || newHiveMission).trim();
      if (!mission) return;
      setHiveStarting(true);
      try {
         const res = await fetch('/api/hive/missions', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mission, autostart: true })
         });
         if (!res.ok) throw new Error(`HTTP ${res.status}`);
         const data = await res.json();
         if (Array.isArray(data.hive)) {
            setState(prev => prev ? { ...prev, hive: data.hive } : prev);
         }
         setNewHiveMission('');
         refreshState();
      } catch (err) {
         console.error("Failed to start hive mission:", err);
      } finally {
         setHiveStarting(false);
      }
   };

   const controlHive = async (hiveId: string, action: 'pause' | 'resume' | 'stop') => {
      try {
         const res = await fetch(`/api/hive/${encodeURIComponent(hiveId)}/${action}`, { method: 'POST' });
         if (!res.ok) throw new Error(`HTTP ${res.status}`);
         refreshState();
      } catch (err) {
         console.error(`Failed to ${action} hive:`, err);
      }
   };

   const removeHive = async (hiveId: string) => {
      try {
         const res = await fetch(`/api/hive/${encodeURIComponent(hiveId)}`, { method: 'DELETE' });
         if (!res.ok) throw new Error(`HTTP ${res.status}`);
         const data = await res.json();
         if (Array.isArray(data.hive)) {
            setState(prev => prev ? { ...prev, hive: data.hive } : prev);
         }
         refreshState();
      } catch (err) {
         console.error("Failed to remove hive:", err);
      }
   };

   const controlHiveTask = async (hiveId: string, taskId: string, action: 'stop' | 'resume' | 'remove') => {
      try {
         const url = `/api/hive/${encodeURIComponent(hiveId)}/tasks/${encodeURIComponent(taskId)}`;
         const res = await fetch(action === 'remove' ? url : `${url}/${action}`, { method: action === 'remove' ? 'DELETE' : 'POST' });
         if (!res.ok) throw new Error(`HTTP ${res.status}`);
         refreshState();
      } catch (err) {
         console.error(`Failed to ${action} hive task:`, err);
      }
   };

   const cardVersion = (item: any) => String(item?.evolution_version || item?.ui_version || item?.card_version || item?.config?.evolution_version || item?.config?.ui_version || item?.config?.card_version || '1');
   const formatCardName = (name: string) => {
      if (!name) return 'Unnamed';
      return String(name)
         .replace(/^plugin:/i, 'Plugin: ')
         .replace(/[_-]+/g, ' ')
         .replace(/\s+/g, ' ')
         .trim()
         .replace(/\b\w/g, char => char.toUpperCase());
   };
   const formatProviderName = (name: string) => {
      const aliases: Record<string, string> = {
         openrouter: 'OpenRouter',
         sovereign_brain: 'Sovereign Brain',
         lm_studio: 'LM Studio',
         azure_openai: 'Azure OpenAI',
         openai: 'OpenAI',
         deepseek: 'DeepSeek',
         groq: 'Groq',
         gemini: 'Gemini',
         cohere: 'Cohere',
         fireworks: 'Fireworks',
         mistral: 'Mistral',
         perplexity: 'Perplexity',
         nvidia: 'NVIDIA'
      };
      return aliases[String(name || '').toLowerCase()] || formatCardName(name);
   };
   const cleanAssetDescription = (description: string, name?: string) => {
      const fallback = 'No summary configured.';
      if (!description) return fallback;
      let text = String(description)
         .replace(/\r/g, '\n')
         .replace(/^---\s*/gm, '')
         .replace(/#+\s*/g, '')
         .replace(/\*\*/g, '')
         .replace(/\bmetadata:\s*/gi, '')
         .replace(/\bversion:\s*[\w.-]+/gi, '')
         .replace(/\bINSTRUCTIONS?\s*\d*/gi, '')
         .replace(/\bOBJECTIVE\b/gi, '')
         .replace(/\bDISCOVERY\b/gi, '')
         .replace(/\s+/g, ' ')
         .trim();
      if (name) {
         const escapedName = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
         text = text.replace(new RegExp(`^name:\\s*${escapedName}\\s*description:\\s*`, 'i'), '');
         text = text.replace(new RegExp(`^${escapedName}\\s*description:\\s*`, 'i'), '');
      }
      text = text
         .replace(/^name:\s*[^ ]+\s+description:\s*/i, '')
         .replace(/^description:\s*/i, '')
         .replace(/\s+:/g, ':')
         .trim();
      if (!text) return fallback;
      return text.length > 220 ? `${text.slice(0, 217).trim()}...` : text;
   };

   const defaultAssetConfig = (kind: 'skills' | 'tools', active = true, description = '') => {
      if (kind === 'skills') {
         return {
            active,
            description,
            model: '',
            instructions: '',
            permissions: [],
            triggers: [],
            metadata: {}
         };
      }
      return {
         active,
         description,
         command: '',
         permissions: [],
         timeout: null,
         environment: {},
         metadata: {}
      };
   };

   const configureAsset = (kind: 'skills' | 'tools', item: { name: string; active?: boolean; description: string; config?: Record<string, any> }) => {
      const active = item.active !== false;
      const description = cleanAssetDescription(item.description, item.name);
      const config = {
         ...defaultAssetConfig(kind, active, description),
         ...(item.config || {}),
         active,
         description: (item.config?.description || description)
      };
      setAssetPanel({
         open: true,
         kind,
         mode: 'edit',
         name: item.name,
         description,
         active,
         configText: JSON.stringify(config, null, 2)
      });
   };

   const configurePlugin = (plugin: any) => {
      const active = plugin.active !== false;
      const description = cleanAssetDescription(plugin.description, plugin.name);
      const config = {
         id: plugin.id,
         name: plugin.name,
         description,
         active,
         version: plugin.version || '0.1.0',
         install_kind: plugin.install_kind || 'plugin',
         source_url: plugin.source_url || '',
         category: plugin.category || plugin.source || 'plugin'
      };
      setAssetPanel({
         open: true,
         kind: 'plugins',
         mode: 'edit',
         id: plugin.id,
         name: plugin.name,
         description,
         active,
         configText: JSON.stringify(config, null, 2)
      });
   };

   const addAsset = (kind: 'skills' | 'tools') => {
      const config = defaultAssetConfig(kind, true, '');
      setAssetPanel({
         open: true,
         kind,
         mode: 'add',
         name: '',
         description: '',
         active: true,
         configText: JSON.stringify(config, null, 2)
      });
   };

   const saveAssetPanel = async () => {
      if (!assetPanel) return;
      const name = assetPanel.name.trim();
      if (!name) {
         setAssetPanel({ ...assetPanel, error: `${assetPanel.kind === 'skills' ? 'Skill' : assetPanel.kind === 'tools' ? 'Tool' : 'Plugin'} name is required.` });
         return;
      }
      try {
         const parsedConfig = JSON.parse(assetPanel.configText || '{}');
         if (!parsedConfig || typeof parsedConfig !== 'object' || Array.isArray(parsedConfig)) {
            throw new Error('JSON definition must be an object.');
         }
         const active = Boolean(parsedConfig.active ?? assetPanel.active);
         const description = String(parsedConfig.description ?? assetPanel.description ?? '').trim()
            || `${assetPanel.kind === 'skills' ? 'Skill' : assetPanel.kind === 'tools' ? 'Tool' : 'Plugin'} capability for NEXUS operations.`;
         const endpoint = assetPanel.kind === 'plugins' ? '/api/plugins/configure' : `/api/assets/${assetPanel.kind}/configure`;
         const payload = assetPanel.kind === 'plugins'
            ? {
               id: assetPanel.id || parsedConfig.id || name,
               active,
               config: {
                  ...parsedConfig,
                  active,
                  description
               }
            }
            : {
               name,
               config: {
                  ...parsedConfig,
                  active,
                  description
               }
            };
         const res = await fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
         });
         if (!res.ok) throw new Error(`HTTP ${res.status}`);
         setAssetPanel(null);
         await refreshState();
      } catch (err) {
         console.error(`Save ${assetPanel.kind} error:`, err);
         setAssetPanel({ ...assetPanel, error: err instanceof SyntaxError ? 'Invalid JSON definition.' : 'Save failed. Check the backend log and try again.' });
      }
   };

   const updateVisibleActiveState = (kind: 'skills' | 'tools' | 'mcp', names: string[], active: boolean) => {
      setState(prev => {
         if (!prev) return prev;
         const nameSet = new Set(names);
         if (kind === 'mcp') {
            return {
               ...prev,
               mcp: {
                  ...prev.mcp,
                  servers: (prev.mcp?.servers || []).map((srv: any) => nameSet.has(srv.name) ? { ...srv, active } : srv)
               }
            };
         }
         return {
            ...prev,
            [kind]: (prev[kind] || []).map((item: any) => nameSet.has(item.name) ? { ...item, active } : item)
         };
      });
   };

   const powerButtonStyle = (isOn: boolean) => ({
      width: '30px',
      height: '30px',
      display: 'inline-flex',
      alignItems: 'center',
      justifyContent: 'center',
      background: isOn ? 'rgba(34,197,94,0.10)' : 'rgba(239,68,68,0.10)',
      border: isOn ? '1px solid rgba(34,197,94,0.24)' : '1px solid rgba(239,68,68,0.24)',
      color: isOn ? '#4ade80' : '#f87171',
      borderRadius: '8px',
      cursor: 'pointer'
   });

   const toggleAsset = async (kind: 'skills' | 'tools', name: string, active: boolean | undefined, description: string, config?: Record<string, any>) => {
      const nextActive = !(active !== false);
      updateVisibleActiveState(kind, [name], nextActive);
      try {
         const res = await fetch(`/api/assets/${kind}/configure`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, config: { ...(config || {}), active: nextActive, description } })
         });
         if (!res.ok) throw new Error(`HTTP ${res.status}`);
         await refreshState();
      } catch (err) {
         console.error(`Toggle ${kind} error:`, err);
         await refreshState();
      }
   };

   const bulkToggleAssets = async (kind: 'skills' | 'tools', items: { name: string; active?: boolean; description: string; config?: Record<string, any> }[], targetActive: boolean) => {
      if (!items.length || bulkUpdating) return;
      setBulkUpdating(true);
      updateVisibleActiveState(kind, items.map(item => item.name), targetActive);
      try {
         const results = await Promise.all(items.map(item => fetch(`/api/assets/${kind}/configure`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
               name: item.name,
               config: {
                  ...(item.config || {}),
                  active: targetActive,
                  description: item.description
               }
            })
         })));
         const failed = results.find(res => !res.ok);
         if (failed) throw new Error(`HTTP ${failed.status}`);
         await refreshState();
      } catch (err) {
         console.error(`Bulk toggle ${kind} error:`, err);
         await refreshState();
      } finally {
         setBulkUpdating(false);
      }
   };

   const addProvider = async () => {
      setSelectedProv({ name: '', status: 'CONFIGURED', description: '', endpoint: '', config_source: 'configs/nexus_config.yaml' });
      setProviderFamilyName('');
      setInstanceName('');
      setEditingInstanceId(null);
      setApiKey('');
      setTargetModel('');
      setProviderEndpoint('');
      setProviderCheck(null);
      setShowApiKey(false);
      setShowProviderPanel(true);
   };

   const routeBaseId = (providerName: string) => String(providerName || 'provider')
      .toLowerCase()
      .replace(/[^a-z0-9_-]+/g, '_')
      .replace(/^_+|_+$/g, '') || 'provider';

   const nextProviderRouteId = (providerName: string, routes: any[] = []) => {
      const base = routeBaseId(providerName);
      const used = new Set(routes.map(route => String(route.id || '').toLowerCase()));
      if (!used.has(base)) return base;
      let index = 2;
      while (used.has(`${base}_${index}`)) index += 1;
      return `${base}_${index}`;
   };

   const isAddingProvider = showProviderPanel && !selectedProv?.name && !editingInstanceId;

   const currentProviderRoute = () => state?.provider_instances?.find((inst) => inst.id === editingInstanceId || inst.id === instanceName);

   const runProviderCheck = async (kind: 'test' | 'ping') => {
      const providerId = (providerFamilyName || selectedProv?.name || '').trim();
      if (!providerId) return;
      setProviderCheck({ status: 'running', message: kind === 'test' ? 'Testing API...' : 'Pinging endpoint...' });
      try {
         const res = await fetch(`/api/providers/${kind}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
               name: providerId,
               instance_id: instanceName || routeBaseId(providerId),
               api_key: apiKey,
               model: targetModel,
               endpoint: providerEndpoint || currentProviderRoute()?.endpoint || selectedProv?.endpoint || ''
            })
         });
         const data = await res.json();
         setProviderCheck(data);
      } catch (err: any) {
         setProviderCheck({ status: 'error', ok: false, message: err?.message || 'Check failed.' });
      }
   };

   const saveMcpPanel = async () => {
      const name = newMcpName.trim();
      if (!name) {
         setMcpPanelError('MCP server name is required.');
         return;
      }
      try {
         const parsed = JSON.parse(newMcpConfig || '{}');
         if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
            throw new Error('MCP config must be a JSON object.');
         }
         const res = await fetch('/api/mcp/configure', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, config: parsed })
         });
         if (!res.ok) throw new Error(`HTTP ${res.status}`);
         setShowAddMcpModal(false);
         setMcpPanelError('');
         await refreshState();
      } catch (err: any) {
         setMcpPanelError(err instanceof SyntaxError ? 'Invalid JSON config.' : (err?.message || 'Failed to save MCP config.'));
      }
   };

   const saveProviderPanel = async () => {
      const providerId = (providerFamilyName || selectedProv?.name || '').trim();
      const routeId = (instanceName || routeBaseId(providerId)).trim();
      if (!providerId || !routeId) {
         setProviderCheck({ status: 'error', ok: false, message: 'Provider name and route id are required.' });
         return;
      }
      try {
         const res = await fetch('/api/providers/configure', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
               name: providerId,
               instance_id: routeId,
               api_key: apiKey,
               model: targetModel,
               endpoint: providerEndpoint || selectedProv?.endpoint || ''
            })
         });
         const data = await res.json().catch(() => ({}));
         if (!res.ok || data.status === 'error') {
            throw new Error(data.message || `HTTP ${res.status}`);
         }
         setShowProviderPanel(false);
         setProviderCheck(null);
         await refreshState();
      } catch (err: any) {
         setProviderCheck({ status: 'error', ok: false, message: err?.message || 'Failed to save provider route.' });
      }
   };

   const closeSettings = () => {
      setSettingsOpen(false);
      setAssetPanel(null);
      setShowAddMcpModal(false);
      setShowProviderPanel(false);
      setConfirmModal(null);
   };

   const switchSettingsTab = (tabId: string) => {
      setSettingsTab(tabId);
      setAssetPanel(null);
      setShowAddMcpModal(false);
      setShowProviderPanel(false);
   };

   const deleteAsset = (kind: 'skills' | 'tools', name: string) => {
      setConfirmModal({
         show: true,
         title: `DELETE ${kind === 'skills' ? 'SKILL' : 'TOOL'}`,
         message: `Hide "${name}" from the active ${kind} list?`,
         onConfirm: async () => {
            try {
               await fetch(`/api/${kind}/delete/${encodeURIComponent(name)}`, { method: 'DELETE' });
               await refreshState();
            } catch (err) {
               console.error(`Delete ${kind} error:`, err);
            }
            setConfirmModal(null);
         }
      });
   };

   const configureMcp = (srv: any) => {
      setMcpPanelMode('edit');
      setMcpPanelError('');
      setNewMcpName(srv.name || '');
      setNewMcpConfig(JSON.stringify({
         command: srv.command || '',
         args: Array.isArray(srv.args) ? srv.args : [],
         active: srv.active !== false,
         description: srv.description || ''
      }, null, 2));
      setShowAddMcpModal(true);
   };

   const openAddMcpPanel = () => {
      setMcpPanelMode('add');
      setMcpPanelError('');
      setNewMcpName('');
      setNewMcpConfig(JSON.stringify({
         command: '',
         args: [],
         active: true,
         description: ''
      }, null, 2));
      setShowAddMcpModal(true);
   };

   const toggleMcp = async (srv: any) => {
      const nextActive = !(srv.active !== false);
      updateVisibleActiveState('mcp', [srv.name], nextActive);
      try {
         const res = await fetch('/api/mcp/configure', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
               name: srv.name,
               config: {
                  command: srv.command || '',
                  args: Array.isArray(srv.args) ? srv.args : [],
                  active: nextActive,
                  description: srv.description || ''
               }
            })
         });
         if (!res.ok) throw new Error(`HTTP ${res.status}`);
         await refreshState();
      } catch (err) {
         console.error("Toggle MCP error:", err);
         await refreshState();
      }
   };

   const bulkToggleMcp = async (servers: any[] = [], targetActive: boolean) => {
      if (!servers.length || bulkUpdating) return;
      setBulkUpdating(true);
      updateVisibleActiveState('mcp', servers.map(srv => srv.name), targetActive);
      try {
         const results = await Promise.all(servers.map(srv => fetch('/api/mcp/configure', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
               name: srv.name,
               config: {
                  command: srv.command || '',
                  args: Array.isArray(srv.args) ? srv.args : [],
                  active: targetActive,
                  description: srv.description || ''
               }
            })
         })));
         const failed = results.find(res => !res.ok);
         if (failed) throw new Error(`HTTP ${failed.status}`);
         await refreshState();
      } catch (err) {
         console.error("Bulk toggle MCP error:", err);
         await refreshState();
      } finally {
         setBulkUpdating(false);
      }
   };

   const deleteMcp = (name: string) => {
      setConfirmModal({
         show: true,
         title: "DELETE MCP",
         message: `Remove MCP server "${name}" from configuration?`,
         onConfirm: async () => {
            try {
               await fetch(`/api/mcp/delete/${encodeURIComponent(name)}`, { method: 'DELETE' });
               await refreshState();
            } catch (err) {
               console.error("Delete MCP error:", err);
            }
            setConfirmModal(null);
         }
      });
   };

   useEffect(() => {
      const fetchData = async () => {
         try {
            const health = await fetch('/api/health', { signal: AbortSignal.timeout(5000) });
            if (!health.ok) throw new Error(`Health HTTP ${health.status}`);
            const res = await fetch('/api/state', { signal: AbortSignal.timeout(45000) });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            setState(data);
            setBackendOffline(false);
            setSessionNotice(prev => prev?.message?.includes('Reconnecting') ? null : prev);
            setLoading(false);
         } catch (err) {
            setBackendOffline(true);
            setLoading(false);
         }
      };

      fetchData();
      fetchHistory();
      fetchSessions();
      syncActiveSession();
      loadSources();
      const interval = setInterval(fetchData, 3000);
      const sessionInterval = setInterval(syncActiveSession, 5000);
      return () => {
         clearInterval(interval);
         clearInterval(sessionInterval);
      };
   }, []);

   useEffect(() => {
      if (activeTab !== 'audit') return;
      refreshEvolutionAudit();
      const interval = setInterval(refreshEvolutionAudit, 7000);
      return () => clearInterval(interval);
   }, [activeTab]);

   useEffect(() => {
      if (activeTab !== 'config') return;
      if (!configDraft) loadConfig();
   }, [activeTab]);

   const isPlanningArtifact = (row: any): boolean => {
      const kind = String(row?.kind || row?.type || '').toLowerCase();
      const target = String(row?.target || row?.path || '').toLowerCase();
      return kind === 'artifact' && (
         target.includes('implementation_plan') ||
         target.includes('task.md') ||
         target.includes('walkthrough')
      );
   };

   const getWorkEventsForMessage = (msgIndex: number, _isLatest: boolean) => {
      const assistantMessageIndices = messages
         .map((m, idx) => ({ role: m.role, index: idx }))
         .filter(m => m.role === 'assistant')
         .map(m => m.index);
      const assistantRank = assistantMessageIndices.indexOf(msgIndex);
      if (assistantRank === -1) return [];
      const isLatestAssistant = assistantRank === assistantMessageIndices.length - 1;
      const sortedEvents = [...workEvents].sort((a, b) => (a.created_at || 0) - (b.created_at || 0));
      const uniqueTurns: string[] = [];
      sortedEvents.forEach(e => {
         if (e.turn_id && !uniqueTurns.includes(e.turn_id)) {
            uniqueTurns.push(e.turn_id);
         }
      });
      let targetTurnId = uniqueTurns[assistantRank] || '';
      if (isLatestAssistant && !targetTurnId) {
         targetTurnId = currentTurnId;
      }
      if (!targetTurnId) {
         if (isLatestAssistant) {
            return workEvents.filter(e => !e.turn_id || e.turn_id === currentTurnId);
         }
         return [];
      }
      return workEvents.filter(e => e.turn_id === targetTurnId);
   };

   const getTurnEventsForCanvas = () => {
      const targetTurnId = canvasPlaybackTurnId || String(selectedWorkEvent?.turn_id || '');
      if (targetTurnId) {
         return workEvents.filter(e => e.turn_id === targetTurnId);
      }
      const latestAssistant = [...messages].reverse().find(message => message.role === 'assistant');
      if (latestAssistant) {
         const idx = messages.indexOf(latestAssistant);
         return getWorkEventsForMessage(idx, true);
      }
      return [];
   };

   const allWorkActivities = getTurnEventsForCanvas();
   const planningRows = allWorkActivities.filter(row => String(row.kind || row.type || '').toLowerCase() === 'todo');
   // Natural insertion order = real SSE arrival order from backend (same as LemonAI).
   // NO sorting — todo rows have created_at=0 which corrupts any timestamp sort.
   // Trust the order events were inserted: that IS the real execution order.
   const timelineWorkActivities = allWorkActivities
      .filter(row => !isPlanningArtifact(row));

   const activePlaybackIndex = canvasPlaybackTime !== null
      ? Math.min(timelineWorkActivities.length - 1, Math.floor(canvasPlaybackTime / 5))
      : Math.max(0, timelineWorkActivities.length - 1);

   const clampedCanvasPlaybackIndex = activePlaybackIndex;
   const activeCanvasWorkEvent = canvasPlaybackTime !== null
      ? timelineWorkActivities[clampedCanvasPlaybackIndex] || null
      : selectedWorkEvent || timelineWorkActivities[clampedCanvasPlaybackIndex] || null;

   const canvasProgress = canvasPlaybackTime !== null && timelineWorkActivities.length > 1
      ? (canvasPlaybackTime / ((timelineWorkActivities.length - 1) * 5)) * 100
      : 100;


   useEffect(() => {
      if (!isPlaying) return;
      const interval = window.setInterval(() => {
         setCanvasPlaybackTime(prev => {
            const current = prev !== null ? prev : (timelineWorkActivities.length - 1) * 5;
            const totalDuration = (timelineWorkActivities.length - 1) * 5;
            if (current >= totalDuration) {
               setIsPlaying(false);
               return null;
            }
            const next = current + 0.1;
            if (next >= totalDuration) {
               setIsPlaying(false);
               return null;
            }
            return next;
         });
      }, 50);
      return () => window.clearInterval(interval);
   }, [isPlaying, timelineWorkActivities.length]);

   const navItems = [
      { id: 'session', label: 'GUI', icon: <LayoutDashboard size={18} /> },
      { id: 'hive', label: 'Hive', icon: <Activity size={18} /> },
      { id: 'mcp', label: 'MCP', icon: <Database size={18} /> },
      { id: 'audit', label: 'Evolution', icon: <Sparkles size={18} /> },
      { id: 'skills', label: 'Skills', icon: <GraduationCap size={18} /> },
      { id: 'tools', label: 'Tools', icon: <Wrench size={18} /> },
      { id: 'providers', label: 'Providers', icon: <BrainCircuit size={18} /> },
      { id: 'plugins', label: 'Plugins', icon: <Puzzle size={18} /> },
      { id: 'config', label: 'Config', icon: <Settings2 size={18} /> },
      { id: 'reminders', label: 'Reminders', icon: <Bell size={18} /> },
      { id: 'health', label: 'Health', icon: <HeartPulse size={18} /> }
   ];

    if (loading) return <LoadingScreen label="[ NEXUS_SYNCHRONIZING ]" />;

   if (!state) return (
      <LoadingScreen
         label="NEXUS RECONNECTING"
         reconnecting
         subtext="Waiting for the local API. The GUI will open automatically when it answers."
      />
   );

   const cpuVal = parseInt(state.health?.cpu?.replace('%', '') || '0');
   const healthClass = state.health?.status === 'CRITICAL' || cpuVal > 80 ? 'red' : 'green';
   const taskFileCount = getTaskFileItems().length;
   const currentSessionTitle = sessionList.find(session => session.id === currentSessionId)?.title || 'New Chat';
   const formatDuration = (seconds?: number) => {
      const total = Number(seconds || 0);
      const hours = Math.floor(total / 3600);
      const minutes = Math.floor((total % 3600) / 60);
      if (hours > 24) return `${Math.floor(hours / 24)}d ${hours % 24}h`;
      if (hours > 0) return `${hours}h ${minutes}m`;
      return `${minutes}m`;
   };
   const itemMatchesSearch = (item: any, query: string) => {
      const needle = query.trim().toLowerCase();
      if (!needle) return true;
      return [
         item?.name,
         item?.description,
         item?.command,
         Array.isArray(item?.args) ? item.args.join(' ') : ''
      ].some(value => String(value || '').toLowerCase().includes(needle));
   };
   const filteredSkills = state.skills?.filter(item => itemMatchesSearch(item, skillsSearch)) || [];
   const filteredTools = state.tools?.filter(item => itemMatchesSearch(item, toolsSearch)) || [];
   const filteredMcpServers = state.mcp?.servers?.filter((item: any) => itemMatchesSearch(item, mcpSearch)) || [];
   const filteredPlugins = (state.plugins || []).filter((plugin: any) => itemMatchesSearch(plugin, pluginSearch) || String(plugin.path || '').toLowerCase().includes(pluginSearch.trim().toLowerCase()));
   const allFilteredSkillsOn = filteredSkills.length > 0 && filteredSkills.every(item => item.active !== false);
   const allFilteredToolsOn = filteredTools.length > 0 && filteredTools.every(item => item.active !== false);
   const allFilteredMcpOn = filteredMcpServers.length > 0 && filteredMcpServers.every((item: any) => item.active !== false);
   const allFilteredCurrentOn = activeTab === 'mcp' ? allFilteredMcpOn : activeTab === 'skills' ? allFilteredSkillsOn : allFilteredToolsOn;
   const bulkPowerStyle = allFilteredCurrentOn
      ? { background: 'rgba(34,197,94,0.09)', border: '1px solid rgba(34,197,94,0.24)', color: '#4ade80' }
      : { background: 'rgba(239,68,68,0.09)', border: '1px solid rgba(239,68,68,0.24)', color: '#f87171' };
   const activeTabTitle = navItems.find(item => item.id === activeTab)?.label || activeTab;
   const evolutionProgress = Math.round((state.audit?.roadmap?.completion_ratio || 0) * 100);
   const evolutionCounts = state.audit?.roadmap?.counts || { done: 0, partial: 0, missing: 0 };
   const evolutionNext = state.audit?.roadmap?.remaining_top || [];
   const evolutionSources = Object.entries(state.audit?.unified_graph?.by_source || {}).slice(0, 7);
   const evolutionMaxSource = Math.max(1, ...evolutionSources.map(([, value]) => Number(value) || 0));
   const evolutionTools = (state.audit?.tool_economy || []).slice(0, 8);
   const evolutionEvidenceEntries = Object.entries(state.audit?.evidence?.by_status || {});
   const evolutionEvents = (state.audit?.mission_replay || []).slice(0, 8);
   const evolutionHasAuditData = Boolean(state.audit?.roadmap?.total || state.audit?.unified_graph?.nodes || state.audit?.tool_economy?.length);
   const evolutionStatusColor = (status: string) => status === 'done' ? '#4ade80' : status === 'missing' ? '#f87171' : '#60a5fa';
   const evolutionSourceTotal = evolutionSources.reduce((sum, [, value]) => sum + (Number(value) || 0), 0);
   const evolutionReliability = evolutionTools.length
      ? Math.round(evolutionTools.reduce((sum: number, tool: any) => sum + (Number(tool.success_rate) || 0), 0) / evolutionTools.length * 100)
      : 0;
   const compactNumber = (value: any) => Intl.NumberFormat('en', { notation: Number(value) >= 10000 ? 'compact' : 'standard', maximumFractionDigits: 1 }).format(Number(value) || 0);
   const formatEventTime = (timestamp?: number) => timestamp ? new Date(timestamp * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '--';
   const canvasLatestAssistant = [...messages].reverse().find(message => message.role === 'assistant' && message.content.trim());

   const isAssistantError = (content: string): boolean => {
      const t = (content || '').trim().toLowerCase();
      return (
         t.startsWith('error:') ||
         t.startsWith('traceback') ||
         t.includes('unhandled exception') ||
         t.includes('syntaxerror') ||
         t.includes('typeerror') ||
         t.includes('nameerror') ||
         t.includes('cannot find module')
      );
   };

   const collapseWorkActivities = (rows: any[]): any[] => {
      const seen = new Set<string>();
      return rows.filter(row => {
         const key = `${row.kind || row.type}|${row.target || row.path || row.action}`;
         if (seen.has(key)) return false;
         seen.add(key);
         return true;
      });
   };

   // Alias: active canvas file preview (same as canvasPreview state)
   const activeCanvasPreview = canvasPreview;
   // Path the canvas is currently targeting
   const canvasPreviewTarget = canvasPreview?.path || '';
   // ─────────────────────────────────────────────────────────────────────────

   const latestWorkActivity = timelineWorkActivities[timelineWorkActivities.length - 1] || null;
   const activeWorkKind = activeCanvasWorkEvent ? String(activeCanvasWorkEvent.kind || activeCanvasWorkEvent.type || '').toLowerCase() : '';
   const isCommandWork = activeWorkKind === 'command' || activeWorkKind === 'bash' || activeWorkKind === 'exec';
   const isBrowserWork = activeWorkKind === 'browser' || activeWorkKind === 'search' || activeWorkKind === 'web';
   const isMcpWork = activeWorkKind === 'mcp';
   const isToolWork = activeWorkKind === 'tool' || activeWorkKind === 'skill' || activeWorkKind === 'hive';
   const isReflectionWork = activeWorkKind === 'reflection' || activeWorkKind === 'thinking';

   const realActionRows = timelineWorkActivities;
   const startedPhaseIndexes = new Set(realActionRows.map(row => Number(row.phase_index) || 0).filter(Boolean));
   const highestStartedPhaseIndex = Math.max(1, ...Array.from(startedPhaseIndexes));
   const visiblePlanningRows = planningRows.filter((row, index) => {
      const phaseIndex = Number(row.phase_index) || index + 1;
      if (index === 0) return true;
      return phaseIndex <= highestStartedPhaseIndex;
   });
   const parseInlineMarkdown = (text: string): React.ReactNode[] => {
      if (!text) return [];
      const parts = text.split(/(\*\*.*?\*\*|\*.*?\*|`.*?`)/g);
      return parts.map((part, idx) => {
         if (part.startsWith('**') && part.endsWith('**')) {
            return <strong key={idx}>{part.slice(2, -2)}</strong>;
         }
         if (part.startsWith('*') && part.endsWith('*')) {
            return <em key={idx}>{part.slice(1, -1)}</em>;
         }
         if (part.startsWith('`') && part.endsWith('`')) {
            return <code key={idx} style={{
               background: agentLite ? 'rgba(0,0,0,0.05)' : 'rgba(255,255,255,0.08)',
               padding: '2px 4px',
               borderRadius: '4px',
               fontFamily: 'var(--font-mono)',
               fontSize: '0.9em'
            }}>{part.slice(1, -1)}</code>;
         }
         return part;
      });
   };

   const renderMessageMarkdown = (content: string, _isUserMsg: boolean): React.ReactNode => {
      if (!content) return null;
      const parts = content.split(/(```[\s\S]*?```)/g);
      return (
         <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {parts.map((part, index) => {
               if (part.startsWith('```')) {
                  const match = part.match(/```([a-zA-Z0-9_-]*)\n([\s\S]*?)```/);
                  const lang = match ? match[1] : '';
                  const code = match ? match[2].trim() : part.slice(3, -3).trim();
                  return (
                     <div key={index} className="code-block-card" style={{
                        margin: '10px 0',
                        borderRadius: '8px',
                        overflow: 'hidden',
                        border: '1px solid ' + (agentLite ? 'rgba(0,0,0,0.08)' : 'rgba(255,255,255,0.08)'),
                        background: agentLite ? '#f9fafb' : '#0d0d0d',
                        width: '100%',
                        maxWidth: '100%'
                     }}>
                        <div className="code-block-header" style={{
                           padding: '6px 12px',
                           fontSize: '0.72rem',
                           color: '#888',
                           background: agentLite ? '#f3f4f6' : 'rgba(255,255,255,0.02)',
                           borderBottom: '1px solid ' + (agentLite ? 'rgba(0,0,0,0.06)' : 'rgba(255,255,255,0.05)'),
                           display: 'flex',
                           justifyContent: 'space-between',
                           alignItems: 'center'
                        }}>
                           <span>{lang ? lang.toUpperCase() : 'CODE'}</span>
                           <button
                              onClick={() => {
                                 navigator.clipboard.writeText(code);
                              }}
                              style={{
                                 background: 'transparent',
                                 border: 'none',
                                 color: '#3b82f6',
                                 cursor: 'pointer',
                                 fontWeight: 600,
                                 fontSize: '0.7rem'
                              }}
                           >
                              Copy
                           </button>
                        </div>
                        <pre style={{
                           margin: 0,
                           padding: '12px',
                           overflowX: 'auto',
                           fontFamily: 'var(--font-mono)',
                           fontSize: '0.84rem',
                           lineHeight: '1.45',
                           color: agentLite ? '#111827' : '#e5e7eb'
                        }}>
                           <code>{code}</code>
                        </pre>
                     </div>
                  );
               }
               const lines = part.split('\n');
               return (
                  <div key={index} style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                     {lines.map((line, lineIdx) => {
                        const trimmed = line.trim();
                        if (!trimmed && lineIdx > 0 && lineIdx < lines.length - 1) {
                           return <div key={lineIdx} style={{ height: '8px' }} />;
                        }
                        const headerMatch = line.match(/^(#{1,6})\s+(.*)/);
                        if (headerMatch) {
                           const level = headerMatch[1].length;
                           const fontSize = level === 1 ? '1.35rem' : level === 2 ? '1.18rem' : '1.05rem';
                           return (
                              <div key={lineIdx} style={{
                                 fontWeight: 800,
                                 fontSize,
                                 margin: '12px 0 6px',
                                 color: agentLite ? '#111827' : '#ffffff'
                              }}>
                                 {parseInlineMarkdown(headerMatch[2])}
                              </div>
                           );
                        }
                        const bulletMatch = line.match(/^([-*+])\s+(.*)/);
                        if (bulletMatch) {
                           return (
                              <div key={lineIdx} style={{
                                 display: 'flex',
                                 flexDirection: 'row',
                                 alignItems: 'flex-start',
                                 paddingLeft: '12px',
                                 gap: '8px',
                                 margin: '2px 0'
                              }}>
                                 <span style={{ color: '#3b82f6', fontWeight: 'bold' }}>•</span>
                                 <span>{parseInlineMarkdown(bulletMatch[2])}</span>
                              </div>
                           );
                        }
                        const numMatch = line.match(/^(\d+)\.\s+(.*)/);
                        if (numMatch) {
                           return (
                              <div key={lineIdx} style={{
                                 display: 'flex',
                                 flexDirection: 'row',
                                 alignItems: 'flex-start',
                                 paddingLeft: '12px',
                                 gap: '8px',
                                 margin: '2px 0'
                              }}>
                                 <span style={{ color: '#3b82f6', fontWeight: 600 }}>{numMatch[1]}.</span>
                                 <span>{parseInlineMarkdown(numMatch[2])}</span>
                              </div>
                           );
                        }
                        return (
                           <div key={lineIdx} style={{ margin: '1px 0' }}>
                              {parseInlineMarkdown(line)}
                           </div>
                        );
                     })}
                  </div>
               );
            })}
         </div>
      );
   };

   const extractCanvasArtifact = () => {
      const allText = [...messages].reverse()
         .filter(message => !isAssistantError(message.content || ''))
         .map(message => message.content || '')
         .join('\n');
      const fenced = allText.match(/```([a-zA-Z0-9_-]*)\n([\s\S]*?)```/);
      if (fenced) {
         const lang = fenced[1] || 'code';
         const code = fenced[2].trim();
         return {
            lang,
            name: lang === 'html' ? 'index.html' : lang === 'python' || lang === 'py' ? 'main.py' : lang === 'tsx' ? 'App.tsx' : `artifact.${lang}`,
            code,
         };
      }
      const htmlStart = allText.search(/<!doctype\b|<html\b/i);
      if (htmlStart >= 0) {
         const code = allText.slice(htmlStart).trim();
         return { lang: 'html', name: 'index.html', code };
      }
      const implicitStart = allText.search(/\b(function|const|let|class|def|import|from)\b/);
      if (implicitStart >= 0) {
         const code = allText.slice(implicitStart).trim();
         return { lang: 'code', name: 'scratch.txt', code };
      }
      return {
         lang: 'note',
         name: 'canvas.md',
         code: isAssistantError(canvasLatestAssistant?.content || '')
            ? 'No artifact yet. Ask NEXUS to build code, edit files, or create a plan.'
            : cleanAssistantText(canvasLatestAssistant?.content || 'No artifact yet. Ask NEXUS to build code, edit files, or create a plan.'),
      };
   };
   const canvasArtifact = extractCanvasArtifact();
   const canvasFileName = (() => {
      if (activeCanvasWorkEvent) {
         if (activeWorkKind === 'todo') return 'todo.md';
         if (isCommandWork) return 'terminal';
         if (isReflectionWork) return 'thinking';
         if (isBrowserWork) return activeWorkKind === 'search' ? 'search' : 'browser';
         if (isMcpWork) return 'mcp';
         if (isToolWork) return activeWorkKind || 'tool';
         const target = resolveWorkActivityTarget(activeCanvasWorkEvent) || getWorkActivityTarget(activeCanvasWorkEvent);
         const normalizedTarget = String(target || '').replace(/\\/g, '/').split(/\s+/)[0];
         return normalizedTarget.split('/').filter(Boolean).pop() || activeWorkKind || canvasArtifact.name;
      }
      if (activeCanvasPreview?.name) return activeCanvasPreview.name;
      const target = canvasPreviewTarget || String(latestWorkActivity?.target || '').trim();
      if (!target) return canvasArtifact.name;
      const normalized = target.replace(/\\/g, '/').split(/\s+/)[0];
      return normalized.split('/').pop() || canvasArtifact.name;
   })();
   const canvasModeLabel = isCommandWork ? 'Terminal'
      : isBrowserWork ? 'Browser'
      : isMcpWork ? 'MCP'
      : activeWorkKind === 'todo' ? 'Planning'
      : isReflectionWork ? 'Thinking'
      : isToolWork ? 'Tool'
      : 'Editor';
   const canvasStatusText = `NEXUS is using ${canvasModeLabel}`;
    const canvasFileStatus = activeCanvasWorkEvent
       ? activeWorkKind === 'todo'
          ? `Performing todo.md`
          : isCommandWork
             ? `Performing ${shortWorkTarget(resolveWorkActivityTarget(activeCanvasWorkEvent), 96)}`
             : isReflectionWork
                ? 'Performing Reasoning Log'
             : `Performing ${getWorkActivityTarget(activeCanvasWorkEvent)}`
       : canvasFileName ? `Performing ${canvasFileName}` : 'Ready';
    const selectedResolvedTarget = activeCanvasWorkEvent ? resolveWorkActivityTarget(activeCanvasWorkEvent) : '';
    const selectedCommandRun = activeCanvasWorkEvent ? commandRuns[commandEventKey(activeCanvasWorkEvent)] : undefined;
    const terminalPrompt = 'nexus@local:~ $';
    const selectedCommandText = activeCanvasWorkEvent && isCommandWork
       ? String(selectedCommandRun?.command || activeCanvasWorkEvent.command || selectedResolvedTarget || '').trim()
       : '';
    const selectedTerminalTranscript = activeCanvasWorkEvent && isCommandWork
       ? (() => {
          const stdout = String(selectedCommandRun?.stdout || activeCanvasWorkEvent.stdout || '').trimEnd();
          const stderr = String(selectedCommandRun?.stderr || activeCanvasWorkEvent.stderr || '').trimEnd();
          const output = String(selectedCommandRun?.output || activeCanvasWorkEvent.output || '').trimEnd();
          let body = [stdout || output, stderr].filter(Boolean).join('\n');
          return [
             selectedCommandText ? `${terminalPrompt} ${selectedCommandText}` : '',
             body,
          ].filter(line => line !== '').join('\n');
       })()
       : '';
    const formatActivityValue = (value: any) => {
       if (value === null || value === undefined || value === '') return '';
       if (typeof value === 'string') return value.trim();
       try {
          return JSON.stringify(value, null, 2);
       } catch {
          return String(value);
       }
    };
    const selectedActivityDetails = activeCanvasWorkEvent ? [
       { label: 'Action', value: getWorkActivityLabel(activeCanvasWorkEvent) },
       { label: 'Target', value: selectedResolvedTarget || getWorkActivityTarget(activeCanvasWorkEvent) },
       { label: 'Status', value: activeCanvasWorkEvent.status },
       { label: 'Tool', value: activeCanvasWorkEvent.tool || activeCanvasWorkEvent.name },
       { label: 'Server', value: activeCanvasWorkEvent.server || activeCanvasWorkEvent.mcp_server },
       { label: 'Provider', value: activeCanvasWorkEvent.provider || activeCanvasWorkEvent.model },
       { label: 'Result', value: activeCanvasWorkEvent.result || activeCanvasWorkEvent.output || activeCanvasWorkEvent.stdout },
       { label: 'Error', value: activeCanvasWorkEvent.stderr || activeCanvasWorkEvent.preview_error || activeCanvasWorkEvent.error },
    ]
       .map(item => ({ ...item, value: formatActivityValue(item.value) }))
       .filter(item => item.value)
    : [];
    const selectedWorkDetail = activeCanvasWorkEvent
       ? String(activeCanvasWorkEvent.kind || activeCanvasWorkEvent.type || '').toLowerCase() === 'todo'
         ? String(activeCanvasWorkEvent.preview || '').trim() || [
            '# TODO Plan',
            '',
            activeCanvasWorkEvent.task ? `Task: ${activeCanvasWorkEvent.task}` : '',
            '',
            ...(visiblePlanningRows.length
               ? visiblePlanningRows.map(row => {
                  const selected = row.id && activeCanvasWorkEvent.id && row.id === activeCanvasWorkEvent.id ? '>> ' : '';
                  const done = String(row.status || '').toLowerCase() === 'done' ? 'x' : ' ';
                  const title = row.phase || row.title || row.action || getWorkActivityTarget(row);
                  const childRows = collapseWorkActivities(allWorkActivities)
                     .filter(action => String(action.kind || action.type || '').toLowerCase() !== 'todo')
                     .filter(action => Number(action.phase_index) === Number(row.phase_index));
                  return [
                     `${selected}- [${done}] ${title}`,
                     ...childRows.map(action => {
                        const actionDone = String(action.status || '').toLowerCase() === 'done' ? 'x' : ' ';
                        return `  - [${actionDone}] ${getWorkActivityLabel(action)}: ${getWorkActivityTarget(action)}`;
                     }),
                  ].join('\n');
               })
               : [activeCanvasWorkEvent].filter(Boolean).map(item => `- [ ] ${getWorkActivityLabel(item)}: ${getWorkActivityTarget(item)}`)),
          ].filter(line => line !== '').join('\n')
        : String(activeCanvasWorkEvent.kind || activeCanvasWorkEvent.type || '').toLowerCase() === 'command'
           ? selectedTerminalTranscript
          : selectedActivityDetails.map(item => `${item.label}: ${item.value}`).join('\n\n')
       : '';
   const inferCanvasLanguage = (fileName = '', fallback = 'code') => {
      const ext = (fileName.split('.').pop() || '').toLowerCase();
      const labels: Record<string, string> = {
         md: 'markdown',
         markdown: 'markdown',
         py: 'python',
         pyw: 'python',
         html: 'html',
         htm: 'html',
         css: 'css',
         scss: 'scss',
         sass: 'sass',
         js: 'javascript',
         jsx: 'jsx',
         ts: 'typescript',
         tsx: 'tsx',
         json: 'json',
         jsonl: 'jsonl',
         yaml: 'yaml',
         yml: 'yaml',
         cpp: 'c++',
         cc: 'c++',
         cxx: 'c++',
         c: 'c',
         h: 'c/c++',
         hpp: 'c++',
         cs: 'c#',
         java: 'java',
         rs: 'rust',
         go: 'go',
         rb: 'ruby',
         php: 'php',
         sh: 'shell',
         bash: 'shell',
         ps1: 'powershell',
         sql: 'sql',
         xml: 'xml',
         txt: 'text',
         thinking: 'thinking',
         reflection: 'thinking',
      };
      return labels[ext] || fallback || 'code';
   };
   const canvasEditorLang = inferCanvasLanguage(
      activeCanvasWorkEvent ? canvasFileName : activeCanvasPreview?.name || canvasFileName,
      activeCanvasWorkEvent
         ? (isCommandWork ? 'shell' : isReflectionWork ? 'thinking' : activeWorkKind === 'todo' ? 'md' : activeWorkKind || 'json')
         : activeCanvasPreview?.ext || canvasArtifact.lang
   );
    const canvasEditorCode = (() => {
        if (activeCanvasWorkEvent && isCommandWork) return selectedTerminalTranscript;
        
        let code = '';
        if (canvasPlaybackTime !== null) {
           // Convert virtual seconds to step index for slicing
           const _sliceStepIndex = Math.min(timelineWorkActivities.length - 1, Math.floor(canvasPlaybackTime / 5));
           const pastFileEvents = timelineWorkActivities
              .slice(0, _sliceStepIndex + 1)
              .filter(event => 
                 String(event.kind || event.type || '').toLowerCase() === 'file' &&
                 event.preview
              );
           if (pastFileEvents.length > 0) {
              const latestFileEvent = pastFileEvents[pastFileEvents.length - 1];
              code = latestFileEvent.preview || '';
           } else {
              code = activeCanvasWorkEvent?.preview || canvasArtifact.code || '';
           }
        } else {
           if (activeCanvasPreview?.content) code = activeCanvasPreview.content;
           else if (activeCanvasWorkEvent?.preview) code = activeCanvasWorkEvent.preview;
           else code = selectedWorkDetail || (canvasPreviewError ? `Preview unavailable: ${canvasPreviewError}` : canvasArtifact.code || 'No artifact yet.');
        }

        if (activeCanvasWorkEvent && String(activeCanvasWorkEvent.kind || '').toLowerCase() === 'todo') {
           const title = activeCanvasWorkEvent.title || activeCanvasWorkEvent.action || 'Workspace Phase';
           const status = String(activeCanvasWorkEvent.status || 'pending').toUpperCase();
           const items = Array.isArray(activeCanvasWorkEvent.items) ? activeCanvasWorkEvent.items : [];
           const checked = Array.isArray(activeCanvasWorkEvent.checked_items) ? activeCanvasWorkEvent.checked_items : [];
           const lines = [
              `# ${title}`,
              `Status: **${status}**`,
              '',
              '## Objectives / Checklist',
           ];
           if (items.length > 0) {
              items.forEach((item: string) => {
                 const isDone = checked.includes(item) || status === 'DONE';
                 const box = isDone ? '[x]' : status === 'RUNNING' ? '[/]' : '[ ]';
                 lines.push(`- ${box} ${item}`);
              });
           } else {
              lines.push('*No checklist items defined for this phase.*');
           }
           return lines.join('\n');
        }
        return code;
     })();
   const canvasEditorLineCount = Math.max(1, canvasEditorCode.split('\n').length);
   const canvasEditorLineNumbers = Array.from({ length: canvasEditorLineCount }, (_, index) => index + 1).join('\n');
   const canvasCanRunHtml = /^(html?|xml)$/i.test(canvasEditorLang) || /<!doctype\b|<html\b|<canvas\b[\s>]/i.test(canvasEditorCode);
   const normalizeSearchResult = (item: any, index: number) => {
      if (item && typeof item === 'object') {
         const url = String(item.url || item.href || item.link || item.source_url || item.source || '').trim();
         const title = String(item.title || item.name || item.heading || item.url || `Result ${index + 1}`).trim();
         const snippet = String(item.snippet || item.description || item.content || item.summary || item.text || '').trim();
         let domain = String(item.domain || item.site || item.provider || '').trim();
         try {
            if (!domain && url) domain = new URL(url).hostname.replace(/^www\./, '');
         } catch {
            domain = '';
         }
         return { title, snippet, url, domain };
      }

      const line = String(item || '').trim();
      const markdown = line.match(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/);
      const urlMatch = line.match(/https?:\/\/[^\s)]+/);
      const url = markdown?.[2] || urlMatch?.[0] || '';
      const cleaned = line
         .replace(/^\s*[-*]\s*/, '')
         .replace(/^\s*\d+[\).]\s*/, '')
         .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/, '$1')
         .replace(url, '')
         .replace(/\s+[-–—]\s*$/, '')
         .trim();
      const parts = cleaned.split(/\s+[-–—]\s+/).filter(Boolean);
      const title = parts[0] || (url ? url.replace(/^https?:\/\//, '') : `Result ${index + 1}`);
      const snippet = parts.slice(1).join(' - ');
      let domain = '';
      try {
         if (url) domain = new URL(url).hostname.replace(/^www\./, '');
      } catch {
         domain = '';
      }
      return { title, snippet, url, domain };
   };

   const canvasSearchResults = (() => {
      if (activeWorkKind !== 'search') return [];
      const raw = activeCanvasWorkEvent?.results || activeCanvasWorkEvent?.items || activeCanvasWorkEvent?.output || activeCanvasWorkEvent?.preview || '';
      const rawResults = raw && typeof raw === 'object' && !Array.isArray(raw)
         ? (raw.results || raw.items || raw.sources || raw.data || [])
         : raw;
      if (Array.isArray(rawResults)) {
         return rawResults.map(normalizeSearchResult).filter((result: any) => result.title || result.snippet || result.url).slice(0, 8);
      }
      const text = String(rawResults || '');
      const markdownLinks = [...text.matchAll(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)(?:\s*[-–—]\s*([^\n]+))?/g)];
      if (markdownLinks.length) {
         return markdownLinks.map((match, index) => normalizeSearchResult({
            title: match[1],
            url: match[2],
            snippet: match[3] || '',
         }, index)).slice(0, 8);
      }
      return text
         .split('\n')
         .map(line => line.trim())
         .filter(Boolean)
         .slice(0, 8)
         .map(normalizeSearchResult)
         .filter((result: any) => result.title || result.snippet || result.url);
    })();
    const renderCanvasMain = () => {
       if (isCommandWork) {
          const terminalLines = (canvasEditorCode || (selectedCommandText ? `${terminalPrompt} ${selectedCommandText}` : 'No command captured.')).split('\n');
          return (
             <div className="canvas-terminal-view">
                <div className="canvas-terminal-transcript">
                   {terminalLines.map((line, index) => (
                      <div
                         className="canvas-terminal-row"
                         key={`${index}-${line}`}
                      >
                         <span className="canvas-terminal-lines" aria-hidden="true">{index + 1}</span>
                         <span className={`canvas-terminal-line ${line.startsWith(terminalPrompt) ? 'prompt' : ''}`}>
                            {line || ' '}
                         </span>
                      </div>
                   ))}
                </div>
             </div>
          );
       }
      if (activeWorkKind === 'search') {
         const searchQuery = activeCanvasWorkEvent ? resolveWorkActivityTarget(activeCanvasWorkEvent) : '';
         return (
            <div className="canvas-search-view">
               <div className="canvas-search-titlebar">Search</div>
               <div className="canvas-search-summary">
                  <Search size={16} />
                  <span>{canvasSearchResults.length ? `Found ${canvasSearchResults.length} source${canvasSearchResults.length === 1 ? '' : 's'}` : 'Search activity'}</span>
                  {searchQuery && <code>{shortWorkTarget(searchQuery, 96)}</code>}
               </div>
               <div className="canvas-search-list">
                  {canvasSearchResults.length ? canvasSearchResults.map((result: any, index: number) => (
                     <a
                        className={`canvas-search-result ${result.url ? 'clickable' : ''}`}
                        href={result.url || undefined}
                        target={result.url ? '_blank' : undefined}
                        rel={result.url ? 'noreferrer' : undefined}
                        key={`${result.url || result.title || index}`}
                        onClick={event => {
                           if (!result.url) event.preventDefault();
                        }}
                     >
                        <span className="canvas-search-source-mark">{String(result.domain || result.title || '?').slice(0, 1).toUpperCase()}</span>
                        <span className="canvas-search-result-main">
                           <span className="canvas-search-result-title">{result.title || result.name || result.url || `Result ${index + 1}`}</span>
                           {(result.snippet || result.content || result.description) && <span className="canvas-search-snippet">{result.snippet || result.content || result.description}</span>}
                           {(result.domain || result.url) && <span className="canvas-search-url">{result.domain || result.url}</span>}
                        </span>
                     </a>
                  )) : <pre>{canvasEditorCode}</pre>}
               </div>
            </div>
         );
      }
       if (activeWorkKind === 'browser') {
          const targetUrl = selectedResolvedTarget || getWorkActivityTarget(activeCanvasWorkEvent) || 'about:blank';
          const screenshotUrl = canvasPlaybackTime !== null && activeCanvasWorkEvent
             ? `/api/screenshot/live?event=${activeCanvasWorkEvent.id}&t=${Date.now()}`
             : `/api/screenshot/live?event=live&t=${Date.now()}`;
          return (
             <div className="canvas-browser-view">
                <div className="canvas-browser-navbar">
                   <div className="canvas-browser-dots">
                      <span className="dot dot-red"></span>
                      <span className="dot dot-yellow"></span>
                      <span className="dot dot-green"></span>
                   </div>
                   <div className="canvas-browser-address-bar">
                      <Monitor size={12} className="canvas-browser-address-icon" />
                      <input type="text" readOnly value={targetUrl} />
                   </div>
                </div>
                <div className="canvas-browser-viewport">
                   <img 
                      src={screenshotUrl} 
                      alt="Browser Screenshot" 
                      className="canvas-browser-screenshot" 
                      onError={(e) => {
                         e.currentTarget.style.display = 'none';
                      }}
                      onLoad={(e) => {
                         e.currentTarget.style.display = 'block';
                      }}
                   />
                   <div className="canvas-activity-fields">
                      {selectedActivityDetails.length ? (
                         <div className="canvas-activity-fields-row">
                            {selectedActivityDetails.map(item => (
                               <div className="canvas-activity-field" key={`${item.label}-${item.value.slice(0, 24)}`}>
                                  <span>{item.label}</span>
                                  <p>{item.value}</p>
                               </div>
                            ))}
                         </div>
                      ) : (
                         <div className="canvas-activity-empty">No captured browser result yet.</div>
                      )}
                   </div>
                </div>
             </div>
          );
       }
       if (activeCanvasWorkEvent && (isMcpWork || isToolWork || ['skill', 'plugin', 'provider', 'hive'].includes(activeWorkKind))) {
          const ActivityDetailIcon = getWorkActivityIcon(activeWorkKind);
          return (
             <div className="canvas-activity-view">
                <div className="canvas-activity-hero">
                   <span className="canvas-activity-icon"><ActivityDetailIcon size={20} /></span>
                   <span>
                      <strong>{getWorkActivityLabel(activeCanvasWorkEvent)}</strong>
                      <small>{selectedResolvedTarget || getWorkActivityTarget(activeCanvasWorkEvent)}</small>
                   </span>
                </div>
                <div className="canvas-activity-fields">
                   {selectedActivityDetails.length ? selectedActivityDetails.map(item => (
                      <div className="canvas-activity-field" key={`${item.label}-${item.value.slice(0, 24)}`}>
                         <span>{item.label}</span>
                         <p>{item.value}</p>
                      </div>
                   )) : (
                      <div className="canvas-activity-empty">No captured result yet.</div>
                   )}
                </div>
             </div>
          );
       }
      if (canvasCanRunHtml && canvasViewMode === 'preview') {
         return (
            <iframe
               className="canvas-html-preview canvas-html-preview-main"
               title="NEXUS artifact preview"
               sandbox="allow-scripts allow-pointer-lock"
               srcDoc={canvasEditorCode}
            />
         );
      }
      return (
         <div className="canvas-editor-source">
            <pre className="canvas-editor-lines" aria-hidden="true">{canvasEditorLineNumbers}</pre>
            <pre className="canvas-editor-code"><code>{canvasEditorCode}</code></pre>
         </div>
      );
   };
   const latestAssistantIndex = messages.map(message => message.role).lastIndexOf('assistant');
   const renderWorkActivityTimeline = (rows: WorkEvent[], options: { compact?: boolean; phaseLabel?: string } = {}) => (
      <WorkActivityTimeline
         allWorkActivities={allWorkActivities}
         collapseWorkActivities={collapseWorkActivities}
         compact={options.compact}
         getWorkActivityIcon={getWorkActivityIcon}
         getWorkActivityLabel={getWorkActivityLabel}
         getWorkActivityTarget={getWorkActivityTarget}
         isPlanningArtifact={isPlanningArtifact}
         messages={messages}
         openWorkEvent={openWorkEvent}
         phaseLabel={options.phaseLabel}
         rows={rows}
      />
   );
   const startEvolutionPrompt = (prompt: string) => {
      setActiveTab('session');
      setInputValue(prompt);
   };
   const agentLite = ['light', 'white'].includes(interfaceMode);
   void [
      Eye,
      EyeOff,
      ShieldAlert,
      securityStates,
      setSecurityStates,
      setShowChatAvatars,
      setShowLogoInHeader,
      setShowLogoMark,
      showAddMcpModal,
      newMcpName,
      newMcpConfig,
      mcpPanelMode,
      mcpPanelError,
      showApiKey,
      providerCheck,
      confirmModal,
      saveAssetPanel,
      isAddingProvider,
      runProviderCheck,
   ];
   const modalTextColor = agentLite ? '#111827' : '#f8fafc';
   const modalMutedColor = agentLite ? '#64748b' : '#9ca3af';
   const modalCardStyle: React.CSSProperties = {
      background: agentLite ? '#fbfaf8' : 'rgba(255,255,255,0.035)',
      border: agentLite ? '1px solid #e4dfd8' : '1px solid rgba(255,255,255,0.08)',
      borderRadius: '12px',
      padding: '16px',
      display: 'flex',
      flexDirection: 'column',
      gap: '10px',
      minHeight: '118px',
   };
   const modalGridStyle: React.CSSProperties = {
      display: 'grid',
      gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))',
      gap: '14px',
      paddingRight: '6px',
   };
   const modalButtonStyle: React.CSSProperties = {
      border: agentLite ? '1px solid #cbd5e1' : '1px solid rgba(255,255,255,0.10)',
      background: agentLite ? '#ffffff' : 'rgba(255,255,255,0.045)',
      color: modalTextColor,
      borderRadius: '9px',
      padding: '8px 10px',
      fontWeight: 800,
      fontSize: '0.72rem',
      cursor: 'pointer',
   };
   const modalCardActionsStyle: React.CSSProperties = {
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'flex-end',
      gap: '7px',
      flexShrink: 0,
      flexWrap: 'wrap',
   };
   const modalIconButtonStyle = (tone: 'neutral' | 'blue' | 'red' = 'neutral'): React.CSSProperties => ({
      width: '30px',
      height: '30px',
      display: 'inline-flex',
      alignItems: 'center',
      justifyContent: 'center',
      padding: 0,
      background: tone === 'blue'
         ? 'rgba(59,130,246,0.10)'
         : tone === 'red'
            ? 'rgba(239,68,68,0.08)'
            : modalButtonStyle.background,
      border: tone === 'blue'
         ? '1px solid rgba(59,130,246,0.25)'
         : tone === 'red'
            ? '1px solid rgba(239,68,68,0.18)'
            : modalButtonStyle.border,
      color: tone === 'blue' ? 'var(--accent-blue)' : tone === 'red' ? '#f87171' : modalButtonStyle.color,
      borderRadius: '8px',
      cursor: 'pointer',
   });
   const modalVersionBadgeStyle: React.CSSProperties = {
      width: '30px',
      height: '30px',
      display: 'inline-flex',
      alignItems: 'center',
      justifyContent: 'center',
      fontSize: '0.68rem',
      fontWeight: 900,
      color: '#b8c7ff',
      background: 'rgba(59,130,246,0.10)',
      border: '1px solid rgba(59,130,246,0.22)',
      borderRadius: '8px',
      whiteSpace: 'nowrap',
   };
   const configDrawerOverlayStyle: React.CSSProperties = {
      position: 'absolute',
      top: 0,
      left: 0,
      width: '100%',
      height: '100%',
      zIndex: 9100,
      display: 'flex',
      justifyContent: 'flex-end',
      alignItems: 'stretch',
      padding: 0,
      background: agentLite ? 'rgba(15, 23, 42, 0.15)' : 'rgba(0, 0, 0, 0.45)',
      backdropFilter: 'blur(5px)',
      WebkitBackdropFilter: 'blur(5px)',
      borderRadius: '24px',
      pointerEvents: 'auto',
   };
   const configDrawerStyle: React.CSSProperties = {
      width: '460px',
      maxWidth: 'calc(100% - 60px)',
      height: '100%',
      maxHeight: '100%',
      overflow: 'hidden',
      borderRadius: '0 24px 24px 0',
      padding: 0,
      borderLeft: agentLite ? '1px solid #cbd5e1' : '1px solid rgba(255,255,255,0.08)',
      background: agentLite ? '#ffffff' : '#0d0d11',
      boxShadow: '-10px 0 40px rgba(0,0,0,0.3)',
      animation: 'config-drawer-in 220ms cubic-bezier(0.16, 1, 0.3, 1)',
      pointerEvents: 'auto',
   };
   const modalInputStyle: React.CSSProperties = {
      width: '100%',
      height: '38px',
      border: agentLite ? '1px solid #cbd5e1' : '1px solid rgba(255,255,255,0.10)',
      background: agentLite ? '#ffffff' : 'rgba(0,0,0,0.22)',
      color: modalTextColor,
      borderRadius: '9px',
      padding: '0 12px',
      outline: 'none',
      fontWeight: 700,
   };
   const getModalInputStyle = (disabled?: boolean): React.CSSProperties => ({
      ...modalInputStyle,
      border: disabled
         ? (agentLite ? '1px solid #cbd5e1' : '1px solid rgba(255,255,255,0.05)')
         : modalInputStyle.border,
      background: disabled
         ? (agentLite ? '#f1f5f9' : 'rgba(0,0,0,0.35)')
         : modalInputStyle.background,
      color: disabled
         ? (agentLite ? '#94a3b8' : '#55555d')
         : modalInputStyle.color,
      cursor: disabled ? 'not-allowed' : 'text',
      opacity: disabled ? 0.75 : 1,
   });
   const renderSettingsHeader = (title: string, subtitle: string, action?: React.ReactNode) => (
      <div style={{
         display: 'flex',
         justifyContent: 'space-between',
         alignItems: 'flex-start',
         gap: '16px',
         marginBottom: '16px',
         padding: '0 44px 10px 0',
         position: 'sticky',
         top: 0,
         zIndex: 4,
         background: agentLite ? '#ffffff' : '#0d0d0d',
      }}>
         <div>
            <h2 style={{ fontSize: '1.55rem', fontWeight: 900, color: modalTextColor, margin: '0 0 8px' }}>{title}</h2>
            <p style={{ color: modalMutedColor, margin: 0, lineHeight: 1.5, fontSize: '0.84rem' }}>{subtitle}</p>
         </div>
         {action}
      </div>
   );
   const settingsBulkOn = (tab: string) => (
      tab === 'mcp' ? allFilteredMcpOn
      : tab === 'skills' ? allFilteredSkillsOn
      : tab === 'tools' ? allFilteredToolsOn
      : false
   );
   const renderSettingsSearch = (
      value: string,
      setValue: (value: string) => void,
      placeholder: string,
      tab?: 'mcp' | 'skills' | 'tools',
   ) => (
      <div style={{ display: 'flex', gap: '10px', alignItems: 'center', marginBottom: '16px' }}>
         <div style={{ position: 'relative', flex: 1 }}>
            <Search size={15} style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', color: modalMutedColor }} />
            <input value={value} onChange={(event) => setValue(event.target.value)} placeholder={placeholder} style={{ ...modalInputStyle, paddingLeft: '36px' }} />
         </div>
         {tab && (
            <button
               disabled={bulkUpdating}
               onClick={() => {
                  const targetActive = !settingsBulkOn(tab);
                  if (tab === 'mcp') bulkToggleMcp(filteredMcpServers, targetActive);
                  if (tab === 'skills') bulkToggleAssets('skills', filteredSkills, targetActive);
                  if (tab === 'tools') bulkToggleAssets('tools', filteredTools, targetActive);
               }}
               style={{ ...modalButtonStyle, minWidth: '92px', opacity: bulkUpdating ? 0.55 : 1 }}
            >
               {bulkUpdating ? 'Updating' : settingsBulkOn(tab) ? 'All On' : 'All Off'}
            </button>
         )}
      </div>
   );
   const renderAssetSettingsCards = (kind: 'skills' | 'tools') => {
      const items = kind === 'skills' ? filteredSkills : filteredTools;
      return (
         <div style={modalGridStyle}>
            {items.map((item: any) => (
               <div key={item.name} style={modalCardStyle}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: '10px', alignItems: 'flex-start' }}>
                     <strong style={{ color: modalTextColor, fontSize: '0.98rem', overflowWrap: 'anywhere' }}>{formatCardName(item.name)}</strong>
                     <div style={modalCardActionsStyle}>
                        <span title="Version" style={modalVersionBadgeStyle}>{cardVersion(item)}</span>
                        <button title="Configure" style={modalIconButtonStyle('blue')} onClick={() => configureAsset(kind, item)}><Settings2 size={13} /></button>
                        <button title={item.active === false ? 'Off - click to turn on' : 'On - click to turn off'} style={powerButtonStyle(item.active !== false)} onClick={() => toggleAsset(kind, item.name, item.active, item.description, item.config)}><Power size={13} /></button>
                        <button title="Delete" style={modalIconButtonStyle('red')} onClick={() => deleteAsset(kind, item.name)}><Trash2 size={13} /></button>
                     </div>
                  </div>
                  <p style={{ color: modalMutedColor, lineHeight: 1.45, fontSize: '0.76rem', margin: 0 }}>{cleanAssetDescription(item.description, item.name)}</p>
               </div>
            ))}
            {items.length === 0 && <div style={modalCardStyle}>No {kind} match this search.</div>}
         </div>
      );
   };
   const renderMcpSettings = () => (
      <>
         {renderSettingsHeader('MCP Servers', `${filteredMcpServers.length} shown / ${state?.mcp?.total || state?.mcp?.servers?.length || 0} configured.`, (
            <button style={modalButtonStyle} onClick={openAddMcpPanel}>+ Add MCP</button>
         ))}
         {renderSettingsSearch(mcpSearch, setMcpSearch, 'Search MCP servers...', 'mcp')}
         <div style={modalGridStyle}>
            {filteredMcpServers.map((srv: any) => (
               <div key={srv.name} style={modalCardStyle}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: '10px', alignItems: 'flex-start' }}>
                     <strong style={{ color: modalTextColor, overflowWrap: 'anywhere' }}>{formatCardName(srv.name)}</strong>
                     <div style={modalCardActionsStyle}>
                        <span title="Version" style={modalVersionBadgeStyle}>{cardVersion(srv)}</span>
                        <button title="Configure MCP" style={modalIconButtonStyle('blue')} onClick={() => configureMcp(srv)}><Settings2 size={13} /></button>
                        <button title={srv.active === false ? 'Off - click to turn on' : 'On - click to turn off'} style={powerButtonStyle(srv.active !== false)} onClick={() => toggleMcp(srv)}><Power size={13} /></button>
                        <button title="Delete" style={modalIconButtonStyle('red')} onClick={() => deleteMcp(srv.name)}><Trash2 size={13} /></button>
                     </div>
                  </div>
                  <p style={{ color: modalMutedColor, fontSize: '0.76rem', lineHeight: 1.45, margin: 0 }}>{cleanAssetDescription(srv.description || srv.command, srv.name)}</p>
               </div>
            ))}
         </div>
      </>
   );
   const renderProviderSettings = () => (
      <>
         {renderSettingsHeader('LLM Providers', `${state?.provider_instances?.length || 0} routes across ${state?.providers?.length || 0} providers.`, (
            <button style={modalButtonStyle} onClick={addProvider}>+ Add Provider</button>
         ))}
         <div style={modalGridStyle}>
            {(state?.providers || []).map((provider: any) => {
               const routes = state?.provider_instances?.filter(route => route.parent === provider.name) || [];
               return (
                  <div key={provider.name} style={modalCardStyle}>
                     <div style={{ display: 'flex', justifyContent: 'space-between', gap: '10px', alignItems: 'flex-start' }}>
                        <strong style={{ color: modalTextColor, overflowWrap: 'anywhere' }}>{formatProviderName(provider.name)}</strong>
                        <div style={modalCardActionsStyle}>
                           <span title="Saved routes" style={modalVersionBadgeStyle}>{routes.length}</span>
                           <button
                              title="Add route"
                              style={modalIconButtonStyle('blue')}
                              onClick={() => {
                                 const routeId = nextProviderRouteId(provider.name, routes);
                                 setSelectedProv(provider);
                                 setProviderFamilyName(provider.name);
                                 setInstanceName(routeId);
                                 setEditingInstanceId(null);
                                 setApiKey('');
                                 setTargetModel(routes[0]?.model || '');
                                 setProviderEndpoint(provider.endpoint || '');
                                 setProviderCheck(null);
                                 setShowProviderPanel(true);
                              }}
                           >
                              <PlusCircle size={13} />
                           </button>
                        </div>
                     </div>
                     <p style={{ color: modalMutedColor, fontSize: '0.76rem', lineHeight: 1.45, margin: 0 }}>{cleanAssetDescription(provider.description || provider.endpoint, provider.name)}</p>
                     <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                        {routes.slice(0, 3).map(route => (
                           <button
                              key={route.id}
                              style={{ ...modalButtonStyle, textAlign: 'left', display: 'flex', justifyContent: 'space-between', gap: '8px' }}
                              onClick={() => {
                                 setSelectedProv(provider);
                                 setProviderFamilyName(provider.name);
                                 setInstanceName(route.id);
                                 setEditingInstanceId(route.id);
                                 setApiKey(route.api_key || '');
                                 setTargetModel(route.model || '');
                                 setProviderEndpoint(route.endpoint || provider.endpoint || '');
                                 setProviderCheck(null);
                                 setShowProviderPanel(true);
                              }}
                           >
                              <span>{route.id}</span>
                              <span style={{ color: route.has_api_key ? '#4ade80' : '#f87171' }}>{route.has_api_key ? 'KEY' : 'NO KEY'}</span>
                           </button>
                        ))}
                     </div>
                  </div>
               );
            })}
         </div>
      </>
   );
   const renderPluginSettings = () => (
      <>
         {renderSettingsHeader('Plugins', `${filteredPlugins.length} shown / ${(state?.plugins || []).length} installed or available.`, (
            <button style={modalButtonStyle} onClick={refreshPlugins} disabled={pluginBusy === 'install'}>Rescan</button>
         ))}
         <div style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: '10px', marginBottom: '10px' }}>
            <input value={pluginInstallUrl} onChange={(event) => setPluginInstallUrl(event.target.value)} placeholder="owner/repo, Git URL, or marketplace URL" style={modalInputStyle} />
            <button style={modalButtonStyle} onClick={installPlugin} disabled={pluginBusy === 'install'}>{pluginBusy === 'install' ? 'Installing' : 'Install'}</button>
         </div>
         {renderSettingsSearch(pluginSearch, setPluginSearch, 'Search plugins...')}
         <div style={modalGridStyle}>
            {filteredPlugins.map((plugin: any) => (
               <div key={plugin.id || plugin.name} style={modalCardStyle}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: '10px', alignItems: 'flex-start' }}>
                     <strong style={{ color: modalTextColor, overflowWrap: 'anywhere' }}>{formatCardName(plugin.name)}</strong>
                     <div style={modalCardActionsStyle}>
                        <span title="Version" style={modalVersionBadgeStyle}>{cardVersion(plugin)}</span>
                        {plugin.installed === false ? (
                           <button style={{ ...modalButtonStyle, height: '30px', padding: '0 10px', opacity: pluginBusy === plugin.id ? 0.55 : 1 }} onClick={() => installPluginFromCard(plugin)} disabled={pluginBusy === plugin.id}>Install</button>
                        ) : (
                        <>
                           <button title="Configure plugin" style={{ ...modalIconButtonStyle('blue'), opacity: pluginBusy === plugin.id ? 0.55 : 1 }} onClick={() => configurePlugin(plugin)} disabled={pluginBusy === plugin.id}><Settings2 size={13} /></button>
                           <button title={plugin.active === false ? 'Off - click to turn on' : 'On - click to turn off'} style={{ ...powerButtonStyle(plugin.active !== false), opacity: pluginBusy === plugin.id ? 0.55 : 1 }} onClick={() => togglePlugin(plugin)} disabled={pluginBusy === plugin.id}><Power size={13} /></button>
                           <button title={plugin.disk_removable ? 'Delete plugin files' : 'Hide plugin'} style={{ ...modalIconButtonStyle('red'), opacity: pluginBusy === plugin.id ? 0.55 : 1 }} onClick={() => removePlugin(plugin)} disabled={pluginBusy === plugin.id}><Trash2 size={13} /></button>
                        </>
                        )}
                     </div>
                  </div>
                  <p style={{ color: modalMutedColor, fontSize: '0.76rem', lineHeight: 1.45, margin: 0 }}>{cleanAssetDescription(plugin.description, plugin.name)}</p>
               </div>
            ))}
         </div>
      </>
   );
   const modalSwitchStyle = (isOn: boolean): React.CSSProperties => ({
      width: '42px',
      height: '24px',
      borderRadius: '999px',
      border: isOn ? '1px solid rgba(34,197,94,0.35)' : agentLite ? '1px solid #cbd5e1' : '1px solid rgba(255,255,255,0.14)',
      background: isOn ? 'rgba(34,197,94,0.18)' : agentLite ? '#e5e7eb' : 'rgba(255,255,255,0.08)',
      display: 'inline-flex',
      alignItems: 'center',
      justifyContent: isOn ? 'flex-end' : 'flex-start',
      padding: '2px',
      transition: 'all 0.18s ease',
      flexShrink: 0,
   });
   const modalSwitchKnobStyle = (isOn: boolean): React.CSSProperties => ({
      width: '18px',
      height: '18px',
      borderRadius: '999px',
      background: isOn ? '#4ade80' : '#94a3b8',
      boxShadow: '0 2px 8px rgba(0,0,0,0.24)',
   });
   const renderSwitchControl = (
      label: string,
      value: boolean,
      onChange: (value: boolean) => void,
      detail?: string,
      tone: 'green' | 'red' | 'blue' = 'green',
      compact = false,
   ) => (
      <button
         type="button"
         onClick={() => onChange(!value)}
         style={{
            ...modalCardStyle,
            minHeight: compact ? '72px' : '88px',
            padding: compact ? '12px 14px' : modalCardStyle.padding,
            textAlign: 'left',
            cursor: 'pointer',
            border: value
               ? tone === 'red' ? '1px solid rgba(248,113,113,0.30)' : tone === 'blue' ? '1px solid rgba(59,130,246,0.30)' : '1px solid rgba(34,197,94,0.30)'
               : modalCardStyle.border,
         }}
      >
         <span style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '14px' }}>
            <span>
               <strong style={{ color: modalTextColor, display: 'block', marginBottom: '4px' }}>{label}</strong>
               {detail && <small style={{ color: modalMutedColor, lineHeight: 1.35 }}>{detail}</small>}
            </span>
            <span style={modalSwitchStyle(value)} aria-hidden="true"><span style={modalSwitchKnobStyle(value)} /></span>
         </span>
      </button>
   );
   const renderAppearanceSettings = () => (
      <>
         {renderSettingsHeader('Interface GUI', 'Tune the shell, brand, accent, avatars, and display mode.')}
         <div style={{ display: 'grid', gridTemplateColumns: 'minmax(280px, 1.2fr) minmax(260px, 0.8fr)', gap: '12px', alignItems: 'start' }}>
            <div style={{ ...modalCardStyle, minHeight: 'auto', padding: '14px' }}>
               <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', alignItems: 'center' }}>
                  <strong style={{ color: modalTextColor }}>Display Mode</strong>
                  <span style={{ color: 'var(--accent-blue)', fontWeight: 900, fontSize: '0.68rem', textTransform: 'uppercase' }}>{interfaceMode}</span>
               </div>
               <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, minmax(0, 1fr))', gap: '8px' }}>
                  {['dark', 'light', 'grey', 'night', 'white'].map(mode => {
                     const selected = interfaceMode === mode;
                     return (
                        <button
                           key={mode}
                           style={{
                              ...modalButtonStyle,
                              minHeight: '44px',
                              padding: '7px 6px',
                              color: selected ? '#ffffff' : modalTextColor,
                              background: selected ? 'var(--accent-blue)' : modalButtonStyle.background,
                              border: selected ? '1px solid var(--accent-blue)' : modalButtonStyle.border,
                           }}
                           onClick={() => setInterfaceMode(mode)}
                        >
                           {formatCardName(mode)}
                        </button>
                     );
                  })}
               </div>
            </div>
            <div style={{ ...modalCardStyle, minHeight: 'auto', padding: '14px' }}>
               <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', alignItems: 'center' }}>
                  <strong style={{ color: modalTextColor }}>Brand</strong>
                  <span style={{ color: accentColor, fontWeight: 900, fontSize: '0.72rem', letterSpacing: '0.18em' }}>{brandMark || 'N'} {brandName || 'NEXUS'}</span>
               </div>
               <label style={{ color: modalMutedColor, fontSize: '0.7rem', fontWeight: 800 }}>
                  Name
                  <input value={brandName} onChange={(event) => setBrandName(event.target.value)} style={{ ...modalInputStyle, height: '34px', marginTop: '6px' }} aria-label="Brand name" />
               </label>
               <label style={{ color: modalMutedColor, fontSize: '0.7rem', fontWeight: 800 }}>
                  Mark
                  <input value={brandMark} onChange={(event) => setBrandMark(event.target.value)} style={{ ...modalInputStyle, height: '34px', marginTop: '6px' }} aria-label="Brand mark" />
               </label>
            </div>
            <div style={{ ...modalCardStyle, minHeight: 'auto', padding: '14px' }}>
               <strong style={{ color: modalTextColor }}>Accent</strong>
               <div style={{ display: 'grid', gridTemplateColumns: '1fr 56px', gap: '10px', alignItems: 'center' }}>
                  <input value={accentColor} onChange={(event) => setAccentColor(event.target.value)} style={{ ...modalInputStyle, height: '34px' }} aria-label="Accent hex" />
                  <input type="color" value={accentColor} onChange={(event) => setAccentColor(event.target.value)} style={{ ...modalInputStyle, height: '38px', padding: '5px' }} aria-label="Accent color" />
               </div>
               <div style={{ height: '10px', borderRadius: '999px', background: accentColor, boxShadow: `0 0 18px ${accentColor}55` }} />
            </div>
            <div style={{ ...modalCardStyle, minHeight: 'auto', padding: '14px' }}>
               <strong style={{ color: modalTextColor }}>Avatars</strong>
               <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}>
                  <label style={{ color: modalMutedColor, fontSize: '0.7rem', fontWeight: 800 }}>
                     Assistant
                     <input value={assistantAvatar} onChange={(event) => setAssistantAvatar(event.target.value)} style={{ ...modalInputStyle, height: '34px', marginTop: '6px' }} aria-label="Assistant avatar" />
                  </label>
                  <label style={{ color: modalMutedColor, fontSize: '0.7rem', fontWeight: 800 }}>
                     Operator
                     <input value={userAvatar} onChange={(event) => setUserAvatar(event.target.value)} style={{ ...modalInputStyle, height: '34px', marginTop: '6px' }} aria-label="User avatar" />
                  </label>
               </div>
            </div>
            <div style={{ gridColumn: '1 / -1', display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: '12px' }}>
               {renderSwitchControl('Chat avatars', showChatAvatars, setShowChatAvatars, 'Show icons beside chat turns.', 'blue', true)}
               {renderSwitchControl('Header logo', showLogoInHeader, setShowLogoInHeader, 'Keep brand in top shell.', 'blue', true)}
               {renderSwitchControl('Sidebar mark', showLogoMark, setShowLogoMark, 'Show mark by wordmark.', 'blue', true)}
            </div>
         </div>
      </>
   );
   const renderSecuritySettings = () => (
      <>
         {renderSettingsHeader('Security & Gates', 'Local safety switches for autonomous work and risky actions.')}
         <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '14px' }}>
            {renderSwitchControl(
               'Safety shield',
               securityStates.shield,
               (value) => setSecurityStates(prev => ({ ...prev, shield: value })),
               'Risk scoring and local safeguards stay active for autonomous actions.',
            )}
            {renderSwitchControl(
               'Command handshake',
               securityStates.handshake,
               (value) => setSecurityStates(prev => ({ ...prev, handshake: value })),
               'Commands keep their safety gate before high-risk execution.',
            )}
            {renderSwitchControl(
               'Emergency killswitch',
               securityStates.killswitch,
               (value) => setSecurityStates(prev => ({ ...prev, killswitch: value })),
               'Stop autonomous execution immediately when enabled.',
               'red',
            )}
            <div style={{ ...modalCardStyle, gridColumn: '1 / -1', minHeight: '96px' }}>
               <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', alignItems: 'center' }}>
                  <strong style={{ color: modalTextColor }}>Gate Status</strong>
                  <span style={{
                     color: securityStates.killswitch ? '#f87171' : '#4ade80',
                     background: securityStates.killswitch ? 'rgba(248,113,113,0.12)' : 'rgba(34,197,94,0.12)',
                     border: securityStates.killswitch ? '1px solid rgba(248,113,113,0.22)' : '1px solid rgba(34,197,94,0.22)',
                     borderRadius: '999px',
                     padding: '6px 10px',
                     fontWeight: 900,
                     fontSize: '0.68rem',
                     textTransform: 'uppercase',
                  }}>
                     {securityStates.killswitch ? 'Stopped' : 'Operational'}
                  </span>
               </div>
               <p style={{ color: modalMutedColor, margin: 0, lineHeight: 1.5, fontSize: '0.8rem' }}>
                  {securityStates.killswitch
                     ? 'Autonomous actions should remain paused while the emergency switch is enabled.'
                     : 'Current gates allow autonomous work while preserving shield and command safeguards.'}
               </p>
            </div>
         </div>
      </>
   );
   const renderSettingsContent = () => {
      if (settingsTab === 'appearance') return renderAppearanceSettings();
      if (settingsTab === 'providers') return renderProviderSettings();
      if (settingsTab === 'mcp') return renderMcpSettings();
      if (settingsTab === 'skills') return (
         <>
            {renderSettingsHeader('Skills', `${filteredSkills.length} shown / ${state?.skills?.length || 0} available.`, <button style={modalButtonStyle} onClick={() => addAsset('skills')}>+ Add Skill</button>)}
            {renderSettingsSearch(skillsSearch, setSkillsSearch, 'Search skills...', 'skills')}
            {renderAssetSettingsCards('skills')}
         </>
      );
      if (settingsTab === 'tools') return (
         <>
            {renderSettingsHeader('Tools', `${filteredTools.length} shown / ${state?.tools?.length || 0} available.`, <button style={modalButtonStyle} onClick={() => addAsset('tools')}>+ Add Tool</button>)}
            {renderSettingsSearch(toolsSearch, setToolsSearch, 'Search tools...', 'tools')}
            {renderAssetSettingsCards('tools')}
         </>
      );
      if (settingsTab === 'plugins') return renderPluginSettings();
      if (settingsTab === 'security') return renderSecuritySettings();
      return null;
   };

   return (
      <>
         <ActivityBar
            activeTab={activeActivityTab}
            onTabChange={(tab) => {
               setActiveActivityTab(tab);
               if (tab === 'chat') setActiveTab('session');
               else if (tab === 'settings') setSettingsOpen(true);
               else if (tab === 'canvas') setDrawerType('canvas');
               else if (tab === 'explorer') { setActiveTab('session'); }
            }}
            sidebarVisible={sidebarVisible}
            onToggleSidebar={() => setSidebarVisible(!sidebarVisible)}
            agentLite={agentLite}
         />
         <Sidebar
            brandName={brandName}
            brandMark={brandMark}
            showLogoMark={showLogoMark}
            currentSessionId={currentSessionId}
            deleteSession={deleteSession}
            editTitle={editTitle}
            editingId={editingId}
            historySearch={historySearch}
            hoveredSessionId={hoveredSessionId}
            isSidebarResizing={isSidebarResizing}
            loadSession={loadSession}
            operatorName={operatorName}
            renameSession={renameSession}
            sessionList={sessionList}
            sessionNotice={sessionNotice}
            settingsOpen={settingsOpen}
            setActiveTab={setActiveTab}
            setEditTitle={setEditTitle}
            setEditingId={setEditingId}
            setHistorySearch={setHistorySearch}
            setHoveredSessionId={setHoveredSessionId}
            setIsSidebarResizing={setIsSidebarResizing}
            setSettingsOpen={setSettingsOpen}
            sidebarVisible={sidebarVisible}
            sidebarWidth={sidebarWidth}
            newChat={handleNewChat}
         />

         <div
            className={`main-content ${agentLite ? 'lemon-lite' : ''} ${sidebarVisible ? '' : 'sidebar-collapsed'} ${drawerType !== 'none' ? 'drawer-open' : ''} ${drawerType === 'canvas' ? 'canvas-open' : ''} ${isCanvasResizing || isDrawerResizing ? 'canvas-resizing-active' : ''}`}
            data-task-files-open={taskFilesOpen ? 'true' : 'false'}
            style={{ ['--canvas-panel-width' as any]: `${canvasWidth}px`, ['--drawer-panel-width' as any]: `${drawerWidth}px` }}
         >
            {backendOffline && <BackendOfflineBanner />}
            <FloatingNavControls
               chatScrolled={chatScrolled}
               handleNewChat={handleNewChat}
               isSidebarResizing={isSidebarResizing}
               setSidebarVisible={setSidebarVisible}
               sidebarVisible={sidebarVisible}
               sidebarWidth={sidebarWidth}
            />
            <HeaderStatusRail
               chatScrolled={chatScrolled}
               drawerType={drawerType}
               healthClass={healthClass}
               hiveCount={state.hive?.length || 0}
               reminderCount={state.reminders?.length || 0}
               setDrawerType={setDrawerType}
            />
            <div
               className="task-action-cluster task-action-cluster-floating"
               aria-label="Task actions"
               onClickCapture={(event) => {
                  const target = event.target as HTMLElement | null;
                  if (target?.closest?.('button[aria-label="View all files in this task"]')) {
                     setActiveTab('session');
                     setTaskMenuOpen(false);
                     setTaskFilesOpen(true);
                     loadSources();
                     loadWorkEvents(currentSessionId, '');
                  }
               }}
               style={{ opacity: chatScrolled ? 0.16 : 1, pointerEvents: chatScrolled ? 'none' : 'auto', transform: chatScrolled ? 'translateY(-10px)' : 'translateY(0)' }}
            >
               <button
                  className="task-action-btn share"
                  type="button"
                  title="Copy share link"
                  aria-label="Copy share link"
                  onClick={copyChatLink}
               >
                  <Link2 size={16} />
                  <span>Share</span>
               </button>
               <button
                  className="task-action-btn files"
                  type="button"
                  title={taskFileCount ? `View ${taskFileCount} file${taskFileCount === 1 ? '' : 's'} in this task` : 'View all files in this task'}
                  aria-label="View all files in this task"
                  onClick={() => {
                     setActiveTab('session');
                     setTaskMenuOpen(false);
                     setTaskFilesOpen(true);
                     loadSources();
                     loadWorkEvents(currentSessionId, '');
                  }}
               >
                  <FileSearch size={16} />
                  <span>Files</span>
                  {taskFileCount > 0 && <span className="task-file-count">{taskFileCount}</span>}
               </button>
               <button
                  className="task-action-btn icon more"
                  type="button"
                  title="More task actions"
                  aria-label="More task actions"
                  onClick={(event) => {
                     event.stopPropagation();
                     setTaskFilesOpen(false);
                     setTaskMenuOpen(open => !open);
                  }}
               >
                  <MoreHorizontal size={17} />
               </button>
            </div>

            {taskMenuOpen && (
               <div
                  className={`task-more-menu ${agentLite ? 'lemon-lite' : ''}`}
                  onClick={event => event.stopPropagation()}
               >
                  <button
                     type="button"
                     onClick={() => {
                        setTaskMenuOpen(false);
                        setEditingId(currentSessionId);
                        setEditTitle(currentSessionTitle);
                        setSessionNotice({ kind: 'success', message: 'Rename this chat from the sidebar title field.' });
                     }}
                  >
                     <Edit2 size={17} />
                     <span>Rename</span>
                  </button>
                  <button
                     type="button"
                     onClick={() => {
                        setTaskMenuOpen(false);
                        setDrawerType('reminders');
                     }}
                  >
                     <Bell size={17} />
                     <span>Schedule a task</span>
                     <em>New</em>
                  </button>
                  <button
                     type="button"
                     onClick={() => {
                        setTaskMenuOpen(false);
                        setSessionNotice({ kind: 'success', message: 'Added to favorites for this workspace session.' });
                     }}
                  >
                     <Sparkles size={17} />
                     <span>Add to favorites</span>
                  </button>
                  <button
                     type="button"
                     onClick={() => {
                        setTaskMenuOpen(false);
                        setDrawerType('canvas');
                     }}
                  >
                     <FileSearch size={17} />
                     <span>Task details</span>
                  </button>
                  <button
                     type="button"
                     className="danger"
                     onClick={() => {
                        setTaskMenuOpen(false);
                        deleteSession(currentSessionId);
                     }}
                  >
                     <Trash2 size={17} />
                     <span>Delete</span>
                  </button>
               </div>
            )}

            {taskFilesOpen && (() => {
               const allTaskFiles = getTaskFileItems();
               const visibleTaskFiles = allTaskFiles.filter(file => {
                  const query = taskFilesSearch.trim().toLowerCase();
                  return (taskFilesFilter === 'All' || taskFilesFilter === file.kind) &&
                     (!query || file.name.toLowerCase().includes(query) || file.subtitle.toLowerCase().includes(query));
               });
               const taskFileFilters: Array<typeof taskFilesFilter> = ['All', 'Document', 'Image', 'Code file', 'Link'];
               return (
                  <div className={`settings-overlay ${agentLite ? 'lemon-lite' : ''}`} onClick={() => setTaskFilesOpen(false)} style={{ zIndex: 12020, background: agentLite ? 'rgba(15,23,42,0.38)' : 'rgba(0,0,0,0.62)', backdropFilter: 'blur(6px)' }}>
                     <div
                        className="settings-modal task-files-modal"
                        onClick={event => event.stopPropagation()}
                     >
                        <div className="task-files-header">
                           <h2>All files in this task</h2>
                           <div className="task-files-actions">
                              <button title="Download all as ZIP" onClick={downloadAllTaskFiles}><Download size={20} /></button>
                              <button title="Add files" onClick={() => sourceFileInputRef.current?.click()}><FileSearch size={20} /></button>
                              <button title="Close" onClick={() => setTaskFilesOpen(false)}><X size={20} /></button>
                           </div>
                        </div>

                        <div className="task-files-search-row">
                           <div className="task-files-search">
                              <Search size={17} />
                              <input
                                 value={taskFilesSearch}
                                 onChange={event => setTaskFilesSearch(event.target.value)}
                                 placeholder="Search files..."
                              />
                           </div>
                           <button className="task-files-sort" type="button">Time (Newest first)</button>
                        </div>

                        <div className="task-files-tabs">
                           {taskFileFilters.map(filter => (
                              <button
                                 key={filter}
                                 className={taskFilesFilter === filter ? 'active' : ''}
                                 onClick={() => setTaskFilesFilter(filter)}
                              >
                                 {filter === 'Code file' ? 'Code files' : filter === 'Document' ? 'Documents' : filter === 'Image' ? 'Images' : filter === 'Link' ? 'Links' : 'All'}
                              </button>
                           ))}
                        </div>

                        <div className="task-files-list custom-scrollbar">
                           {visibleTaskFiles.length === 0 ? (
                              <div className="task-files-empty">
                                 <FileText size={36} strokeWidth={1.7} />
                                 <span>No files in this chat yet</span>
                                 <button onClick={() => sourceFileInputRef.current?.click()}>Add files</button>
                              </div>
                           ) : (
                              <>
                                 <div className="task-files-group-label">Earlier</div>
                                 {visibleTaskFiles.map(file => {
                                    const iconClass = file.kind === 'Code file' ? 'code' : file.kind === 'Link' ? 'link' : file.kind === 'Image' ? 'image' : 'document';
                                    return (
                                       <div className="task-file-row" key={file.id}>
                                          <span className={`task-file-icon ${iconClass}`}>
                                             {file.kind === 'Link' ? <Globe size={18} /> : file.kind === 'Code file' ? <TerminalSquare size={18} /> : <FileText size={18} />}
                                          </span>
                                          <button
                                             className="task-file-main"
                                             onClick={() => {
                                                setSelectedSource(file);
                                                setDrawerType('canvas');
                                                setTaskFilesOpen(false);
                                             }}
                                          >
                                             <strong>{file.name}</strong>
                                             <small>{file.subtitle}</small>
                                          </button>
                                          <button className="task-file-download" title={file.url ? 'Open link' : 'Download file'} onClick={() => downloadTaskFile(file)}>
                                             <Download size={18} />
                                          </button>
                                       </div>
                                    );
                                 })}
                              </>
                           )}
                        </div>
                     </div>
                  </div>
               );
            })()}

            {/* DETAILS DRAWER */}
            <div
               className={`details-drawer ${drawerType === 'canvas' ? 'canvas-drawer' : ''} ${drawerType !== 'none' ? 'open' : ''}`}
               style={drawerType === 'canvas' ? { ['--canvas-panel-width' as any]: `${canvasWidth}px` } : { ['--drawer-panel-width' as any]: `${drawerWidth}px` }}
            >
               {drawerType === 'canvas' && (
                  <button
                     className="canvas-resize-handle"
                     title="Drag to resize canvas"
                     aria-label="Resize canvas"
                     onPointerDown={(event) => {
                        event.preventDefault();
                        setIsCanvasResizing(true);
                     }}
                  />
               )}
               {drawerType !== 'none' && drawerType !== 'canvas' && (
                  <button
                     className="drawer-resize-handle"
                     title="Drag to resize drawer"
                     aria-label="Resize drawer"
                     onPointerDown={(event) => {
                        event.preventDefault();
                        setIsDrawerResizing(true);
                     }}
                  />
               )}
               {drawerType === 'canvas' ? (
                  <div className="canvas-drawer-header">
                     <div className="canvas-drawer-title">NEXUS's computer</div>
                     <div className="canvas-drawer-actions">
                        <svg viewBox="0 0 24 24" width="24" height="24" fill="currentColor">
                           <path d="M23.15 2.587L18.21.21a1.494 1.494 0 0 0-1.705.29l-9.46 8.63-4.12-3.128a.999.999 0 0 0-1.276.057L.327 7.261A1 1 0 0 0 .326 8.74L3.899 12 .326 15.26a1 1 0 0 0 .001 1.479L1.65 17.94a.999.999 0 0 0 1.276.057l4.12-3.128 9.46 8.63a1.492 1.492 0 0 0 1.704.29l4.942-2.377A1.5 1.5 0 0 0 24 20.06V3.939a1.5 1.5 0 0 0-.85-1.352zm-5.146 14.861L10.826 12l7.178-5.448v10.896z" />
                        </svg>
                        <span>VS Code</span>
                        <button title="Close canvas" onClick={() => setDrawerType('none')}><X size={18} /></button>
                     </div>
                  </div>
               ) : (
                  <div className="drawer-header">
                     <span>{drawerType === 'health' ? 'NEXUS HEALTH' : drawerType === 'reminders' ? 'REMINDERS' : 'HIVE INTELLIGENCE'}</span>
                     <X size={18} style={{ cursor: 'pointer' }} onClick={() => setDrawerType('none')} />
                  </div>
               )}

               <div className={`drawer-content ${drawerType === 'canvas' ? 'canvas-drawer-content' : ''}`}>
                  {drawerType === 'canvas' && (
                     <CanvasPanel
                        canvasPlaybackTime={canvasPlaybackTime}
                        isPlaying={isPlaying}
                        setIsPlaying={setIsPlaying}
                        activePlaybackIndex={activePlaybackIndex}
                        allWorkActivities={timelineWorkActivities}
                        canvasCanRunHtml={canvasCanRunHtml}
                        canvasEditorCode={canvasEditorCode}
                        canvasEditorLang={canvasEditorLang}
                        canvasEditorLineCount={canvasEditorLineCount}
                        canvasFileName={canvasFileName}
                        canvasFileStatus={canvasFileStatus}
                        canvasProgress={canvasProgress}
                        canvasStatusText={canvasStatusText}
                        canvasViewMode={canvasViewMode}
                        isCanvasRealtime={canvasPlaybackTime === null}
                        renderCanvasMain={renderCanvasMain}
                        setCanvasPlaybackTime={setCanvasPlaybackTime}
                        setCanvasViewMode={setCanvasViewMode}
                        setSelectedWorkEvent={setSelectedWorkEvent}
                     />
                  )}

                  {drawerType === 'hive' && (
                     <HiveDrawer
                        controlHive={controlHive}
                        controlHiveTask={controlHiveTask}
                        formatCardName={formatCardName}
                        hive={state.hive}
                        hiveStarting={hiveStarting}
                        newHiveMission={newHiveMission}
                        removeHive={removeHive}
                        setNewHiveMission={setNewHiveMission}
                        startHiveMission={startHiveMission}
                     />
                  )}

                  {drawerType === 'health' && (
                     <HealthDrawer health={state.health} formatDuration={formatDuration} />
                  )}

                  {drawerType === 'reminders' && (
                     <RemindersDrawer
                        createReminder={createReminder}
                        deleteReminder={deleteReminder}
                        newReminderDue={newReminderDue}
                        newReminderText={newReminderText}
                        notificationPermission={notificationPermission}
                        nowSeconds={Date.now() / 1000}
                        reminders={state.reminders}
                        requestReminderNotifications={requestReminderNotifications}
                        setNewReminderDue={setNewReminderDue}
                        setNewReminderText={setNewReminderText}
                     />
                  )}
               </div>
            </div>

            {activeTab === 'session' ? (
               <div style={{ display: 'flex', flexDirection: 'row', flex: '1 1 auto', width: '100%', height: '100%', minHeight: 0, overflow: 'hidden' }}>
                  {/* SOURCES/EXPAND PANEL */}
                  {sourcesPanelOpen && (
                     <div style={{
                        width: '320px',
                        maxWidth: '34vw',
                        minWidth: '300px',
                        height: '100%',
                        background: agentLite ? '#fcfbf9' : '#0d0d0f',
                        borderRight: agentLite ? '1px solid #e5e7eb' : '1px solid rgba(255,255,255,0.08)',
                        display: 'flex',
                        flexDirection: 'column',
                        flexShrink: 0,
                        zIndex: 9,
                        animation: 'fadeIn 0.2s ease-out',
                     }}>
                        <div style={{ padding: '18px 16px 10px', display: 'grid', gap: '18px' }}>
                           <button
                              title="Hide sources"
                              onClick={() => setSourcesPanelOpen(false)}
                              style={{
                                 width: '34px',
                                 height: '34px',
                                 borderRadius: '8px',
                                 background: 'transparent',
                                 border: 'none',
                                 color: agentLite ? '#111827' : '#d8dce3',
                                 display: 'flex',
                                 alignItems: 'center',
                                 justifyContent: 'center',
                                 cursor: 'pointer',
                                 padding: 0,
                              }}
                           >
                              <ThreeLineMenu color={agentLite ? '#111827' : '#d8dce3'} />
                           </button>

                           <div style={{
                              display: 'grid',
                              gridTemplateColumns: '1fr 1fr',
                              gap: '6px',
                              padding: '6px',
                              borderRadius: '12px',
                              background: agentLite ? '#f3f4f6' : 'rgba(255,255,255,0.045)',
                              border: agentLite ? '1px solid #e5e7eb' : '1px solid rgba(255,255,255,0.06)',
                           }}>
                              {(['source', 'result'] as const).map(tab => (
                                 <button
                                    key={tab}
                                    onClick={() => setSourcesTab(tab)}
                                    style={{
                                       minHeight: '58px',
                                       borderRadius: '9px',
                                       background: sourcesTab === tab
                                          ? (agentLite ? '#ffffff' : 'rgba(255,255,255,0.085)')
                                          : 'transparent',
                                       border: sourcesTab === tab
                                          ? (agentLite ? '1px solid #e5e7eb' : '1px solid rgba(255,255,255,0.08)')
                                          : '1px solid transparent',
                                       color: sourcesTab === tab
                                          ? (agentLite ? '#111827' : '#ffffff')
                                          : (agentLite ? '#6b7280' : '#9ca3af'),
                                       display: 'flex',
                                       flexDirection: 'column',
                                       alignItems: 'center',
                                       justifyContent: 'center',
                                       gap: '6px',
                                       fontSize: '0.82rem',
                                       fontWeight: 800,
                                       cursor: 'pointer',
                                       boxShadow: sourcesTab === tab ? '0 1px 6px rgba(0,0,0,0.12)' : 'none',
                                    }}
                                 >
                                    {tab === 'source' ? <FileText size={18} /> : <Database size={18} />}
                                    {tab === 'source' ? 'Source' : 'Result'}
                                 </button>
                              ))}
                           </div>
                        </div>

                        {sourcesTab === 'source' ? (
                           <div style={{ padding: '0 16px 16px', display: 'flex', flexDirection: 'column', gap: '14px', flex: 1, overflowY: 'auto' }}>
                              <button 
                                 onClick={() => sourceFileInputRef.current?.click()}
                                 style={{
                                    width: '100%',
                                    minHeight: '44px',
                                    padding: '10px 14px',
                                    borderRadius: '8px',
                                    background: agentLite ? 'rgba(0,0,0,0.02)' : 'rgba(255,255,255,0.03)',
                                    border: agentLite ? '1px dashed #cbd5e1' : '1px dashed rgba(255,255,255,0.15)',
                                    color: agentLite ? '#111827' : '#f4f4f5',
                                    fontSize: '0.95rem',
                                    fontWeight: 800,
                                    cursor: 'pointer',
                                 }}
                              >
                                 + Add Source
                              </button>
                              <button 
                                 onClick={importWebsiteSource}
                                 style={{
                                    width: '100%',
                                    minHeight: '44px',
                                    padding: '10px 14px',
                                    borderRadius: '8px',
                                    background: 'transparent',
                                    border: agentLite ? '1px solid #cbd5e1' : '1px solid rgba(255,255,255,0.08)',
                                    color: agentLite ? '#111827' : '#f4f4f5',
                                    fontSize: '0.95rem',
                                    fontWeight: 800,
                                    cursor: 'pointer',
                                 }}
                              >
                                 Import from Library
                              </button>
                              
                              <input
                                 type="file"
                                 ref={sourceFileInputRef}
                                 onChange={handleSourceFileUpload}
                                 multiple
                                 style={{ display: 'none' }}
                              />

                              <div style={{
                                 display: 'grid',
                                 gap: '10px',
                                 padding: '12px',
                                 borderRadius: '10px',
                                 background: agentLite ? '#ffffff' : 'rgba(255,255,255,0.025)',
                                 border: agentLite ? '1px solid #e5e7eb' : '1px solid rgba(255,255,255,0.08)',
                              }}>
                                 <div style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '8px',
                                    minHeight: '40px',
                                    padding: '0 10px',
                                    borderRadius: '8px',
                                    background: agentLite ? '#ffffff' : '#151518',
                                    border: agentLite ? '1px solid #d1d5db' : '1px solid rgba(255,255,255,0.10)',
                                 }}>
                                    <Globe size={18} style={{ color: agentLite ? '#6b7280' : '#a1a1aa', flex: '0 0 auto' }} />
                                    <input
                                       type="text"
                                       value={sourceSearchQuery}
                                       onChange={(e) => setSourceSearchQuery(e.target.value)}
                                       placeholder="Search for new sources on the web..."
                                       style={{
                                          width: '100%',
                                          minWidth: 0,
                                          background: 'transparent',
                                          border: 'none',
                                          color: agentLite ? '#111827' : '#fff',
                                          fontSize: '0.88rem',
                                          outline: 'none',
                                       }}
                                    />
                                 </div>
                                 <button
                                    disabled={!sourceSearchQuery.trim()}
                                    onClick={() => {
                                       setSourceImportUrl(sourceSearchQuery.trim());
                                       setSourceImportError('');
                                       setSourceImportOpen(true);
                                    }}
                                    style={{
                                       minHeight: '42px',
                                       borderRadius: '8px',
                                       background: sourceSearchQuery.trim()
                                          ? (agentLite ? '#111827' : 'rgba(255,255,255,0.09)')
                                          : (agentLite ? '#f3f4f6' : 'rgba(255,255,255,0.035)'),
                                       border: agentLite ? '1px solid #e5e7eb' : '1px solid rgba(255,255,255,0.07)',
                                       color: sourceSearchQuery.trim()
                                          ? (agentLite ? '#ffffff' : '#f8fafc')
                                          : (agentLite ? '#9ca3af' : '#5f6673'),
                                       fontSize: '0.88rem',
                                       fontWeight: 800,
                                       cursor: sourceSearchQuery.trim() ? 'pointer' : 'not-allowed',
                                    }}
                                 >
                                    Search
                                 </button>
                              </div>

                              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: '10px', paddingBottom: '4px', fontSize: '0.86rem', color: agentLite ? '#111827' : '#d4d4d8', fontWeight: 800 }}>
                                 <span>Select All Sources</span>
                                 <input 
                                    type="checkbox" 
                                    checked={sources.length > 0 && sources.every(s => s.checked)}
                                    onChange={() => {
                                       const allChecked = sources.length > 0 && sources.every(s => s.checked);
                                       const updated = sources.map(s => ({ ...s, checked: !allChecked }));
                                       setSources(updated);
                                       updated.forEach(source => {
                                          fetch(`/api/sources/${encodeURIComponent(source.id)}`, {
                                             method: 'PATCH',
                                             headers: { 'Content-Type': 'application/json' },
                                             body: JSON.stringify({ checked: source.checked }),
                                          }).catch(() => {});
                                       });
                                    }}
                                    style={{ cursor: 'pointer', width: '18px', height: '18px', accentColor: agentLite ? '#111827' : '#f8fafc' }} 
                                 />
                              </div>

                              <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', marginTop: '0', borderTop: agentLite ? '1px solid #e5e7eb' : '1px solid rgba(255,255,255,0.07)', paddingTop: '12px' }}>
                                 {sources.length === 0 && (
                                    <div style={{
                                       padding: '18px 12px',
                                       borderRadius: '8px',
                                       border: agentLite ? '1px dashed #cbd5e1' : '1px dashed rgba(255,255,255,0.10)',
                                       color: agentLite ? '#64748b' : '#7f8794',
                                       fontSize: '0.75rem',
                                       lineHeight: 1.6,
                                       textAlign: 'center',
                                    }}>
                                       No saved sources yet. Upload a file or import a website to add it to Library.
                                    </div>
                                 )}
                                 {sources.map((src) => {
                                    const isSelected = selectedSource?.id === src.id;
                                    return (
                                       <div
                                          key={src.id}
                                          onMouseEnter={() => setHoveredSourceId(src.id)}
                                          onMouseLeave={() => setHoveredSourceId(null)}
                                          onClick={(e) => {
                                             if (editingSourceId === src.id) return;
                                             const target = e.target as HTMLElement;
                                             if (target.closest('.source-menu-trigger') || target.closest('.source-menu-dropdown') || target.tagName === 'INPUT') {
                                                return;
                                             }
                                             setSelectedSource(src);
                                             setSelectedWorkEvent(null);
                                             setCanvasPlaybackTime(null);
                                             setCanvasPlaybackTurnId('');
                                             setCanvasViewMode('source');
                                             setDrawerType('canvas');
                                          }}
                                          style={{
                                             display: 'flex',
                                             alignItems: 'center',
                                             gap: '12px',
                                             minHeight: '74px',
                                             padding: '12px',
                                             background: isSelected 
                                                ? (agentLite ? 'rgba(59, 130, 246, 0.08)' : 'rgba(59, 130, 246, 0.15)')
                                                : (agentLite ? '#fff' : 'rgba(255,255,255,0.02)'),
                                             border: isSelected
                                                ? '1px solid #3b82f6'
                                                : (agentLite ? '1px solid #d1d5db' : '1px solid rgba(255,255,255,0.08)'),
                                             borderRadius: '8px',
                                             boxShadow: '0 1px 3px rgba(0,0,0,0.02)',
                                             position: 'relative',
                                             cursor: editingSourceId === src.id ? 'default' : 'pointer',
                                             transition: 'all 0.15s ease',
                                          }}
                                       >
                                          <input 
                                             type="checkbox" 
                                             checked={src.checked} 
                                             onChange={async () => {
                                                const nextChecked = !src.checked;
                                                const updated = sources.map(s => s.id === src.id ? { ...s, checked: nextChecked } : s);
                                                setSources(updated);
                                                try {
                                                   await fetch(`/api/sources/${encodeURIComponent(src.id)}`, {
                                                      method: 'PATCH',
                                                      headers: { 'Content-Type': 'application/json' },
                                                      body: JSON.stringify({ checked: nextChecked }),
                                                   });
                                                } catch {
                                                   setSources(sources);
                                                }
                                             }}
                                             style={{ cursor: 'pointer', width: '18px', height: '18px', accentColor: agentLite ? '#111827' : '#f8fafc', flex: '0 0 auto' }} 
                                          />
                                          <div style={{
                                             width: '44px',
                                             height: '44px',
                                             borderRadius: '10px',
                                             background: agentLite ? '#f3f4f6' : 'rgba(255,255,255,0.055)',
                                             color: src.type === 'File' ? '#94a3b8' : '#86efac',
                                             display: 'flex',
                                             alignItems: 'center',
                                             justifyContent: 'center',
                                             flex: '0 0 auto',
                                          }}>
                                             {src.type === 'File' ? <FileText size={18} /> : <Globe size={18} />}
                                          </div>
                                          <div style={{ display: 'flex', flexDirection: 'column', minWidth: 0, flex: 1 }}>
                                             {editingSourceId === src.id ? (
                                                <input
                                                   type="text"
                                                   value={editSourceName}
                                                   onChange={(e) => setEditSourceName(e.target.value)}
                                                   onKeyDown={(e) => {
                                                      if (e.key === 'Enter') {
                                                         renameSource(src.id, editSourceName);
                                                      } else if (e.key === 'Escape') {
                                                         setEditingSourceId(null);
                                                      }
                                                   }}
                                                   onBlur={() => renameSource(src.id, editSourceName)}
                                                   autoFocus
                                                   style={{
                                                      fontSize: '0.72rem',
                                                      color: agentLite ? '#111827' : '#fff',
                                                      background: agentLite ? '#fff' : '#1e1e24',
                                                      border: '1px solid #3b82f6',
                                                      borderRadius: '4px',
                                                      padding: '2px 4px',
                                                      outline: 'none',
                                                      width: '100%',
                                                   }}
                                                />
                                             ) : (
                                                <span 
                                                   style={{ 
                                                      fontSize: '0.92rem', 
                                                      color: isSelected 
                                                         ? (agentLite ? '#1d4ed8' : '#60a5fa')
                                                         : (agentLite ? '#1f2937' : '#eee'), 
                                                      overflow: 'hidden', 
                                                      textOverflow: 'ellipsis', 
                                                      whiteSpace: 'nowrap', 
                                                      fontWeight: 800 
                                                   }} 
                                                   title={src.name}
                                                >
                                                   {src.name}
                                                </span>
                                             )}
                                             <span style={{ marginTop: '4px', fontSize: '0.74rem', color: agentLite ? '#6b7280' : '#8b949e', fontWeight: 700 }}>{src.type}</span>
                                          </div>

                                          {(hoveredSourceId === src.id || activeSourceMenuId === src.id) && editingSourceId !== src.id && (
                                             <div style={{ position: 'relative' }}>
                                                <button
                                                   className="source-menu-trigger"
                                                   onClick={(e) => {
                                                      e.stopPropagation();
                                                      setActiveSourceMenuId(activeSourceMenuId === src.id ? null : src.id);
                                                   }}
                                                   style={{
                                                      background: 'transparent',
                                                      border: 'none',
                                                      color: agentLite ? '#4b5563' : '#a1a1aa',
                                                      cursor: 'pointer',
                                                      padding: '4px',
                                                      display: 'flex',
                                                      alignItems: 'center',
                                                      justifyContent: 'center',
                                                   }}
                                                >
                                                   <MoreVertical size={14} />
                                                </button>

                                                {activeSourceMenuId === src.id && (
                                                   <div
                                                      className="source-menu-dropdown"
                                                      onClick={(e) => e.stopPropagation()}
                                                      style={{
                                                         position: 'absolute',
                                                         right: '10px',
                                                         top: '34px',
                                                         background: agentLite ? '#ffffff' : '#18181b',
                                                         border: agentLite ? '1px solid #e2e8f0' : '1px solid rgba(255,255,255,0.08)',
                                                         borderRadius: '8px',
                                                         boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
                                                         zIndex: 100,
                                                         display: 'flex',
                                                         flexDirection: 'column',
                                                         padding: '4px 0',
                                                         minWidth: '130px',
                                                      }}
                                                   >
                                                      <button
                                                   onClick={() => {
                                                      setEditingSourceId(src.id);
                                                      setEditSourceName(src.name);
                                                      setActiveSourceMenuId(null);
                                                   }}
                                                   style={{
                                                      display: 'flex',
                                                      alignItems: 'center',
                                                      gap: '8px',
                                                      padding: '8px 12px',
                                                      background: 'transparent',
                                                      border: 'none',
                                                      color: agentLite ? '#374151' : '#e4e4e7',
                                                      fontSize: '0.72rem',
                                                      fontWeight: 500,
                                                      cursor: 'pointer',
                                                      textAlign: 'left',
                                                      width: '100%',
                                                   }}
                                                >
                                                   <Edit2 size={12} />
                                                   Rename
                                                </button>
                                                <button
                                                   onClick={() => {
                                                      handleSourceAction('reparse', src.id, src.name);
                                                      setActiveSourceMenuId(null);
                                                   }}
                                                   style={{
                                                      display: 'flex',
                                                      alignItems: 'center',
                                                      gap: '8px',
                                                      padding: '8px 12px',
                                                      background: 'transparent',
                                                      border: 'none',
                                                      color: agentLite ? '#374151' : '#e4e4e7',
                                                      fontSize: '0.72rem',
                                                      fontWeight: 500,
                                                      cursor: 'pointer',
                                                      textAlign: 'left',
                                                      width: '100%',
                                                   }}
                                                >
                                                   <RefreshCw size={12} />
                                                   Reparse
                                                </button>
                                                <button
                                                   onClick={() => {
                                                      handleSourceAction('deep-reparse', src.id, src.name);
                                                      setActiveSourceMenuId(null);
                                                   }}
                                                   style={{
                                                      display: 'flex',
                                                      alignItems: 'center',
                                                      gap: '8px',
                                                      padding: '8px 12px',
                                                      background: 'transparent',
                                                      border: 'none',
                                                      color: agentLite ? '#374151' : '#e4e4e7',
                                                      fontSize: '0.72rem',
                                                      fontWeight: 500,
                                                      cursor: 'pointer',
                                                      textAlign: 'left',
                                                      width: '100%',
                                                   }}
                                                 >
                                                    <ShieldCheck size={12} />
                                                    Deep Reparse
                                                 </button>
                                                 <div style={{ height: '1px', background: agentLite ? '#e2e8f0' : 'rgba(255,255,255,0.06)', margin: '4px 0' }} />
                                                 <button
                                                    onClick={() => {
                                                       handleSourceAction('delete', src.id, src.name);
                                                       setActiveSourceMenuId(null);
                                                    }}
                                                    style={{
                                                       display: 'flex',
                                                       alignItems: 'center',
                                                       gap: '8px',
                                                       padding: '8px 12px',
                                                       background: 'transparent',
                                                       border: 'none',
                                                       color: '#ef4444',
                                                       fontSize: '0.72rem',
                                                       fontWeight: 600,
                                                       cursor: 'pointer',
                                                       textAlign: 'left',
                                                       width: '100%',
                                                    }}
                                                 >
                                                    <Trash2 size={12} style={{ color: '#ef4444' }} />
                                                    Delete
                                                 </button>
                                              </div>
                                           )}
                                        </div>
                                     )}
                                  </div>
                               );
                                   })}
                                </div>
                             </div>
                          ) : (
                             <div style={{ padding: '24px', color: '#666', fontSize: '0.75rem', textAlign: 'center', fontWeight: 500 }}>
                                No results generated yet.
                             </div>
                          )}
                       </div>
                    )}

                    <div className="chat-pane" style={{
                       display: 'flex',
                       flexDirection: 'column',
                       flex: '1 1 auto',
                       height: '100%',
                       overflow: 'hidden',
                       position: 'relative',
                       background: agentLite ? 'linear-gradient(180deg, #f8fafc 0%, #f1f5f9 100%)' : undefined
                    }}>
                       {!sourcesPanelOpen && (
                          <button
                             title="Show sources"
                             onClick={() => setSourcesPanelOpen(true)}
                             style={{
                                position: 'absolute',
                                left: '24px',
                                top: '22px',
                                zIndex: 10,
                                width: '24px',
                                height: '24px',
                                borderRadius: '4px',
                                background: 'transparent',
                                border: 'none',
                                color: agentLite ? '#111827' : '#d8dce3',
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                cursor: 'pointer',
                                transition: 'all 0.2s',
                                boxShadow: 'none',
                                padding: 0,
                             }}
                             className="hover-white"
                          >
                             <ThreeLineMenu color={agentLite ? '#111827' : '#d8dce3'} />
                          </button>
                       )}

                     <div className="messages-container" style={{
                        flex: '1 1 auto',
                        overflowY: 'auto',
                        padding: '24px 28px 24px',
                        display: 'flex',
                        flexDirection: 'column',
                        gap: '20px',
                        minHeight: 0
                     }}>
{messages.length === 0 ? (
                        <div className="chat-welcome-screen" style={{
                           display: 'flex',
                           flexDirection: 'column',
                           alignItems: 'center',
                           justifyContent: 'center',
                           flex: '1 1 auto',
                           minHeight: '100%',
                           textAlign: 'center',
                           padding: '24px 20px',
                           color: agentLite ? '#374151' : '#cbd5e1'
                        }}>
                           {showLogoInHeader && (
                              <div style={{
                                 fontSize: '4rem',
                                 marginBottom: '18px',
                                 filter: 'drop-shadow(0 4px 24px rgba(59,130,246,0.18))',
                                 animation: 'nexus-breathe 4s ease-in-out infinite'
                              }}>
                                 {brandMark}
                              </div>
                           )}
                           <h2 style={{
                              fontSize: '2.2rem',
                              fontWeight: 900,
                              textTransform: 'uppercase',
                              letterSpacing: '6px',
                              marginBottom: '12px',
                              background: 'linear-gradient(135deg, #3b82f6 0%, #8b5cf6 100%)',
                              WebkitBackgroundClip: 'text',
                              WebkitTextFillColor: 'transparent',
                              backgroundClip: 'text'
                           }}>
                              {brandName}
                           </h2>
                           <p style={{
                              fontSize: '0.95rem',
                              maxWidth: '420px',
                              lineHeight: '1.7',
                              color: agentLite ? '#64748b' : '#94a3b8',
                              margin: '0 auto 32px'
                           }}>
                              Autonomous agent kernel active. Type a command or request assistance below.
                           </p>
                        </div>
                     ) : (
                        messages.map((m, i) => {
                           const isUser = m.role === 'user';
                           const msgEvents = getWorkEventsForMessage(i, i === latestAssistantIndex);
                           return (
                              <div
                                 key={i}
                                 className={`message-row ${isUser ? 'user' : 'assistant'}`}
                                 onMouseEnter={() => setHoveredMsgId(i)}
                                 onMouseLeave={() => setHoveredMsgId(null)}
                                 style={{
                                    display: 'flex',
                                    flexDirection: 'row',
                                    alignItems: 'flex-start',
                                    gap: '14px',
                                    width: '100%',
                                    alignSelf: 'flex-start',
                                    animation: 'fadeIn 0.3s ease-out'
                                 }}
                              >
                                 {showChatAvatars && (
                                    <div className="avatar" style={{
                                       width: '34px',
                                       height: '34px',
                                       borderRadius: '50%',
                                       display: 'flex',
                                       alignItems: 'center',
                                       justifyContent: 'center',
                                       fontSize: '1.25rem',
                                       background: isUser ? 'var(--avatar-user-bg)' : 'var(--avatar-assistant-bg)',
                                       border: '1px solid ' + (isUser ? 'var(--avatar-user-border)' : 'var(--avatar-assistant-border)'),
                                       flexShrink: 0,
                                       boxShadow: '0 2px 4px rgba(0,0,0,0.05)'
                                    }}>
                                       {isUser ? userAvatar : assistantAvatar}
                                    </div>
                                 )}

                                 <div style={{ display: 'flex', flexDirection: 'column', flex: '1 1 auto', minWidth: 0, alignItems: 'flex-start' }}>
                                    <div className={`message-bubble ${isUser ? 'user-bubble' : 'assistant-bubble'}`} style={{
                                       padding: '12px 18px',
                                       borderRadius: '16px',
                                       background: isUser ? 'var(--user-bubble-bg)' : 'var(--assistant-bubble-bg)',
                                       border: '1px solid ' + (isUser ? 'var(--user-bubble-border)' : 'var(--assistant-bubble-border)'),
                                       color: isUser ? 'var(--user-bubble-text)' : 'var(--assistant-bubble-text)',
                                       width: 'fit-content',
                                       maxWidth: '88%',
                                       boxShadow: '0 1px 3px rgba(0,0,0,0.02)',
                                       wordBreak: 'break-word',
                                       fontSize: '0.96rem',
                                       lineHeight: '1.6'
                                    }}>
                                       {isUser ? renderMessageMarkdown(cleanUserMessage(m.content), isUser) : renderMessageMarkdown(m.content, isUser)}
                                    </div>

                                    {!isUser && m.content && (
                                       <div style={{
                                          display: 'flex',
                                          alignItems: 'center',
                                          gap: '8px',
                                          marginTop: '6px',
                                          opacity: hoveredMsgId === i ? 0.8 : 0,
                                          transition: 'opacity 0.2s ease',
                                          minHeight: '20px'
                                       }}>
                                          <button
                                             title="Copy"
                                             onClick={() => { navigator.clipboard.writeText(cleanAssistantText(m.content)); setCopiedMsgId(i); setTimeout(() => setCopiedMsgId(null), 2000); }}
                                             style={{ background: 'transparent', border: 'none', borderRadius: '4px', cursor: 'pointer', padding: '2px 6px', display: 'inline-flex', alignItems: 'center', color: copiedMsgId === i ? '#10b981' : '#888', transition: 'all 0.2s', outline: 'none' }}
                                          >
                                             {copiedMsgId === i ? (
                                                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3"><polyline points="20 6 9 17 4 12"/></svg>
                                             ) : (
                                                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>
                                             )}
                                          </button>
                                          <button title="Good response" style={{ background: 'transparent', border: 'none', cursor: 'pointer', padding: '2px 4px', display: 'inline-flex', alignItems: 'center', color: '#888', outline: 'none' }} onMouseEnter={e => (e.currentTarget.style.color='#10b981')} onMouseLeave={e => (e.currentTarget.style.color='#888')}><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M14 9V5a3 3 0 00-3-3l-4 9v11h11.28a2 2 0 002-1.7l1.38-9a2 2 0 00-2-2.3H14z"/><path d="M7 22H4a2 2 0 01-2-2v-7a2 2 0 012-2h3"/></svg></button>
                                          <button title="Bad response" style={{ background: 'transparent', border: 'none', cursor: 'pointer', padding: '2px 4px', display: 'inline-flex', alignItems: 'center', color: '#888', outline: 'none' }} onMouseEnter={e => (e.currentTarget.style.color='#ef4444')} onMouseLeave={e => (e.currentTarget.style.color='#888')}><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M10 15v4a3 3 0 003 3l4-9V2H5.72a2 2 0 00-2 1.7l-1.38 9a2 2 0 002 2.3H10z"/><path d="M17 2h2.67A2.31 2.31 0 0122 4v7a2.31 2.31 0 01-2.33 2H17"/></svg></button>
                                          {!isStreaming && (
                                             <button
                                                title="Regenerate"
                                                onClick={() => {
                                                   const lastUser = [...messages].reverse().find(x => x.role === 'user');
                                                   if (lastUser) {
                                                      setMessages(prev => prev.slice(0, -1));
                                                      setInputValue(lastUser.content);
                                                      setTimeout(handleSend, 50);
                                                   }
                                                }}
                                                style={{ background: 'transparent', border: 'none', cursor: 'pointer', padding: '2px 4px', display: 'inline-flex', alignItems: 'center', color: '#888', outline: 'none' }}
                                                onMouseEnter={e => (e.currentTarget.style.color='#3b82f6')}
                                                onMouseLeave={e => (e.currentTarget.style.color='#888')}
                                             >
                                                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 102.13-9.36L1 10"/></svg>
                                             </button>
                                          )}
                                       </div>
                                    )}

                                    {isUser && m.content && (
                                       <div style={{
                                          display: 'flex',
                                          alignItems: 'center',
                                          gap: '8px',
                                          marginTop: '6px',
                                          opacity: hoveredMsgId === i ? 0.8 : 0,
                                          transition: 'opacity 0.2s ease',
                                          minHeight: '20px'
                                       }}>
                                          <button
                                             title="Copy"
                                             onClick={() => { navigator.clipboard.writeText(cleanUserMessage(m.content)); setCopiedMsgId(i); setTimeout(() => setCopiedMsgId(null), 2000); }}
                                             style={{ background: 'transparent', border: 'none', borderRadius: '4px', cursor: 'pointer', padding: '2px 6px', display: 'inline-flex', alignItems: 'center', color: copiedMsgId === i ? '#10b981' : '#888', transition: 'all 0.2s', outline: 'none' }}
                                          >
                                             {copiedMsgId === i ? (
                                                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3"><polyline points="20 6 9 17 4 12"/></svg>
                                             ) : (
                                                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>
                                             )}
                                          </button>
                                       </div>
                                    )}

                                    {!isUser && msgEvents.length > 0 && (
                                       <div className="work-timeline-wrapper" style={{ marginTop: '14px', width: '100%', maxWidth: '760px' }}>
                                          {renderWorkActivityTimeline(msgEvents)}
                                       </div>
                                    )}
                                 </div>
                              </div>
                           );
                        })
                     )}
                      {isStreaming && (
                         <div style={{
                            display: 'flex', flexDirection: 'row', alignItems: 'flex-start',
                            gap: '14px', width: '100%', animation: 'msg-rise 0.28s ease both'
                         }}>
                            <div style={{
                               width: '34px', height: '34px', borderRadius: '50%', flexShrink: 0,
                               display: 'flex', alignItems: 'center', justifyContent: 'center',
                               fontSize: '0.85rem', fontWeight: 800,
                               background: 'rgba(16,185,129,0.1)', border: '1px solid rgba(16,185,129,0.2)', color: '#10b981'
                            }}>N</div>
                            <div style={{ paddingTop: '4px' }}>
                               <div style={{
                                  display: 'flex', alignItems: 'center', gap: '8px',
                                  padding: '10px 16px', borderRadius: '6px 18px 18px 18px',
                                  background: agentLite ? '#ffffff' : 'rgba(255,255,255,0.03)',
                                  border: '1px solid ' + (agentLite ? 'rgba(0,0,0,0.07)' : 'rgba(255,255,255,0.07)'),
                                  boxShadow: '0 1px 4px rgba(0,0,0,0.04)'
                               }}>
                                  <span style={{ display: 'flex', gap: '5px', color: '#3b82f6' }}>
                                     <span className="chat-typing-dot" />
                                     <span className="chat-typing-dot" />
                                     <span className="chat-typing-dot" />
                                  </span>
                                  {latestWorkActivity && (
                                     <span style={{ fontSize: '0.75rem', color: agentLite ? '#6b7280' : '#9ca3af', fontStyle: 'italic' }}>
                                        {getWorkActivityLabel(latestWorkActivity)}{getWorkActivityTarget(latestWorkActivity) ? ` \u2192 ${getWorkActivityTarget(latestWorkActivity).split("/").pop()}` : ""}
                                     </span>
                                  )}
                               </div>
                            </div>
                         </div>
                      )}
                      
                     <div ref={messagesEndRef} />
                  </div>

                  <style>{`
                     @keyframes fadeIn { from { opacity: 0; transform: translateY(14px); } to { opacity: 1; transform: translateY(0); } }
                     @keyframes pulse { 0% { opacity: 0.4; } 50% { opacity: 0.9; } 100% { opacity: 0.4; } }
                     .messages-container { scrollbar-width: none; -ms-overflow-style: none; }
                     .messages-container::-webkit-scrollbar { width: 0; height: 0; display: none; }
                     .messages-container::-webkit-scrollbar-track { background: transparent; }
                     .messages-container::-webkit-scrollbar-thumb { background: transparent; }
                     .work-timeline {
                        width: 100%;
                        margin: 10px 0 4px;
                        position: relative;
                     }
                     .work-timeline::before {
                        content: '';
                        position: absolute;
                        left: 12px;
                        top: 32px;
                        bottom: 12px;
                        width: 1px;
                        background: ${agentLite ? 'rgba(0,0,0,0.06)' : 'rgba(255,255,255,0.08)'};
                     }
                     .work-timeline.collapsed::before {
                        display: none;
                     }
                     .work-phase {
                        width: 100%;
                        min-height: 34px;
                        display: grid;
                        grid-template-columns: 26px minmax(0, 1fr) 18px;
                        align-items: center;
                        gap: 10px;
                        border: 0;
                        background: transparent;
                        color: ${agentLite ? '#111827' : '#f8fafc'};
                        text-align: left;
                        cursor: pointer;
                        padding: 4px 6px;
                        border-radius: 6px;
                        transition: background 0.2s;
                     }
                     .work-phase:hover {
                        background: ${agentLite ? 'rgba(0,0,0,0.02)' : 'rgba(255,255,255,0.02)'};
                     }
                     .work-phase-icon {
                        display: flex;
                        align-items: center;
                        justify-content: center;
                        width: 24px;
                        height: 24px;
                        border-radius: 50%;
                        background: ${agentLite ? '#f3f4f6' : 'rgba(255,255,255,0.04)'};
                        color: ${agentLite ? '#6b7280' : '#9ca3af'};
                     }
                     .work-phase-label {
                        font-size: 0.82rem;
                        font-weight: 600;
                        letter-spacing: 0.5px;
                     }
                     .work-phase-arrow {
                        display: flex;
                        align-items: center;
                        justify-content: center;
                        color: #888;
                        transition: transform 0.2s;
                     }
                     .work-phase-arrow.open {
                        transform: rotate(180deg);
                     }
                     .work-phase-content {
                        padding: 8px 12px 12px 36px;
                        display: flex;
                        flex-direction: column;
                        gap: 8px;
                     }
                     .work-row {
                        display: grid;
                        grid-template-columns: 24px minmax(120px, auto) minmax(60px, 1fr);
                        align-items: center;
                        gap: 10px;
                        font-size: 0.78rem;
                        background: transparent;
                        border: none;
                        text-align: left;
                        cursor: pointer;
                        padding: 5px 8px;
                        border-radius: 6px;
                        width: 100%;
                        color: ${agentLite ? '#4b5563' : '#9ca3af'};
                        transition: all 0.2s;
                     }
                     .work-row:hover {
                        background: ${agentLite ? 'rgba(0,0,0,0.03)' : 'rgba(255,255,255,0.03)'};
                        color: ${agentLite ? '#111827' : '#f8fafc'};
                     }
                     .work-row.active {
                        background: ${agentLite ? 'rgba(59,130,246,0.06)' : 'rgba(59,130,246,0.12)'};
                        color: #3b82f6;
                        font-weight: 600;
                     }
                     .work-row-icon {
                        display: flex;
                        align-items: center;
                        justify-content: center;
                        width: 18px;
                        height: 18px;
                     }
                     .work-row-icon.done { color: #10b981; }
                     .work-row-icon.running { color: #3b82f6; animation: pulse 1.5s infinite ease-in-out; }
                     .work-row-icon.error { color: #ef4444; }
                     .work-row-label {
                        overflow: hidden;
                        text-overflow: ellipsis;
                        white-space: nowrap;
                     }
                     .work-row-target {
                        font-family: monospace;
                        overflow: hidden;
                        text-overflow: ellipsis;
                        white-space: nowrap;
                        opacity: 0.7;
                        font-size: 0.9em;
                     }
                  `}</style>
            <div className={`search-container composer-dock ${messages.length === 0 ? 'empty-composer' : ''}`}
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

                         {(screenSharing || screenShareError) && (
                            <div className={`screen-share-status ${screenSharing ? 'active' : 'error'}`}>
                               <Monitor size={14} />
                               <span>{screenSharing ? 'Screen sharing active' : screenShareError}</span>
                               {screenSharing && (
                                  <button type="button" onClick={stopScreenShare}>Stop</button>
                               )}
                            </div>
                         )}

                         {(voiceListening || voiceError) && (
                            <div className={`voice-status ${voiceListening ? 'active' : 'error'}`}>
                               <Mic size={14} />
                               <span>{voiceListening ? (voiceTranscript || 'Listening...') : voiceError}</span>
                               {voiceListening && (
                                  <button type="button" onClick={stopVoiceConversation}>Stop</button>
                               )}
                            </div>
                         )}

                        <div className="composer-main-row">
                           <textarea
                              ref={composerInputRef}
                              className="main-input"
                              placeholder={`Type to ${brandName.trim() || 'NEXUS'}...`}
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
                              style={{ resize: 'none', overflowY: 'hidden', minHeight: '28px', maxHeight: '160px', lineHeight: '1.5' }}
                           />
                           <div
                              className={`send-arrow ${(inputValue || uploadedFiles.length > 0) ? 'active' : ''}`}
                              style={{ cursor: (inputValue || uploadedFiles.length > 0) ? 'pointer' : 'default' }}
                              onClick={() => handleSend()}
                           >
                              <Send size={18} />
                           </div>
                        </div>

                        <div className="input-footer">
                           <div className="action-icons">
                              <label className="icon-btn" style={{ cursor: 'pointer', color: '#888', transition: 'all 0.2s' }}>
                                 <input type="file" multiple style={{ display: 'none' }} onChange={(e) => {
                                    if (e.target.files && e.target.files.length > 0) {
                                       setUploadedFiles(prev => [...prev, ...Array.from(e.target.files!)]);
                                    }
                                 }} />
                                 <PlusCircle size={20} className="hover-white" />
                              </label>
                              <button
                                 type="button"
                                 className={`icon-btn voice-btn ${voiceListening ? 'voice-active' : ''}`}
                                 title={voiceListening ? 'Stop listening' : 'Start voice conversation'}
                                 aria-label={voiceListening ? 'Stop voice conversation' : 'Start voice conversation'}
                                 onClick={startVoiceConversation}
                              >
                                 <Mic size={20} className="hover-white" />
                              </button>
                              <button
                                 type="button"
                                 className={`icon-btn screen-share-btn ${screenSharing ? 'screen-active' : ''}`}
                                 title={screenSharing ? 'Screen share is active. Double-click to stop.' : 'Share entire screen'}
                                 aria-label={screenSharing ? 'Screen share active' : 'Share entire screen'}
                                 onClick={ensureScreenShare}
                                 onDoubleClick={stopScreenShare}
                              >
                                 <Monitor size={20} className="hover-white" />
                              </button>
                              <div className="model-selector-wrap" style={{ position: 'relative' }} ref={modelMenuRef}>
                               <div 
                                  onClick={() => setShowModelMenu(!showModelMenu)}
                                  className="model-selector hover-bright"
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
                        </div>
                     </div>

                     {messages.length === 0 && (
                        <div className="empty-prompt-row">
                           {[
                              'Summarize this code',
                              'Find bugs',
                              'Run diagnostics',
                              'Explain the project',
                              'Review recent changes',
                              'Search the codebase',
                              'Improve the UI',
                              'Write tests',
                              'Check providers',
                              'Plan next steps',
                              'Refactor safely',
                              'Open system report'
                           ].map(prompt => (
                              <button
                                 key={prompt}
                                 className="empty-prompt-chip"
                                 onClick={() => setInputValue(prompt)}
                              >
                                 {prompt}
                              </button>
                           ))}
                        </div>
                     )}
                  </div>
               </div>
            </div>
            ) : (
               <div className="tab-view" style={{ padding: '80px 40px', maxWidth: '1200px', margin: '0 auto', width: '100%', height: 'auto', overflowY: 'auto', overflowX: 'hidden' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '30px', height: 'auto' }}>
                     <h1 style={{ display: 'block', fontSize: '2.2rem', textTransform: 'uppercase', letterSpacing: '3px', fontWeight: 900, color: '#fff', margin: 0 }}>{activeTabTitle}</h1>
                     {activeTab === 'mcp' && (
                        <button
                           onClick={openAddMcpPanel}
                           style={{ background: 'rgba(59, 130, 246, 0.1)', border: '1px solid var(--accent-blue)', color: 'var(--accent-blue)', padding: '8px 16px', borderRadius: '8px', fontSize: '0.7rem', fontWeight: 900, cursor: 'pointer', letterSpacing: '1px' }}
                        >
                           + ADD MCP
                        </button>
                     )}
                     {activeTab === 'skills' && (
                        <button
                           onClick={() => addAsset('skills')}
                           style={{ background: 'rgba(59, 130, 246, 0.1)', border: '1px solid var(--accent-blue)', color: 'var(--accent-blue)', padding: '8px 16px', borderRadius: '8px', fontSize: '0.7rem', fontWeight: 900, cursor: 'pointer', letterSpacing: '1px' }}
                        >
                           + ADD SKILL
                        </button>
                     )}
                     {activeTab === 'tools' && (
                        <button
                           onClick={() => addAsset('tools')}
                           style={{ background: 'rgba(59, 130, 246, 0.1)', border: '1px solid var(--accent-blue)', color: 'var(--accent-blue)', padding: '8px 16px', borderRadius: '8px', fontSize: '0.7rem', fontWeight: 900, cursor: 'pointer', letterSpacing: '1px' }}
                        >
                           + ADD TOOL
                        </button>
                     )}
                     {activeTab === 'providers' && (
                        <button
                           onClick={addProvider}
                           style={{ background: 'rgba(59, 130, 246, 0.1)', border: '1px solid var(--accent-blue)', color: 'var(--accent-blue)', padding: '8px 16px', borderRadius: '8px', fontSize: '0.7rem', fontWeight: 900, cursor: 'pointer', letterSpacing: '1px' }}
                        >
                           + ADD PROVIDER
                        </button>
                     )}
                  </div>

                  {['mcp', 'skills', 'tools'].includes(activeTab) && (
                     <div style={{ display: 'flex', gap: '12px', alignItems: 'center', marginBottom: '24px', flexWrap: 'wrap' }}>
                        <div style={{ position: 'relative', flex: '1 1 280px', maxWidth: '520px' }}>
                           <Search size={15} style={{ position: 'absolute', left: '14px', top: '50%', transform: 'translateY(-50%)', color: '#5f636d' }} />
                           <input
                              type="text"
                              placeholder={`Search ${activeTab}...`}
                              value={activeTab === 'mcp' ? mcpSearch : activeTab === 'skills' ? skillsSearch : toolsSearch}
                              onChange={(e) => {
                                 if (activeTab === 'mcp') setMcpSearch(e.target.value);
                                 if (activeTab === 'skills') setSkillsSearch(e.target.value);
                                 if (activeTab === 'tools') setToolsSearch(e.target.value);
                              }}
                              style={{ width: '100%', height: '40px', background: 'rgba(255,255,255,0.035)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: '10px', padding: '0 14px 0 40px', color: '#fff', fontSize: '0.82rem', outline: 'none', fontWeight: 600 }}
                           />
                        </div>
                        <button
                           disabled={bulkUpdating}
                           title={`Click to turn ${allFilteredCurrentOn ? 'off' : 'on'} all shown ${activeTab}`}
                           onClick={() => {
                              const targetActive = !allFilteredCurrentOn;
                              if (activeTab === 'mcp') bulkToggleMcp(filteredMcpServers, targetActive);
                              if (activeTab === 'skills') bulkToggleAssets('skills', filteredSkills, targetActive);
                              if (activeTab === 'tools') bulkToggleAssets('tools', filteredTools, targetActive);
                           }}
                           style={{ height: '40px', display: 'inline-flex', alignItems: 'center', gap: '9px', ...bulkPowerStyle, opacity: bulkUpdating ? 0.55 : 1, padding: '0 14px', borderRadius: '10px', fontSize: '0.68rem', fontWeight: 900, cursor: bulkUpdating ? 'wait' : 'pointer', letterSpacing: '1px', textTransform: 'uppercase' }}
                        >
                           <Power size={14} />
                           {bulkUpdating ? 'Updating...' : allFilteredCurrentOn ? 'All On' : 'All Off'}
                        </button>
                     </div>
                  )}

                  {activeTab === 'skills' && (
                     <div className="grid-list" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: '25px' }}>
                        {filteredSkills.map((s, i) => (
                           <div key={i} className="asset-card" style={{ background: 'linear-gradient(180deg, rgba(255,255,255,0.035), rgba(255,255,255,0.015))', border: '1px solid rgba(255,255,255,0.075)', padding: '26px', borderRadius: '10px', display: 'flex', flexDirection: 'column', gap: '16px', minHeight: '210px', boxShadow: '0 18px 45px rgba(0,0,0,0.18)' }}>
                              <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', alignItems: 'flex-start' }}>
                                 <div style={{ minWidth: 0, fontSize: '1.2rem', fontWeight: '800', color: '#fff', letterSpacing: '-0.5px', lineHeight: '1.15', overflowWrap: 'anywhere' }}>{formatCardName(s.name)}</div>
                                 <div style={{ display: 'flex', alignItems: 'center', gap: '7px', flexShrink: 0 }}>
                                    <span title="Version" style={{ width: '30px', height: '30px', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontSize: '0.68rem', fontWeight: 900, color: '#b8c7ff', background: 'rgba(59,130,246,0.10)', border: '1px solid rgba(59,130,246,0.22)', borderRadius: '8px', whiteSpace: 'nowrap' }}>{cardVersion(s)}</span>
                                    <button title="Configure summary" onClick={() => configureAsset('skills', s)} style={{ width: '30px', height: '30px', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(59,130,246,0.10)', border: '1px solid rgba(59,130,246,0.25)', color: 'var(--accent-blue)', borderRadius: '8px', cursor: 'pointer' }}><Settings2 size={14} /></button>
                                    <button title={s.active === false ? 'Off - click to turn on' : 'On - click to turn off'} onClick={() => toggleAsset('skills', s.name, s.active, s.description, s.config)} style={powerButtonStyle(s.active !== false)}><Power size={14} /></button>
                                    <button title="Delete" onClick={() => deleteAsset('skills', s.name)} style={{ width: '30px', height: '30px', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.18)', color: '#f87171', borderRadius: '8px', cursor: 'pointer' }}><Trash2 size={14} /></button>
                                 </div>
                              </div>
                              <div style={{ fontSize: '0.86rem', color: '#8a8d96', lineHeight: '1.6', flex: 1, marginTop: '4px' }}>{cleanAssetDescription(s.description, s.name)}</div>
                           </div>
                        ))}
                     </div>
                  )}

                  {activeTab === 'tools' && (
                     <div className="grid-list" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: '25px' }}>
                        {filteredTools.map((t, i) => (
                           <div key={i} className="asset-card" style={{ background: 'linear-gradient(180deg, rgba(255,255,255,0.035), rgba(255,255,255,0.015))', border: '1px solid rgba(255,255,255,0.075)', padding: '26px', borderRadius: '10px', display: 'flex', flexDirection: 'column', gap: '16px', minHeight: '210px', boxShadow: '0 18px 45px rgba(0,0,0,0.18)' }}>
                              <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', alignItems: 'flex-start' }}>
                                 <div style={{ minWidth: 0, fontSize: '1.2rem', fontWeight: '800', color: '#fff', lineHeight: '1.15', overflowWrap: 'anywhere' }}>{formatCardName(t.name)}</div>
                                 <div style={{ display: 'flex', alignItems: 'center', gap: '7px', flexShrink: 0 }}>
                                    <span title="Version" style={{ width: '30px', height: '30px', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontSize: '0.68rem', fontWeight: 900, color: '#b8c7ff', background: 'rgba(59,130,246,0.10)', border: '1px solid rgba(59,130,246,0.22)', borderRadius: '8px', whiteSpace: 'nowrap' }}>{cardVersion(t)}</span>
                                    <button title="Configure summary" onClick={() => configureAsset('tools', t)} style={{ width: '30px', height: '30px', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(59,130,246,0.10)', border: '1px solid rgba(59,130,246,0.25)', color: 'var(--accent-blue)', borderRadius: '8px', cursor: 'pointer' }}><Settings2 size={14} /></button>
                                    <button title={t.active === false ? 'Off - click to turn on' : 'On - click to turn off'} onClick={() => toggleAsset('tools', t.name, t.active, t.description, t.config)} style={powerButtonStyle(t.active !== false)}><Power size={14} /></button>
                                    <button title="Delete" onClick={() => deleteAsset('tools', t.name)} style={{ width: '30px', height: '30px', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.18)', color: '#f87171', borderRadius: '8px', cursor: 'pointer' }}><Trash2 size={14} /></button>
                                 </div>
                              </div>
                              <div style={{ fontSize: '0.86rem', color: '#8a8d96', lineHeight: '1.6', flex: 1, marginTop: '4px' }}>{cleanAssetDescription(t.description, t.name)}</div>
                           </div>
                        ))}
                     </div>
                  )}

                  {activeTab === 'mcp' && (
                     <div className="grid-list" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: '25px' }}>
                        {filteredMcpServers.map((srv: any, i: number) => (
                           <div key={i} className="asset-card" style={{ background: 'linear-gradient(180deg, rgba(255,255,255,0.035), rgba(255,255,255,0.015))', border: '1px solid rgba(255,255,255,0.075)', padding: '26px', borderRadius: '10px', display: 'flex', flexDirection: 'column', gap: '16px', minHeight: '210px', boxShadow: '0 18px 45px rgba(0,0,0,0.18)' }}>
                              <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', alignItems: 'flex-start' }}>
                                 <div style={{ minWidth: 0, fontSize: '1.2rem', fontWeight: '800', color: '#fff', letterSpacing: '-0.5px', lineHeight: '1.15', overflowWrap: 'anywhere' }}>{formatCardName(srv.name)}</div>
                                 <div style={{ display: 'flex', alignItems: 'center', gap: '7px', flexShrink: 0 }}>
                                    <span title="Version" style={{ width: '30px', height: '30px', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontSize: '0.68rem', fontWeight: 900, color: '#b8c7ff', background: 'rgba(59,130,246,0.10)', border: '1px solid rgba(59,130,246,0.22)', borderRadius: '8px', whiteSpace: 'nowrap' }}>{cardVersion(srv)}</span>
                                    <button title="Configure MCP" onClick={() => configureMcp(srv)} style={{ width: '30px', height: '30px', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(59,130,246,0.10)', border: '1px solid rgba(59,130,246,0.25)', color: 'var(--accent-blue)', borderRadius: '8px', cursor: 'pointer' }}><Settings2 size={14} /></button>
                                    <button title={srv.active === false ? 'Off - click to turn on' : 'On - click to turn off'} onClick={() => toggleMcp(srv)} style={powerButtonStyle(srv.active !== false)}><Power size={14} /></button>
                                    <button title="Delete" onClick={() => deleteMcp(srv.name)} style={{ width: '30px', height: '30px', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.18)', color: '#f87171', borderRadius: '8px', cursor: 'pointer' }}><Trash2 size={14} /></button>
                                 </div>
                              </div>
                              <div style={{ fontSize: '0.86rem', color: '#8a8d96', lineHeight: '1.6', flex: 1, marginTop: '4px' }}>{cleanAssetDescription(srv.description, srv.name)}</div>
                           </div>
                        ))}
                     </div>
                  )}

                  {activeTab === 'audit' && (
                     <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr)', gap: '18px', alignItems: 'start' }}>
                        <div className="asset-card" style={{ background: agentLite ? 'linear-gradient(180deg, #fbfaf8, #f5f3ef)' : 'linear-gradient(180deg, rgba(18,28,38,0.96), rgba(12,14,18,0.98))', border: agentLite ? '1px solid #cbd5e1' : '1px solid rgba(120,144,180,0.16)', padding: '22px', borderRadius: '8px', display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) auto', gap: '20px', alignItems: 'start', boxShadow: '0 18px 55px rgba(0,0,0,0.06)' }}>
                           <div style={{ minWidth: 0 }}>
                              <div style={{ display: 'flex', gap: '10px', alignItems: 'center', flexWrap: 'wrap', marginBottom: '14px' }}>
                                 <span style={{ display: 'inline-flex', alignItems: 'center', gap: '7px', color: evolutionRefreshing ? '#facc15' : evolutionHasAuditData ? '#10b981' : '#ef4444', fontSize: '0.68rem', fontWeight: 900, letterSpacing: '1px', textTransform: 'uppercase' }}>
                                    <span style={{ width: '7px', height: '7px', borderRadius: '999px', background: evolutionRefreshing ? '#facc15' : evolutionHasAuditData ? '#10b981' : '#ef4444' }} />
                                    {evolutionRefreshing ? 'Refreshing Audit' : evolutionHasAuditData ? 'Audit Online' : 'No Audit Data'}
                                 </span>
                                 <span style={{ color: agentLite ? '#64748b' : '#7d8490', fontSize: '0.72rem', fontWeight: 750 }}>{evolutionUpdatedAt ? `updated ${evolutionUpdatedAt}` : 'using latest state snapshot'}</span>
                              </div>
                              <div style={{ color: agentLite ? '#1f2937' : '#fff', fontSize: '1.15rem', lineHeight: 1.35, fontWeight: 850, maxWidth: '720px' }}>
                                 Real evolution status from roadmap audits, evidence ledger, mission replay, and tool economy.
                              </div>
                              <div style={{ marginTop: '18px', height: '8px', width: '100%', maxWidth: '720px', background: agentLite ? 'rgba(0,0,0,0.05)' : 'rgba(255,255,255,0.06)', borderRadius: '999px', overflow: 'hidden', border: agentLite ? '1px solid #cbd5e1' : '1px solid rgba(255,255,255,0.07)' }}>
                                 <div style={{ height: '100%', width: `${Math.min(100, Math.max(0, evolutionProgress))}%`, background: 'linear-gradient(90deg, #3b82f6, #22c55e)', borderRadius: '999px' }} />
                              </div>
                           </div>
                           <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
                              <button onClick={refreshEvolutionAudit} disabled={evolutionRefreshing} style={{ height: '36px', background: agentLite ? '#ffffff' : 'rgba(255,255,255,0.05)', border: agentLite ? '1px solid #cbd5e1' : '1px solid rgba(255,255,255,0.12)', color: agentLite ? '#4b5563' : '#e5e7eb', padding: '0 12px', borderRadius: '8px', fontSize: '0.66rem', fontWeight: 900, cursor: evolutionRefreshing ? 'wait' : 'pointer', letterSpacing: '0.8px', textTransform: 'uppercase' }}>{evolutionRefreshing ? 'Refreshing' : 'Refresh'}</button>
                              <button onClick={() => runEvolutionControl('plan')} disabled={Boolean(evolutionWorking)} style={{ height: '36px', background: 'rgba(59,130,246,0.12)', border: '1px solid rgba(59,130,246,0.30)', color: '#2563eb', padding: '0 12px', borderRadius: '8px', fontSize: '0.66rem', fontWeight: 900, cursor: evolutionWorking ? 'wait' : 'pointer', letterSpacing: '0.8px', textTransform: 'uppercase', opacity: evolutionWorking ? 0.65 : 1 }}>{evolutionWorking === 'plan' ? 'Planning' : 'Plan'}</button>
                              <button onClick={() => runEvolutionControl('verify')} disabled={Boolean(evolutionWorking)} style={{ height: '36px', background: 'rgba(34,197,94,0.10)', border: '1px solid rgba(34,197,94,0.24)', color: '#16a34a', padding: '0 12px', borderRadius: '8px', fontSize: '0.66rem', fontWeight: 900, cursor: evolutionWorking ? 'wait' : 'pointer', letterSpacing: '0.8px', textTransform: 'uppercase', opacity: evolutionWorking ? 0.65 : 1 }}>{evolutionWorking === 'verify' ? 'Verifying' : 'Verify'}</button>
                           </div>
                        </div>

                        {evolutionAction.kind !== 'idle' && (
                           <div className="asset-card" style={{ background: agentLite ? '#fbfaf8' : 'rgba(255,255,255,0.024)', border: `1px solid ${evolutionAction.kind === 'error' ? '#fca5a5' : (agentLite ? '#cbd5e1' : 'rgba(59,130,246,0.16)')}`, borderRadius: '8px', padding: '18px', display: 'grid', gap: '12px' }}>
                              <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', alignItems: 'center' }}>
                                 <div style={{ color: agentLite ? '#1f2937' : '#fff', fontSize: '0.82rem', fontWeight: 900, letterSpacing: '1.2px', textTransform: 'uppercase' }}>
                                    {evolutionAction.kind === 'plan' ? 'Real Evolution Plan' : evolutionAction.kind === 'verify' ? 'Real Verification Result' : 'Evolution Error'}
                                 </div>
                                 <button onClick={() => setEvolutionAction({ kind: 'idle', message: '' })} style={{ height: '28px', padding: '0 10px', borderRadius: '7px', border: agentLite ? '1px solid #cbd5e1' : '1px solid rgba(255,255,255,0.10)', background: agentLite ? '#ffffff' : 'rgba(255,255,255,0.04)', color: agentLite ? '#4b5563' : '#a8adb7', cursor: 'pointer', fontSize: '0.62rem', fontWeight: 900 }}>Clear</button>
                              </div>
                              <div style={{ color: evolutionAction.kind === 'error' ? '#f87171' : (agentLite ? '#4b5563' : '#a8adb7'), fontSize: '0.8rem', lineHeight: 1.55 }}>{evolutionAction.message}</div>
                              {evolutionAction.data?.plan?.steps && (
                                 <div style={{ display: 'grid', gap: '8px' }}>
                                    {evolutionAction.data.plan.steps.slice(0, 5).map((step: any) => (
                                       <div key={step.step} style={{ display: 'grid', gridTemplateColumns: '28px minmax(0, 1fr)', gap: '10px', padding: '10px', borderRadius: '8px', background: agentLite ? '#ffffff' : 'rgba(8,10,14,0.62)', border: agentLite ? '1px solid #cbd5e1' : '1px solid rgba(255,255,255,0.065)' }}>
                                          <span style={{ color: '#2563eb', fontWeight: 900 }}>{step.step}</span>
                                          <div>
                                             <div style={{ color: agentLite ? '#1f2937' : '#fff', fontWeight: 850, fontSize: '0.8rem' }}>{step.title}</div>
                                             <div style={{ color: agentLite ? '#64748b' : '#7f8794', fontSize: '0.7rem', marginTop: '4px' }}>{step.next_action}</div>
                                          </div>
                                       </div>
                                    ))}
                                    <code style={{ color: '#2563eb', fontSize: '0.68rem', overflowWrap: 'anywhere' }}>workspace/evolution_plan.json</code>
                                 </div>
                              )}
                              {evolutionAction.data?.result?.checks && (
                                 <div style={{ display: 'grid', gap: '8px' }}>
                                    {evolutionAction.data.result.checks.map((check: any, idx: number) => (
                                       <div key={idx} style={{ display: 'grid', gridTemplateColumns: '28px minmax(0, 1fr)', gap: '10px', padding: '10px', borderRadius: '8px', background: agentLite ? '#ffffff' : 'rgba(8,10,14,0.62)', border: agentLite ? '1px solid #cbd5e1' : '1px solid rgba(255,255,255,0.065)' }}>
                                          <span style={{ color: check.status === 'pass' ? '#10b981' : '#ef4444', fontWeight: 900 }}>{check.status === 'pass' ? '✓' : '✗'}</span>
                                          <div>
                                             <div style={{ color: agentLite ? '#1f2937' : '#fff', fontWeight: 850, fontSize: '0.8rem' }}>{check.title}</div>
                                             <div style={{ color: agentLite ? '#64748b' : '#7f8794', fontSize: '0.7rem', marginTop: '4px' }}>{check.message}</div>
                                          </div>
                                       </div>
                                    ))}
                                    <code style={{ color: '#2563eb', fontSize: '0.68rem', overflowWrap: 'anywhere' }}>{evolutionAction.data.result.roadmap_path} · {evolutionAction.data.result.evidence_record?.id}</code>
                                 </div>
                              )}
                           </div>
                        )}

                        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))', gap: '12px' }}>
                           {[
                              ['Roadmap maturity', `${evolutionProgress}%`, `${evolutionCounts.done || 0}/${state.audit?.roadmap?.total || 0} complete`, '#10b981'],
                              ['Open gaps', compactNumber((evolutionCounts.partial || 0) + (evolutionCounts.missing || 0)), `${evolutionCounts.missing || 0} missing`, '#ef4444'],
                              ['Evidence records', compactNumber(state.audit?.evidence?.total || 0), `${evolutionEvidenceEntries.length || 0} statuses`, '#2563eb'],
                              ['Graph signals', compactNumber((state.audit?.unified_graph?.nodes || 0) + (state.audit?.unified_graph?.edges || 0)), `${compactNumber(evolutionSourceTotal)} source items`, '#06b6d4'],
                              ['Tool reliability', evolutionTools.length ? `${evolutionReliability}%` : 'No data', `${evolutionTools.length} tracked tools`, '#f59e0b']
                           ].map(([label, value, detail, color]) => (
                              <div key={label as string} className="asset-card" style={{ minHeight: '118px', background: agentLite ? '#fbfaf8' : 'rgba(255,255,255,0.026)', border: agentLite ? '1px solid #cbd5e1' : '1px solid rgba(255,255,255,0.075)', borderRadius: '8px', padding: '18px', display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
                                 <div style={{ color: agentLite ? '#64748b' : '#8d94a0', fontSize: '0.68rem', fontWeight: 900, letterSpacing: '1px', textTransform: 'uppercase' }}>{label}</div>
                                 <div>
                                    <div style={{ color: color as string, fontSize: '1.65rem', fontWeight: 900, lineHeight: 1 }}>{value as string}</div>
                                    <div style={{ color: agentLite ? '#4b5563' : '#a8adb7', fontSize: '0.76rem', marginTop: '7px', fontWeight: 700 }}>{detail as string}</div>
                                 </div>
                              </div>
                           ))}
                        </div>

                        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1.45fr) minmax(300px, 0.75fr)', gap: '18px', alignItems: 'start' }}>
                           <div className="asset-card" style={{ background: agentLite ? '#fbfaf8' : 'rgba(255,255,255,0.024)', border: agentLite ? '1px solid #cbd5e1' : '1px solid rgba(255,255,255,0.075)', borderRadius: '8px', padding: '20px' }}>
                              <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', alignItems: 'center', marginBottom: '14px' }}>
                                 <div style={{ fontSize: '0.72rem', color: agentLite ? '#64748b' : '#9aa2af', fontWeight: 900, letterSpacing: '1.5px', textTransform: 'uppercase' }}>Backlog With Proof</div>
                                 <span style={{ color: agentLite ? '#4b5563' : '#6f7784', fontSize: '0.72rem', fontWeight: 800 }}>{evolutionNext.length} open</span>
                              </div>
                              <div style={{ display: 'grid', gap: '12px' }}>
                                 {evolutionNext.slice(0, 7).map((item: any, i: number) => (
                                    <button key={i} onClick={() => startEvolutionPrompt(`Work on this NEXUS evolution item: ${item.item}. Evidence: ${(item.evidence || []).join(', ')}. Remaining: ${(item.remaining || []).join('; ')}`)} style={{ width: '100%', textAlign: 'left', background: agentLite ? '#ffffff' : 'rgba(8,10,14,0.70)', border: agentLite ? '1px solid #cbd5e1' : '1px solid rgba(255,255,255,0.075)', borderRadius: '8px', padding: '15px', cursor: 'pointer' }}>
                                       <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', alignItems: 'flex-start' }}>
                                          <div style={{ minWidth: 0 }}>
                                             <div style={{ color: agentLite ? '#1f2937' : '#fff', fontSize: '0.9rem', fontWeight: 850, lineHeight: 1.35, overflowWrap: 'anywhere' }}>{item.item}</div>
                                             <div style={{ color: agentLite ? '#64748b' : '#7f8794', fontSize: '0.72rem', marginTop: '6px', fontWeight: 750 }}>{item.phase || 'Roadmap'} · {(item.remaining || [])[0] || 'No remaining gap recorded.'}</div>
                                          </div>
                                          <span style={{ color: evolutionStatusColor(item.status), background: agentLite ? '#f1f5f9' : 'rgba(255,255,255,0.035)', border: agentLite ? '1px solid #cbd5e1' : '1px solid rgba(255,255,255,0.08)', borderRadius: '999px', padding: '4px 8px', fontSize: '0.58rem', fontWeight: 900, textTransform: 'uppercase', flexShrink: 0 }}>{item.status || 'unknown'}</span>
                                       </div>
                                       <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', marginTop: '10px' }}>
                                          {(item.evidence || []).slice(0, 3).map((ev: string) => (
                                             <span key={ev} style={{ color: '#2563eb', background: 'rgba(59,130,246,0.06)', border: '1px solid rgba(59,130,246,0.14)', borderRadius: '7px', padding: '4px 7px', fontSize: '0.64rem', fontWeight: 800, maxWidth: '100%', overflowWrap: 'anywhere' }}>{ev}</span>
                                          ))}
                                       </div>
                                    </button>
                                 ))}
                                 {evolutionNext.length === 0 && (
                                    <div style={{ color: agentLite ? '#64748b' : '#8a8d96', fontSize: '0.82rem', padding: '14px', border: agentLite ? '1px dashed #cbd5e1' : '1px dashed rgba(255,255,255,0.10)', borderRadius: '8px' }}>No unfinished roadmap items returned by the audit.</div>
                                 )}
                              </div>
                           </div>

                           <div style={{ display: 'grid', gap: '14px' }}>
                              <div className="asset-card" style={{ background: agentLite ? '#fbfaf8' : 'rgba(255,255,255,0.024)', border: agentLite ? '1px solid #cbd5e1' : '1px solid rgba(255,255,255,0.075)', borderRadius: '8px', padding: '18px' }}>
                                 <div style={{ fontSize: '0.72rem', color: agentLite ? '#64748b' : '#9aa2af', fontWeight: 900, letterSpacing: '1.5px', textTransform: 'uppercase', marginBottom: '14px' }}>Roadmap State</div>
                                 {[
                                    ['Done', evolutionCounts.done || 0, '#10b981'],
                                    ['Partial', evolutionCounts.partial || 0, '#3b82f6'],
                                    ['Missing', evolutionCounts.missing || 0, '#ef4444']
                                 ].map(([label, value, color]) => (
                                    <div key={label as string} style={{ display: 'grid', gridTemplateColumns: '72px 1fr 34px', gap: '10px', alignItems: 'center', marginBottom: '12px' }}>
                                       <span style={{ color: agentLite ? '#4b5563' : '#b8bdc7', fontSize: '0.76rem', fontWeight: 800 }}>{label}</span>
                                       <div style={{ height: '7px', background: agentLite ? 'rgba(0,0,0,0.06)' : 'rgba(255,255,255,0.07)', borderRadius: '999px', overflow: 'hidden' }}>
                                          <div style={{ height: '100%', width: `${Math.max(3, Math.round(((Number(value) || 0) / Math.max(1, state.audit?.roadmap?.total || 1)) * 100))}%`, background: color as string }} />
                                       </div>
                                       <span style={{ color: color as string, fontSize: '0.78rem', fontWeight: 900, textAlign: 'right' }}>{value as number}</span>
                                    </div>
                                 ))}
                              </div>

                              <div className="asset-card" style={{ background: agentLite ? '#fbfaf8' : 'rgba(255,255,255,0.024)', border: agentLite ? '1px solid #cbd5e1' : '1px solid rgba(255,255,255,0.075)', borderRadius: '8px', padding: '18px' }}>
                                 <div style={{ fontSize: '0.72rem', color: agentLite ? '#64748b' : '#9aa2af', fontWeight: 900, letterSpacing: '1.5px', textTransform: 'uppercase', marginBottom: '14px' }}>Evidence Ledger</div>
                                 {evolutionEvidenceEntries.map(([key, value]) => (
                                    <div key={key} style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', color: agentLite ? '#4b5563' : '#a8adb7', fontSize: '0.78rem', marginBottom: '10px' }}>
                                       <span>{formatCardName(key)}</span>
                                       <span style={{ color: key === 'supported' ? (agentLite ? '#16a34a' : '#10b981') : key === 'contradicted' ? (agentLite ? '#ef4444' : '#ef4444') : (agentLite ? '#1f2937' : '#fff'), fontWeight: 900 }}>{value as number}</span>
                                    </div>
                                 ))}
                                 {evolutionEvidenceEntries.length === 0 && <div style={{ color: '#777', fontSize: '0.78rem' }}>No evidence ledger summary returned.</div>}
                              </div>
                           </div>
                        </div>

                        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: '18px' }}>
                           <div className="asset-card" style={{ background: agentLite ? '#fbfaf8' : 'rgba(255,255,255,0.024)', border: agentLite ? '1px solid #cbd5e1' : '1px solid rgba(255,255,255,0.075)', borderRadius: '8px', padding: '20px' }}>
                              <div style={{ fontSize: '0.72rem', color: agentLite ? '#64748b' : '#9aa2af', fontWeight: 900, letterSpacing: '1.5px', textTransform: 'uppercase', marginBottom: '16px' }}>Tool Economy</div>
                              <div style={{ display: 'grid', gap: '13px' }}>
                                 {evolutionTools.map((tool: any) => {
                                    const rate = Math.round((tool.success_rate || 0) * 100);
                                    return (
                                       <div key={tool.tool}>
                                          <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) auto auto', gap: '10px', alignItems: 'center', fontSize: '0.74rem', marginBottom: '6px' }}>
                                             <span style={{ color: agentLite ? '#1f2937' : '#e5e7eb', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontWeight: 800 }}>{formatCardName(tool.tool)}</span>
                                             <span style={{ color: agentLite ? '#64748b' : '#8d94a0', fontWeight: 800 }}>{compactNumber(tool.calls)} calls</span>
                                             <span style={{ color: rate >= 90 ? (agentLite ? '#16a34a' : '#10b981') : rate >= 70 ? '#d97706' : (agentLite ? '#ef4444' : '#ef4444'), fontWeight: 900 }}>{rate}%</span>
                                          </div>
                                          <div style={{ height: '6px', background: agentLite ? 'rgba(0,0,0,0.06)' : 'rgba(255,255,255,0.07)', borderRadius: '999px', overflow: 'hidden' }}>
                                             <div style={{ width: `${Math.max(3, rate)}%`, height: '100%', background: rate >= 90 ? '#22c55e' : rate >= 70 ? '#f59e0b' : '#ef4444', borderRadius: '999px' }} />
                                          </div>
                                          <div style={{ color: agentLite ? '#64748b' : '#6f7784', fontSize: '0.66rem', marginTop: '5px' }}>{Math.round(tool.avg_latency_ms || 0)} ms avg · {tool.risk_hint || 'risk unknown'}</div>
                                       </div>
                                    );
                                 })}
                                 {evolutionTools.length === 0 && <div style={{ color: '#777', fontSize: '0.8rem' }}>No tool economy metrics recorded yet.</div>}
                              </div>
                           </div>

                           <div className="asset-card" style={{ background: agentLite ? '#fbfaf8' : 'rgba(255,255,255,0.024)', border: agentLite ? '1px solid #cbd5e1' : '1px solid rgba(255,255,255,0.075)', borderRadius: '8px', padding: '20px' }}>
                              <div style={{ fontSize: '0.72rem', color: agentLite ? '#64748b' : '#9aa2af', fontWeight: 900, letterSpacing: '1.5px', textTransform: 'uppercase', marginBottom: '16px' }}>Signal Sources</div>
                              <div style={{ display: 'grid', gap: '13px' }}>
                                 {evolutionSources.map(([key, value]) => {
                                    const amount = Number(value) || 0;
                                    return (
                                       <div key={key}>
                                          <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', fontSize: '0.75rem', marginBottom: '6px' }}>
                                             <span style={{ color: agentLite ? '#1f2937' : '#e5e7eb', overflowWrap: 'anywhere', fontWeight: 800 }}>{formatCardName(key)}</span>
                                             <span style={{ color: agentLite ? '#1f2937' : '#fff', fontWeight: 900 }}>{compactNumber(amount)}</span>
                                          </div>
                                          <div style={{ height: '6px', background: agentLite ? 'rgba(0,0,0,0.06)' : 'rgba(255,255,255,0.07)', borderRadius: '999px', overflow: 'hidden' }}>
                                             <div style={{ width: `${Math.max(3, Math.round((amount / evolutionMaxSource) * 100))}%`, height: '100%', background: '#3b82f6', borderRadius: '999px' }} />
                                          </div>
                                       </div>
                                    );
                                 })}
                                 {evolutionSources.length === 0 && <div style={{ color: '#777', fontSize: '0.8rem' }}>No unified graph source counts returned.</div>}
                              </div>
                           </div>
                        </div>

                        <div className="asset-card" style={{ background: agentLite ? '#fbfaf8' : 'rgba(255,255,255,0.024)', border: agentLite ? '1px solid #cbd5e1' : '1px solid rgba(255,255,255,0.075)', borderRadius: '8px', padding: '20px' }}>
                           <div style={{ fontSize: '0.72rem', color: agentLite ? '#64748b' : '#9aa2af', fontWeight: 900, letterSpacing: '1.5px', textTransform: 'uppercase', marginBottom: '12px' }}>Mission Replay</div>
                           <div style={{ display: 'grid' }}>
                              {evolutionEvents.map((event: any, i: number) => (
                                 <div key={`${event.timestamp || i}-${event.event_type || 'event'}`} style={{ display: 'grid', gridTemplateColumns: '74px 150px minmax(0, 1fr)', gap: '14px', alignItems: 'center', fontSize: '0.75rem', color: agentLite ? '#4b5563' : '#8d94a0', borderTop: i === 0 ? 'none' : (agentLite ? '1px solid #cbd5e1' : '1px solid rgba(255,255,255,0.06)'), padding: '11px 0' }}>
                                    <span style={{ color: agentLite ? '#64748b' : '#6f7784', fontWeight: 800 }}>{formatEventTime(event.timestamp)}</span>
                                    <span style={{ color: agentLite ? '#1f2937' : '#fff', fontWeight: 850, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{formatCardName(event.event_type)}</span>
                                    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{event.data?.tool || event.data?.task || event.data?.note || event.mission_id || 'system signal'}</span>
                                 </div>
                              ))}
                              {evolutionEvents.length === 0 && <div style={{ color: '#777', fontSize: '0.8rem', padding: '10px 0' }}>No mission replay events recorded.</div>}
                           </div>
                        </div>
                     </div>
                  )}

                  {activeTab === 'config' && (
                     <ConfigPanel
                        configDirty={configDirty}
                        configDraft={configDraft}
                        configJsonText={configJsonText}
                        configMode={configMode}
                        configSearch={configSearch}
                        configSection={configSection}
                        configStatus={configStatus}
                        filteredConfigSections={filteredConfigSections}
                        formatCardName={formatCardName}
                        loadConfig={loadConfig}
                        resetConfigDraft={() => {
                           const reset = cloneConfig(configData || {});
                           setConfigDraft(reset);
                           setConfigJsonText(JSON.stringify(reset, null, 2));
                           setConfigStatus({ kind: 'valid', message: 'Draft reset to last loaded config.' });
                        }}
                        saveConfigDraft={saveConfigDraft}
                        selectedConfigValue={selectedConfigValue}
                        setConfigDraft={setConfigDraft}
                        setConfigJsonText={setConfigJsonText}
                        setConfigMode={setConfigMode}
                        setConfigSearch={setConfigSearch}
                        setConfigSection={setConfigSection}
                        setConfigStatus={setConfigStatus}
                        updateConfigPath={updateConfigPath}
                        validateConfigDraft={validateConfigDraft}
                     />
                  )}

                  {activeTab === 'plugins' && (
                     <div className="plugins-page">
                        <div className="plugin-install-card">
                           <div className="plugin-install-head">
                              <div>
                                 <h2>Install From Source</h2>
                                 <p>Download GitHub or marketplace source into the local plugin library.</p>
                              </div>
                              <button onClick={refreshPlugins} disabled={pluginBusy === 'install'}><Activity size={14} /> Rescan</button>
                           </div>
                           <div className="plugin-install-row">
                              <input
                                 value={pluginInstallUrl}
                                 onChange={(e) => setPluginInstallUrl(e.target.value)}
                                 placeholder="owner/repo, Git URL, or marketplace source URL"
                              />
                              <button className="primary" onClick={installPlugin} disabled={pluginBusy === 'install'}>
                                 {pluginBusy === 'install' ? 'Installing...' : 'Install'}
                              </button>
                           </div>
                           <div className="plugin-flags">
                              <label><input type="checkbox" checked={pluginForceInstall} onChange={(e) => setPluginForceInstall(e.target.checked)} /> Force reinstall</label>
                              <label><input type="checkbox" checked={pluginEnableAfterInstall} onChange={(e) => setPluginEnableAfterInstall(e.target.checked)} /> Enable after install</label>
                           </div>
                           <div className={`plugin-message ${pluginStatus.kind}`}>{pluginStatus.message}</div>
                        </div>

                        <div className="plugin-list-head">
                           <div>
                              <h2>Plugin Bundles</h2>
                              <p>{filteredPlugins.length} shown / {(state.plugins || []).length} installed or available.</p>
                           </div>
                           <div className="plugin-search">
                              <Search size={15} />
                              <input value={pluginSearch} onChange={(e) => setPluginSearch(e.target.value)} placeholder="Search plugins..." />
                           </div>
                        </div>

                        <div className="plugin-grid">
                           {filteredPlugins.map((plugin: any) => (
                              <div key={plugin.id} className="asset-card plugin-card-unified">
                                 <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', alignItems: 'flex-start' }}>
                                   <div style={{ minWidth: 0 }}>
                                      <div className="plugin-title">{formatCardName(plugin.name)}</div>
                                       <div className="plugin-subline">{plugin.installed === false ? 'Available plugin' : 'External plugin'}</div>
                                    </div>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '7px', flexShrink: 0 }}>
                                       <span title="Version" style={{ width: '30px', height: '30px', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontSize: '0.68rem', fontWeight: 900, color: '#b8c7ff', background: 'rgba(59,130,246,0.10)', border: '1px solid rgba(59,130,246,0.22)', borderRadius: '8px', whiteSpace: 'nowrap' }}>
                                          1
                                       </span>
                                       {plugin.installed === false ? (
                                          <button title="Install plugin" onClick={() => installPluginFromCard(plugin)} disabled={pluginBusy === plugin.id} style={{ minWidth: '78px', height: '30px', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: '7px', padding: '0 10px', background: 'rgba(59,130,246,0.12)', border: '1px solid rgba(59,130,246,0.28)', color: '#93c5fd', borderRadius: '8px', cursor: 'pointer', opacity: pluginBusy === plugin.id ? 0.55 : 1, fontSize: '0.66rem', fontWeight: 900, textTransform: 'uppercase' }}><PlusCircle size={14} /> Install</button>
                                       ) : (
                                          <>
                                             <button title="Configure plugin" onClick={() => configurePlugin(plugin)} disabled={pluginBusy === plugin.id} style={{ width: '30px', height: '30px', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(59,130,246,0.10)', border: '1px solid rgba(59,130,246,0.25)', color: 'var(--accent-blue)', borderRadius: '8px', cursor: 'pointer', opacity: pluginBusy === plugin.id ? 0.55 : 1 }}><Settings2 size={14} /></button>
                                             <button title={plugin.active === false ? 'Off - click to turn on' : 'On - click to turn off'} onClick={() => togglePlugin(plugin)} disabled={pluginBusy === plugin.id} style={powerButtonStyle(plugin.active !== false)}><Power size={14} /></button>
                                             <button title={plugin.disk_removable ? 'Delete plugin files' : 'Hide plugin'} onClick={() => removePlugin(plugin)} disabled={pluginBusy === plugin.id} style={{ width: '30px', height: '30px', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.18)', color: '#f87171', borderRadius: '8px', cursor: 'pointer', opacity: pluginBusy === plugin.id ? 0.55 : 1 }}><Trash2 size={14} /></button>
                                          </>
                                       )}
                                    </div>
                                 </div>
                                 <div className="plugin-summary">{cleanAssetDescription(plugin.description, plugin.name)}</div>
                              </div>
                           ))}
                           {filteredPlugins.length === 0 && (
                              <div className="config-empty big">
                                 <Puzzle size={24} />
                                 <b>No plugin bundles found</b>
                                 <button onClick={refreshPlugins}>Rescan Plugins</button>
                              </div>
                           )}
                        </div>
                     </div>
                  )}

                  {activeTab === 'providers' && (
                     <div className="grid-list" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: '25px', alignItems: 'stretch' }}>
                        {state.providers?.map((p, i) => {
                           const instances = state.provider_instances?.filter(pi => pi.parent === p.name) || [];

                           return (
                              <div
                                 key={i}
                                 className="asset-card"
                                 onClick={(e) => {
                                    // If they clicked an instance box, let that edit flow handle it.
                                    if ((e.target as any).closest('.instance-box')) return;
                                    const firstRoute = instances[0];
                                    setSelectedProv(p);
                                    setProviderFamilyName(p.name);
                                    setShowProviderPanel(true);
                                    setProviderCheck(null);
                                    setApiKey(firstRoute?.api_key || '');
                                    setTargetModel(firstRoute?.model || '');
                                    setProviderEndpoint(firstRoute?.endpoint || p.endpoint || '');
                                    setInstanceName(firstRoute?.id || '');
                                    setEditingInstanceId(firstRoute?.id || null);
                                 }}
                                 style={{ background: 'linear-gradient(180deg, rgba(255,255,255,0.035), rgba(255,255,255,0.015))', border: '1px solid rgba(255,255,255,0.075)', padding: '26px', borderRadius: '10px', cursor: 'pointer', transition: 'all 0.3s ease', display: 'flex', flexDirection: 'column', gap: '16px', minHeight: '210px', height: '100%', boxShadow: '0 18px 45px rgba(0,0,0,0.35)' }}
                              >
                                 <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                                    <b style={{ fontSize: '1rem', fontWeight: 700 }}>{formatProviderName(p.name)}</b>
                                    <span style={{ fontSize: '0.65rem', letterSpacing: '1px', color: p.status === 'ok' ? '#4ade80' : '#f87171', textTransform: 'uppercase', fontWeight: 800 }}>{p.status || 'unknown'}</span>
                                 </div>
                                 <div style={{ fontSize: '0.75rem', color: '#94a3b8', lineHeight: 1.5 }}>
                                    {instances.length > 0 ? (
                                       <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', marginTop: '4px' }}>
                                          {instances.map((inst: any) => (
                                             <div key={inst.id} className="instance-box" onClick={(e) => { e.stopPropagation(); configureProviderRoute(inst, p); }} style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: '8px', padding: '10px 12px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '10px' }}>
                                                <span style={{ fontSize: '0.7rem', fontWeight: 600, color: '#cbd5e1' }}>{inst.model || 'default'}</span>
                                                <span style={{ fontSize: '0.6rem', color: inst.status === 'ok' ? '#86efac' : '#fca5a5' }}>{inst.status}</span>
                                             </div>
                                          ))}
                                       </div>
                                    ) : (
                                       <span>No instances configured</span>
                                    )}
                                 </div>
                                 <div style={{ marginTop: 'auto', fontSize: '0.68rem', color: '#64748b' }}>
                                    Endpoint: {p.endpoint || 'default'}
                                 </div>
                              </div>
                           )})}
                        {state.providers?.length === 0 && (
                           <div className="config-empty big">
                              <Cpu size={24} />
                              <b>No providers configured</b>
                           </div>
                        )}
                     </div>
                  )}
               </div>

            )}

            {showProviderPanel && (
               <ConfigPanel
                  kind="provider"
                  name={providerFamilyName}
                  endpoint={providerEndpoint}
                  apiKey={apiKey}
                  model={targetModel}
                  instanceName={instanceName}
                  editingInstanceId={editingInstanceId}
                  providerCheck={providerCheck}
                  onSave={saveProvider}
                  onClose={() => setShowProviderPanel(false)}
                  onCheck={() => checkProvider(providerFamilyName)}
               />
            )}
         </div>
      </>
   );
}

export default App;
