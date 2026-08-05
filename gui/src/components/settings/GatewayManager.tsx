import { useState } from 'react'
import { Globe, MessageSquare, Zap, Send, Network, Plus, CheckCircle2, CircleAlert, RefreshCw } from 'lucide-react'
import { type InventoryItem } from '../../lib/api'
import { labelFor, Description } from './utils'

export function GatewayManager({ items, pending, onToggle }: { items: InventoryItem[]; pending: string; onToggle: (name: string, enabled: boolean) => void }) {
  const [activeTab, setActiveTab] = useState<'overview' | 'platforms' | 'messages' | 'settings'>('overview')

  // Mock statistics for demonstration
  const stats = {
    totalPlatforms: items.length,
    activePlatforms: items.filter(i => i.enabled).length,
    totalMessages: Math.floor(Math.random() * 5000),
    activeConnections: items.filter(i => i.available && i.enabled).length,
  }

  const platforms = [
    { id: 'telegram', name: 'Telegram', icon: '📱', description: 'Connect to Telegram for bot interactions', users: '1.2K', status: 'active' },
    { id: 'discord', name: 'Discord', icon: '🎮', description: 'Integrate with Discord servers and channels', users: '856', status: 'active' },
    { id: 'whatsapp', name: 'WhatsApp', icon: '💬', description: 'WhatsApp Business API integration', users: '432', status: 'inactive' },
    { id: 'slack', name: 'Slack', icon: '💼', description: 'Enterprise messaging and collaboration', users: '234', status: 'active' },
    { id: 'signal', name: 'Signal', icon: '🔒', description: 'Encrypted messaging platform', users: '89', status: 'inactive' },
  ]

  const recentMessages = [
    { platform: 'Telegram', user: 'john_doe', message: 'Help me debug this code', time: '2 min ago', status: 'processed' },
    { platform: 'Discord', user: 'dev_team', message: 'Deploy to production?', time: '15 min ago', status: 'pending' },
    { platform: 'Slack', user: 'sarah_k', message: 'Review my PR', time: '1 hour ago', status: 'processed' },
    { platform: 'Telegram', user: 'alex_m', message: 'What is the weather?', time: '2 hours ago', status: 'processed' },
    { platform: 'WhatsApp', user: '+1234567890', message: 'Schedule meeting', time: '3 hours ago', status: 'failed' },
  ]

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-semibold">Messaging Gateway</h3>
        <p className="mt-1 text-sm text-muted-foreground">Connect Nexus AI to multiple messaging platforms for seamless communication.</p>
      </div>

      {/* Tab Navigation */}
      <div className="flex gap-2 border-b border-border">
        {[
          { id: 'overview', label: 'Overview' },
          { id: 'platforms', label: 'Platforms' },
          { id: 'messages', label: 'Messages' },
          { id: 'settings', label: 'Settings' },
        ].map(tab => (
          <button
            key={tab.id}
            type="button"
            onClick={() => setActiveTab(tab.id as any)}
            className={`px-4 py-2 text-sm font-medium transition ${activeTab === tab.id ? 'border-b-2 border-foreground text-foreground' : 'text-muted-foreground hover:text-foreground'}`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Overview Tab */}
      {activeTab === 'overview' && (
        <div className="space-y-6">
          {/* Statistics Cards */}
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <div className="rounded-lg border border-border bg-card p-4">
              <div className="flex items-center gap-2">
                <Globe size={18} className="text-muted-foreground" />
                <p className="text-xs font-medium text-muted-foreground">Total Platforms</p>
              </div>
              <p className="mt-2 text-2xl font-bold">{stats.totalPlatforms}</p>
              <p className="mt-1 text-xs text-muted-foreground">{stats.activePlatforms} active</p>
            </div>
            <div className="rounded-lg border border-border bg-card p-4">
              <div className="flex items-center gap-2">
                <MessageSquare size={18} className="text-muted-foreground" />
                <p className="text-xs font-medium text-muted-foreground">Total Messages</p>
              </div>
              <p className="mt-2 text-2xl font-bold">{stats.totalMessages}</p>
              <p className="mt-1 text-xs text-muted-foreground">This month</p>
            </div>
            <div className="rounded-lg border border-border bg-card p-4">
              <div className="flex items-center gap-2">
                <Zap size={18} className="text-muted-foreground" />
                <p className="text-xs font-medium text-muted-foreground">Active Connections</p>
              </div>
              <p className="mt-2 text-2xl font-bold">{stats.activeConnections}</p>
              <p className="mt-1 text-xs text-muted-foreground">Online now</p>
            </div>
            <div className="rounded-lg border border-border bg-card p-4">
              <div className="flex items-center gap-2">
                <Send size={18} className="text-muted-foreground" />
                <p className="text-xs font-medium text-muted-foreground">Response Rate</p>
              </div>
              <p className="mt-2 text-2xl font-bold">98.5%</p>
              <p className="mt-1 text-xs text-muted-foreground">Success rate</p>
            </div>
          </div>

          {/* Active Platforms */}
          <div className="rounded-lg border border-border bg-card p-6">
            <div className="flex items-center justify-between mb-4">
              <h4 className="text-sm font-semibold">Connected Platforms</h4>
              <button
                onClick={() => setActiveTab('platforms')}
                className="flex items-center gap-2 rounded-md bg-foreground px-3 py-1.5 text-xs text-background"
              >
                <Plus size={14} />
                Add Platform
              </button>
            </div>
            {!items.length ? (
              <div className="py-8 text-center">
                <Globe size={48} className="mx-auto text-muted-foreground mb-4" />
                <h4 className="text-sm font-semibold mb-2">No Platforms Connected</h4>
                <p className="text-xs text-muted-foreground mb-4">Connect messaging platforms to enable Nexus AI interactions.</p>
                <button
                  onClick={() => setActiveTab('platforms')}
                  className="rounded-md border border-border px-4 py-2 text-sm"
                >
                  Connect Platform
                </button>
              </div>
            ) : (
              <div className="space-y-3">
                {items.map(item => {
                  const id = String(item.id || item.name || '')
                  const enabled = Boolean(item.enabled)
                  const available = Boolean(item.available)
                  const required = Array.isArray(item.required_env) ? item.required_env as unknown[][] : []
                  return (
                    <div key={id} className="flex items-start gap-4 rounded-lg border border-border p-4 hover:bg-secondary transition-colors">
                      <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full ${enabled && available ? 'bg-emerald-100 text-emerald-600' : 'bg-gray-100 text-gray-600'}`}>
                        <Network size={18} />
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <p className="text-sm font-medium">{labelFor(item)}</p>
                          {enabled && available && (
                            <span className="inline-flex items-center rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-800">
                              Active
                            </span>
                          )}
                          {!available && (
                            <span className="inline-flex items-center rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800">
                              Needs Config
                            </span>
                          )}
                        </div>
                        <Description item={item} kind="gateway" />
                        {required.length > 0 && (
                          <p className="mt-1 text-xs text-muted-foreground">
                            Required: {required.map(group => group.join(' or ')).join(' · ')}
                          </p>
                        )}
                      </div>
                      <button
                        onClick={() => onToggle(id, !enabled)}
                        disabled={pending === id}
                        className={`rounded-md px-2.5 py-1 text-xs ${enabled ? 'bg-foreground text-background' : 'border border-border text-muted-foreground'}`}
                      >
                        {pending === id ? 'Saving…' : enabled ? 'On' : 'Off'}
                      </button>
                    </div>
                  )
                })}
              </div>
            )}
          </div>

          {/* Quick Actions */}
          <div className="rounded-lg border border-border bg-card p-6">
            <h4 className="text-sm font-semibold mb-4">Quick Actions</h4>
            <div className="flex gap-3">
              <button
                onClick={() => setActiveTab('platforms')}
                className="rounded-md bg-foreground px-4 py-2 text-sm text-background"
              >
                Manage Platforms
              </button>
              <button
                onClick={() => setActiveTab('messages')}
                className="rounded-md border border-border px-4 py-2 text-sm"
              >
                View Messages
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Platforms Tab */}
      {activeTab === 'platforms' && (
        <div className="space-y-4">
          <div className="rounded-lg border border-border bg-card p-6">
            <h4 className="text-sm font-semibold mb-4">Available Platforms</h4>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {platforms.map(platform => (
                <div key={platform.id} className="rounded-lg border border-border p-4 hover:bg-secondary transition-colors">
                  <div className="flex items-start gap-3">
                    <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-blue-500 to-purple-600 text-2xl">
                      {platform.icon}
                    </div>
                    <div className="flex-1">
                      <div className="flex items-center gap-2">
                        <h5 className="text-sm font-semibold">{platform.name}</h5>
                        <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
                          platform.status === 'active' ? 'bg-emerald-100 text-emerald-800' : 'bg-gray-100 text-gray-800'
                        }`}>
                          {platform.status}
                        </span>
                      </div>
                      <p className="mt-1 text-xs text-muted-foreground">{platform.description}</p>
                      <p className="mt-2 text-xs text-muted-foreground">{platform.users} users connected</p>
                    </div>
                  </div>
                  <div className="mt-4 flex gap-2">
                    <button className="flex-1 rounded-md bg-foreground px-3 py-1.5 text-xs text-background">
                      Configure
                    </button>
                    <button className="rounded-md border border-border px-3 py-1.5 text-xs">
                      {platform.status === 'active' ? 'Disconnect' : 'Connect'}
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Add Custom Platform */}
          <div className="rounded-lg border border-border bg-card p-6">
            <h4 className="text-sm font-semibold mb-4">Add Custom Platform</h4>
            <div className="space-y-4">
              <div>
                <label className="text-xs font-medium block mb-1">Platform Name</label>
                <input
                  type="text"
                  placeholder="e.g. Custom Bot"
                  className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm"
                />
              </div>
              <div>
                <label className="text-xs font-medium block mb-1">Webhook URL</label>
                <input
                  type="url"
                  placeholder="https://api.example.com/webhook"
                  className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm"
                />
              </div>
              <div>
                <label className="text-xs font-medium block mb-1">API Token</label>
                <input
                  type="password"
                  placeholder="Enter your API token"
                  className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm"
                />
              </div>
              <button className="rounded-md bg-foreground px-4 py-2 text-sm text-background">
                Add Platform
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Messages Tab */}
      {activeTab === 'messages' && (
        <div className="space-y-4">
          <div className="rounded-lg border border-border bg-card p-6">
            <div className="flex items-center justify-between mb-4">
              <h4 className="text-sm font-semibold">Recent Messages</h4>
              <div className="flex gap-2">
                <button className="px-3 py-1.5 text-xs rounded-md border border-border text-muted-foreground">
                  Export Logs
                </button>
                <button className="px-3 py-1.5 text-xs rounded-md border border-border text-muted-foreground">
                  Clear History
                </button>
              </div>
            </div>

            <div className="space-y-3">
              {recentMessages.map((msg, index) => (
                <div key={index} className="flex items-start gap-4 rounded-lg border border-border p-4">
                  <div className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full ${
                    msg.status === 'processed' ? 'bg-emerald-100 text-emerald-600' :
                    msg.status === 'pending' ? 'bg-blue-100 text-blue-600' :
                    'bg-red-100 text-red-600'
                  }`}>
                    {msg.status === 'processed' && <CheckCircle2 size={16} />}
                    {msg.status === 'pending' && <RefreshCw size={16} className="animate-spin" />}
                    {msg.status === 'failed' && <CircleAlert size={16} />}
                  </div>
                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <p className="text-sm font-medium">{msg.platform}</p>
                      <span className="text-xs text-muted-foreground">·</span>
                      <p className="text-xs text-muted-foreground">{msg.user}</p>
                    </div>
                    <p className="mt-1 text-sm">{msg.message}</p>
                    <p className="mt-1 text-xs text-muted-foreground">{msg.time}</p>
                  </div>
                  <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
                    msg.status === 'processed' ? 'bg-emerald-100 text-emerald-800' :
                    msg.status === 'pending' ? 'bg-blue-100 text-blue-800' :
                    'bg-red-100 text-red-800'
                  }`}>
                    {msg.status}
                  </span>
                </div>
              ))}
            </div>

            <div className="flex items-center justify-between pt-4 border-t border-border">
              <p className="text-xs text-muted-foreground">Showing 5 of 1,234 messages</p>
              <div className="flex gap-2">
                <button className="px-3 py-1 text-xs rounded-md border border-border text-muted-foreground" disabled>
                  Previous
                </button>
                <button className="px-3 py-1 text-xs rounded-md border border-border text-muted-foreground">
                  Next
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Settings Tab */}
      {activeTab === 'settings' && (
        <div className="space-y-4">
          <div className="rounded-lg border border-border bg-card p-6">
            <h4 className="text-sm font-semibold mb-4">Gateway Configuration</h4>
            <div className="space-y-4">
              <label className="flex items-center gap-3">
                <input type="checkbox" defaultChecked className="rounded border-border" />
                <span className="text-sm">Auto-reply to incoming messages</span>
              </label>
              <label className="flex items-center gap-3">
                <input type="checkbox" defaultChecked className="rounded border-border" />
                <span className="text-sm">Enable message queuing during high load</span>
              </label>
              <label className="flex items-center gap-3">
                <input type="checkbox" defaultChecked={false} className="rounded border-border" />
                <span className="text-sm">Log all message content</span>
              </label>
              <label className="flex items-center gap-3">
                <input type="checkbox" defaultChecked className="rounded border-border" />
                <span className="text-sm">Send notifications on errors</span>
              </label>
            </div>
          </div>

          <div className="rounded-lg border border-border bg-card p-6">
            <h4 className="text-sm font-semibold mb-4">Security Settings</h4>
            <div className="space-y-4">
              <label className="flex items-center gap-3">
                <input type="checkbox" defaultChecked className="rounded border-border" />
                <span className="text-sm">Require authentication for all platforms</span>
              </label>
              <label className="flex items-center gap-3">
                <input type="checkbox" defaultChecked className="rounded border-border" />
                <span className="text-sm">Encrypt stored credentials</span>
              </label>
              <label className="flex items-center gap-3">
                <input type="checkbox" defaultChecked={false} className="rounded border-border" />
                <span className="text-sm">Rate limit incoming messages</span>
              </label>
            </div>
          </div>

          <div className="rounded-lg border border-border bg-card p-6">
            <h4 className="text-sm font-semibold mb-4">Message Processing</h4>
            <div className="space-y-4">
              <div>
                <label className="text-xs font-medium block mb-1">Max concurrent messages</label>
                <input
                  type="number"
                  defaultValue={10}
                  min="1"
                  max="50"
                  className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm"
                />
              </div>
              <div>
                <label className="text-xs font-medium block mb-1">Message timeout (seconds)</label>
                <input
                  type="number"
                  defaultValue={30}
                  min="5"
                  max="300"
                  className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm"
                />
              </div>
              <div>
                <label className="text-xs font-medium block mb-1">Retry attempts</label>
                <input
                  type="number"
                  defaultValue={3}
                  min="0"
                  max="10"
                  className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm"
                />
              </div>
            </div>
          </div>

          <div className="flex justify-end">
            <button className="rounded-md bg-foreground px-4 py-2 text-sm text-background">
              Save Settings
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
