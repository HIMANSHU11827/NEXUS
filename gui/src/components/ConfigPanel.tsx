/* eslint-disable react-hooks/static-components */
import { FileCode2, FileJson2, FileText, Search, Settings2 } from 'lucide-react'
import type { Dispatch, SetStateAction } from 'react'

type ConfigStatus = { kind: 'idle' | 'valid' | 'error' | 'saving'; message: string }
type ConfigMode = 'editor' | 'info'
type ConfigFile = {
   path: string
   name: string
   format: string
   category: string
   editable: boolean
   size: number
   summary?: string
   content: string
}

type ConfigPanelProps = {
   configDirty: boolean
   configEditorText: string
   configMode: ConfigMode
   configSearch: string
   configSelectedPath: string
   configStatus: ConfigStatus
   filteredConfigFiles: ConfigFile[]
   formatCardName: (value: string) => string
   loadConfig: () => void
   resetConfigDraft: () => void
   saveConfigDraft: () => void
   selectedConfigFile: ConfigFile | null
   setConfigEditorText: Dispatch<SetStateAction<string>>
   setConfigMode: Dispatch<SetStateAction<ConfigMode>>
   setConfigSearch: Dispatch<SetStateAction<string>>
   setConfigSelectedPath: Dispatch<SetStateAction<string>>
}

const iconForFormat = (format: string) => {
   const value = String(format || '').toLowerCase()
   if (value === 'json') return FileJson2
   if (value === 'md') return FileText
   return FileCode2
}

export function ConfigPanel({
   configDirty,
   configEditorText,
   configMode,
   configSearch,
   configSelectedPath,
   configStatus,
   filteredConfigFiles,
   formatCardName,
   loadConfig,
   resetConfigDraft,
   saveConfigDraft,
   selectedConfigFile,
   setConfigEditorText,
   setConfigMode,
   setConfigSearch,
   setConfigSelectedPath,
}: ConfigPanelProps) {
   const file = selectedConfigFile
   const InfoIcon = iconForFormat(file?.format || '')

   return (
      <div className="config-page">
         <div className="config-command-head">
            <div>
               <span>Project Config</span>
               <h2>{file ? formatCardName(file.name) : 'Config Files'}</h2>
               <p>Project config files only. YAML, JSON, TOML, and markdown/OKF notes live here. Skills, tools, plugins, MCP, and providers stay on their own pages.</p>
            </div>
            <div className="config-command-actions">
               <button onClick={loadConfig}>Reload</button>
               <button onClick={resetConfigDraft} disabled={!configDirty}>Reset</button>
               <button onClick={() => setConfigMode(configMode === 'editor' ? 'info' : 'editor')}>{configMode === 'editor' ? 'Info' : 'Editor'}</button>
               <button className="primary" onClick={saveConfigDraft} disabled={!file?.editable || !configDirty}>Save</button>
            </div>
         </div>

         <div className="config-shell">
            <aside className="config-sidebar">
               <div className="config-sidebar-head">
                  <b>Files</b>
                  <span className={`config-status-pill ${configStatus.kind}`}>{configStatus.kind === 'saving' ? 'working' : configStatus.kind}</span>
               </div>
               <div className="config-sidebar-meta">
                  <span>{filteredConfigFiles.length} files</span>
                  <span>{configDirty ? 'unsaved' : 'saved'}</span>
               </div>
               <div className="config-search">
                  <Search size={15} />
                  <input value={configSearch} onChange={(event) => setConfigSearch(event.target.value)} placeholder="Search config files..." />
               </div>
               <div className="config-section-list">
                  {filteredConfigFiles.map(item => {
                     const RowIcon = iconForFormat(item.format)
                     return (
                        <button
                           key={item.path}
                           className={configSelectedPath === item.path ? 'active' : ''}
                           onClick={() => setConfigSelectedPath(item.path)}
                        >
                           <RowIcon size={15} />
                           <span>{item.path.replace(/^config\//, '').replace(/^okf\//, 'OKF / ')}</span>
                           <small>{item.format.toUpperCase()}</small>
                        </button>
                     )
                  })}
               </div>
            </aside>

            <section className="config-main">
               <div className="config-toolbar">
                  <div>
                     <div className="config-title-row">
                        <h2>{file ? formatCardName(file.name) : 'Config Files'}</h2>
                        <span className={configDirty ? 'dirty' : ''}>{configDirty ? 'Unsaved changes' : 'No changes'}</span>
                     </div>
                     <p>{file ? `${file.path} • ${file.editable ? 'editable' : 'read-only'} • ${Math.max(1, Math.round(file.size / 1024))} KB` : 'Select a project config file.'}</p>
                  </div>
               </div>

               <div className={`config-message ${configStatus.kind}`}>
                  <span>{configStatus.message}</span>
               </div>

               {!file ? (
                  <div className="config-empty big">
                     <Settings2 size={24} />
                     <b>Config not loaded</b>
                     <button onClick={loadConfig}>Load Config</button>
                  </div>
               ) : configMode === 'info' ? (
                  <div className="config-form">
                     <div className="config-section-card">
                        <div className="config-nested-title">
                           <span style={{ display: 'inline-flex', alignItems: 'center', gap: '8px' }}>
                              <InfoIcon size={16} />
                              {formatCardName(file.name)}
                           </span>
                           <code>{file.path}</code>
                        </div>
                        <div className="config-field">
                           <div className="config-field-head"><div><label>Format</label><code>{file.format.toUpperCase()}</code></div></div>
                        </div>
                        <div className="config-field">
                           <div className="config-field-head"><div><label>Category</label><code>{formatCardName(file.category)}</code></div></div>
                        </div>
                        <div className="config-field">
                           <div className="config-field-head"><div><label>Access</label><code>{file.editable ? 'Editable' : 'Read-only'}</code></div></div>
                        </div>
                        {file.summary && (
                           <div className="config-field">
                              <div className="config-field-head"><div><label>Summary</label><code>{file.summary}</code></div></div>
                           </div>
                        )}
                     </div>
                  </div>
               ) : (
                  <textarea
                     className="config-json-editor"
                     value={configEditorText}
                     onChange={(event) => setConfigEditorText(event.target.value)}
                     spellCheck={file.format === 'md'}
                     readOnly={!file.editable}
                  />
               )}
            </section>
         </div>
      </div>
   )
}
