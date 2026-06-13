import { Search, Settings2 } from 'lucide-react'
import type { Dispatch, ReactNode, SetStateAction } from 'react'

type ConfigRecord = Record<string, unknown>
type ConfigStatus = { kind: 'idle' | 'valid' | 'error' | 'saving'; message: string }
type ConfigMode = 'form' | 'json'

type ConfigPanelProps = {
   configDirty: boolean
   configDraft: ConfigRecord | null
   configJsonText: string
   configMode: ConfigMode
   configSearch: string
   configSection: string
   configStatus: ConfigStatus
   filteredConfigSections: string[]
   formatCardName: (value: string) => string
   loadConfig: () => void
   resetConfigDraft: () => void
   saveConfigDraft: () => void
   selectedConfigValue: unknown
   setConfigJsonText: Dispatch<SetStateAction<string>>
   setConfigMode: Dispatch<SetStateAction<ConfigMode>>
   setConfigSearch: Dispatch<SetStateAction<string>>
   setConfigSection: Dispatch<SetStateAction<string>>
   setConfigStatus: Dispatch<SetStateAction<ConfigStatus>>
   setConfigDraft: Dispatch<SetStateAction<ConfigRecord | null>>
   updateConfigPath: (path: string[], value: unknown) => void
   validateConfigDraft: (draft: ConfigRecord) => string
}

