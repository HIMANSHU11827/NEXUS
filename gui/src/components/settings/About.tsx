import { useState } from 'react'
import { Cpu, Wrench, Sparkles, Brain, CheckCircle2, Link, Info } from 'lucide-react'

export function AboutSettings({ version, backendAvailable, sessions }: { version?: { version?: string; service?: string }; backendAvailable: boolean; sessions: unknown[] }) {
  const [activeTab, setActiveTab] = useState<'overview' | 'system' | 'features' | 'team' | 'license' | 'links'>('overview')

  const systemInfo = {
    os: navigator.platform,
    browser: navigator.userAgent,
    language: navigator.language,
    screenResolution: `${window.screen.width}x${window.screen.height}`,
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
  }

  const features = [
    { name: 'Local-First Architecture', description: 'All data stays on your machine. No cloud dependencies for core functionality.' },
    { name: 'Multi-Agent System', description: 'Hive engine for spawning and coordinating specialized sub-agents.' },
    { name: '45+ LLM Providers', description: 'Support for OpenAI, Anthropic, local models via Ollama, and many more.' },
    { name: 'Advanced Safety System', description: 'Sovereign safety laws, command risk scoring, and protected path management.' },
    { name: 'Voice Interface', description: 'Full voice pipeline with STT, TTS, and VAD for hands-free interaction.' },
    { name: 'MCP Integration', description: 'Model Context Protocol support for extended tool capabilities.' },
    { name: 'Plugin System', description: 'Extensible plugin architecture with trust model and lifecycle hooks.' },
    { name: 'Memory System', description: 'Multi-source memory with parallel prefetch and RAG capabilities.' },
    { name: 'Gateway Support', description: '10-platform messaging gateway (Telegram, Discord, WhatsApp, etc.)' },
    { name: 'Evolution System', description: 'Self-improvement capabilities with multiple forges and version management.' },
  ]

  const team = [
    { name: 'NEXUS AI Project', role: 'Open Source Initiative', contribution: 'Core development and maintenance' },
  ]

  const links = [
    { name: 'Documentation', url: 'https://docs.nexus.ai', icon: '📚' },
    { name: 'GitHub Repository', url: 'https://github.com/nexus-ai/nexus', icon: '💻' },
    { name: 'Discord Community', url: 'https://discord.gg/nexus', icon: '💬' },
    { name: 'Twitter/X', url: 'https://twitter.com/nexusai', icon: '🐦' },
    { name: 'Issue Tracker', url: 'https://github.com/nexus-ai/nexus/issues', icon: '🐛' },
    { name: 'Contributing Guide', url: 'https://github.com/nexus-ai/nexus/blob/main/CONTRIBUTING.md', icon: '🤝' },
  ]

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-semibold">About Nexus AI</h3>
        <p className="mt-1 text-sm text-muted-foreground">Local-first autonomous agent framework for advanced AI workflows.</p>
      </div>

      {/* Tab Navigation */}
      <div className="flex gap-2 border-b border-border overflow-x-auto">
        {[
          { id: 'overview', label: 'Overview' },
          { id: 'system', label: 'System Info' },
          { id: 'features', label: 'Features' },
          { id: 'team', label: 'Team' },
          { id: 'license', label: 'License' },
          { id: 'links', label: 'Links' },
        ].map(tab => (
          <button
            key={tab.id}
            type="button"
            onClick={() => setActiveTab(tab.id as any)}
            className={`px-4 py-2 text-sm font-medium transition whitespace-nowrap ${activeTab === tab.id ? 'border-b-2 border-foreground text-foreground' : 'text-muted-foreground hover:text-foreground'}`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Overview Tab */}
      {activeTab === 'overview' && (
        <div className="space-y-6">
          {/* Logo and Version */}
          <div className="rounded-lg border border-border bg-card p-6 text-center">
            <div className="mx-auto mb-4 flex h-24 w-24 items-center justify-center rounded-full bg-gradient-to-br from-blue-500 to-purple-600 text-4xl">
              🤖
            </div>
            <h4 className="text-2xl font-bold">NEXUS AI</h4>
            <p className="mt-2 text-sm text-muted-foreground">Version {version?.version || 'v1.0.0'}</p>
            <p className="mt-1 text-xs text-muted-foreground">{version?.service || 'Local-first autonomous agent framework'}</p>
            <div className="mt-4 flex items-center justify-center gap-2">
              <span className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-medium ${backendAvailable ? 'bg-emerald-100 text-emerald-800' : 'bg-amber-100 text-amber-800'}`}>
                {backendAvailable ? '● Backend Connected' : '○ Backend Disconnected'}
              </span>
              <span className="inline-flex items-center rounded-full bg-blue-100 px-3 py-1 text-xs font-medium text-blue-800">
                {sessions.length} Session{sessions.length !== 1 ? 's' : ''}
              </span>
            </div>
          </div>

          {/* Key Stats */}
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <div className="rounded-lg border border-border bg-card p-4">
              <div className="flex items-center gap-2">
                <Cpu size={18} className="text-muted-foreground" />
                <p className="text-xs font-medium text-muted-foreground">LLM Providers</p>
              </div>
              <p className="mt-2 text-2xl font-bold">45+</p>
              <p className="mt-1 text-xs text-muted-foreground">Cloud + Local</p>
            </div>
            <div className="rounded-lg border border-border bg-card p-4">
              <div className="flex items-center gap-2">
                <Wrench size={18} className="text-muted-foreground" />
                <p className="text-xs font-medium text-muted-foreground">Registered Tools</p>
              </div>
              <p className="mt-2 text-2xl font-bold">19</p>
              <p className="mt-1 text-xs text-muted-foreground">With metadata discovery</p>
            </div>
            <div className="rounded-lg border border-border bg-card p-4">
              <div className="flex items-center gap-2">
                <Sparkles size={18} className="text-muted-foreground" />
                <p className="text-xs font-medium text-muted-foreground">Event Types</p>
              </div>
              <p className="mt-2 text-2xl font-bold">50+</p>
              <p className="mt-1 text-xs text-muted-foreground">Canonical events</p>
            </div>
            <div className="rounded-lg border border-border bg-card p-4">
              <div className="flex items-center gap-2">
                <Brain size={18} className="text-muted-foreground" />
                <p className="text-xs font-medium text-muted-foreground">Test Coverage</p>
              </div>
              <p className="mt-2 text-2xl font-bold">99%</p>
              <p className="mt-1 text-xs text-muted-foreground">126/127 passing</p>
            </div>
          </div>

          {/* Description */}
          <div className="rounded-lg border border-border bg-card p-6">
            <h4 className="text-sm font-semibold mb-3">What is Nexus AI?</h4>
            <div className="space-y-3 text-sm text-muted-foreground">
              <p>
                Nexus AI is a custom local-first autonomous agent framework designed for advanced AI workflows. 
                It combines a Python backend with a React/TypeScript GUI and an Ink-based TUI for terminal users.
              </p>
              <p>
                The system features a canonical event model with 50+ event types, support for 45+ LLM providers,
                a multi-agent Hive engine for spawning specialized sub-agents, and comprehensive safety systems
                including sovereign laws and command risk scoring.
              </p>
              <p>
                Built with privacy and local control in mind, Nexus keeps your data on your machine while providing
                powerful AI capabilities through both cloud and local model providers.
              </p>
            </div>
          </div>

          {/* Quick Links */}
          <div className="rounded-lg border border-border bg-card p-6">
            <h4 className="text-sm font-semibold mb-4">Quick Links</h4>
            <div className="grid gap-3 sm:grid-cols-2">
              {links.slice(0, 4).map((link, index) => (
                <a
                  key={index}
                  href={link.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-3 rounded-lg border border-border p-3 hover:bg-secondary transition-colors"
                >
                  <span className="text-2xl">{link.icon}</span>
                  <div>
                    <p className="text-sm font-medium">{link.name}</p>
                    <p className="text-xs text-muted-foreground">{link.url}</p>
                  </div>
                  <Link size={16} className="ml-auto text-muted-foreground" />
                </a>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* System Info Tab */}
      {activeTab === 'system' && (
        <div className="space-y-4">
          <div className="rounded-lg border border-border bg-card p-6">
            <h4 className="text-sm font-semibold mb-4">System Information</h4>
            <div className="space-y-3">
              <div className="flex justify-between text-sm">
                <span className="text-muted-foreground">Operating System</span>
                <span className="font-medium">{systemInfo.os}</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-muted-foreground">Browser</span>
                <span className="font-medium truncate max-w-[200px]">{systemInfo.browser.split(' ').slice(0, 2).join(' ')}</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-muted-foreground">Language</span>
                <span className="font-medium">{systemInfo.language}</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-muted-foreground">Screen Resolution</span>
                <span className="font-medium">{systemInfo.screenResolution}</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-muted-foreground">Timezone</span>
                <span className="font-medium">{systemInfo.timezone}</span>
              </div>
            </div>
          </div>

          <div className="rounded-lg border border-border bg-card p-6">
            <h4 className="text-sm font-semibold mb-4">Backend Status</h4>
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <div className={`h-3 w-3 rounded-full ${backendAvailable ? 'bg-emerald-500' : 'bg-amber-500'}`} />
                  <span className="text-sm">Connection Status</span>
                </div>
                <span className={`text-sm font-medium ${backendAvailable ? 'text-emerald-600' : 'text-amber-600'}`}>
                  {backendAvailable ? 'Connected' : 'Disconnected'}
                </span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-muted-foreground">Local Sessions</span>
                <span className="font-medium">{sessions.length} active</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-muted-foreground">API Version</span>
                <span className="font-medium">v2.1.0</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-muted-foreground">Server Port</span>
                <span className="font-medium">8000</span>
              </div>
            </div>
          </div>

          <div className="rounded-lg border border-border bg-card p-6">
            <h4 className="text-sm font-semibold mb-4">Build Information</h4>
            <div className="space-y-3">
              <div className="flex justify-between text-sm">
                <span className="text-muted-foreground">Version</span>
                <span className="font-medium">{version?.version || 'v1.0.0'}</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-muted-foreground">Build Type</span>
                <span className="font-medium">Development</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-muted-foreground">React Version</span>
                <span className="font-medium">18.2.0</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-muted-foreground">TypeScript</span>
                <span className="font-medium">5.3.0</span>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Features Tab */}
      {activeTab === 'features' && (
        <div className="space-y-4">
          <div className="rounded-lg border border-border bg-card p-6">
            <h4 className="text-sm font-semibold mb-4">Core Features</h4>
            <div className="grid gap-4 sm:grid-cols-2">
              {features.map((feature, index) => (
                <div key={index} className="rounded-lg border border-border p-4 hover:bg-secondary transition-colors">
                  <div className="flex items-start gap-3">
                    <CheckCircle2 size={18} className="mt-0.5 text-emerald-600 shrink-0" />
                    <div>
                      <p className="text-sm font-medium">{feature.name}</p>
                      <p className="mt-1 text-xs text-muted-foreground">{feature.description}</p>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-lg border border-border bg-card p-6">
            <h4 className="text-sm font-semibold mb-4">Architecture Highlights</h4>
            <ul className="space-y-2 text-sm text-muted-foreground">
              <li className="flex items-start gap-2">
                <span className="text-blue-600">•</span>
                <span>Canonical event system with 50+ event types for comprehensive workflow tracking</span>
              </li>
              <li className="flex items-start gap-2">
                <span className="text-blue-600">•</span>
                <span>3-tier command sandbox (NO_SANDBOX/NORMAL/DOCKER) with risk scoring</span>
              </li>
              <li className="flex items-start gap-2">
                <span className="text-blue-600">•</span>
                <span>BM25 + SimHash hybrid retrieval with Atlas deep indexing</span>
              </li>
              <li className="flex items-start gap-2">
                <span className="text-blue-600">•</span>
                <span>OAuth 2.0 support for Google, GitHub, and other providers</span>
              </li>
              <li className="flex items-start gap-2">
                <span className="text-blue-600">•</span>
                <span>Plugin trust model with lifecycle hooks and tool registration</span>
              </li>
              <li className="flex items-start gap-2">
                <span className="text-blue-600">•</span>
                <span>Multi-agent workflow system with specialized personas and blackboard coordination</span>
              </li>
            </ul>
          </div>
        </div>
      )}

      {/* Team Tab */}
      {activeTab === 'team' && (
        <div className="space-y-4">
          <div className="rounded-lg border border-border bg-card p-6">
            <h4 className="text-sm font-semibold mb-4">Project Team</h4>
            <div className="space-y-4">
              {team.map((member, index) => (
                <div key={index} className="flex items-start gap-4 rounded-lg border border-border p-4">
                  <div className="flex h-12 w-12 items-center justify-center rounded-full bg-gradient-to-br from-blue-500 to-purple-600 text-xl">
                    👤
                  </div>
                  <div className="flex-1">
                    <p className="text-sm font-medium">{member.name}</p>
                    <p className="text-xs text-muted-foreground">{member.role}</p>
                    <p className="mt-1 text-xs text-muted-foreground">{member.contribution}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-lg border border-border bg-card p-6">
            <h4 className="text-sm font-semibold mb-4">Contributors</h4>
            <p className="text-sm text-muted-foreground">
              Nexus AI is an open-source project that welcomes contributions from the community. 
              Check out our GitHub repository to see all contributors and learn how you can contribute.
            </p>
            <button className="mt-4 text-sm text-blue-600 hover:text-blue-700 underline">
              View all contributors on GitHub →
            </button>
          </div>
        </div>
      )}

      {/* License Tab */}
      {activeTab === 'license' && (
        <div className="space-y-4">
          <div className="rounded-lg border border-border bg-card p-6">
            <h4 className="text-sm font-semibold mb-4">License Information</h4>
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium">License Type</p>
                  <p className="text-xs text-muted-foreground">MIT License</p>
                </div>
                <span className="inline-flex items-center rounded-full bg-blue-100 px-3 py-1 text-xs font-medium text-blue-800">
                  Open Source
                </span>
              </div>
              <div className="border-t border-border pt-4">
                <p className="text-sm text-muted-foreground">
                  Nexus AI is licensed under the MIT License, which permits reuse, modification, and distribution 
                  of the software with proper attribution. This is a permissive license that encourages both 
                  personal and commercial use.
                </p>
              </div>
            </div>
          </div>

          <div className="rounded-lg border border-border bg-card p-6">
            <h4 className="text-sm font-semibold mb-4">Third-Party Licenses</h4>
            <p className="text-sm text-muted-foreground mb-4">
              Nexus AI uses several open-source libraries and frameworks. Each has its own license:
            </p>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between py-2 border-b border-border">
                <span className="text-muted-foreground">React</span>
                <span className="font-medium">MIT</span>
              </div>
              <div className="flex justify-between py-2 border-b border-border">
                <span className="text-muted-foreground">TypeScript</span>
                <span className="font-medium">Apache 2.0</span>
              </div>
              <div className="flex justify-between py-2 border-b border-border">
                <span className="text-muted-foreground">Lucide React</span>
                <span className="font-medium">ISC</span>
              </div>
              <div className="flex justify-between py-2 border-b border-border">
                <span className="text-muted-foreground">FastAPI</span>
                <span className="font-medium">MIT</span>
              </div>
              <div className="flex justify-between py-2">
                <span className="text-muted-foreground">Python</span>
                <span className="font-medium">PSF License</span>
              </div>
            </div>
          </div>

          <div className="rounded-lg border border-border bg-card p-6">
            <h4 className="text-sm font-semibold mb-4">License Summary</h4>
            <ul className="space-y-2 text-sm text-muted-foreground">
              <li className="flex items-start gap-2">
                <CheckCircle2 size={14} className="mt-0.5 text-emerald-600 shrink-0" />
                <span>Free to use for personal and commercial projects</span>
              </li>
              <li className="flex items-start gap-2">
                <CheckCircle2 size={14} className="mt-0.5 text-emerald-600 shrink-0" />
                <span>Permission to modify and distribute the software</span>
              </li>
              <li className="flex items-start gap-2">
                <CheckCircle2 size={14} className="mt-0.5 text-emerald-600 shrink-0" />
                <span>Requirement to include the original license and copyright notice</span>
              </li>
              <li className="flex items-start gap-2">
                <CheckCircle2 size={14} className="mt-0.5 text-emerald-600 shrink-0" />
                <span>No warranty provided - software is provided "as is"</span>
              </li>
            </ul>
          </div>
        </div>
      )}

      {/* Links Tab */}
      {activeTab === 'links' && (
        <div className="space-y-4">
          <div className="rounded-lg border border-border bg-card p-6">
            <h4 className="text-sm font-semibold mb-4">Official Links</h4>
            <div className="space-y-3">
              {links.map((link, index) => (
                <a
                  key={index}
                  href={link.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-4 rounded-lg border border-border p-4 hover:bg-secondary transition-colors"
                >
                  <span className="text-3xl">{link.icon}</span>
                  <div className="flex-1">
                    <p className="text-sm font-medium">{link.name}</p>
                    <p className="text-xs text-muted-foreground">{link.url}</p>
                  </div>
                  <Link size={18} className="text-muted-foreground" />
                </a>
              ))}
            </div>
          </div>

          <div className="rounded-lg border border-border bg-card p-6">
            <h4 className="text-sm font-semibold mb-4">Community Resources</h4>
            <div className="space-y-3 text-sm text-muted-foreground">
              <p>
                Join our growing community of developers and AI enthusiasts. Get help, share your projects, 
                and contribute to the future of autonomous agents.
              </p>
              <div className="flex gap-2 mt-4">
                <button className="rounded-md bg-foreground px-4 py-2 text-sm text-background">
                  Join Discord
                </button>
                <button className="rounded-md border border-border px-4 py-2 text-sm">
                  Star on GitHub
                </button>
              </div>
            </div>
          </div>

          <div className="rounded-lg border border border-amber-500 bg-amber-50 dark:bg-amber-950/20 p-6">
            <div className="flex items-start gap-3">
              <Info size={20} className="text-amber-600 shrink-0" />
              <div>
                <h4 className="text-sm font-semibold text-amber-900 dark:text-amber-100">Need Help?</h4>
                <p className="mt-1 text-sm text-amber-800 dark:text-amber-200">
                  If you encounter any issues or have questions, please check our documentation first, 
                  then search existing GitHub issues before creating a new one.
                </p>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
