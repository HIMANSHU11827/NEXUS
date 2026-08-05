import { useState } from 'react'

export function KeyboardShortcuts() {
  const [activeTab, setActiveTab] = useState<'general' | 'chat' | 'navigation'>('general')
  
  const generalShortcuts = [
    { keys: ['Ctrl', 'K'], action: 'Open command palette', context: undefined as string | undefined },
    { keys: ['Ctrl', ','], action: 'Open settings', context: undefined as string | undefined },
    { keys: ['Esc'], action: 'Close modal or dialog', context: undefined as string | undefined },
  ]
  
  const chatShortcuts = [
    { keys: ['Enter'], action: 'Send the message in the composer', context: undefined as string | undefined },
    { keys: ['Shift', 'Enter'], action: 'Insert a new line in the composer', context: undefined as string | undefined },
    { keys: ['Ctrl', 'B'], action: 'Show or hide the chat history sidebar', context: undefined as string | undefined },
    { keys: ['Ctrl', 'K'], action: 'Focus the chat-history search box', context: undefined as string | undefined },
  ]
  
  const navigationShortcuts = [
    { keys: ['Enter'], action: 'Confirm a file or chat rename', context: 'while renaming' as string | undefined },
    { keys: ['Esc'], action: 'Cancel a file or chat rename', context: 'while renaming' as string | undefined },
    { keys: ['Ctrl', 'N'], action: 'Create new chat', context: undefined as string | undefined },
    { keys: ['Ctrl', 'T'], action: 'Create new file', context: undefined as string | undefined },
  ]

  return <div className="space-y-4">
    <div><h3 className="text-sm font-semibold">Keyboard shortcuts</h3><p className="mt-1 text-sm text-muted-foreground">These are the shortcuts implemented in this Nexus GUI. Use ⌘ instead of Ctrl on macOS.</p></div>
    
    <div className="flex gap-2 border-b border-border">
      {[
        { id: 'general', label: 'General' },
        { id: 'chat', label: 'Chat' },
        { id: 'navigation', label: 'Navigation' },
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
      <div className="rounded-lg border border-border bg-card">
        <div className="divide-y divide-border">
          {generalShortcuts.map((shortcut, index) => (
            <div key={`${shortcut.action}-${index}`} className="flex items-center justify-between gap-6 px-4 py-3">
              <div>
                <p className="text-sm text-foreground">{shortcut.action}</p>
                {shortcut.context && <p className="mt-0.5 text-xs text-muted-foreground">{shortcut.context}</p>}
              </div>
              <div className="flex shrink-0 items-center gap-1">
                {shortcut.keys.map(key => <kbd key={key} className="rounded border border-border bg-secondary px-1.5 py-0.5 text-xs font-medium text-foreground">{key}</kbd>)}
              </div>
            </div>
          ))}
        </div>
      </div>
    )}

    {activeTab === 'chat' && (
      <div className="rounded-lg border border-border bg-card">
        <div className="divide-y divide-border">
          {chatShortcuts.map((shortcut, index) => (
            <div key={`${shortcut.action}-${index}`} className="flex items-center justify-between gap-6 px-4 py-3">
              <div>
                <p className="text-sm text-foreground">{shortcut.action}</p>
                {shortcut.context && <p className="mt-0.5 text-xs text-muted-foreground">{shortcut.context}</p>}
              </div>
              <div className="flex shrink-0 items-center gap-1">
                {shortcut.keys.map(key => <kbd key={key} className="rounded border border-border bg-secondary px-1.5 py-0.5 text-xs font-medium text-foreground">{key}</kbd>)}
              </div>
            </div>
          ))}
        </div>
      </div>
    )}

    {activeTab === 'navigation' && (
      <div className="rounded-lg border border-border bg-card">
        <div className="divide-y divide-border">
          {navigationShortcuts.map((shortcut, index) => (
            <div key={`${shortcut.action}-${index}`} className="flex items-center justify-between gap-6 px-4 py-3">
              <div>
                <p className="text-sm text-foreground">{shortcut.action}</p>
                {shortcut.context && <p className="mt-0.5 text-xs text-muted-foreground">{shortcut.context}</p>}
              </div>
              <div className="flex shrink-0 items-center gap-1">
                {shortcut.keys.map(key => <kbd key={key} className="rounded border border-border bg-secondary px-1.5 py-0.5 text-xs font-medium text-foreground">{key}</kbd>)}
              </div>
            </div>
          ))}
        </div>
      </div>
    )}
  </div>
}
