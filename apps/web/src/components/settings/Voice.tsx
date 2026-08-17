import { useState, useEffect } from 'react'
import { api } from '../../lib/api'

function InfoBlock({ title, value, detail }: { title: string; value: string; detail: string }) {
  return <div className="mb-4 rounded-lg border border-border bg-card p-4"><p className="text-sm font-medium">{title}</p><p className="mt-2 text-lg font-semibold">{value}</p><p className="mt-1 text-sm text-muted-foreground">{detail}</p></div>
}

export function VoiceSettings({ status, onChanged }: { status?: { running?: boolean; mode?: string; phase?: string; transcript_preview?: string; reply_preview?: string }; onChanged: () => void }) {
  const [working, setWorking] = useState(false)
  const [message, setMessage] = useState('')
  const running = status?.running || false
  
  // New state for enhanced voice features
  const [stats, setStats] = useState<Record<string, unknown> | null>(null)
  const [history, setHistory] = useState<Array<{ timestamp: number; transcript: string; reply: string; success: boolean; voice_name?: string; language?: string }>>([])
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<Array<{ timestamp: number; transcript: string; reply: string; success: boolean; voice_name?: string; language?: string }>>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [activeTab, setActiveTab] = useState<'overview' | 'history' | 'settings' | 'export'>('overview')
  const [exportFormat, setExportFormat] = useState<'json' | 'text'>('json')
  const [exportData, setExportData] = useState('')
  
  // Settings state
  const [availableVoices, setAvailableVoices] = useState<string[]>([])
  const [availableLanguages, setAvailableLanguages] = useState<string[]>([])
  const [audioDevices, setAudioDevices] = useState<Record<string, unknown> | null>(null)
  const [voiceName, setVoiceName] = useState('Jasper')
  const [whisperLanguage, setWhisperLanguage] = useState('auto')
  const [volume, setVolume] = useState(1.0)
  const [speechSpeed, setSpeechSpeed] = useState(1.0)
  const [autoSpeak, setAutoSpeak] = useState(true)
  const [continuousListening, setContinuousListening] = useState(true)

  const loadStats = async () => {
    try {
      const result = await api.voiceStatistics()
      if (result.status === 'success') {
        setStats(result.statistics)
      }
    } catch (err) {
      console.error('Voice stats error:', err)
    }
  }

  const loadHistory = async () => {
    try {
      const result = await api.voiceHistory('default', 50)
      if (result.status === 'success') {
        setHistory(result.history)
      }
    } catch (err) {
      console.error('Voice history error:', err)
    }
  }

  const performSearch = async () => {
    if (!searchQuery.trim()) return
    setLoading(true); setError('')
    try {
      const result = await api.voiceSearch(searchQuery)
      if (result.status === 'success') {
        setSearchResults(result.results)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Search failed')
    } finally {
      setLoading(false)
    }
  }

  const performExport = async () => {
    setLoading(true); setError('')
    try {
      const result = await api.voiceExport(exportFormat)
      if (result.status === 'success') {
        setExportData(result.data)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Export failed')
    } finally {
      setLoading(false)
    }
  }

  const clearHistory = async () => {
    if (!window.confirm('Clear voice transcription history? This cannot be undone.')) return
    setLoading(true); setError('')
    try {
      const result = await api.voiceClearHistory()
      if (result.status === 'success') {
        setError(result.message)
        loadHistory()
        loadStats()
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Clear failed')
    } finally {
      setLoading(false)
    }
  }

  const resetStats = async () => {
    if (!window.confirm('Reset voice statistics? This cannot be undone.')) return
    setLoading(true); setError('')
    try {
      const result = await api.voiceResetStatistics()
      if (result.status === 'success') {
        setError(result.message)
        loadStats()
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Reset failed')
    } finally {
      setLoading(false)
    }
  }

  const loadVoicesAndLanguages = async () => {
    try {
      const [voicesResult, languagesResult, devicesResult] = await Promise.all([
        api.voiceVoices(),
        api.voiceLanguages(),
        api.voiceDevices(),
      ])
      if (voicesResult.status === 'success') setAvailableVoices(voicesResult.voices)
      if (languagesResult.status === 'success') setAvailableLanguages(languagesResult.languages)
      if (devicesResult.status === 'success') setAudioDevices(devicesResult.devices)
    } catch (err) {
      console.error('Failed to load voice options:', err)
    }
  }

  const saveSettings = async () => {
    setLoading(true); setError('')
    try {
      await api.voiceSettings({
        voice_name: voiceName,
        whisper_language: whisperLanguage,
        volume,
        speech_speed: speechSpeed,
        auto_speak: autoSpeak,
        continuous_listening: continuousListening,
      })
      setError('Voice settings saved')
      onChanged()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Save failed')
    } finally {
      setLoading(false)
    }
  }

  const change = async () => { setWorking(true); setMessage(''); try { if (running) await api.stopVoice(); else await api.startVoice('auto'); onChanged() } catch (error) { setMessage(error instanceof Error ? error.message : 'Voice service could not be changed.') } finally { setWorking(false) } }

  useEffect(() => {
    loadStats()
    loadHistory()
    loadVoicesAndLanguages()
  }, [])

  return <div className="space-y-4">
    <div><h3 className="text-sm font-semibold">Voice runtime</h3><p className="mt-1 text-sm text-muted-foreground">Manage NEXUS voice assistant with comprehensive controls and history.</p></div>
    
    <div className="flex gap-2 border-b border-border">
      {[
        { id: 'overview', label: 'Overview' },
        { id: 'history', label: 'History' },
        { id: 'settings', label: 'Settings' },
        { id: 'export', label: 'Export' },
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

    {activeTab === 'overview' && (
      <div className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <InfoBlock title="Status" value={running ? 'Running' : 'Stopped'} detail={`Mode: ${status?.mode || 'off'} · Phase: ${status?.phase || 'off'}`} />
          {stats && (
            <>
              <InfoBlock title="Total transcriptions" value={String(stats.total_transcriptions || 0)} detail="All voice transcriptions in session." />
              <InfoBlock title="Successful turns" value={String(stats.successful_turns || 0)} detail="Completed voice interactions." />
              <InfoBlock title="Failed turns" value={String(stats.failed_turns || 0)} detail="Failed voice interactions." />
              <InfoBlock title="Session duration" value={`${((Number(stats.session_duration) || 0) / 60).toFixed(1)} min`} detail="Current voice session length." />
            </>
          )}
        </div>
        
        <div className="rounded-lg border border-border bg-card p-4">
          <p className="text-sm font-medium">Latest voice activity</p>
          <p className="mt-1 text-sm text-muted-foreground">{status?.transcript_preview || status?.reply_preview || 'No live voice transcript or reply is available.'}</p>
        </div>

        <div className="flex items-center justify-between gap-4">
          <p className="text-sm text-destructive" role="status">{message || error}</p>
          <button type="button" disabled={working} onClick={change} className="rounded-md bg-foreground px-3 py-2 text-sm font-medium text-background disabled:opacity-50">{working ? 'Working…' : running ? 'Stop voice' : 'Start voice'}</button>
        </div>

        <div className="flex gap-2">
          <button onClick={resetStats} disabled={loading} className="rounded-md border border-border px-3 py-1.5 text-sm font-medium text-foreground disabled:opacity-50">
            {loading ? 'Resetting...' : 'Reset Statistics'}
          </button>
        </div>
      </div>
    )}

    {activeTab === 'history' && (
      <div className="space-y-4">
        <div className="flex gap-2">
          <input
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            placeholder="Search transcriptions..."
            className="flex-1 h-9 rounded-md border border-border bg-background px-3 text-sm"
            onKeyDown={e => e.key === 'Enter' && performSearch()}
          />
          <button onClick={performSearch} disabled={loading || !searchQuery.trim()} className="rounded-md bg-foreground px-3 py-1.5 text-sm font-medium text-background disabled:opacity-50">
            {loading ? 'Searching...' : 'Search'}
          </button>
        </div>
        
        {error && <p className="text-sm text-destructive" role="alert">{error}</p>}
        
        {searchResults.length > 0 && (
          <div className="rounded-lg border border-border bg-card">
            <p className="px-4 py-3 text-sm font-medium">{searchResults.length} result{searchResults.length === 1 ? '' : 's'}</p>
            <div className="divide-y divide-border">
              {searchResults.map((result, i) => (
                <div key={i} className="px-4 py-3">
                  <p className="text-xs font-medium text-muted-foreground">{new Date(result.timestamp * 1000).toLocaleString()}</p>
                  <p className="mt-1 text-sm font-medium">{result.transcript}</p>
                  <p className="mt-1 text-sm text-muted-foreground">{result.reply}</p>
                </div>
              ))}
            </div>
          </div>
        )}
        
        {searchResults.length === 0 && (
          <div className="rounded-lg border border-border bg-card">
            <div className="flex items-center justify-between px-4 py-3 border-b border-border">
              <p className="text-sm font-medium">Transcription History ({history.length})</p>
              <button onClick={clearHistory} disabled={loading} className="rounded-md bg-destructive px-2 py-1 text-xs font-medium text-background disabled:opacity-50">
                Clear
              </button>
            </div>
            <div className="divide-y divide-border max-h-96 overflow-y-auto">
              {history.length === 0 ? (
                <p className="px-4 py-8 text-sm text-muted-foreground">No transcriptions yet.</p>
              ) : (
                history.map((entry, i) => (
                  <div key={i} className="px-4 py-3">
                    <p className="text-xs font-medium text-muted-foreground">{new Date(entry.timestamp * 1000).toLocaleString()}</p>
                    <p className="mt-1 text-sm font-medium">{entry.transcript}</p>
                    <p className="mt-1 text-sm text-muted-foreground">{entry.reply}</p>
                  </div>
                ))
              )}
            </div>
          </div>
        )}
      </div>
    )}

    {activeTab === 'settings' && (
      <div className="space-y-4">
        <div className="rounded-lg border border-border bg-card p-4">
          <p className="text-sm font-medium">Voice Settings</p>
          <p className="mt-1 text-sm text-muted-foreground">Configure voice assistant behavior and audio settings.</p>
          
          <div className="mt-4 space-y-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <label className="grid gap-1.5 text-sm font-medium">
                Voice
                <select value={voiceName} onChange={e => setVoiceName(e.target.value)} className="h-9 rounded-md border border-border bg-background px-3 text-sm font-normal">
                  {availableVoices.length > 0 ? availableVoices.map(v => <option key={v} value={v}>{v}</option>) : <option value="Jasper">Jasper</option>}
                </select>
              </label>
              <label className="grid gap-1.5 text-sm font-medium">
                Language
                <select value={whisperLanguage} onChange={e => setWhisperLanguage(e.target.value)} className="h-9 rounded-md border border-border bg-background px-3 text-sm font-normal">
                  {availableLanguages.length > 0 ? availableLanguages.map(l => <option key={l} value={l}>{l}</option>) : <option value="auto">Auto</option>}
                </select>
              </label>
            </div>
            
            <div className="grid gap-4 sm:grid-cols-2">
              <label className="grid gap-1.5 text-sm font-medium">
                Volume ({volume.toFixed(1)})
                <input type="range" min="0" max="2" step="0.1" value={volume} onChange={e => setVolume(parseFloat(e.target.value))} className="w-full" />
              </label>
              <label className="grid gap-1.5 text-sm font-medium">
                Speech Speed ({speechSpeed.toFixed(1)})
                <input type="range" min="0.5" max="2" step="0.1" value={speechSpeed} onChange={e => setSpeechSpeed(parseFloat(e.target.value))} className="w-full" />
              </label>
            </div>
            
            <div className="flex gap-4">
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={autoSpeak} onChange={e => setAutoSpeak(e.target.checked)} className="rounded border-border" />
                Auto-speak responses
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={continuousListening} onChange={e => setContinuousListening(e.target.checked)} className="rounded border-border" />
                Continuous listening
              </label>
            </div>
            
            <button onClick={saveSettings} disabled={loading} className="rounded-md bg-foreground px-3 py-1.5 text-sm font-medium text-background disabled:opacity-50">
              {loading ? 'Saving...' : 'Save Settings'}
            </button>
          </div>
        </div>

        {audioDevices && (
          <div className="rounded-lg border border-border bg-card p-4">
            <p className="text-sm font-medium">Audio Devices</p>
            <p className="mt-1 text-sm text-muted-foreground">
              Input devices: {(audioDevices as any).input_devices?.length || 0} · 
              Output devices: {(audioDevices as any).output_devices?.length || 0}
            </p>
          </div>
        )}
      </div>
    )}

    {activeTab === 'export' && (
      <div className="space-y-4">
        <div className="rounded-lg border border-border bg-card p-4">
          <p className="text-sm font-medium">Export Voice Data</p>
          <p className="mt-1 text-sm text-muted-foreground">Export voice statistics and transcription history.</p>
          <div className="mt-3 flex gap-2">
            <select value={exportFormat} onChange={e => setExportFormat(e.target.value as 'json' | 'text')} className="h-9 rounded-md border border-border bg-background px-2 text-sm">
              <option value="json">JSON</option>
              <option value="text">Text</option>
            </select>
            <button onClick={performExport} disabled={loading} className="rounded-md bg-foreground px-3 py-1.5 text-sm font-medium text-background disabled:opacity-50">
              {loading ? 'Exporting...' : 'Export'}
            </button>
          </div>
          {exportData && (
            <div className="mt-3">
              <textarea
                value={exportData}
                readOnly
                rows={10}
                className="w-full rounded-md border border-border bg-background px-3 py-2 text-xs font-mono"
              />
            </div>
          )}
        </div>
      </div>
    )}

    {error && <p className="text-sm text-destructive" role="alert">{error}</p>}
  </div>
}
