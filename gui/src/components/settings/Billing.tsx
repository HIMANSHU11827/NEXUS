import { useState } from 'react'
import { ReceiptText, Cpu, Brain, CircleAlert, CheckCircle2, Info } from 'lucide-react'

export function BillingSettings({ billing }: { billing?: { tier?: string; message?: string; status?: string; usage?: Record<string, unknown>; limits?: Record<string, unknown> } }) {
  void billing
  const [activeTab, setActiveTab] = useState<'overview' | 'usage' | 'providers' | 'limits' | 'history'>('overview')
  const [timeRange, setTimeRange] = useState<'today' | 'week' | 'month' | 'year'>('month')
  
  // Mock data for demonstration - in production this would come from the API
  const usageData = {
    totalTokens: 1250000,
    totalCost: 45.67,
    apiCalls: 3420,
    providers: [
      { name: 'OpenAI', tokens: 850000, cost: 32.50, calls: 2100, icon: '🤖' },
      { name: 'Anthropic', tokens: 320000, cost: 11.20, calls: 980, icon: '🧠' },
      { name: 'Local (Ollama)', tokens: 80000, cost: 1.97, calls: 340, icon: '💻' },
    ],
    dailyUsage: [
      { date: 'Mon', tokens: 42000, cost: 1.45 },
      { date: 'Tue', tokens: 58000, cost: 2.10 },
      { date: 'Wed', tokens: 35000, cost: 1.20 },
      { date: 'Thu', tokens: 72000, cost: 2.65 },
      { date: 'Fri', tokens: 89000, cost: 3.15 },
      { date: 'Sat', tokens: 45000, cost: 1.60 },
      { date: 'Sun', tokens: 31000, cost: 1.12 },
    ],
    budget: {
      monthly: 100,
      used: 45.67,
      remaining: 54.33,
      alertThreshold: 80,
      alertsEnabled: true,
    },
    models: [
      { name: 'GPT-4', tokens: 450000, cost: 18.00, percentage: 36 },
      { name: 'GPT-3.5-Turbo', tokens: 400000, cost: 14.50, percentage: 32 },
      { name: 'Claude-3-Sonnet', tokens: 320000, cost: 11.20, percentage: 26 },
      { name: 'Llama-2-70B', tokens: 80000, cost: 1.97, percentage: 6 },
    ],
  }

  const budgetPercentage = (usageData.budget.used / usageData.budget.monthly) * 100
  const isOverBudget = budgetPercentage > usageData.budget.alertThreshold

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-semibold">Billing & Usage</h3>
        <p className="mt-1 text-sm text-muted-foreground">Monitor your API usage, costs, and provider spending across all configured services.</p>
      </div>

      {/* Tab Navigation */}
      <div className="flex gap-2 border-b border-border">
        {[
          { id: 'overview', label: 'Overview' },
          { id: 'usage', label: 'Usage Analytics' },
          { id: 'providers', label: 'Providers' },
          { id: 'limits', label: 'Budget & Limits' },
          { id: 'history', label: 'History' },
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
          {/* Summary Cards */}
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <div className="rounded-lg border border-border bg-card p-4">
              <div className="flex items-center gap-2">
                <ReceiptText size={18} className="text-muted-foreground" />
                <p className="text-xs font-medium text-muted-foreground">Total Cost (Month)</p>
              </div>
              <p className="mt-2 text-2xl font-bold">${usageData.totalCost.toFixed(2)}</p>
              <p className="mt-1 text-xs text-muted-foreground">vs ${100.00} budget</p>
            </div>
            <div className="rounded-lg border border-border bg-card p-4">
              <div className="flex items-center gap-2">
                <Cpu size={18} className="text-muted-foreground" />
                <p className="text-xs font-medium text-muted-foreground">Total Tokens</p>
              </div>
              <p className="mt-2 text-2xl font-bold">{(usageData.totalTokens / 1000000).toFixed(2)}M</p>
              <p className="mt-1 text-xs text-muted-foreground">{usageData.apiCalls.toLocaleString()} API calls</p>
            </div>
            <div className="rounded-lg border border-border bg-card p-4">
              <div className="flex items-center gap-2">
                <Brain size={18} className="text-muted-foreground" />
                <p className="text-xs font-medium text-muted-foreground">Active Providers</p>
              </div>
              <p className="mt-2 text-2xl font-bold">{usageData.providers.length}</p>
              <p className="mt-1 text-xs text-muted-foreground">2 cloud, 1 local</p>
            </div>
            <div className={`rounded-lg border p-4 ${isOverBudget ? 'border-amber-500 bg-amber-50 dark:bg-amber-950/20' : 'border-border bg-card'}`}>
              <div className="flex items-center gap-2">
                <CircleAlert size={18} className={isOverBudget ? 'text-amber-600' : 'text-muted-foreground'} />
                <p className="text-xs font-medium text-muted-foreground">Budget Status</p>
              </div>
              <p className="mt-2 text-2xl font-bold">{budgetPercentage.toFixed(0)}%</p>
              <p className="mt-1 text-xs text-muted-foreground">{isOverBudget ? 'Approaching limit' : 'On track'}</p>
            </div>
          </div>

          {/* Budget Progress */}
          <div className="rounded-lg border border-border bg-card p-6">
            <div className="flex items-center justify-between mb-4">
              <h4 className="text-sm font-semibold">Monthly Budget</h4>
              <select 
                value={timeRange}
                onChange={(e) => setTimeRange(e.target.value as any)}
                className="h-8 rounded-md border border-border bg-background px-2 text-xs"
              >
                <option value="today">Today</option>
                <option value="week">This Week</option>
                <option value="month">This Month</option>
                <option value="year">This Year</option>
              </select>
            </div>
            <div className="space-y-3">
              <div className="flex items-center justify-between text-sm">
                <span className="text-muted-foreground">Spent</span>
                <span className="font-medium">${usageData.budget.used.toFixed(2)} / ${usageData.budget.monthly.toFixed(2)}</span>
              </div>
              <div className="h-3 w-full rounded-full bg-secondary overflow-hidden">
                <div 
                  className={`h-full rounded-full transition-all ${isOverBudget ? 'bg-amber-500' : 'bg-emerald-500'}`}
                  style={{ width: `${Math.min(budgetPercentage, 100)}%` }}
                />
              </div>
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <span>${usageData.budget.remaining.toFixed(2)} remaining</span>
                <span>{budgetPercentage.toFixed(0)}% used</span>
              </div>
            </div>
          </div>

          {/* Top Providers */}
          <div className="rounded-lg border border-border bg-card p-6">
            <h4 className="text-sm font-semibold mb-4">Cost by Provider</h4>
            <div className="space-y-4">
              {usageData.providers.map((provider, index) => {
                const percentage = (provider.cost / usageData.totalCost) * 100
                return (
                  <div key={index} className="space-y-2">
                    <div className="flex items-center justify-between text-sm">
                      <div className="flex items-center gap-2">
                        <span className="text-lg">{provider.icon}</span>
                        <span className="font-medium">{provider.name}</span>
                      </div>
                      <span className="text-muted-foreground">${provider.cost.toFixed(2)}</span>
                    </div>
                    <div className="h-2 w-full rounded-full bg-secondary overflow-hidden">
                      <div 
                        className="h-full rounded-full bg-blue-500"
                        style={{ width: `${percentage}%` }}
                      />
                    </div>
                    <div className="flex items-center justify-between text-xs text-muted-foreground">
                      <span>{provider.tokens.toLocaleString()} tokens · {provider.calls} calls</span>
                      <span>{percentage.toFixed(1)}%</span>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>

          {/* Model Breakdown */}
          <div className="rounded-lg border border-border bg-card p-6">
            <h4 className="text-sm font-semibold mb-4">Usage by Model</h4>
            <div className="space-y-3">
              {usageData.models.map((model, index) => (
                <div key={index} className="flex items-center justify-between py-2 border-b border-border last:border-0">
                  <div className="flex-1">
                    <p className="text-sm font-medium">{model.name}</p>
                    <p className="text-xs text-muted-foreground">{model.tokens.toLocaleString()} tokens</p>
                  </div>
                  <div className="text-right">
                    <p className="text-sm font-medium">${model.cost.toFixed(2)}</p>
                    <p className="text-xs text-muted-foreground">{model.percentage}%</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Usage Analytics Tab */}
      {activeTab === 'usage' && (
        <div className="space-y-6">
          <div className="rounded-lg border border-border bg-card p-6">
            <div className="flex items-center justify-between mb-6">
              <h4 className="text-sm font-semibold">Token Usage Over Time</h4>
              <div className="flex gap-2">
                <button className="px-3 py-1 text-xs rounded-md bg-foreground text-background">Tokens</button>
                <button className="px-3 py-1 text-xs rounded-md border border-border text-muted-foreground">Cost</button>
                <button className="px-3 py-1 text-xs rounded-md border border-border text-muted-foreground">Calls</button>
              </div>
            </div>
            {/* Simple bar chart visualization */}
            <div className="flex items-end gap-2 h-40">
              {usageData.dailyUsage.map((day, index) => {
                const maxTokens = Math.max(...usageData.dailyUsage.map(d => d.tokens))
                const height = (day.tokens / maxTokens) * 100
                return (
                  <div key={index} className="flex-1 flex flex-col items-center gap-2">
                    <div 
                      className="w-full rounded-t bg-blue-500 hover:bg-blue-600 transition-colors cursor-pointer"
                      style={{ height: `${height}%` }}
                      title={`${day.date}: ${day.tokens.toLocaleString()} tokens, $${day.cost.toFixed(2)}`}
                    />
                    <span className="text-xs text-muted-foreground">{day.date}</span>
                  </div>
                )
              })}
            </div>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="rounded-lg border border-border bg-card p-6">
              <h4 className="text-sm font-semibold mb-4">Usage Statistics</h4>
              <div className="space-y-3">
                <div className="flex justify-between text-sm">
                  <span className="text-muted-foreground">Average tokens/day</span>
                  <span className="font-medium">{Math.round(usageData.totalTokens / 7).toLocaleString()}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-muted-foreground">Average cost/day</span>
                  <span className="font-medium">${(usageData.totalCost / 7).toFixed(2)}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-muted-foreground">Peak usage day</span>
                  <span className="font-medium">Fri</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-muted-foreground">Avg. tokens/call</span>
                  <span className="font-medium">{Math.round(usageData.totalTokens / usageData.apiCalls)}</span>
                </div>
              </div>
            </div>

            <div className="rounded-lg border border-border bg-card p-6">
              <h4 className="text-sm font-semibold mb-4">Cost Optimization Tips</h4>
              <ul className="space-y-2 text-sm text-muted-foreground">
                <li className="flex items-start gap-2">
                  <CheckCircle2 size={14} className="mt-0.5 text-emerald-600 shrink-0" />
                  <span>Use GPT-3.5-Turbo for simple tasks to save 40%</span>
                </li>
                <li className="flex items-start gap-2">
                  <CheckCircle2 size={14} className="mt-0.5 text-emerald-600 shrink-0" />
                  <span>Enable response caching for repeated queries</span>
                </li>
                <li className="flex items-start gap-2">
                  <CheckCircle2 size={14} className="mt-0.5 text-emerald-600 shrink-0" />
                  <span>Use local models for offline development</span>
                </li>
                <li className="flex items-start gap-2">
                  <CheckCircle2 size={14} className="mt-0.5 text-emerald-600 shrink-0" />
                  <span>Set up budget alerts to prevent overspending</span>
                </li>
              </ul>
            </div>
          </div>
        </div>
      )}

      {/* Providers Tab */}
      {activeTab === 'providers' && (
        <div className="space-y-4">
          {usageData.providers.map((provider, index) => (
            <div key={index} className="rounded-lg border border-border bg-card p-6">
              <div className="flex items-start justify-between gap-4">
                <div className="flex items-center gap-3">
                  <span className="text-3xl">{provider.icon}</span>
                  <div>
                    <h4 className="text-sm font-semibold">{provider.name}</h4>
                    <p className="text-xs text-muted-foreground">
                      {provider.name === 'Local (Ollama)' ? 'Local provider - no external costs' : 'Cloud provider - charges apply'}
                    </p>
                  </div>
                </div>
                <div className="text-right">
                  <p className="text-lg font-bold">${provider.cost.toFixed(2)}</p>
                  <p className="text-xs text-muted-foreground">This month</p>
                </div>
              </div>
              <div className="mt-4 grid grid-cols-3 gap-4">
                <div>
                  <p className="text-xs text-muted-foreground">Tokens</p>
                  <p className="text-sm font-medium">{provider.tokens.toLocaleString()}</p>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">API Calls</p>
                  <p className="text-sm font-medium">{provider.calls.toLocaleString()}</p>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">Avg Cost/1K Tokens</p>
                  <p className="text-sm font-medium">${((provider.cost / provider.tokens) * 1000).toFixed(4)}</p>
                </div>
              </div>
              {provider.name !== 'Local (Ollama)' && (
                <div className="mt-4 pt-4 border-t border-border">
                  <button className="text-xs text-blue-600 hover:text-blue-700 underline">
                    View {provider.name} dashboard →
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Budget & Limits Tab */}
      {activeTab === 'limits' && (
        <div className="space-y-6">
          <div className="rounded-lg border border-border bg-card p-6">
            <h4 className="text-sm font-semibold mb-4">Budget Settings</h4>
            <div className="space-y-4">
              <div>
                <label className="text-sm font-medium block mb-2">Monthly Budget Limit ($)</label>
                <input 
                  type="number" 
                  defaultValue={usageData.budget.monthly}
                  className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm"
                />
              </div>
              <div>
                <label className="text-sm font-medium block mb-2">Alert Threshold (%)</label>
                <input 
                  type="number" 
                  defaultValue={usageData.budget.alertThreshold}
                  min="10"
                  max="100"
                  className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm"
                />
                <p className="mt-1 text-xs text-muted-foreground">Send alert when usage exceeds this percentage of budget</p>
              </div>
              <label className="flex items-center gap-3">
                <input 
                  type="checkbox" 
                  defaultChecked={usageData.budget.alertsEnabled}
                  className="rounded border-border" 
                />
                <span className="text-sm">Enable budget alerts via email</span>
              </label>
              <label className="flex items-center gap-3">
                <input type="checkbox" defaultChecked className="rounded border-border" />
                <span className="text-sm">Auto-switch to local provider when budget exceeded</span>
              </label>
            </div>
            <div className="mt-6 flex justify-end">
              <button className="rounded-md bg-foreground px-4 py-2 text-sm text-background">
                Save Budget Settings
              </button>
            </div>
          </div>

          <div className="rounded-lg border border-border bg-card p-6">
            <h4 className="text-sm font-semibold mb-4">Usage Limits</h4>
            <div className="space-y-4">
              <div>
                <label className="text-sm font-medium block mb-2">Daily Token Limit</label>
                <input 
                  type="number" 
                  placeholder="No limit"
                  className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm"
                />
              </div>
              <div>
                <label className="text-sm font-medium block mb-2">Daily API Call Limit</label>
                <input 
                  type="number" 
                  placeholder="No limit"
                  className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm"
                />
              </div>
              <div>
                <label className="text-sm font-medium block mb-2">Max Cost per Request ($)</label>
                <input 
                  type="number" 
                  step="0.01"
                  placeholder="No limit"
                  className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm"
                />
              </div>
            </div>
          </div>

          <div className="rounded-lg border border-amber-500 bg-amber-50 dark:bg-amber-950/20 p-6">
            <div className="flex items-start gap-3">
              <CircleAlert size={20} className="text-amber-600 shrink-0" />
              <div>
                <h4 className="text-sm font-semibold text-amber-900 dark:text-amber-100">Budget Warning</h4>
                <p className="mt-1 text-sm text-amber-800 dark:text-amber-200">
                  You are currently at {budgetPercentage.toFixed(0)}% of your monthly budget. Consider reviewing your usage patterns or adjusting your budget settings.
                </p>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* History Tab */}
      {activeTab === 'history' && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h4 className="text-sm font-semibold">Usage History</h4>
            <div className="flex gap-2">
              <button className="px-3 py-1.5 text-xs rounded-md border border-border text-muted-foreground hover:bg-secondary">
                Export CSV
              </button>
              <button className="px-3 py-1.5 text-xs rounded-md border border-border text-muted-foreground hover:bg-secondary">
                Export JSON
              </button>
            </div>
          </div>

          <div className="rounded-lg border border-border bg-card">
            <div className="grid grid-cols-5 gap-4 px-4 py-3 border-b border-border bg-secondary/30 text-xs font-medium">
              <span>Date</span>
              <span>Provider</span>
              <span>Tokens</span>
              <span>Cost</span>
              <span>Action</span>
            </div>
            <div className="divide-y divide-border">
              {[
                { date: '2026-08-01', provider: 'OpenAI', tokens: 45000, cost: 1.65, model: 'GPT-4' },
                { date: '2026-08-01', provider: 'Anthropic', tokens: 32000, cost: 1.12, model: 'Claude-3-Sonnet' },
                { date: '2026-07-31', provider: 'OpenAI', tokens: 58000, cost: 2.10, model: 'GPT-3.5-Turbo' },
                { date: '2026-07-31', provider: 'Local (Ollama)', tokens: 25000, cost: 0.00, model: 'Llama-2-70B' },
                { date: '2026-07-30', provider: 'Anthropic', tokens: 41000, cost: 1.45, model: 'Claude-3-Sonnet' },
                { date: '2026-07-30', provider: 'OpenAI', tokens: 38000, cost: 1.38, model: 'GPT-4' },
              ].map((entry, index) => (
                <div key={index} className="grid grid-cols-5 gap-4 px-4 py-3 text-sm">
                  <span className="text-muted-foreground">{entry.date}</span>
                  <span className="font-medium">{entry.provider}</span>
                  <span>{entry.tokens.toLocaleString()}</span>
                  <span className={entry.cost > 0 ? 'font-medium' : 'text-muted-foreground'}>
                    {entry.cost > 0 ? `$${entry.cost.toFixed(2)}` : 'Free'}
                  </span>
                  <button className="text-xs text-blue-600 hover:text-blue-700 underline">
                    Details
                  </button>
                </div>
              ))}
            </div>
          </div>

          <div className="flex items-center justify-between">
            <p className="text-xs text-muted-foreground">Showing 6 of 342 entries</p>
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
      )}

      {/* Footer Note */}
      <div className="rounded-lg border border-border bg-secondary/30 p-4">
        <div className="flex items-start gap-3">
          <Info size={16} className="mt-0.5 text-muted-foreground shrink-0" />
          <div className="text-sm text-muted-foreground">
            <p className="font-medium text-foreground">Nexus is local-first</p>
            <p className="mt-1">
              Provider charges are handled by the provider account you configure, not by Nexus. 
              Local providers like Ollama run entirely on your machine with no per-token costs.
              Review detailed usage and invoices in each cloud provider's own dashboard.
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
