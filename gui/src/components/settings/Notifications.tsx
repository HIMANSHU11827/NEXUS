import { useState } from 'react'

export function NotificationSettings() {
  const [enabled, setEnabled] = useState(() => localStorage.getItem('nexus-notifications') === 'enabled')
  const [soundEnabled, setSoundEnabled] = useState(() => localStorage.getItem('nexus-notification-sound') === 'enabled')
  const [message, setMessage] = useState('')
  const [activeTab, setActiveTab] = useState<'general' | 'sound'>('general')
  
  const update = async () => { 
    if (!enabled && 'Notification' in window) { 
      const permission = await Notification.requestPermission(); 
      if (permission !== 'granted') { 
        setMessage('Browser notifications were not permitted.'); 
        return 
      } 
    } 
    const next = !enabled; 
    setEnabled(next); 
    localStorage.setItem('nexus-notifications', next ? 'enabled' : 'disabled'); 
    setMessage(next ? 'Browser notifications are enabled on this device.' : 'Browser notifications are disabled on this device.') 
  }

  const updateSound = () => {
    const next = !soundEnabled
    setSoundEnabled(next)
    localStorage.setItem('nexus-notification-sound', next ? 'enabled' : 'disabled')
    setMessage(next ? 'Notification sounds enabled.' : 'Notification sounds disabled.')
  }

  const supported = typeof window !== 'undefined' && 'Notification' in window
  
  return <div className="space-y-4">
    <div><h3 className="text-sm font-semibold">Notifications</h3><p className="mt-1 text-sm text-muted-foreground">Configure how Nexus notifies you about events and updates.</p></div>
    
    {message && <div className="rounded-lg border border-emerald-30 bg-emerald-5 px-4 py-3 text-sm text-emerald-700" role="status">{message}</div>}
    
    <div className="flex gap-2 border-b border-border">
      {[
        { id: 'general', label: 'General' },
        { id: 'sound', label: 'Sound' },
      ].map(tab => (
        <button
          key={tab.id}
          onClick={() => setActiveTab(tab.id as any)}
          className={`px-3 py-2 text-sm font-medium transition ${activeTab === tab.id ? 'border-b-2 border-foreground text-foreground' : 'text-muted-foreground hover:text-foreground'}`}
        >
          {tab.label}
        </button>
      ))}
    </div>

    {activeTab === 'general' && (
      <div className="space-y-4">
        <div className="rounded-lg border border-border bg-card p-4">
          <div className="flex items-center justify-between gap-4">
            <div className="flex-1">
              <p className="text-sm font-medium">Browser notifications</p>
              <p className="mt-1 text-xs text-muted-foreground">{supported ? `Browser permission: ${Notification.permission}` : 'This browser does not support notifications.'}</p>
            </div>
            <button type="button" disabled={!supported} onClick={update} className={`rounded-md px-3 py-1.5 text-xs font-medium ${enabled ? 'bg-foreground text-background' : 'border border-border text-muted-foreground'}`}>{enabled ? 'On' : 'Off'}</button>
          </div>
        </div>

        <div className="rounded-lg border border-border bg-card p-4">
          <p className="text-sm font-medium">Notification types</p>
          <p className="mt-1 text-xs text-muted-foreground">Choose which events trigger notifications.</p>
          <div className="mt-3 space-y-3">
            <label className="flex items-center gap-3">
              <input type="checkbox" defaultChecked className="rounded border-border" />
              <span className="text-sm">Task completion</span>
            </label>
            <label className="flex items-center gap-3">
              <input type="checkbox" defaultChecked className="rounded border-border" />
              <span className="text-sm">Error alerts</span>
            </label>
            <label className="flex items-center gap-3">
              <input type="checkbox" defaultChecked={false} className="rounded border-border" />
              <span className="text-sm">New messages</span>
            </label>
          </div>
        </div>
      </div>
    )}

    {activeTab === 'sound' && (
      <div className="space-y-4">
        <div className="rounded-lg border border-border bg-card p-4">
          <div className="flex items-center justify-between gap-4">
            <div className="flex-1">
              <p className="text-sm font-medium">Notification sounds</p>
              <p className="mt-1 text-xs text-muted-foreground">Play sound when notifications arrive.</p>
            </div>
            <button type="button" onClick={updateSound} className={`rounded-md px-3 py-1.5 text-xs font-medium ${soundEnabled ? 'bg-foreground text-background' : 'border border-border text-muted-foreground'}`}>{soundEnabled ? 'On' : 'Off'}</button>
          </div>
        </div>

        <div className="rounded-lg border border-border bg-card p-4">
          <p className="text-sm font-medium">Volume</p>
          <p className="mt-1 text-xs text-muted-foreground">Adjust notification sound volume.</p>
          <div className="mt-3">
            <input type="range" min="0" max="100" defaultValue="50" className="w-full" />
          </div>
        </div>
      </div>
    )}
  </div>
}
