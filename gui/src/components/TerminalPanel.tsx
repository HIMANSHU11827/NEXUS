import { useEffect, useRef, useState } from 'react'
import { AlertTriangle, ChevronDown, Columns2, Eraser, Expand, Filter, ListFilter, Loader2, Lock, MoreHorizontal, Plus, Search, Settings2, SquareTerminal, Trash2, X } from 'lucide-react'
import { api } from '../lib/api'

type TerminalLine = { kind: string; text: string }

export default function TerminalPanel({ onClose, onOpenSettings }: { onClose: () => void; onOpenSettings?: () => void }) {
  const [activeTab, setActiveTab] = useState('Terminal')
  const [command, setCommand] = useState('')
  const [debugCommand, setDebugCommand] = useState('')
  const [outputFilter, setOutputFilter] = useState('')
  const [problemsFilter, setProblemsFilter] = useState('')
  const [debugFilter, setDebugFilter] = useState('')
  const [outputChannel, setOutputChannel] = useState('Nexus')
  const [outputLocked, setOutputLocked] = useState(false)
  const [problemsCollapsed, setProblemsCollapsed] = useState(false)
  const [panelExpanded, setPanelExpanded] = useState(false)
  const [panelNotice, setPanelNotice] = useState('')
  const [shellProfile, setShellProfile] = useState('pwsh')
  const [profileMenuOpen, setProfileMenuOpen] = useState(false)
  const [moreMenuOpen, setMoreMenuOpen] = useState(false)
  const [terminalSessions, setTerminalSessions] = useState<Array<{ id: number; profile: string }>>([{ id: 1, profile: 'pwsh' }])
  const [activeTerminalId, setActiveTerminalId] = useState(1)
  const [lines, setLines] = useState<TerminalLine[]>([])
  const [terminalBuffers, setTerminalBuffers] = useState<Record<number, TerminalLine[]>>({ 1: [] })
  const [running, setRunning] = useState(false)
  const [history, setHistory] = useState<string[]>([])
  const [historyIndex, setHistoryIndex] = useState(-1)
  const [portInput, setPortInput] = useState('')
  const [forwardedPorts, setForwardedPorts] = useState<Array<{ port: number; address: string }>>([])
  const [apiOnline, setApiOnline] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const portInputRef = useRef<HTMLInputElement>(null)
  const debugInputRef = useRef<HTMLInputElement>(null)
  const problemsInputRef = useRef<HTMLInputElement>(null)
  const outputInputRef = useRef<HTMLInputElement>(null)

  const appendTerminalLine = (sessionId: number, line: TerminalLine) => {
    setTerminalBuffers(previous => ({ ...previous, [sessionId]: [...(previous[sessionId] ?? []), line] }))
    setLines(previous => [...previous, line])
  }

  useEffect(() => {
    fetch('/api/health', { cache: 'no-store' }).then(response => setApiOnline(response.ok)).catch(() => setApiOnline(false))
  }, [])

  const notice = (message: string) => {
    setPanelNotice(message)
    window.setTimeout(() => setPanelNotice(current => current === message ? '' : current), 1800)
  }

  const toggleExpanded = () => setPanelExpanded(value => !value)
  const clearPanel = (label: string) => { setLines([]); notice(`${label} cleared`) }
  const terminalProfiles = [
    { id: 'pwsh', label: 'PowerShell' },
    { id: 'cmd', label: 'Command Prompt' },
    { id: 'bash', label: 'Git Bash' },
    { id: 'wsl', label: 'Ubuntu (WSL)' },
  ]
  const workspacePath = 'C:\\Users\\himan\\Desktop\\NEXUS AI'
  const promptFor = (profile: string) => profile === 'cmd' ? `${workspacePath}>` : profile === 'pwsh' ? `(nexus-ai) PS ${workspacePath}>` : profile === 'wsl' ? `nexus-ai@workspace:${workspacePath}>` : `nexus-ai:${workspacePath}$`
  const createTerminal = (profile: string) => {
    const id = terminalSessions.length ? Math.max(...terminalSessions.map(session => session.id)) + 1 : 1
    setLines([])
    setTerminalBuffers(previous => ({ ...previous, [id]: [] }))
    setCommand('')
    setShellProfile(profile)
    setTerminalSessions(previous => [...previous, { id, profile }])
    setActiveTerminalId(id)
    setProfileMenuOpen(false)
    notice(`${profile} terminal ${id} created`)
  }

  const run = async () => {
    const value = command.trim(); if (!value || running) return
    const sessionId = activeTerminalId
    setCommand(''); setHistory(previous => [...previous, value]); setHistoryIndex(-1); setRunning(true)
    appendTerminalLine(sessionId, { kind: 'command', text: `${promptFor(shellProfile)} ${value}` })
    await api.runCommandStream(value,
      (text, stream) => appendTerminalLine(sessionId, { kind: stream, text }),
      result => { appendTerminalLine(sessionId, { kind: 'status', text: result.status === 'done' ? 'Process completed' : `Process exited with ${result.exit_code ?? 'an error'}` }); setRunning(false) },
      error => { appendTerminalLine(sessionId, { kind: 'stderr', text: error }); setRunning(false) },
      shellProfile,
    )
    setRunning(false)
  }

  const handleCommandKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'ArrowUp') {
      event.preventDefault()
      if (history.length === 0) return
      const next = historyIndex < 0 ? history.length - 1 : Math.max(0, historyIndex - 1)
      setHistoryIndex(next); setCommand(history[next])
    } else if (event.key === 'ArrowDown') {
      event.preventDefault()
      if (historyIndex < 0) return
      const next = historyIndex + 1
      if (next >= history.length) { setHistoryIndex(-1); setCommand('') } else { setHistoryIndex(next); setCommand(history[next]) }
    } else if (event.ctrlKey && event.key.toLowerCase() === 'l') {
      event.preventDefault(); setLines([]); setTerminalBuffers(previous => ({ ...previous, [activeTerminalId]: [] }))
    }
  }

  const tabs = ['Problems', 'Output', 'Debug Console', 'Terminal', 'Ports']

  const renderPanelTools = () => {
    const tool = (label: string, icon: React.ReactNode, onClick?: () => void) => <button type="button" onClick={onClick} className="panel-tool" title={label} aria-label={label}>{icon}</button>
    if (activeTab === 'Problems') return <>
      <input ref={problemsInputRef} value={problemsFilter} onChange={event => setProblemsFilter(event.target.value)} className="panel-filter" placeholder="Filter problems..." aria-label="Filter problems" />
      {tool('Focus problem filter', <Filter size={14} />, () => problemsInputRef.current?.focus())}
      {tool('Collapse all problems', <ListFilter size={14} />, () => setProblemsCollapsed(value => !value))}
      {tool(panelExpanded ? 'Restore panel' : 'Maximize panel', <Expand size={14} />, toggleExpanded)}
      {tool('Close panel', <X size={14} />, onClose)}
    </>
    if (activeTab === 'Output') return <>
      <input ref={outputInputRef} value={outputFilter} onChange={event => setOutputFilter(event.target.value)} className="panel-filter" placeholder="Filter output..." aria-label="Filter output" />
      <select className="panel-channel" aria-label="Output channel" value={outputChannel} onChange={event => setOutputChannel(event.target.value)}><option>Nexus</option><option>Python</option><option>Server</option></select>
      {tool('Clear output', <Eraser size={14} />, () => clearPanel('Output'))}
      {tool(outputLocked ? 'Unlock output' : 'Lock output', <Lock size={14} />, () => setOutputLocked(value => !value))}
      {tool('Output settings', <Settings2 size={14} />, () => notice(`Output channel: ${outputChannel}`))}
      {tool('More output actions', <MoreHorizontal size={15} />, () => notice('Output actions are ready'))}
      {tool(panelExpanded ? 'Restore panel' : 'Maximize panel', <Expand size={14} />, toggleExpanded)}
      {tool('Close panel', <X size={14} />, onClose)}
    </>
    if (activeTab === 'Debug Console') return <>
      <input value={debugFilter} onChange={event => setDebugFilter(event.target.value)} className="panel-filter" placeholder="Filter expressions..." aria-label="Filter expressions" />
      {tool('Search debug console', <Search size={14} />, () => debugInputRef.current?.focus())}
      {tool('Clear debug console', <Eraser size={14} />, () => clearPanel('Debug console'))}
      {tool(panelExpanded ? 'Restore panel' : 'Maximize panel', <Expand size={14} />, toggleExpanded)}
      {tool('Close panel', <X size={14} />, onClose)}
    </>
    if (activeTab === 'Ports') return <>
      {tool('Forward a port', <Plus size={15} />, () => portInputRef.current?.focus())}
      {tool('Port actions', <MoreHorizontal size={15} />, () => notice('Port actions are ready'))}
      {tool(panelExpanded ? 'Restore panel' : 'Maximize panel', <Expand size={14} />, toggleExpanded)}
      {tool('Close panel', <X size={14} />, onClose)}
    </>
    return <>
      <button type="button" className="panel-shell-select" title="Change shell profile" aria-label="Change shell profile" onClick={() => setProfileMenuOpen(value => !value)}><SquareTerminal size={13} /><span>{shellProfile}</span></button>
      {tool('Terminal warning', <AlertTriangle size={14} />, () => notice('Commands are checked by the Nexus sandbox'))}
      <div className="terminal-new-menu-wrap terminal-new-group">
        {tool(`New ${shellProfile} terminal`, <Plus size={15} />, () => createTerminal(shellProfile))}
        <button type="button" className="terminal-menu-toggle" title="Choose terminal profile" aria-label="Choose terminal profile" aria-expanded={profileMenuOpen} onClick={() => setProfileMenuOpen(value => !value)}><ChevronDown size={13} /></button>
        {profileMenuOpen && <div className="terminal-profile-menu" role="menu" aria-label="New terminal profile">
          <button type="button" role="menuitem" onClick={() => createTerminal(shellProfile)}>New {shellProfile} terminal</button>
          <div className="terminal-profile-divider" />
          <button type="button" role="menuitem" onClick={() => { setProfileMenuOpen(false); const opened = window.open(window.location.href, '_blank', 'noopener,noreferrer'); if (!opened) notice('Allow pop-ups to open another Nexus terminal window') }}>New terminal window <span className="terminal-menu-shortcut">Ctrl+Shift+Alt+`</span></button>
          <button type="button" role="menuitem" onClick={() => { setProfileMenuOpen(false); createTerminal(shellProfile); notice(`${shellProfile} split session created`) }}>Split terminal <span className="terminal-menu-shortcut">Ctrl+Shift+5</span></button>
          <button type="button" role="menuitem" onClick={() => { setProfileMenuOpen(false); notice('GitHub Copilot CLI is not configured in this Nexus workspace') }}>GitHub Copilot CLI</button>
          <div className="terminal-profile-divider" />
          {terminalProfiles.map(profile => <button key={profile.id} type="button" role="menuitem" onClick={() => { setShellProfile(profile.id); setProfileMenuOpen(false); notice(`${profile.label} selected for new terminals`) }}><SquareTerminal size={13} /><span>{profile.label}</span></button>)}
          <div className="terminal-profile-divider" />
          <button type="button" role="menuitem" onClick={() => { setProfileMenuOpen(false); notice(`Default profile: ${shellProfile}`) }}>Select default profile</button>
          <button type="button" role="menuitem" onClick={() => { setProfileMenuOpen(false); onOpenSettings?.() }}>Configure terminal settings</button>
        </div>}
      </div>
      {tool('Split terminal (create another session)', <Columns2 size={14} />, () => createTerminal(shellProfile))}
      {tool('Kill terminal', <Trash2 size={14} />, () => {
        if (terminalSessions.length === 1) { setLines([]); setTerminalBuffers(previous => ({ ...previous, [activeTerminalId]: [] })); setCommand(''); notice('The last terminal was cleared'); return }
        const remaining = terminalSessions.filter(session => session.id !== activeTerminalId)
        const next = remaining[remaining.length - 1]
        setTerminalSessions(remaining)
        setTerminalBuffers(previous => { const copy = { ...previous }; delete copy[activeTerminalId]; return copy })
        setActiveTerminalId(next.id); setShellProfile(next.profile); setLines(terminalBuffers[next.id] ?? []); setCommand(''); notice(`Terminal ${activeTerminalId} closed`)
      })}
      <div className="terminal-new-menu-wrap">
        {tool('More terminal actions', <MoreHorizontal size={15} />, () => setMoreMenuOpen(value => !value))}
        {moreMenuOpen && <div className="terminal-profile-menu terminal-actions-menu" role="menu" aria-label="Terminal actions">
          <button type="button" role="menuitem" onClick={() => { setLines([]); setTerminalBuffers(previous => ({ ...previous, [activeTerminalId]: [] })); setMoreMenuOpen(false); notice('Current terminal cleared') }}>Clear current terminal</button>
          <button type="button" role="menuitem" onClick={() => { setLines([]); setTerminalBuffers({ [activeTerminalId]: [] }); setMoreMenuOpen(false); notice('All terminal output cleared') }}>Clear all terminal output</button>
          <button type="button" role="menuitem" onClick={() => { setMoreMenuOpen(false); inputRef.current?.focus(); notice('Terminal input focused') }}>Focus terminal input</button>
        </div>}
      </div>
      {tool(panelExpanded ? 'Restore panel' : 'Maximize panel', <Expand size={14} />, toggleExpanded)}
      {tool('Close panel', <X size={14} />, onClose)}
    </>
  }

  const renderContent = () => {
    if (activeTab === 'Problems') return problemsCollapsed ? <div className="panel-collapsed">Problems collapsed</div> : <div className="panel-empty"><div className="panel-empty-title">{problemsFilter ? 'No matching problems' : 'No problems detected'}</div><div>{problemsFilter ? `No problem matches “${problemsFilter}”.` : 'Everything looks good in the workspace.'}</div></div>
    if (activeTab === 'Output') { const outputLines = lines.filter(line => !outputFilter || line.text.toLowerCase().includes(outputFilter.toLowerCase())); return <div className="panel-list" role="log">{outputLines.length === 0 ? <div className="panel-empty">{outputFilter ? 'No matching output.' : 'No output to display.'}</div> : outputLines.map((line, index) => <div key={`${index}-${line.text}`} className={`terminal-line terminal-${line.kind}`}>{line.text}</div>)}</div> }
    if (activeTab === 'Ports') { const guiPort = window.location.port || '5173'; return <div className="ports-table-wrap"><div className="ports-table-header"><span>Port</span><span>Forwarded Address</span><span>Running Process</span><span>Origin</span></div><form className="ports-entry" onSubmit={async event => { event.preventDefault(); const value = portInput.trim(); if (!value) return; try { const result = await api.probePort(value); setForwardedPorts(previous => previous.some(item => item.port === result.port) ? previous : [...previous, { port: result.port, address: result.address }]); setPortInput(''); notice(`Port ${result.port} is listening`) } catch (error) { notice(error instanceof Error ? error.message : 'Port is not available') } }}><input ref={portInputRef} value={portInput} onChange={event => setPortInput(event.target.value)} placeholder="Port number or address (e.g. 3000 or 10.0.0.5:8080)" aria-label="Port number or address" /><span /><span /><span /></form>{forwardedPorts.map(item => <div className="ports-row" key={item.port}><span>{item.port}</span><span>{item.address}</span><span>Detected service</span><span className="ports-origin-cell">Manual <button type="button" className="port-remove" onClick={() => { setForwardedPorts(previous => previous.filter(port => port.port !== item.port)); notice(`Port ${item.port} removed`) }} title={`Remove port ${item.port}`} aria-label={`Remove port ${item.port}`}><Trash2 size={12} /></button></span></div>)}<div className="ports-row"><span>{guiPort}</span><span>http://127.0.0.1:{guiPort}</span><span>Nexus GUI · Running</span><span>Workspace</span></div><div className="ports-row"><span>8000</span><span>http://127.0.0.1:8000</span><span>Nexus API · {apiOnline ? 'Running' : 'Offline'}</span><span>Workspace</span></div></div> }
    if (activeTab === 'Debug Console') { const debugLines = lines.filter(line => !debugFilter || line.text.toLowerCase().includes(debugFilter.toLowerCase())); return <div className="debug-console"><div className="panel-empty">{debugLines.length ? debugLines.map((line, index) => <div key={`${index}-${line.text}`} className={`terminal-line terminal-${line.kind}`}>{line.text}</div>) : 'Start a debug session to evaluate expressions.'}</div><form className="debug-input-row" onSubmit={async event => { event.preventDefault(); const value = debugCommand.trim(); if (!value || running) return; setDebugCommand(''); setRunning(true); setLines(previous => [...previous, { kind: 'command', text: `› ${value}` }]); await api.runCommandStream(value, (text, stream) => setLines(previous => [...previous, { kind: stream, text }]), () => setRunning(false), error => { setLines(previous => [...previous, { kind: 'stderr', text: error }]); setRunning(false) }); setRunning(false) }}><span>›</span><input ref={debugInputRef} value={debugCommand} onChange={event => setDebugCommand(event.target.value)} placeholder="Evaluate expression..." aria-label="Debug expression" /></form></div> }
    const activeLines = terminalBuffers[activeTerminalId] ?? []
    return <div className="terminal-layout"><div className="terminal-output" role="log" aria-live="polite" onClick={() => inputRef.current?.focus()}>{activeLines.length === 0 && <div className="text-muted-foreground/45">Click here and type a command, then press Enter.</div>}{activeLines.map((line, index) => <div key={`${index}-${line.text}`} className={`terminal-line terminal-${line.kind}`}>{line.text}</div>)}</div><aside className="terminal-session-list" aria-label="Terminal sessions">{terminalSessions.map(session => <div key={session.id} className={`terminal-session-item ${activeTerminalId === session.id ? 'terminal-session-active' : ''}`}><button type="button" className="terminal-session-main" onClick={() => { setActiveTerminalId(session.id); setShellProfile(session.profile); setLines(terminalBuffers[session.id] ?? []); notice(`${session.profile} selected`) }}><SquareTerminal size={13} /><span>{session.profile}</span></button><button type="button" className="terminal-session-close" onClick={() => { if (terminalSessions.length === 1) { setLines([]); setTerminalBuffers(previous => ({ ...previous, [session.id]: [] })); notice('The last terminal was cleared'); return } const remaining = terminalSessions.filter(item => item.id !== session.id); const next = remaining[remaining.length - 1]; setTerminalSessions(remaining); setTerminalBuffers(previous => { const copy = { ...previous }; delete copy[session.id]; return copy }); if (session.id === activeTerminalId) { setActiveTerminalId(next.id); setShellProfile(next.profile); setLines(terminalBuffers[next.id] ?? []) } notice(`${session.profile} closed`) }} title={`Close ${session.profile}`} aria-label={`Close ${session.profile}`}><X size={11} /></button></div>)}</aside></div>
  }

  return <section className={`terminal-drawer ${panelExpanded ? 'terminal-drawer-expanded' : ''}`} aria-label="Nexus bottom panel">
    <nav className="terminal-tabs" aria-label="Bottom panel tabs">
      {tabs.map(tab => <button key={tab} type="button" onClick={() => setActiveTab(tab)} className={`terminal-tab ${activeTab === tab ? 'terminal-tab-active' : ''}`} aria-selected={activeTab === tab}>{tab}</button>)}
      {panelNotice && <span className="panel-feedback" role="status">{panelNotice}</span>}
      <div className="panel-tools">{renderPanelTools()}</div>
    </nav>
    {activeTab === 'Terminal' ? <>
      <form className="terminal-command-form" onSubmit={event => { event.preventDefault(); run() }}>
        <span className="terminal-prompt">{promptFor(shellProfile)}</span>
        <input ref={inputRef} value={command} onChange={event => setCommand(event.target.value)} onKeyDown={handleCommandKeyDown} placeholder="" aria-label="Terminal command" disabled={running} className="min-w-0 flex-1 bg-transparent font-mono text-xs text-foreground outline-none placeholder:text-muted-foreground/40 disabled:opacity-50" autoFocus />
        {running && <Loader2 size={13} className="animate-spin text-muted-foreground/60" aria-label="Running command" />}
      </form>
    </> : null}
    {renderContent()}
  </section>
}