export function ConfigPanel({
   configDirty,
   configDraft,
   configJsonText,
   configMode,
   configSearch,
   configSection,
   configStatus,
   filteredConfigSections,
   formatCardName,
   loadConfig,
   resetConfigDraft,
   saveConfigDraft,
   selectedConfigValue,
   setConfigDraft,
   setConfigJsonText,
   setConfigMode,
   setConfigSearch,
   setConfigSection,
   setConfigStatus,
   updateConfigPath,
   validateConfigDraft,
}: ConfigPanelProps) {
   const renderConfigValue = (value: unknown, path: string[], depth = 0): ReactNode => {
      const key = path[path.length - 1] || 'root';
      const label = formatCardName(key);
      const pathLabel = path.join('.');
      if (value === null || ['string', 'number', 'boolean'].includes(typeof value)) {
         const isBool = typeof value === 'boolean';
         const isNumber = typeof value === 'number';
         const optionMap: Record<string, string[]> = {
            'gui.interface_mode': ['dark', 'light', 'grey', 'night', 'white'],
            'system.default_provider': ['local', 'cloud'],
            'system.brain_mode': ['AUTO', 'LOCAL', 'CLOUD'],
            'system.log_level': ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
            'voice_input.whisper_device': ['auto', 'cpu', 'cuda'],
            'voice_input.whisper_language': ['auto', 'en', 'hi'],
            'memory.persistence': ['atomic_checkpoints', 'session_json', 'disabled'],
            'memory.vault_mode': ['gravity_rag', 'bm25', 'hybrid', 'disabled'],
            'security.sandbox_mode': ['firecracker_ev', 'local_guarded', 'disabled'],
         };
         const options = optionMap[pathLabel];
         return (
            <div className="config-field" key={pathLabel}>
               <div className="config-field-head">
                  <div>
                     <label>{label}</label>
                     <code>{pathLabel}</code>
                  </div>
                  {isBool && (
                     <button
                        className={`config-toggle ${value ? 'on' : ''}`}
                        onClick={() => updateConfigPath(path, !value)}
                     >
                        {value ? 'ON' : 'OFF'}
                     </button>
                  )}
               </div>
               {!isBool && options && (
                  <select
                     value={String(value ?? '')}
                     onChange={(event) => updateConfigPath(path, event.target.value)}
                  >
                     {options.map(option => <option key={option} value={option}>{option}</option>)}
                  </select>
               )}
               {!isBool && !options && (
                  <input
                     type={isNumber ? 'number' : 'text'}
                     value={String(value ?? '')}
                     onChange={(event) => updateConfigPath(path, isNumber ? Number(event.target.value) : event.target.value)}
                  />
               )}
            </div>
         );
      }
      if (Array.isArray(value)) {
         return (
            <div className="config-field" key={pathLabel}>
               <div className="config-field-head">
                  <div>
                     <label>{label}</label>
                     <code>{pathLabel} · array[{value.length}]</code>
                  </div>
               </div>
               <textarea
                  value={JSON.stringify(value, null, 2)}
                  onChange={(event) => {
                     try {
                        updateConfigPath(path, JSON.parse(event.target.value));
                     } catch {
                        setConfigStatus({ kind: 'error', message: `Invalid JSON array at ${pathLabel}` });
                     }
                  }}
               />
            </div>
         );
      }
      if (value && typeof value === 'object') {
         const entries = Object.entries(value);
         return (
            <div className={depth === 0 ? 'config-section-card' : 'config-nested-card'} key={pathLabel}>
               {depth > 0 && (
                  <div className="config-nested-title">
                     <span>{label}</span>
                     <code>{pathLabel}</code>
                  </div>
               )}
               {entries.length === 0 ? (
                  <div className="config-empty">Empty object</div>
               ) : entries.map(([childKey, childValue]) => renderConfigValue(childValue, [...path, childKey], depth + 1))}
            </div>
         );
      }
      return null;
   };

   return (
      <div className="config-page">
         <div className="config-command-head">
            <div>
               <span>Active Profile</span>
               <h2>{formatCardName(configSection || 'Config')}</h2>
               <p>Edit the runtime config directly. Vision settings live here now; providers, tools, skills, MCP, and plugins stay on their own pages.</p>
            </div>
            <div className="config-command-actions">
               <button onClick={loadConfig}>Reload</button>
               <button onClick={resetConfigDraft} disabled={!configDirty}>Reset</button>
               <button onClick={() => setConfigMode(configMode === 'form' ? 'json' : 'form')}>{configMode === 'form' ? 'JSON' : 'Form'}</button>
               <button className="primary" onClick={saveConfigDraft} disabled={!configDirty && configMode === 'form'}>Save</button>
            </div>
         </div>

         <div className="config-shell">
            <aside className="config-sidebar">
               <div className="config-sidebar-head">
                  <b>Settings</b>
                  <span className={`config-status-pill ${configStatus.kind}`}>{configStatus.kind === 'saving' ? 'working' : configStatus.kind}</span>
               </div>
               <div className="config-sidebar-meta">
                  <span>{filteredConfigSections.length} sections</span>
                  <span>{configDirty ? 'unsaved' : 'saved'}</span>
               </div>
               <div className="config-search">
                  <Search size={15} />
                  <input value={configSearch} onChange={(event) => setConfigSearch(event.target.value)} placeholder="Search config..." />
               </div>
               <div className="config-section-list">
                  {filteredConfigSections.map(section => (
                     <button
                        key={section}
                        className={configSection === section ? 'active' : ''}
                        onClick={() => setConfigSection(section)}
                     >
                        <Settings2 size={15} />
                        <span>{formatCardName(section)}</span>
                        <small>{configDraft?.[section] && typeof configDraft[section] === 'object' ? Object.keys(configDraft[section] as ConfigRecord).length : 1}</small>
                     </button>
                  ))}
               </div>
            </aside>

            <section className="config-main">
               <div className="config-toolbar">
                  <div>
                     <div className="config-title-row">
                        <h2>{formatCardName(configSection || 'Config')}</h2>
                        <span className={configDirty ? 'dirty' : ''}>{configDirty ? 'Unsaved changes' : 'No changes'}</span>
                     </div>
                     <p>{configSection === 'vision' ? 'Camera, stream, model, and acceleration defaults.' : `Editing ${formatCardName(configSection || 'config')} settings.`}</p>
                  </div>
               </div>

               <div className={`config-message ${configStatus.kind}`}>
                  <span>{configStatus.message}</span>
               </div>

               {configMode === 'json' ? (
                  <textarea
                     className="config-json-editor"
                     value={configJsonText}
                     onChange={(event) => {
                        setConfigJsonText(event.target.value);
                        try {
                           const parsed = JSON.parse(event.target.value) as ConfigRecord;
                           setConfigDraft(parsed);
                           const validation = validateConfigDraft(parsed);
                           setConfigStatus(validation ? { kind: 'error', message: validation } : { kind: 'valid', message: 'JSON is valid. Save to persist.' });
                        } catch (error) {
                           setConfigStatus({ kind: 'error', message: `JSON parse error: ${error instanceof Error ? error.message : String(error)}` });
                        }
                     }}
                     spellCheck={false}
                  />
               ) : configDraft ? (
                  <div className="config-form">
                     {selectedConfigValue === undefined ? (
                        <div className="config-empty">Select a section to edit.</div>
                     ) : renderConfigValue(selectedConfigValue, [configSection], 0)}
                  </div>
               ) : (
                  <div className="config-empty big">
                     <Settings2 size={24} />
                     <b>Config not loaded</b>
                     <button onClick={loadConfig}>Load Config</button>
                  </div>
               )}
            </section>
         </div>
      </div>
   );
}
