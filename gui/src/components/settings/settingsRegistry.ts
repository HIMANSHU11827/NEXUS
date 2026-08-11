import type { LucideIcon } from 'lucide-react'
import {
  Bell, Brain, Clock3, Cpu, Info, Keyboard, Mic, Monitor, Network, Palette, Puzzle,
  Radio, ReceiptText, Settings2, ShieldCheck, SlidersHorizontal, Sparkles, UsersRound, Wrench,
} from 'lucide-react'

export type SettingsSectionId =
  | 'appearance' | 'workspace' | 'safety' | 'notifications' | 'shortcuts' | 'voice' | 'providers'
  | 'memory' | 'evolution' | 'config' | 'skills' | 'tools' | 'plugins' | 'mcp' | 'hive'
  | 'gateway' | 'cron' | 'billing' | 'about'

export type SettingsSection = {
  id: SettingsSectionId
  label: string
  description: string
  purpose: string
  searchTerms: string[]
  icon: LucideIcon
  group: string
}

/** The source-of-truth map for Settings navigation and Settings search. */
export const settingsSections: SettingsSection[] = [
  { id: 'appearance', label: 'Theme & appearance', description: 'Personalize the workspace', purpose: 'Visual preferences', searchTerms: ['theme', 'dark mode', 'light', 'color', 'appearance'], icon: Palette, group: 'Personal' },
  { id: 'notifications', label: 'Notifications', description: 'Alerts and sound', purpose: 'Event alerts', searchTerms: ['browser', 'alerts', 'sound', 'volume', 'task completion', 'error alerts'], icon: Bell, group: 'Personal' },
  { id: 'shortcuts', label: 'Keyboard shortcuts', description: 'Quick actions', purpose: 'Command reference', searchTerms: ['keyboard', 'hotkeys', 'ctrl', 'command palette', 'chat'], icon: Keyboard, group: 'Personal' },
  { id: 'workspace', label: 'Workspace', description: 'Files, indexing, instructions', purpose: 'Project context', searchTerms: ['root', 'directory', 'index', 'instructions', 'files'], icon: Monitor, group: 'Workspace' },
  { id: 'memory', label: 'Memory & context', description: 'Sessions and retrieval', purpose: 'Recall and retrieval', searchTerms: ['memory', 'retrieval', 'search', 'sessions', 'export', 'import'], icon: Brain, group: 'Workspace' },
  { id: 'safety', label: 'Safety', description: 'Permissions and protected paths', purpose: 'Policy guardrails', searchTerms: ['permissions', 'sandbox', 'protected paths', 'diagnostics', 'policies'], icon: ShieldCheck, group: 'Workspace' },
  { id: 'providers', label: 'Providers', description: 'Models and connections', purpose: 'Model connections', searchTerms: ['provider', 'api key', 'oauth', 'endpoint', 'model', 'health'], icon: Cpu, group: 'Runtime' },
  { id: 'voice', label: 'Voice', description: 'Speech and transcription', purpose: 'Speech runtime', searchTerms: ['voice', 'speech', 'microphone', 'transcription', 'tts', 'stt'], icon: Mic, group: 'Runtime' },
  { id: 'config', label: 'Configuration', description: 'Runtime and session defaults', purpose: 'Runtime defaults', searchTerms: ['model', 'provider', 'agent', 'goal', 'sandbox', 'tokens', 'temperature', 'prompt'], icon: Settings2, group: 'Runtime' },
  { id: 'evolution', label: 'Evolution', description: 'Self-improvement status', purpose: 'Self-improvement', searchTerms: ['evolution', 'forge', 'lifecycle', 'self improvement'], icon: Sparkles, group: 'Runtime' },
  { id: 'skills', label: 'Skills', description: 'Installed capabilities', purpose: 'Capability library', searchTerms: ['skills', 'capabilities', 'installed', 'categories'], icon: Wrench, group: 'Extensions' },
  { id: 'tools', label: 'Tools', description: 'Tool registry', purpose: 'Execution capabilities', searchTerms: ['tools', 'registry', 'file', 'code', 'search', 'read only'], icon: SlidersHorizontal, group: 'Extensions' },
  { id: 'plugins', label: 'Plugins', description: 'Plugin lifecycle', purpose: 'Extension lifecycle', searchTerms: ['plugins', 'marketplace', 'downloads', 'trusted'], icon: Puzzle, group: 'Extensions' },
  { id: 'mcp', label: 'MCP', description: 'External tool servers', purpose: 'External tool servers', searchTerms: ['mcp', 'server', 'resources', 'protocol', 'external tools'], icon: Network, group: 'Extensions' },
  { id: 'hive', label: 'Hive', description: 'Multi-agent coordination', purpose: 'Agent orchestration', searchTerms: ['hive', 'agents', 'personas', 'spawn', 'delegation', 'concurrency'], icon: UsersRound, group: 'Automation' },
  { id: 'gateway', label: 'Gateway', description: 'Messaging integrations', purpose: 'Messaging connections', searchTerms: ['gateway', 'telegram', 'discord', 'whatsapp', 'platforms', 'messages', 'message history', 'delivery logs'], icon: Radio, group: 'Automation' },
  { id: 'cron', label: 'Scheduled jobs', description: 'Recurring work', purpose: 'Recurring automation', searchTerms: ['scheduled', 'jobs', 'cron', 'recurring', 'history'], icon: Clock3, group: 'Automation' },
  { id: 'billing', label: 'Billing', description: 'Usage and limits', purpose: 'Usage visibility', searchTerms: ['billing', 'usage', 'limits', 'plan', 'cost'], icon: ReceiptText, group: 'System' },
  { id: 'about', label: 'About', description: 'Version and diagnostics', purpose: 'System identity', searchTerms: ['version', 'diagnostics', 'features', 'license', 'links'], icon: Info, group: 'System' },
]
