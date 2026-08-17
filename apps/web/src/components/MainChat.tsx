import { Send, Copy, Check, CheckCircle, CheckCircle2, StopCircle, Globe, Terminal, FileEdit, Search, Code, Users, XCircle, ChevronDown, ChevronRight, ExternalLink, Mic, MicOff, Volume2, VolumeX, Cpu, ShieldCheck, MonitorUp, MonitorOff, Headphones, FolderOpen, Plus, GitBranch } from 'lucide-react'
import { createElement, useState, useRef, useEffect, useCallback, type ReactNode } from 'react'
import { useStore, type Message } from '../lib/store'
import { api, type CommandDTO } from '../lib/api'
import ApprovalPanel from './ApprovalPanel'
import BackgroundTasksPanel from './BackgroundTasksPanel'
import HivePanel from './HivePanel'
import QueuePanel from './QueuePanel'
import ClaudeAnimation from './ClaudeAnimation'
import { useStreamChat, type TimelineEvent } from '../hooks/useStreamChat'
import { formatTaskDuration, taskDurationMs, type TaskTiming } from '../lib/taskDuration'
import mascot from '../assets/nexus-mascot-brand.png'
import MonacoEditor from '@monaco-editor/react'

type BrowserSpeechRecognition = {
  continuous: boolean
  interimResults: boolean
  lang: string
  start: () => void
  stop: () => void
  abort: () => void
  onresult: ((event: any) => void) | null
  onend: (() => void) | null
  onerror: ((event: any) => void) | null
}

type BrowserSpeechRecognitionConstructor = new () => BrowserSpeechRecognition
type SavedModel = { model: string; provider: string; profile?: string; alias?: string; label: string }
type ModelPreferences = { thinking: boolean; effort: string }
type Attachment = { name: string; path: string }
type QueuedTask = { id: string; prompt: string; attachments: Attachment[] }

const defaultModelPreferences: ModelPreferences = { thinking: false, effort: 'medium' }

function providerForModel(model: string): string | undefined {
  const normalized = model.trim().toLowerCase()
  if (normalized === 'deepseek-chat' || normalized === 'deepseek-reasoner') return 'deepseek'
  if (normalized.startsWith('nvidia/')) return 'openrouter'
  if (normalized.startsWith('grok-')) return 'grok'
  if (normalized === 'llama3') return 'ollama'
  if (normalized.startsWith('qwen3.5-')) return 'lm_studio'
  return undefined
}

function Spinner({ size = 14, className = '' }: { size?: number; className?: string }) {
  return (
    <span className={`inline-block animate-spin ${className}`} style={{ width: size, height: size }}>
      <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
        <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeDasharray="31.416" strokeDashoffset="25.133" className="opacity-25" />
        <path d="M12 2C6.477 2 2 6.477 2 12" stroke="currentColor" strokeWidth="3" strokeLinecap="round" className="opacity-75" />
      </svg>
    </span>
  )
}

declare global {
  interface Window {
    SpeechRecognition?: BrowserSpeechRecognitionConstructor
    webkitSpeechRecognition?: BrowserSpeechRecognitionConstructor
  }
}

const suggestions = ['Write code', 'Search web', 'Analyze files', 'Run terminal']
const permissionOptions = [
  { value: 'auto', label: 'Automatic' },
  { value: 'ask', label: 'Ask every time' },
  { value: 'allowlist', label: 'Allowlist only' },
  { value: 'all', label: 'Allow all' },
]
const sandboxOptions = [
  { value: 'no_sandbox', label: 'No Sandbox' },
  { value: 'normal', label: 'Sandbox' },
  { value: 'docker', label: 'Advanced Sandbox' },
]
function extractCodeBlocks(text: string) {
  const parts: { type: 'text' | 'code'; content: string; language?: string }[] = []
  const regex = /```(\w*)\n([\s\S]*?)```/g
  let last = 0, match
  while ((match = regex.exec(text)) !== null) {
    if (match.index > last) parts.push({ type: 'text', content: text.slice(last, match.index) })
    parts.push({ type: 'code', content: match[2], language: match[1] || undefined })
    last = match.index + match[0].length
  }
  if (last < text.length) parts.push({ type: 'text', content: text.slice(last) })
  return parts
}


/** Render the small, safe Markdown subset returned by providers without injecting HTML. */
function InlineMarkdown({ text }: { text: string }) {
  const tokenPattern = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\(https?:\/\/[^\s)]+\))/g
  const nodes: ReactNode[] = []
  let lastIndex = 0
  let match: RegExpExecArray | null

  while ((match = tokenPattern.exec(text)) !== null) {
    if (match.index > lastIndex) nodes.push(text.slice(lastIndex, match.index))
    const token = match[0]

    if (token.startsWith('**')) {
      nodes.push(<strong key={`bold-${match.index}`} className="font-semibold text-foreground">{token.slice(2, -2)}</strong>)
    } else if (token.startsWith('`')) {
      nodes.push(<code key={`code-${match.index}`} className="rounded bg-secondary px-1 py-0.5 font-mono text-[0.85em] text-foreground">{token.slice(1, -1)}</code>)
    } else {
      const linkMatch = /^\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)$/.exec(token)
      if (linkMatch) {
        nodes.push(
          <a key={`link-${match.index}`} href={linkMatch[2]} target="_blank" rel="noreferrer" className="text-primary underline underline-offset-2">
            {linkMatch[1]}
          </a>,
        )
      } else {
        nodes.push(token)
      }
    }
    lastIndex = match.index + token.length
  }

  if (lastIndex < text.length) nodes.push(text.slice(lastIndex))
  return <>{nodes}</>
}

function splitMarkdownTableRow(line: string) {
  const trimmed = line.trim().replace(/^\|/, '').replace(/\|$/, '')
  return trimmed.split(/(?<!\\)\|/).map(cell => cell.trim().replace(/\\\|/g, '|'))
}

function isMarkdownTableSeparator(line: string) {
  const cells = splitMarkdownTableRow(line)
  return cells.length > 0 && cells.every(cell => /^:?-{3,}:?$/.test(cell))
}

function MarkdownText({ text }: { text: string }) {
  const lines = text.replace(/\r\n/g, '\n').split('\n')
  const blocks: ReactNode[] = []
  let paragraph: string[] = []
  let blockIndex = 0

  const flushParagraph = () => {
    if (!paragraph.length) return
    const paragraphLines = paragraph
    paragraph = []
    blocks.push(
      <p key={`paragraph-${blockIndex++}`} className="mb-3 last:mb-0">
        {paragraphLines.map((line, index) => (
          <span key={index}>{index > 0 && <br />}<InlineMarkdown text={line} /></span>
        ))}
      </p>,
    )
  }

  for (let lineIndex = 0; lineIndex < lines.length;) {
    const line = lines[lineIndex]
    const heading = /^(#{1,6})\s+(.+)$/.exec(line)
    const unordered = /^\s*[-*+]\s+(.+)$/.exec(line)
    const ordered = /^\s*\d+[.)]\s+(.+)$/.exec(line)

    if (!line.trim()) {
      flushParagraph()
      lineIndex += 1
      continue
    }

    if (heading) {
      flushParagraph()
      const level = Math.min(heading[1].length, 6)
      const classes = level === 1
        ? 'mb-2 mt-5 text-xl font-semibold text-foreground first:mt-0'
        : level === 2
          ? 'mb-2 mt-4 text-lg font-semibold text-foreground first:mt-0'
          : 'mb-1.5 mt-4 text-base font-semibold text-foreground first:mt-0'
      const tag = `h${level}` as keyof JSX.IntrinsicElements
      blocks.push(createElement(tag, { key: `heading-${blockIndex++}`, className: classes }, <InlineMarkdown text={heading[2]} />))
      lineIndex += 1
      continue
    }

    if (line.includes('|') && lineIndex + 1 < lines.length && isMarkdownTableSeparator(lines[lineIndex + 1])) {
      flushParagraph()
      const headers = splitMarkdownTableRow(line)
      const alignments = splitMarkdownTableRow(lines[lineIndex + 1]).map(cell => (
        cell.startsWith(':') && cell.endsWith(':') ? 'center' : cell.endsWith(':') ? 'right' : 'left'
      ))
      const rows: string[][] = []
      lineIndex += 2
      while (lineIndex < lines.length && lines[lineIndex].trim() && lines[lineIndex].includes('|')) {
        rows.push(splitMarkdownTableRow(lines[lineIndex]))
        lineIndex += 1
      }
      blocks.push(
        <div key={`table-${blockIndex++}`} className="mb-3 overflow-x-auto rounded-md border border-border">
          <table className="min-w-full border-collapse text-left text-sm">
            <thead className="bg-secondary/65 text-foreground">
              <tr>{headers.map((header, index) => <th key={index} scope="col" className="border-b border-border px-3 py-2 font-semibold" style={{ textAlign: alignments[index] }}>{<InlineMarkdown text={header} />}</th>)}</tr>
            </thead>
            <tbody>
              {rows.map((row, rowIndex) => (
                <tr key={rowIndex} className="border-b border-border/70 last:border-b-0 even:bg-secondary/25">
                  {headers.map((_, cellIndex) => <td key={cellIndex} className="px-3 py-2 align-top text-foreground/85" style={{ textAlign: alignments[cellIndex] }}>{<InlineMarkdown text={row[cellIndex] || ''} />}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>,
      )
      continue
    }

    if (unordered) {
      flushParagraph()
      const items: string[] = []
      while (lineIndex < lines.length) {
        const item = /^\s*[-*+]\s+(.+)$/.exec(lines[lineIndex])
        if (!item) break
        items.push(item[1])
        lineIndex += 1
      }
      blocks.push(
        <ul key={`unordered-${blockIndex++}`} className="mb-3 list-disc space-y-1 pl-5 marker:text-muted-foreground">
          {items.map((item, index) => <li key={index}><InlineMarkdown text={item} /></li>)}
        </ul>,
      )
      continue
    }

    if (ordered) {
      flushParagraph()
      const items: string[] = []
      while (lineIndex < lines.length) {
        const item = /^\s*\d+[.)]\s+(.+)$/.exec(lines[lineIndex])
        if (!item) break
        items.push(item[1])
        lineIndex += 1
      }
      blocks.push(
        <ol key={`ordered-${blockIndex++}`} className="mb-3 list-decimal space-y-1 pl-5 marker:text-muted-foreground">
          {items.map((item, index) => <li key={index}><InlineMarkdown text={item} /></li>)}
        </ol>,
      )
      continue
    }

    paragraph.push(line)
    lineIndex += 1
  }

  flushParagraph()
  return <>{blocks}</>
}

function CodeBlock({ code, language }: { code: string; language?: string }) {
  const [copied, setCopied] = useState(false)
  const languageMap: Record<string, string> = {
    ts: 'typescript',
    tsx: 'typescript',
    js: 'javascript',
    jsx: 'javascript',
    py: 'python',
    rs: 'rust',
    go: 'go',
    css: 'css',
    scss: 'scss',
    html: 'html',
    json: 'json',
    toml: 'toml',
    yml: 'yaml',
    yaml: 'yaml',
    md: 'markdown',
    xml: 'xml',
    txt: 'plaintext',
    sh: 'shell',
    bash: 'shell',
    zsh: 'shell',
    ps1: 'powershell',
    c: 'c',
    cpp: 'cpp',
    h: 'c',
    hpp: 'cpp',
    java: 'java',
    kt: 'kotlin',
    swift: 'swift',
    php: 'php',
    rb: 'ruby',
    sql: 'sql',
  }
  const detectedLanguage = languageMap[language || ''] || language || 'plaintext'
  return (
    <div className="my-2 rounded-lg overflow-hidden border border-border bg-secondary/50 not-prose">
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-border bg-secondary/30">
        <span className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">{language || 'code'}</span>
        <button
          onClick={() => { navigator.clipboard.writeText(code); setCopied(true); setTimeout(() => setCopied(false), 1400) }}
          className="flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] text-muted-foreground hover:text-foreground hover:bg-foreground/5 transition"
        >
          {copied ? <Check size={11} /> : <Copy size={11} />}
          <span>{copied ? 'Copied' : 'Copy'}</span>
        </button>
      </div>
      <div className="max-h-96 overflow-auto">
        <MonacoEditor
          height="300px"
          language={detectedLanguage}
          value={code}
          theme="vs"
          options={{
            readOnly: true,
            minimap: { enabled: false },
            fontSize: 12,
            lineNumbers: 'on',
            scrollBeyondLastLine: false,
            automaticLayout: true,
            tabSize: 2,
            wordWrap: 'on',
            folding: true,
            renderWhitespace: 'selection',
            lineHeight: 18,
            padding: { top: 12, bottom: 12 },
          }}
        />
      </div>
    </div>
  )
}

function MessageEntry({ msg }: { msg: Message }) {
  const isUser = msg.role === 'user'
  const [copied, setCopied] = useState(false)
  const hasActivity = !isUser && Boolean(msg.activity?.length)
  // Codex-style runs keep the public activity narrative visible by default.
  // The header still lets the user collapse it when they only want the answer.
  const [activityExpanded, setActivityExpanded] = useState(true)
  const totalWorkDuration = hasActivity ? runDuration(msg.activity!) : undefined
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [restoring, setRestoring] = useState(false)
  const [restoreError, setRestoreError] = useState('')
  const [restoreBlocked, setRestoreBlocked] = useState(false)
  const [restoreSuccess, setRestoreSuccess] = useState('')
  const sessionId = useStore(state => state.activeSessionId)
  const setMessageCheckpointRestored = useStore(state => state.setMessageCheckpointRestored)

  const confirmRestore = async () => {
    if (!msg.checkpointId || restoring) return
    if (!sessionId) {
      setRestoreError('No active session.')
      return
    }
    setConfirmOpen(false)
    setRestoring(true)
    setRestoreError('')
    try {
      const result = await api.restoreCheckpoint(msg.checkpointId, sessionId)
      setMessageCheckpointRestored(sessionId, msg.id)
      setRestoreSuccess(`Checkpoint restored. ${result.restored} file${result.restored === 1 ? '' : 's'} restored${result.removed > 0 ? ` and ${result.removed} removed` : ''}.`)
      window.dispatchEvent(new CustomEvent('nexus-sandbox-folder', { detail: { path: result.workspace_root || '' } }))
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Could not restore the checkpoint.'
      setRestoreError(message)
      if (/not found|corrupt/i.test(message)) setRestoreBlocked(true)
    } finally {
      setRestoring(false)
    }
  }

  return (
    <div className={`mb-5 flex group ${isUser ? 'justify-end' : 'justify-start'}`} data-testid="message-bubble">
      <div className={`max-w-[min(86%,760px)] ${isUser ? 'items-end' : 'items-start'} flex flex-col`}>
        <div className={`mb-1.5 px-1 text-xs font-medium ${isUser ? 'text-primary' : 'text-muted-foreground'}`}>
          {isUser ? 'You' : 'Nexus'}
        </div>
        {hasActivity && hasRenderableActivity(msg.activity!) && (
          <div className="mb-3 w-full">
            <button
              type="button"
              onClick={() => setActivityExpanded(expanded => !expanded)}
              aria-expanded={activityExpanded}
              className="flex w-full items-center gap-1 border-b border-border/60 px-1 pb-1.5 text-left text-sm text-muted-foreground transition hover:text-foreground"
            >
              {activityExpanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
              <span>{totalWorkDuration ? `Worked for ${formatDuration(totalWorkDuration)}` : 'Work details'}</span>
            </button>
            {activityExpanded && <div className="pt-2"><EventActivity events={msg.activity!} /></div>}
          </div>
        )}
        <div className={`relative rounded-lg border px-4 pb-5 pt-1.5 shadow-sm ${isUser
          ? 'border-border bg-background text-foreground shadow-foreground/10'
          : 'border-border/80 bg-card/70 text-foreground/90'
        }`}>
          {isUser ? (
            <p className="whitespace-pre-wrap text-sm leading-relaxed">{msg.content}</p>
          ) : (
            <>
              <div className="text-sm leading-relaxed">
                {extractCodeBlocks(msg.content).map((part, i) =>
                  part.type === 'code'
                    ? <CodeBlock key={i} code={part.content} language={part.language} />
                    : <MarkdownText key={i} text={part.content} />
                )}
              </div>
            </>
          )}
          <div className="absolute bottom-1 left-3 hidden items-center gap-1 rounded bg-background/85 px-1 transition-opacity group-hover:flex">
            <button
              onClick={() => { navigator.clipboard.writeText(msg.content); setCopied(true); setTimeout(() => setCopied(false), 1400) }}
              aria-label="Copy message"
              title="Copy message"
              className="flex size-5 items-center justify-center rounded text-muted-foreground/40 transition hover:bg-secondary hover:text-muted-foreground"
            >
              {copied ? <Check size={11} /> : <Copy size={11} />}
            </button>
            <span className="text-[10px] text-muted-foreground/45">{new Date(msg.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
          </div>
        </div>
        {!isUser && hasActivity && (
          <div className="mt-2 flex w-full flex-col items-end border-t border-border/60 pt-2">
            {(restoreSuccess || restoreError) && (
              <p role={restoreError ? 'alert' : 'status'} className={`mb-1 text-[10px] ${restoreError ? 'text-destructive/75' : 'text-emerald-600/80'}`}>
                {restoreError || restoreSuccess}
              </p>
            )}
            <div className="flex items-center gap-2">
              {msg.checkpointRestored ? (
                <button
                  type="button"
                  disabled
                  title="Files from this run were restored."
                  className="flex items-center gap-2 px-2 py-1 text-xs text-emerald-600/80"
                >
                  <span>Checkpoint Restored</span>
                  <CheckCircle size={14} />
                </button>
              ) : msg.checkpointId ? (
                <button
                  type="button"
                  onClick={() => { setRestoreError(''); setConfirmOpen(true) }}
                  disabled={restoring || restoreBlocked}
                  title={restoreBlocked ? 'This checkpoint is no longer available.' : 'Restore the files changed by this run.'}
                  className="flex items-center gap-2 px-2 py-1 text-xs text-muted-foreground transition hover:text-foreground disabled:opacity-50"
                >
                  {restoring ? <Spinner size={14} className="text-muted-foreground" /> : <GitBranch size={14} />}
                  <span>{restoring ? 'Restoring…' : 'Restore Checkpoint'}</span>
                </button>
              ) : (
                <button
                  type="button"
                  disabled
                  title="A restorable file checkpoint is not available for this run."
                  className="flex items-center gap-2 px-2 py-1 text-xs text-muted-foreground/60"
                >
                  <span>Restore Checkpoint</span>
                  <GitBranch size={14} />
                </button>
              )}
            </div>
            {confirmOpen && (
              <div className="mt-2 w-full rounded-md border border-border bg-card/70 p-3">
                <p className="text-xs leading-relaxed text-foreground/85">Restore the files changed by this run? This reverts modified files, restores deleted files, and removes files created by this run. You cannot undo this.</p>
                <div className="mt-2 flex justify-end gap-2">
                  <button type="button" onClick={() => setConfirmOpen(false)} disabled={restoring} className="rounded px-3 py-1 text-xs text-muted-foreground transition hover:bg-secondary disabled:opacity-50">Cancel</button>
                  <button type="button" onClick={confirmRestore} disabled={restoring} className="flex items-center gap-1.5 rounded bg-foreground px-3 py-1 text-xs font-medium text-background transition hover:opacity-80 disabled:opacity-50">
                    {restoring && <Spinner size={12} className="text-background" />}
                    <span>{restoring ? 'Restoring…' : 'Confirm Restore'}</span>
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

function eventIcon(type: string) {
  if (type.startsWith('agent.thinking') || type.startsWith('thinking') || type.startsWith('thought')) return Cpu
  if (type.startsWith('command') || type.startsWith('terminal')) return Terminal
  if (type.startsWith('file')) return FileEdit
  if (type.startsWith('search') || type.startsWith('web') || type.startsWith('browse') || type.startsWith('browser')) return Search
  if (type.startsWith('tool') || type.startsWith('mcp')) return Globe
  if (type.startsWith('hive') || type.startsWith('subagent')) return Users
  if (type.startsWith('code') || type.startsWith('generate')) return Code
  return Code
}

function formatDuration(ms?: number): string {
  return formatTaskDuration(ms)
}

function toolLabel(event: TimelineEvent): string {
  if (event.type.startsWith('agent.thinking') || event.type.startsWith('thinking') || event.type.startsWith('thought')) return 'Thought'
  if (event.type.startsWith('command') || event.type.startsWith('terminal')) return 'Run command'
  if (event.type.startsWith('web') || event.type.startsWith('search')) return 'Web search'
  if (event.type.startsWith('browse') || event.type.startsWith('browser')) return 'Browser'
  if (event.type.startsWith('file')) {
    const action = `${event.action || ''} ${event.title || ''}`.toLowerCase()
    if (event.type.includes('read') || action.includes('read')) return 'Read file'
    if (event.type.includes('created') || action.includes('create') || action.includes('write')) return 'Create file'
    if (event.type.includes('deleted') || action.includes('delete') || action.includes('remove')) return 'Delete file'
    return event.type.includes('diff') ? 'Patch file' : 'Edit file'
  }
  if (event.type.startsWith('git')) return 'Git'
  if (event.type.startsWith('test')) return 'Test'
  if (event.type.startsWith('plan')) return 'Plan'
  if (event.stage === 'planning') return 'Plan'
  if (event.kind === 'mcp') return 'MCP'
  if (event.kind === 'hive' || event.kind === 'subagent') return 'Hive'
  if (event.type.startsWith('tool')) return event.tool || 'Tool'
  if (event.type.startsWith('mcp')) return 'MCP'
  if (event.type.startsWith('hive') || event.type.startsWith('subagent')) return event.subagent || 'Sub-agent'
  if (event.type.startsWith('skill')) return event.skill || 'Skill'
  if (event.type.startsWith('plugin')) return 'Plugin'
  if (event.type.startsWith('code') || event.type.startsWith('generate')) return 'Generate'
  if (event.type.startsWith('memory')) return 'Memory'
  if (event.type.startsWith('evolution')) return 'Evolution'
  return event.title || 'Action'
}

function toolTarget(event: TimelineEvent): string {
  // Web search → show the query
  if (event.type.startsWith('web') || event.type.startsWith('search')) {
    return event.query || event.title || ''
  }
  // Terminal/command → show the command
  if (event.type.startsWith('command') || event.type.startsWith('terminal')) {
    return event.command || ''
  }
  // File operations → never expose the path in chat; show the filename only.
  if (event.type.startsWith('file')) {
    return fileName(event.path || event.title || '')
  }
  // Git → show the action
  if (event.type.startsWith('git')) {
    return event.target || event.title || ''
  }
  // Tool/MCP/Hive/Skill/Plugin → show what was called
  if (event.type.startsWith('tool') || event.type.startsWith('mcp') ||
      event.type.startsWith('hive') || event.type.startsWith('subagent') ||
      event.type.startsWith('skill') || event.type.startsWith('plugin') ||
      event.type.startsWith('code') || event.type.startsWith('generate')) {
    if (event.type.startsWith('mcp') && (event.server || event.mcpTool)) {
      return [event.server, event.mcpTool].filter(Boolean).join(' · ')
    }
    return event.target || event.skill || event.subagent || event.tool || event.title || event.query || event.command || ''
  }
  return event.target || event.command || event.title || event.query || ''
}

function fileName(value: string): string {
  const normalized = value.replace(/\\/g, '/')
  return normalized.split('/').filter(Boolean).pop() || value
}

function isTerminalEvent(event: TimelineEvent) {
  return event.type.startsWith('command') || event.type.startsWith('terminal')
}

function isWebEvent(event: TimelineEvent) {
  return event.type.startsWith('web') || event.type.startsWith('search') || event.type.startsWith('browse') || event.type.startsWith('browser')
}

function isFileEvent(event: TimelineEvent) {
  return event.type.startsWith('file')
}

function fileOperation(event: TimelineEvent): 'read' | 'created' | 'deleted' | 'edited' {
  const action = `${event.action || ''} ${event.title || ''}`.toLowerCase()
  if (event.type.includes('read') || action.includes('read')) return 'read'
  if (event.type.includes('created') || action.includes('create') || action.includes('write')) return 'created'
  if (event.type.includes('deleted') || action.includes('delete') || action.includes('remove')) return 'deleted'
  return 'edited'
}

function boundedOutput(value: string, maxLength = 12000): { value: string; truncated: boolean } {
  if (value.length <= maxLength) return { value, truncated: false }
  return { value: value.slice(-maxLength), truncated: true }
}

function eventOutput(event: TimelineEvent): string {
  return event.output || event.lines?.filter(Boolean).join('') || ''
}

function sourceLabel(source: string): string {
  try {
    return new URL(source).hostname.replace(/^www\./, '') || source
  } catch {
    return source
  }
}

interface SearchResult {
  title: string
  url: string
  snippet: string
}

function finalSearchUrl(source: string): string {
  try {
    const parsed = new URL(source)
    // Bing returns redirect links; expose the actual cited source instead.
    const destination = parsed.searchParams.get('url') || parsed.searchParams.get('u')
    if (destination && /^https?:\/\//i.test(destination)) return destination
  } catch {
    // Keep the original value below when it is not a URL.
  }
  return source
}

function parseSearchResults(output: string): SearchResult[] {
  const results: SearchResult[] = []
  const seen = new Set<string>()
  const pattern = /^\s*[-*]\s*\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)\s*(?:—|-)?\s*([^\n]*)/gm
  let match: RegExpExecArray | null
  while ((match = pattern.exec(output)) !== null) {
    const url = finalSearchUrl(match[2])
    if (seen.has(url)) continue
    seen.add(url)
    results.push({ title: match[1].trim(), url, snippet: match[3].trim() })
  }
  return results.slice(0, 8)
}

function ActivityCode({ value, terminal = false }: { value: string; terminal?: boolean }) {
  const output = boundedOutput(value)
  const wrappedLines = output.value.split('\n').reduce((total, line) => total + Math.max(1, Math.ceil(line.length / 120)), 0)
  const autoHeight = Math.min(220, Math.max(52, wrappedLines * 17 + 18))
  return (
    <div className="border-t border-border/50 px-2 py-2">
      {output.truncated && <p className="mb-1 text-[10px] text-muted-foreground/60">Showing the last 12,000 characters emitted by this activity.</p>}
      <div className={`overflow-hidden rounded ${terminal ? 'bg-[#0c0c0c]' : 'bg-background/70'}`} style={{ height: `${autoHeight}px` }}>
        <MonacoEditor
          height={`${autoHeight}px`}
          language="plaintext"
          value={output.value}
          theme={terminal ? 'vs-dark' : 'vs'}
          options={{
            readOnly: true,
            minimap: { enabled: false },
            fontSize: terminal ? 12 : 11,
            lineNumbers: terminal ? 'off' : 'on',
            scrollBeyondLastLine: false,
            automaticLayout: true,
            tabSize: 2,
            wordWrap: 'on',
            folding: !terminal,
            renderWhitespace: 'selection',
            lineHeight: 16,
            padding: { top: 8, bottom: 8 },
          }}
        />
      </div>
    </div>
  )
}

function EventDetails({ event }: { event: TimelineEvent }) {
  const output = eventOutput(event)

  if (event.type.startsWith('plan')) {
    return (
      <div className="border-t border-border/50 px-3 py-2 text-[11px] text-foreground/75">
        {event.planType === 'advanced' && event.phases && event.phases.length > 0 ? (
          <div className="space-y-3">
            {event.phases.map((phase, index) => (
              <section key={`${index}-${phase.title}`}>
                <p className="font-medium text-foreground/85">Phase {index + 1}: {phase.title}</p>
                {phase.subgoals.length > 0 && <ul className="mt-1 list-disc space-y-1 pl-4 text-muted-foreground/80">
                  {phase.subgoals.map((goal, subIndex) => <li key={`${subIndex}-${goal}`}>{goal}</li>)}
                </ul>}
              </section>
            ))}
          </div>
        ) : event.items && event.items.length > 0 ? (
          <ol className="list-decimal space-y-1 pl-4">
            {event.items.map((item, index) => <li key={`${index}-${item}`}>{item}</li>)}
          </ol>
        ) : output ? <ActivityCode value={output} /> : (
          <p className="text-muted-foreground/75">{event.summary || event.action || 'Planning update received.'}</p>
        )}
      </div>
    )
  }

  if (isFileEvent(event)) {
    const operation = fileOperation(event)
    const hasRange = event.lineStart !== undefined || event.lineEnd !== undefined
    return (
      <div className="text-[11px] text-foreground/75">
        {operation === 'read' && hasRange && (
          <div className="border-t border-border/50 px-2 py-1.5 text-muted-foreground/70">
            Lines {event.lineStart ?? 1}–{event.lineEnd ?? event.lineStart}
          </div>
        )}
        {output && <ActivityCode value={output} />}
      </div>
    )
  }

  if (isTerminalEvent(event)) {
    const prompt = event.cwd ? `${event.cwd}>` : '>'
    const isFinished = event.status !== 'running' && event.status !== 'pending'
    const terminalText = [
      event.command ? `${prompt}${event.command}` : '',
      output || event.error || '',
      isFinished ? prompt : '',
    ].filter(Boolean).join('\n')
    return (
      <div className="border-t border-border/50 px-2 py-2 text-[11px] text-foreground/75">
        {event.cwd && <p className="mb-1 text-muted-foreground/70">Workspace: {event.cwd}</p>}
        {event.exitCode !== undefined && <p className="mb-1 text-muted-foreground/70">Exit code: {event.exitCode}</p>}
        {terminalText && <ActivityCode value={terminalText} terminal />}
      </div>
    )
  }

  if (isWebEvent(event)) {
    const results = parseSearchResults(output)
    const fallbackSources = (event.sources || [])
      .map(finalSearchUrl)
      .filter((source, index, sources) => source && sources.indexOf(source) === index)
      .slice(0, 8)
    return (
      <div className="border-t border-border/50 px-2 py-2 text-[11px] text-foreground/75">
        {event.query && <p className="mb-2 font-mono text-muted-foreground/80">{event.query}</p>}
        {!event.query && event.target && <p className="mb-2 font-mono text-muted-foreground/80">{event.target}</p>}
        {event.action && event.action !== event.target && <p className="mb-2 text-muted-foreground/75">{event.action}</p>}
        {results.length > 0 && (
          <div className="space-y-1">
            {results.map((result, index) => (
              <div key={`${result.url}-${index}`} className="min-w-0">
                <p className="text-foreground/80"><span className="mr-1 text-muted-foreground/60">{index + 1}.</span>{result.title}</p>
                {result.snippet && <p className="mt-0.5 max-h-8 overflow-hidden text-muted-foreground/70">{result.snippet}</p>}
                <a href={result.url} target="_blank" rel="noreferrer" className="mt-0.5 flex w-fit max-w-full items-center gap-1 text-primary/80 hover:text-primary hover:underline">
                  <ExternalLink size={11} className="shrink-0" />
                  <span className="truncate">Source: {sourceLabel(result.url)}</span>
                </a>
              </div>
            ))}
          </div>
        )}
        {results.length === 0 && fallbackSources.length > 0 && (
          <div className="space-y-1">
            {fallbackSources.map((source, index) => (
              <a key={`${source}-${index}`} href={source} target="_blank" rel="noreferrer" className="flex w-fit max-w-full items-center gap-1 text-primary/80 hover:text-primary hover:underline">
                <ExternalLink size={11} className="shrink-0" />
                <span className="truncate">{sourceLabel(source)}</span>
              </a>
            ))}
          </div>
        )}
        {output && results.length === 0 && fallbackSources.length === 0 && <ActivityCode value={output} />}
        {event.error && !output && <p className="mt-1 text-destructive/80">{event.error}</p>}
      </div>
    )
  }

  return (
    <div className="border-t border-border/50 px-2 py-2 text-[11px] text-foreground/75">
      {event.target && <p className="mb-1 text-muted-foreground/75">{event.target}</p>}
      {event.action && event.action !== event.target && <p className="mb-1 text-muted-foreground/75">{event.action}</p>}
      {output && <ActivityCode value={output} />}
      {!output && event.error && <p className="text-destructive/80">{event.error}</p>}
      {!output && !event.error && event.summary && <p className="text-muted-foreground/75">{event.summary}</p>}
    </div>
  )
}

function LiveRunStatus({ events }: { events: TimelineEvent[] }) {
  const startedAt = useRef(Date.now())
  const [elapsed, setElapsed] = useState(0)
  useEffect(() => {
    const tick = () => setElapsed(Math.max(0, Date.now() - startedAt.current))
    tick()
    const id = setInterval(tick, 250)
    return () => clearInterval(id)
  }, [])

  const activeEvent = [...events].reverse().find(event =>
    isExternalEvent(event) && (event.status === 'running' || event.status === 'pending')
  )
  const label = activeEvent
    ? `${toolLabel(activeEvent)} is ${activeEvent.status === 'pending' ? 'queued' : 'running'}`
    : 'Nexus is working'

  return (
    <div role="status" aria-live="polite" className="mb-2 flex items-center gap-2 text-xs font-semibold text-foreground/80">
      <ClaudeAnimation />
      <span>{label}</span>
      <span className="tabular-nums text-muted-foreground/70">· {formatDuration(elapsed)}</span>
    </div>
  )
}

function isTaskActive(event: TimelineEvent): boolean {
  return event.status === 'running' || event.status === 'pending' || event.status === 'blocked' || event.type.startsWith('retry')
}

// Tasks still moving (running, retrying) pulse; waiting/paused hold still.
function taskStatusLabel(event: TimelineEvent): { label: string; active: boolean } {
  if (event.type.startsWith('retry')) return { label: 'Retrying', active: true }
  switch (event.status) {
    case 'running':
      return { label: 'Running', active: true }
    case 'pending':
      return { label: 'Waiting', active: false }
    case 'blocked':
      return { label: 'Paused', active: false }
    case 'success':
      return { label: 'Done', active: false }
    case 'failed':
      return { label: isTimeoutEvent(event) ? 'Timed out' : 'Failed', active: false }
    case 'cancelled':
      return { label: 'Cancelled', active: false }
    case 'timed_out':
      return { label: 'Timed out', active: false }
    default:
      return { label: 'Stopped', active: false }
  }
}

function isTimeoutEvent(event: TimelineEvent): boolean {
  const haystack = `${event.error || ''} ${event.summary || ''} ${event.title || ''}`.toLowerCase()
  return /timeout|timed out|exceeded/.test(haystack)
}

// Real duration for the row. Finished tasks freeze at finishedAt - startedAt;
// active tasks tick with the shared `now`. Falls back to the backend's own
// durationMs, and only reports '—' when the task truly has no timing data.
const TERMINAL_TASK_STATUSES = new Set(['success', 'failed', 'cancelled', 'skipped'])

function taskDurationFor(event: TimelineEvent, now: number): number | undefined {
  const finished = TERMINAL_TASK_STATUSES.has(event.status)
  const timing: TaskTiming = {
    // Finished rows never invent a start from their own (terminal) timestamp;
    // active rows may, since their event timestamp is the start of the attempt.
    startedAt: finished
      ? event.startedAt ?? event.startTime
      : event.startedAt ?? event.startTime ?? event.timestamp,
    finishedAt: finished ? event.finishedAt : undefined,
  }
  const fromTimestamps = taskDurationMs(timing, now)
  if (fromTimestamps !== undefined) return fromTimestamps
  return event.durationMs
}

function ToolEventItem({ event, now }: { event: TimelineEvent; now: number }) {
  const [expanded, setExpanded] = useState(false)
  const Icon = eventIcon(event.type)
  const { label: statusLabel, active } = taskStatusLabel(event)
  const isFailed = event.status === 'failed'
  const isDone = event.status === 'success'
  const label = toolLabel(event)
  const target = toolTarget(event)
  const duration = formatTaskDuration(taskDurationFor(event, now))
  // File errors can contain an absolute path from the backend. File activity
  // intentionally shows filenames only, so keep that transport detail out of
  // the visible row as well.
  const detail = isFailed && !isFileEvent(event) ? event.error || target : target
  const hasDetails = Boolean(
    eventOutput(event) || event.error || event.command || event.cwd || event.exitCode !== undefined ||
    event.sources?.length || event.lineStart !== undefined || event.lineEnd !== undefined || event.summary ||
    event.target || event.action || event.tool || event.skill || event.subagent || event.server || event.mcpTool || event.title
  )
  const isThought = event.type.startsWith('agent.thinking') || event.type.startsWith('thinking') || event.type.startsWith('thought')
  const cardClass = isThought
    ? 'border-dashed bg-background/35'
    : isTerminalEvent(event)
      ? 'bg-secondary/35 border-border/70'
      : 'bg-secondary/55 border-border/50'

  return (
    <div className={`min-w-0 rounded-lg border ${cardClass}`} style={{ animation: 'nexus-fade-in 0.2s ease-out' }}>
      <button
        type="button"
        onClick={() => hasDetails && setExpanded(value => !value)}
        aria-expanded={hasDetails ? expanded : undefined}
        aria-label={`${expanded ? 'Collapse' : 'Expand'} ${label} details`}
        className={`flex w-full items-center gap-1.5 px-1.5 py-0.5 text-left text-[10px] ${hasDetails ? 'cursor-pointer hover:bg-foreground/[0.035] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring/50' : 'cursor-default'}`}
        title={isFileEvent(event) ? undefined : event.summary || detail}
      >
        <span className="shrink-0 text-muted-foreground/50">{hasDetails ? (expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />) : <span className="block size-3" />}</span>
        <span className="shrink-0" aria-label={statusLabel}>
          {active ? <Spinner size={12} className="text-muted-foreground/60" />
            : isFailed ? <XCircle size={12} className="text-destructive/70" />
            : isDone ? <CheckCircle2 size={12} className="text-emerald-600/70" />
            : <Icon size={12} className="text-muted-foreground/55" />}
        </span>
        <span className="shrink-0 font-semibold text-foreground/85">{label}</span>
        {detail && <span className="truncate font-mono text-muted-foreground/60" title={detail}>· {detail}</span>}
        <span className={`ml-auto shrink-0 text-[10px] ${isFailed ? 'text-destructive/70' : 'text-muted-foreground/50'}`}>
          {statusLabel}{' · '}{duration || '—'}
        </span>
      </button>
      {expanded && hasDetails && <EventDetails event={event} />}
    </div>
  )
}

// Only show public execution evidence. Internal planning and private thinking
// never enter this feed, and raw output chunks stay with their parent action.
const EXTERNAL_PREFIXES = ['assistant.progress', 'progress', 'plan.', 'tool.', 'command.', 'terminal.', 'file.', 'search.', 'web.', 'browse.', 'browser.', 'git.', 'test.', 'skill.', 'plugin.', 'mcp.', 'hive.', 'subagent.', 'code.', 'generate.', 'agent.thinking', 'thinking.', 'thought.', 'approval.', 'retry.', 'error.']

// Public activity allowlist. An event whose canonical type is unknown is still
// shown when the backend labelled it with one of these public work kinds, so a
// real approval prompt, retry, or failure can never be silently dropped.
const PUBLIC_ACTIVITY_KINDS = ['file', 'command', 'search', 'browser', 'mcp', 'skill', 'plugin', 'hive', 'todo', 'approval', 'retry', 'error']

// Private grounding and internal self-diagnostics are never public evidence and
// must never replay into the visible timeline.
const PRIVATE_EVENT_PATTERNS = [
  /prompt_files/i,
  /critical preventive vaccine/i,
  /tool safety audit/i,
  /agent tools/i,
  /latest tool results/i,
  /tool results accepted/i,
]

export function isPrivateDiagnosticEvent(event: TimelineEvent): boolean {
  const haystack = [event.target, event.path, event.title, event.summary, event.query, event.tool]
    .filter(Boolean)
    .join(' ')
  if (String(event.stage || '').toLowerCase() === 'grounding' && /prompt/i.test(haystack)) return true
  return PRIVATE_EVENT_PATTERNS.some(pattern => pattern.test(haystack))
}

// Failures, approval prompts, and retries are the events a user most needs.
// They stay in the feed even when their canonical type is unfamiliar.
export function isActionableEvent(event: TimelineEvent): boolean {
  const kind = String(event.kind || event.type || '').toLowerCase()
  return kind.includes('approval') || kind.includes('retry') || kind.includes('error')
    || event.status === 'failed'
}

export function actionableEventDetail(event: TimelineEvent, fallbackTarget = ''): string {
  return event.error || event.summary || fallbackTarget
}

function isExternalEvent(event: TimelineEvent): boolean {
  // Internal provider/prompt bookkeeping stays hidden. Public execution events
  // retain their stage so a live plan, search, file, or command card is never
  // lost simply because the backend provided a phase label.
  if (String(event.visibility || '').toLowerCase() === 'internal') return false
  if (isPrivateDiagnosticEvent(event)) return false
  // Planning stage events are explicitly public backend evidence, even when
  // canonicalization names them status.changed rather than plan.started.
  if (String(event.stage || '').toLowerCase() === 'planning'
    && String(event.visibility || '').toLowerCase() === 'public') return true
  if (isActionableEvent(event)) return true
  if (event.kind && PUBLIC_ACTIVITY_KINDS.includes(String(event.kind).toLowerCase())) return true
  // Output/result records are public evidence too.  The renderer can now
  // display them as standalone cards when a producer omitted a parent
  // lifecycle event, so never discard terminal or search output here.
  return EXTERNAL_PREFIXES.some(p => event.type.startsWith(p))
}

function lifecycleBaseType(type: string): string {
  return type
    .replace(/\.(stdout|stderr)$/i, '')
    .replace(/\.(started|completed|failed|cancelled|timed_out)$/i, '')
}

function mergeActivityOutput(current: TimelineEvent, incoming: TimelineEvent): string | undefined {
  const currentOutput = eventOutput(current)
  const incomingOutput = eventOutput(incoming)
  if (!incomingOutput) return currentOutput || undefined
  if (!currentOutput || incomingOutput === currentOutput || currentOutput.endsWith(incomingOutput)) return currentOutput || incomingOutput
  if (incomingOutput.startsWith(currentOutput)) return incomingOutput
  return `${currentOutput}${incomingOutput}`
}

/**
 * Deduplicate tool lifecycle events — keep only the latest status per tool.
 * Groups lifecycle events for the same action while preserving each distinct
 * real search/tool invocation as its own row.
 */
function deduplicateEvents(events: TimelineEvent[]): TimelineEvent[] {
  const map = new Map<string, TimelineEvent>()

  for (const ev of events) {
    if (ev.type === 'assistant.progress') {
      map.set(`assistant.progress|${ev.id}`, ev)
      continue
    }
    const baseType = lifecycleBaseType(ev.type)
    const runIdentity = ev.runId || ev.parentId || 'runless'
    const dedupKey = `${runIdentity}|${baseType}|${ev.tool || ev.skill || ev.subagent || ''}|${ev.command || ev.path || ev.query || ev.title || ev.id}`
    const existing = map.get(dedupKey)
    if (!existing || existing.status === 'running' || existing.status === 'pending') {
      if (!existing) {
        map.set(dedupKey, ev)
      } else if (ev.status !== 'running' && ev.status !== 'pending') {
        map.set(dedupKey, { ...ev, output: mergeActivityOutput(existing, ev) })
      } else if (existing.status === 'running' && ev.status === 'running') {
        map.set(dedupKey, { ...ev, output: mergeActivityOutput(existing, ev) })
      }
    } else {
      // Streaming stdout/stderr records can arrive after the completed
      // lifecycle record during replay. Keep one row and retain their output.
      const mergedOutput = mergeActivityOutput(existing, ev)
      if (mergedOutput && mergedOutput !== existing.output) map.set(dedupKey, { ...existing, output: mergedOutput })
    }
  }

  return Array.from(map.values())
}

function hasRenderableActivity(events: TimelineEvent[]): boolean {
  return deduplicateEvents(events.filter(isExternalEvent)).length > 0
}

function runDuration(events: TimelineEvent[]): number | undefined {
  const completedRun = events.find(event =>
    event.type === 'run.completed' || event.type === 'run.failed' || event.type === 'run.cancelled' || event.type === 'run.timed_out'
  )
  if (completedRun?.durationMs !== undefined) return completedRun.durationMs
  if (completedRun?.startTime !== undefined) {
    return Math.max(0, completedRun.timestamp - completedRun.startTime)
  }

  const startedRun = events.find(event => event.type === 'run.started')
  const terminalEvent = events.find(event =>
    event.type === 'message.completed' || event.type === 'message.failed' || event.type === 'run.completed' || event.type === 'run.failed' || event.type === 'run.timed_out'
  )
  if (startedRun && terminalEvent) return Math.max(0, terminalEvent.timestamp - startedRun.timestamp)
  return undefined
}

function PublicProgress({ event }: { event: TimelineEvent }) {
  const text = event.summary || event.output
  if (!text) return null
  return (
    <div className="rounded-lg border border-border/80 bg-card/70 px-4 py-2 text-sm leading-relaxed text-foreground/90 shadow-sm">
      <MarkdownText text={text} />
    </div>
  )
}

function EventActivity({ events }: { events: TimelineEvent[] }) {
  const visible = deduplicateEvents(events.filter(isExternalEvent))
    .sort((a, b) => (a.sequence ?? 0) - (b.sequence ?? 0) || a.timestamp - b.timestamp)
  const hasActiveTask = visible.some(isTaskActive)
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    if (!hasActiveTask) return
    setNow(Date.now())
    const id = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(id)
  }, [hasActiveTask])

  if (visible.length === 0) return null
  return (
    <div className="mb-3 space-y-2 nexus-event-line" style={{ animation: 'nexus-fade-in 0.25s ease-out' }}>
      {visible.map(ev => (
        <div key={ev.id} className="space-y-1">
          {ev.type === 'assistant.progress' || ev.type === 'progress'
            ? <PublicProgress event={ev} />
            : <ToolEventItem event={ev} now={now} />}
        </div>
      ))}
    </div>
  )
}

export default function MainChat({ onOpenTerminal }: { onOpenTerminal?: () => void }) {
  const { addMessage, getActiveSession, activeSessionId, createSession, setActiveSession, loadSessionsFromServer, backendAvailable } = useStore()
  const { content, events, thinkingText, isThinking, thinkingDone, isProcessing, recoveredActivity, replayGap, error, send, cancel, reset, pendingApproval, respondApproval } = useStreamChat(activeSessionId)
  const [input, setInput] = useState('')
  const [isMicListening, setIsMicListening] = useState(false)
  const [isBackendListening, setIsBackendListening] = useState(false)
  const [speechEnabled, setSpeechEnabled] = useState(() => localStorage.getItem('nexus-speech-enabled') === 'true')
  const [speechError, setSpeechError] = useState('')
  const [voiceStreamController, setVoiceStreamController] = useState<AbortController | null>(null)
  const [screenStream, setScreenStream] = useState<MediaStream | null>(null)
  const [screenError, setScreenError] = useState('')
  const [voiceMode, setVoiceMode] = useState(false)
  const [savedModels, setSavedModels] = useState<SavedModel[]>([])
  const [selectedModel, setSelectedModel] = useState(() => localStorage.getItem('nexus-selected-model') || '')
  const [modelError, setModelError] = useState('')
  const [permissionMode, setPermissionMode] = useState(() => localStorage.getItem('nexus-permission-mode') || 'auto')
  // Preserve an existing explicit choice; default new sessions to the safe sandbox.
  const [sandboxTier, setSandboxTier] = useState(() => localStorage.getItem('nexus-sandbox-tier') || 'normal')
  const [sandboxRoot, setSandboxRoot] = useState(() => localStorage.getItem('nexus-sandbox-root') || '')
  const [sandboxError, setSandboxError] = useState('')
  const [attachments, setAttachments] = useState<Attachment[]>([])
  const [isUploading, setIsUploading] = useState(false)
  const [attachmentError, setAttachmentError] = useState('')
  const [queuedTasks, setQueuedTasks] = useState<QueuedTask[]>([])
  const [showModelPicker, setShowModelPicker] = useState(false)
  const [modelSearch, setModelSearch] = useState('')
  const [commandRegistry, setCommandRegistry] = useState<CommandDTO[]>([])
  const [modelPreferences, setModelPreferences] = useState<Record<string, ModelPreferences>>(() => {
    try { return JSON.parse(localStorage.getItem('nexus-model-preferences') || '{}') as Record<string, ModelPreferences> } catch { return {} }
  })
  const prevSessionId = useRef<string | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const session = getActiveSession()
  const hasStreamed = useRef(false)
  const isSending = useRef(false)
  const lastSavedContent = useRef('')
  const recognitionRef = useRef<BrowserSpeechRecognition | null>(null)
  const screenPreviewRef = useRef<HTMLVideoElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const taskQueueRef = useRef<QueuedTask[]>([])
  const slashQuery = input.trimStart().startsWith('/') ? input.trimStart().slice(1).split(/\s/, 1)[0].toLowerCase() : ''
  const showSlashMenu = input.trimStart().startsWith('/') && !input.trimStart().slice(1).includes(' ')
  const matchingCommands = commandRegistry
    .filter(command => {
      const names = [command.name, ...(command.aliases || [])].map(name => name.replace(/^\//, '').toLowerCase())
      return names.some(name => name.includes(slashQuery)) || command.description.toLowerCase().includes(slashQuery)
    })
    .slice(0, 8)

  const settingsForModel = (model: string): ModelPreferences => modelPreferences[model] || defaultModelPreferences
  const updateModelPreferences = (model: string, next: Partial<ModelPreferences>) => {
    setModelPreferences(current => {
      const updated = { ...current, [model]: { ...settingsForModel(model), ...next } }
      localStorage.setItem('nexus-model-preferences', JSON.stringify(updated))
      return updated
    })
  }

  const setSandboxFolder = async (nextRoot: string) => {
    setSandboxRoot(nextRoot)
    localStorage.setItem('nexus-sandbox-root', nextRoot)
    setSandboxError('')
    try { await api.setSandbox(sandboxTier, nextRoot) } catch (error) { setSandboxError(error instanceof Error ? error.message : 'Could not set the sandbox folder.') }
  }

  const chooseSandboxFolder = () => {
    const nextRoot = window.prompt('Sandbox folder path. Nexus can work only inside this folder while Sandbox is enabled.', sandboxRoot)
    if (nextRoot !== null) void setSandboxFolder(nextRoot.trim())
  }

  const uploadAttachments = async (fileList: FileList | null) => {
    const files = Array.from(fileList || [])
    if (!files.length) return
    setAttachmentError('')
    setIsUploading(true)
    try {
      const result = await api.uploadAttachments(files)
      setAttachments(current => [...current, ...result.files.map(path => ({ path, name: path.replace(/\\/g, '/').split('/').pop() || path }))])
    } catch (error) {
      setAttachmentError(error instanceof Error ? error.message : 'Could not upload the selected items.')
    } finally {
      setIsUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  useEffect(() => {
    const syncExplorerFolder = (event: Event) => {
      const nextRoot = (event as CustomEvent<{ path?: string }>).detail?.path || ''
      void setSandboxFolder(nextRoot)
    }
    window.addEventListener('nexus-sandbox-folder', syncExplorerFolder)
    return () => window.removeEventListener('nexus-sandbox-folder', syncExplorerFolder)
  }, [sandboxTier])

  const speakResponse = useCallback((value: string) => {
    if (!speechEnabled || !('speechSynthesis' in window) || !value.trim()) return
    window.speechSynthesis.cancel()
    const speechText = value
      .replace(/```[\s\S]*?```/g, ' Code response omitted. ')
      .replace(/[#*_>`]/g, '')
      .replace(/\s+/g, ' ')
      .trim()
      .slice(0, 12000)
    if (!speechText) return
    const utterance = new SpeechSynthesisUtterance(speechText)
    utterance.rate = 1
    utterance.pitch = 1
    window.speechSynthesis.speak(utterance)
  }, [speechEnabled])

  useEffect(() => {
    if (prevSessionId.current && prevSessionId.current !== activeSessionId) {
      reset()
      hasStreamed.current = false
      lastSavedContent.current = ''
    }
    prevSessionId.current = activeSessionId
  }, [activeSessionId])

  const autoResize = useCallback(() => {
    const ta = textareaRef.current
    if (!ta) return
    ta.style.height = 'auto'
    ta.style.height = `${Math.min(ta.scrollHeight, 200)}px`
  }, [])

  useEffect(() => { autoResize() }, [input, autoResize])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [session?.messages.length, isProcessing, content])

  useEffect(() => {
    if (hasStreamed.current && !isProcessing && activeSessionId
      && (content !== lastSavedContent.current || events.length > 0)) {
      // Keep the safe, backend-sanitized thought marker with the completed
      // assistant turn so historical chats show the same activity cards as a
      // live run. The backend never sends private chain-of-thought here.
      const completedActivity = thinkingText
        ? [...events, {
            id: `thought-${activeSessionId}-${Date.now()}`,
            type: 'agent.thinking.completed',
            section: 'thinking' as const,
            title: 'Thought',
            status: 'success' as const,
            timestamp: Date.now(),
            summary: thinkingText.slice(0, 240),
            visibility: 'public',
          }]
        : events
      addMessage(activeSessionId, 'assistant', content, completedActivity)
      if (content) speakResponse(content)
      hasStreamed.current = false
      lastSavedContent.current = content
    }
  }, [isProcessing, content, events, thinkingText, activeSessionId, addMessage, speakResponse])

  useEffect(() => () => {
    recognitionRef.current?.abort()
    voiceStreamController?.abort()
    if ('speechSynthesis' in window) window.speechSynthesis.cancel()
  }, [])

  useEffect(() => {
    if (screenPreviewRef.current) screenPreviewRef.current.srcObject = screenStream
  }, [screenStream])

  useEffect(() => () => {
    screenStream?.getTracks().forEach(track => track.stop())
  }, [screenStream])

  useEffect(() => {
    let active = true
    const loadCommands = async () => {
      try {
        const result = await api.commands()
        if (active) setCommandRegistry(Array.isArray(result.commands) ? result.commands : [])
      } catch {
        if (active) setCommandRegistry([])
      }
    }
    void loadCommands()
    return () => { active = false }
  }, [])

  useEffect(() => {
    Promise.all([
      api.savedModels(),
      api.getModel().catch(() => ({ model: '', provider: '' })),
    ]).then(([result, active]) => {
      const models = result.models || []
      setSavedModels(models)
      setSelectedModel(current => {
        const activeModel = String(active.model || '').trim()
        if (activeModel && models.some(item => item.model === activeModel)) {
          localStorage.setItem('nexus-selected-model', activeModel)
          return activeModel
        }
        if (models.some(item => item.model === current)) return current
        const next = models[0]?.model || ''
        localStorage.setItem('nexus-selected-model', next)
        return next
      })
    }).catch(() => setSavedModels([]))
  }, [])

  const toggleListening = () => {
    if (isMicListening) {
      if (recognitionRef.current) {
        recognitionRef.current.stop()
      }
      return
    }
    
    const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition
    if (!Recognition) {
      setSpeechError('Voice input is not supported in this browser.')
      return
    }
    
    setSpeechError('')
    const recognition = new Recognition()
    recognition.continuous = true
    recognition.interimResults = true
    recognition.lang = navigator.language || 'en-US'
    recognition.onresult = (event) => {
      let finalTranscript = ''
      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        const result = event.results[index]
        if (result.isFinal) finalTranscript += result[0].transcript
      }
      if (finalTranscript.trim()) {
        setInput(previous => `${previous}${previous.trim() ? ' ' : ''}${finalTranscript.trim()}`)
      }
    }
    recognition.onerror = (event) => {
      if (event.error !== 'aborted') setSpeechError(event.error === 'not-allowed' ? 'Microphone permission was denied.' : `Microphone error: ${event.error}`)
    }
    recognition.onend = () => setIsMicListening(false)
    recognitionRef.current = recognition
    recognition.start()
    setIsMicListening(true)
  }

  const toggleBackendListening = async () => {
    if (isBackendListening) {
      voiceStreamController?.abort()
      setVoiceStreamController(null)
      setIsBackendListening(false)
      return
    }
    
    try {
      setSpeechError('')
      setIsBackendListening(true)
      
      const controller = api.voiceStream(
        activeSessionId || 'default',
        (text) => {
          setInput(previous => `${previous}${previous.trim() ? ' ' : ''}${text.trim()}`)
        },
        (error) => {
          setSpeechError(error)
          setIsBackendListening(false)
        }
      )
      
      setVoiceStreamController(controller)
    } catch (error) {
      setSpeechError(error instanceof Error ? error.message : 'Failed to start voice stream')
      setIsBackendListening(false)
    }
  }

  const toggleSpeech = () => {
    const enabled = !speechEnabled
    setSpeechEnabled(enabled)
    localStorage.setItem('nexus-speech-enabled', String(enabled))
    if (!enabled && 'speechSynthesis' in window) window.speechSynthesis.cancel()
  }

  const enterVoiceMode = () => {
    setVoiceMode(true)
    // Auto-start backend continuous listening when entering voice mode
    if (!isBackendListening) window.setTimeout(toggleBackendListening, 100)
  }

  const exitVoiceMode = () => {
    voiceStreamController?.abort()
    setVoiceStreamController(null)
    setIsBackendListening(false)
    setVoiceMode(false)
  }

  function VoiceModeIndicator() {
    return (
      <div className="mb-2 flex items-center gap-2 rounded-lg border border-blue-500/30 bg-blue-500/5 px-3 py-2">
        <div className={`flex size-8 items-center justify-center rounded-full ${isBackendListening ? 'bg-blue-500 animate-pulse' : 'bg-muted-foreground/20'} transition-all`}>
          <Mic size={16} className={isBackendListening ? 'text-white' : 'text-muted-foreground'} />
        </div>
        <span className="flex-1 text-sm text-blue-700 dark:text-blue-300">
          {isBackendListening ? 'Listening...' : 'Voice Mode Active'}
        </span>
        <button
          type="button"
          onClick={exitVoiceMode}
          className="rounded px-2 py-1 text-[10px] font-medium text-blue-700 hover:bg-blue-500/10 dark:text-blue-300"
        >
          Exit
        </button>
      </div>
    )
  }

  const stopScreenShare = () => {
    screenStream?.getTracks().forEach(track => track.stop())
    setScreenStream(null)
  }

  const toggleScreenShare = async () => {
    if (screenStream) {
      stopScreenShare()
      return
    }
    if (!navigator.mediaDevices?.getDisplayMedia) {
      setScreenError('Screen sharing is not supported in this browser.')
      return
    }
    try {
      setScreenError('')
      const stream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: false })
      stream.getVideoTracks()[0]?.addEventListener('ended', () => setScreenStream(null))
      setScreenStream(stream)
    } catch (error) {
      if (error instanceof DOMException && error.name === 'NotAllowedError') setScreenError('Screen share was cancelled or permission was denied.')
      else setScreenError('Could not start screen sharing.')
    }
  }

  const runTask = async (task: QueuedTask) => {
    isSending.current = true
    try {
      let sid = activeSessionId
      if (!sid) sid = await createSession()
      await api.setPermissions(permissionMode, sid!)
      await api.setSandbox(sandboxTier, sandboxRoot)
      const selected = selectedModel ? savedModels.find(item => item.model === selectedModel) : undefined
      const selectedProvider = selected?.provider || providerForModel(selectedModel)
      if (selectedModel) {
        await api.setModel(selectedModel, sid!, selectedProvider, selected?.profile)
      }
      const attachmentNote = task.attachments.length ? `\n\nAttached files in the Nexus workspace:\n${task.attachments.map(item => `- ${item.path}`).join('\n')}` : ''
      const promptWithAttachments = `${task.prompt}${attachmentNote}`
      const priorHistory = (getActiveSession()?.messages || []).map(message => ({
        role: message.role,
        content: message.content,
      }))
      const history = [...priorHistory, { role: 'user' as const, content: promptWithAttachments }]
      addMessage(sid!, 'user', task.prompt)
      lastSavedContent.current = ''
      hasStreamed.current = true
      const modelOptions = selectedModel ? settingsForModel(selectedModel) : defaultModelPreferences
      await send(sid!, promptWithAttachments, {
        showThinking: modelOptions.thinking,
        reasoningEffort: modelOptions.effort,
        provider: selectedProvider,
        model: selected?.model || selectedModel,
        profile: selected?.profile,
        history,
      })
    } finally {
      isSending.current = false
      const [next, ...remaining] = taskQueueRef.current
      taskQueueRef.current = remaining
      setQueuedTasks(remaining)
      if (next) void runTask(next)
    }
  }

  const executeSlashCommand = async (value: string) => {
    const [rawCommand, ...args] = value.trim().split(/\s+/)
    const normalized = rawCommand.toLowerCase()
    const command = commandRegistry.find(item => [item.name, ...(item.aliases || [])]
      .some(name => name.toLowerCase() === normalized || name.toLowerCase() === normalized.slice(1)))
    if (!command) return false

    let sid = activeSessionId
    if (!sid) sid = await createSession()
    const commandArgs = args.length ? `${command.name} ${args.join(' ')}` : command.name
    addMessage(sid!, 'user', value.trim())
    try {
      const result = await api.command(command.name, commandArgs, sid!)
      const clientAction = String(result.data?.client_action || '')
      if (clientAction === 'stop') cancel()
      const commandSessionId = String(result.data?.session_id || '')
      if (commandSessionId) {
        if (command.name.replace(/^\//, '') === 'new') {
          // The shared command already created the server session. Refresh the
          // store so the GUI selects that exact session instead of creating a
          // second one locally.
          localStorage.setItem('nexus-active-session-id', commandSessionId)
          await loadSessionsFromServer()
        } else {
          setActiveSession(commandSessionId)
        }
      }
      const output = String(result.output || result.error || `${command.name}: completed`).trim()
      if (output) addMessage(sid!, 'assistant', output)
    } catch (error) {
      addMessage(sid!, 'assistant', `Command error: ${error instanceof Error ? error.message : String(error)}`)
    }
    return true
  }

  const selectSavedModel = async (item: SavedModel) => {
    setSelectedModel(item.model)
    localStorage.setItem('nexus-selected-model', item.model)
    setModelError('')
    setShowModelPicker(false)
    setModelSearch('')
    try {
      await api.setModel(item.model, activeSessionId || undefined, item.provider, item.profile)
    } catch (error) {
      setModelError(error instanceof Error ? error.message : 'Could not switch model.')
    }
  }

  const handleSend = () => {
    const trimmed = input.trim()
    if (!trimmed) return
    if (trimmed.startsWith('/') && commandRegistry.some(command => [command.name, ...(command.aliases || [])]
      .some(name => name.toLowerCase() === trimmed.split(/\s+/, 1)[0].toLowerCase()
        || `/${name.replace(/^\//, '')}`.toLowerCase() === trimmed.split(/\s+/, 1)[0].toLowerCase()))) {
      setInput('')
      setAttachments([])
      void executeSlashCommand(trimmed)
      return
    }
    const task = { id: crypto.randomUUID(), prompt: trimmed, attachments }
    setInput('')
    setAttachments([])
    if (isProcessing || isSending.current) {
      taskQueueRef.current = [...taskQueueRef.current, task]
      setQueuedTasks(taskQueueRef.current)
      return
    }
    void runTask(task)
  }

  const removeQueuedTask = (id: string) => {
    const remaining = taskQueueRef.current.filter(task => task.id !== id)
    taskQueueRef.current = remaining
    setQueuedTasks(remaining)
  }

  const steerQueuedTask = (task: QueuedTask) => {
    setInput(task.prompt)
    setAttachments(task.attachments)
    removeQueuedTask(task.id)
    window.setTimeout(() => textareaRef.current?.focus(), 0)
  }

  const saveQueuedTask = (id: string, prompt: string) => {
    if (!prompt.trim()) return
    const updated = taskQueueRef.current.map(task => task.id === id ? { ...task, prompt } : task)
    taskQueueRef.current = updated
    setQueuedTasks(updated)
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // Co-Pilot approve shortcuts take priority when an approval is pending.
    if (pendingApproval) {
      if (e.key === '1') { e.preventDefault(); respondApproval('yes'); return }
      if (e.key === '2') { e.preventDefault(); respondApproval('no'); return }
      if (e.key === '3') { e.preventDefault(); respondApproval('save'); return }
    }
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const showWelcome = !session || session.messages.length === 0

  return (
    <div className="flex-1 flex flex-col min-h-0 bg-background">
      {showWelcome && !isProcessing ? (
        <div className="flex-1 flex items-center justify-center px-4">
          <div className="text-center max-w-sm">
            <img src={mascot} alt="Nexus AI mascot" className="mx-auto mb-3 size-28 object-contain" />
            <h1 className="mb-1.5 text-lg font-bold tracking-tight text-foreground">NEXUS AI</h1>
            <p className="text-xs text-muted-foreground leading-relaxed">
              Autonomous agent framework. Start a conversation to search the web, write code, manage files, and more.
            </p>
            <div className="mt-6 flex flex-wrap justify-center gap-1.5">
              {suggestions.map(s => (
                <button
                  key={s}
                  onClick={() => { if (s === 'Run terminal') { onOpenTerminal?.(); return }; if (!activeSessionId) createSession(); setInput(s) }}
                  className="px-3 py-1.5 rounded-md bg-secondary text-xs text-muted-foreground hover:text-foreground hover:bg-secondary/80 transition border border-border/30"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto px-4 py-4">
          <div className="mx-auto" style={{ maxWidth: 'var(--composer-width)' }}>
            {session?.messages.map(msg => (
              <MessageEntry key={msg.id} msg={msg} />
            ))}

            {/* During a run, show only live, backend-emitted activity. Once it
                finishes, the same rows are stored with the assistant message above. */}
            {isProcessing && (
              <div className="mb-5" style={{ animation: 'nexus-fade-in 0.25s ease-out' }}>
                <LiveRunStatus events={events} />
                
                {(isThinking || thinkingDone) && thinkingText && (
                  <div className="mb-2 overflow-hidden rounded-lg border border-dashed border-border bg-secondary/25">
                    <div className="flex items-center gap-2 px-3 py-2 text-left text-[11px]">
                      <Cpu size={12} className={isThinking ? 'animate-pulse text-muted-foreground' : 'text-muted-foreground/70'} />
                      <span className="font-semibold text-foreground/80">Thought</span>
                      {isThinking && <Spinner size={11} className="text-muted-foreground/60" />}
                      {thinkingDone && <CheckCircle2 size={11} className="text-emerald-600/70" />}
                    </div>
                    <div className="border-t border-border/50 px-3 py-2 font-mono text-[11px] leading-relaxed text-muted-foreground/75">
                      {thinkingText.slice(0, 240)}{thinkingText.length > 240 ? '…' : ''}
                    </div>
                  </div>
                )}

                {/* Events during processing — live stream */}
                {isProcessing && events.length > 0 && (
                  <div className="mb-1"><EventActivity events={events} /></div>
                )}

                {/* Response text */}
                {isProcessing && content && (
                  <div className="mb-5 flex justify-start" data-testid="streaming-message-bubble">
                    <div className="flex max-w-[min(86%,760px)] flex-col items-start">
                      <div className="mb-1.5 px-1 text-xs font-medium text-muted-foreground">Nexus</div>
                      <div className="relative w-full rounded-lg border border-border/80 bg-card/70 px-4 pb-5 pt-1.5 text-foreground/90 shadow-sm">
                        <div className="text-sm leading-relaxed">
                          {extractCodeBlocks(content).map((part, i) =>
                            part.type === 'code'
                              ? <CodeBlock key={i} code={part.content} language={part.language} />
                              : <MarkdownText key={i} text={part.content} />
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )}

            {recoveredActivity && !isProcessing && events.length > 0 && (
              <div className="mb-5" data-testid="recovered-activity">
                <div className="mb-2 text-xs font-medium text-muted-foreground">Recovered activity</div>
                <EventActivity events={events} />
              </div>
            )}

            {replayGap && (
              <div className="mb-3 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-300" role="status" data-testid="replay-gap-warning">
                Some older activity is no longer retained. Showing events from sequence {replayGap.oldestSequence} onward; the missing range ends at {Math.max(0, replayGap.oldestSequence - 1)}.
              </div>
            )}

            {error && (
              <div role="alert" className="flex items-center gap-2 px-3 py-2 rounded-lg bg-destructive/10 border border-destructive/20 text-xs text-destructive/80 mb-3">
                {error}
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>
        </div>
      )}

      <div className="mx-auto w-full px-4 py-3" style={{ maxWidth: 'var(--composer-width)' }}>
        {pendingApproval ? (
          <ApprovalPanel
            tool={pendingApproval.tool}
            action={pendingApproval.action}
            onRespond={respondApproval}
          />
        ) : null}
        <HivePanel events={events} />
        <BackgroundTasksPanel events={events} onCancel={(runId) => cancel(runId)} />
        <QueuePanel tasks={queuedTasks} onSteer={steerQueuedTask} onRemove={removeQueuedTask} onSave={saveQueuedTask} />
        {voiceMode && <VoiceModeIndicator />}
        {screenStream && <div className="mb-2 flex items-center gap-2 rounded-lg border border-blue-500/30 bg-blue-500/5 px-2 py-1.5"><video ref={screenPreviewRef} autoPlay muted playsInline className="h-10 w-16 rounded object-cover" /><span className="min-w-0 flex-1 truncate text-[11px] font-medium text-blue-700 dark:text-blue-300">Screen sharing is active</span><button type="button" onClick={stopScreenShare} className="rounded px-2 py-1 text-[10px] font-medium text-blue-700 hover:bg-blue-500/10 dark:text-blue-300">Stop</button></div>}
        <div className="relative rounded-md border border-border bg-secondary/90 p-1 shadow-[0_8px_28px_rgba(15,23,42,0.06)] transition focus-within:border-ring/50 focus-within:ring-2 focus-within:ring-ring/10">
          {showSlashMenu && <div className="absolute bottom-full left-0 right-0 z-30 mb-1 overflow-hidden border border-border bg-background shadow-xl" role="listbox" aria-label="Nexus commands">{matchingCommands.length > 0 ? <>{matchingCommands.map(command => { const name = command.name.replace(/^\//, ''); return <button key={command.name} type="button" role="option" onMouseDown={event => event.preventDefault()} onClick={() => { setInput(`/${name} `); window.setTimeout(() => textareaRef.current?.focus(), 0) }} className="flex w-full items-center gap-3 border-b border-border/60 px-3 py-2 text-left hover:bg-secondary last:border-b-0"><code className="w-24 shrink-0 text-xs font-medium text-foreground">/{name}</code><span className="truncate text-[11px] text-muted-foreground">{command.description}</span></button>})}<div className="px-3 py-1.5 text-[10px] text-muted-foreground">Choose a command, then add any details.</div></> : <div className="px-3 py-2 text-xs text-muted-foreground">No Nexus command found.</div>}</div>}
          <textarea
            ref={textareaRef}
            value={input}
            onChange={e => { setInput(e.target.value); autoResize() }}
            onKeyDown={handleKeyDown}
            aria-label="Message NEXUS"
            data-testid="composer-input"
            placeholder={backendAvailable ? 'Type a message...' : 'Backend not connected — start with `python -m nexus --server`'}
            rows={1}
            className="block min-h-[40px] max-h-[160px] w-full resize-none rounded-none border-0 bg-transparent px-2 py-1 pr-11 text-sm leading-relaxed outline-none placeholder:text-muted-foreground/50 disabled:opacity-50"
            disabled={isUploading}
          />
          <div className="absolute right-2 top-2">
            {isProcessing ? (
              <button onClick={() => cancel()} aria-label="Stop response" title="Stop response" className="flex size-8 items-center justify-center rounded-sm bg-foreground text-background transition hover:opacity-80"><StopCircle size={15} /></button>
            ) : (
              <button onClick={handleSend} aria-label="Send message" title="Send message" disabled={!input.trim() || !backendAvailable} className="flex size-8 items-center justify-center rounded-sm bg-foreground text-background transition hover:opacity-80 disabled:opacity-15 disabled:hover:opacity-15"><Send size={14} /></button>
            )}
          </div>
          {(attachments.length > 0 || isUploading) && <div className="mx-2 mb-1 flex flex-wrap items-center gap-1.5">{attachments.map(item => <span key={item.path} className="flex max-w-52 items-center gap-1 rounded-md border border-border bg-background px-2 py-1 text-[11px] text-foreground"><span className="truncate">{item.name}</span><button type="button" onClick={() => setAttachments(current => current.filter(attachment => attachment.path !== item.path))} aria-label={`Remove ${item.name}`} className="text-muted-foreground hover:text-foreground"><XCircle size={13} /></button></span>)}{isUploading && <span className="flex items-center gap-1 text-[11px] text-muted-foreground"><Spinner size={12} /> Uploading…</span>}</div>}
          <div className="mt-0.5 flex items-center justify-between gap-2 border-t border-border/60 pt-0.5">
            <div className="order-2 flex min-w-0 items-center gap-0.5 overflow-visible">
            <label className="flex h-7 max-w-32 items-center gap-1 rounded-lg px-1 text-muted-foreground hover:bg-foreground/5" title="Choose permission mode">
              <ShieldCheck size={13} className="shrink-0" />
              <select
                value={permissionMode}
                onChange={event => { setPermissionMode(event.target.value); localStorage.setItem('nexus-permission-mode', event.target.value) }}
                aria-label="Permission mode"
                className="min-w-0 max-w-24 bg-transparent text-[11px] text-foreground outline-none"
              >
                {permissionOptions.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
              </select>
            </label>
            <label className="flex h-7 max-w-36 items-center gap-1 rounded-lg px-1 text-muted-foreground hover:bg-foreground/5" title="Choose sandbox">
              <ShieldCheck size={13} className="shrink-0" />
              <select
                value={sandboxTier}
                onChange={async event => {
                  const tier = event.target.value
                  setSandboxTier(tier)
                  localStorage.setItem('nexus-sandbox-tier', tier)
                  setSandboxError('')
                  try { await api.setSandbox(tier, sandboxRoot) } catch (error) { setSandboxError(error instanceof Error ? error.message : 'Could not change the sandbox.') }
                }}
                aria-label="Command sandbox"
                className="min-w-0 max-w-28 bg-transparent text-[11px] text-foreground outline-none"
              >
                {sandboxOptions.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
              </select>
            </label>
            {sandboxTier !== 'no_sandbox' && <button type="button" onClick={chooseSandboxFolder} title={sandboxRoot ? `Sandbox folder: ${sandboxRoot}` : 'Sandbox folder: Nexus workspace'} className="flex h-7 max-w-32 items-center gap-1 rounded-lg px-1 text-muted-foreground hover:bg-foreground/5 hover:text-foreground"><FolderOpen size={14} className="shrink-0" /><span className="max-w-20 truncate text-[11px]">{sandboxRoot ? sandboxRoot.replace(/\\/g, '/').split('/').filter(Boolean).pop() : 'Workspace'}</span></button>}
            {savedModels.length > 0 && (
              <div className="relative">
                <button type="button" data-testid="model-selector" onClick={() => {
                  const opening = !showModelPicker
                  setShowModelPicker(opening)
                }} aria-expanded={showModelPicker} title="Saved model, thinking and effort" className="flex h-7 max-w-36 items-center gap-1 rounded-lg px-1 text-muted-foreground hover:bg-foreground/5 hover:text-foreground">
                  <Cpu size={13} className="shrink-0" />
                  <span className="max-w-24 truncate text-[11px]">{savedModels.find(item => item.model === selectedModel)?.label || selectedModel || 'Models'}</span>
                  <ChevronDown size={12} />
                </button>
                {showModelPicker && (
                  <div className="absolute bottom-10 right-0 z-30 w-72 overflow-hidden rounded-lg border border-border bg-background shadow-xl">
                    <div className="border-b border-border p-2"><input autoFocus value={modelSearch} onChange={event => setModelSearch(event.target.value)} placeholder="Search saved models..." className="h-8 w-full rounded-md bg-secondary px-2 text-xs outline-none focus:ring-1 focus:ring-ring/30" /></div>
                    <div className="max-h-56 overflow-y-auto p-1">
                      {savedModels.filter(item => `${item.model} ${item.provider}`.toLowerCase().includes(modelSearch.toLowerCase())).map(item => {
                        const preferences = settingsForModel(item.model)
                        return <div key={item.model} className={`mb-1 rounded-md border ${selectedModel === item.model ? 'border-border bg-secondary/70' : 'border-transparent bg-secondary/35'}`}>
                          <button type="button" data-testid={`saved-model-${item.provider}-${item.model}`} onClick={() => void selectSavedModel(item)} className={`flex w-full items-center justify-between gap-3 rounded-md px-2 py-2 text-left text-xs ${selectedModel === item.model ? 'text-foreground' : 'text-muted-foreground hover:bg-secondary/70 hover:text-foreground'}`}>
                            <span className="min-w-0 truncate">{item.label}</span>{selectedModel === item.model && <Check size={13} className="shrink-0" />}
                          </button>
                          <div className="border-t border-border/60 px-2 py-2">
                            <div className="flex items-center justify-between gap-3"><p className="text-[11px] font-medium text-foreground">Thinking</p><button type="button" onClick={() => updateModelPreferences(item.model, { thinking: !preferences.thinking })} aria-label={`Toggle thinking for ${item.model}`} aria-pressed={preferences.thinking} className={`relative h-5 w-9 rounded-full transition ${preferences.thinking ? 'bg-blue-500' : 'bg-muted'}`}><span className={`absolute top-0.5 size-4 rounded-full bg-white transition ${preferences.thinking ? 'left-4.5' : 'left-0.5'}`} /></button></div>
                            <label className="mt-2 block text-[10px] font-medium uppercase tracking-wide text-muted-foreground">Effort<select value={preferences.effort} onChange={event => updateModelPreferences(item.model, { effort: event.target.value })} className="mt-1 h-8 w-full rounded-md border border-border bg-background px-2 text-xs normal-case text-foreground outline-none"><option value="minimal">Minimal</option><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option><option value="extra_high">Extra high</option><option value="max">Max</option><option value="ultra">Ultra</option></select></label>
                          </div>
                        </div>
                      })}
                    </div>
                  </div>
                )}
              </div>
            )}
            </div>
            <div className="order-1 flex shrink-0 items-center gap-0.5">
            <div>
              <button type="button" onClick={() => fileInputRef.current?.click()} aria-label="Upload anything" title="Upload anything" className="flex size-8 items-center justify-center rounded-lg text-muted-foreground transition hover:bg-foreground/5 hover:text-foreground"><Plus size={17} /></button>
              <input ref={fileInputRef} type="file" multiple className="hidden" onChange={event => void uploadAttachments(event.target.files)} />
            </div>
            <button
              type="button"
              onClick={voiceMode ? exitVoiceMode : enterVoiceMode}
              aria-label={voiceMode ? 'Turn off Voice Mode' : 'Turn on Voice Mode'}
              aria-pressed={voiceMode}
              title={voiceMode ? 'Voice Mode on — click to turn off' : 'Turn on Voice Mode'}
              className={`flex size-8 items-center justify-center rounded-lg transition ${voiceMode ? 'bg-blue-500 text-white hover:bg-blue-600' : 'text-muted-foreground hover:bg-foreground/5 hover:text-foreground'}`}
            >
              <Headphones size={16} />
            </button>
            <button
              type="button"
              onClick={toggleScreenShare}
              aria-label={screenStream ? 'Stop screen sharing' : 'Share screen'}
              aria-pressed={Boolean(screenStream)}
              title={screenStream ? 'Screen sharing on — click to stop' : 'Share your entire screen, a window, or a browser tab'}
              className={`flex size-8 items-center justify-center rounded-lg transition ${screenStream ? 'bg-blue-500 text-white hover:bg-blue-600' : 'text-muted-foreground hover:bg-foreground/5 hover:text-foreground'}`}
            >
              {screenStream ? <MonitorOff size={16} /> : <MonitorUp size={16} />}
            </button>
            <button
              type="button"
              onClick={toggleSpeech}
              aria-label={speechEnabled ? 'Turn off Nexus voice' : 'Turn on Nexus voice'}
              aria-pressed={speechEnabled}
              title={speechEnabled ? 'Nexus voice on — click to turn off' : 'Nexus voice off — click to turn on'}
              className={`flex size-8 items-center justify-center rounded-lg transition ${speechEnabled ? 'bg-blue-500 text-white hover:bg-blue-600' : 'text-muted-foreground hover:bg-foreground/5 hover:text-foreground'}`}
            >
              {speechEnabled ? <Volume2 size={16} /> : <VolumeX size={16} />}
            </button>
            <button
              type="button"
              onClick={toggleListening}
              disabled={isProcessing}
              aria-label={isMicListening ? 'Stop voice input' : 'Start voice input'}
              aria-pressed={isMicListening}
              title={isMicListening ? 'Listening — click to stop' : 'Speak to type'}
              className={`flex size-8 items-center justify-center rounded-lg transition disabled:opacity-30 ${isMicListening ? 'bg-red-500 text-white animate-pulse hover:bg-red-600' : 'text-muted-foreground hover:bg-foreground/5 hover:text-foreground'}`}
            >
              {isMicListening ? <MicOff size={16} /> : <Mic size={16} />}
            </button>
            </div>
          </div>
        </div>
        {speechError && <p role="status" className="mt-1 text-[10px] text-destructive/75">{speechError}</p>}
        {screenError && <p role="status" className="mt-1 text-[10px] text-destructive/75">{screenError}</p>}
        {sandboxError && <p role="status" className="mt-1 text-[10px] text-destructive/75">{sandboxError}</p>}
        {modelError && <p role="alert" className="mt-1 text-[10px] text-destructive/75">{modelError}</p>}
        {attachmentError && <p role="status" className="mt-1 text-[10px] text-destructive/75">{attachmentError}</p>}
      </div>
    </div>
  )
}
