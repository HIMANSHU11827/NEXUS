import { useState, useEffect, useRef, useCallback } from 'react'
import {
  ChevronRight, ChevronDown, File, Search, FileCode2, FileJson, FileType, FileText,
  Folder, Loader2, Download, Upload, Plus, Trash2, X, Check, Image, Archive,
  Pencil, Scissors, ClipboardPaste, FileArchive, FileInput, Save, FolderOpen,
} from 'lucide-react'
import { api } from '../lib/api'

interface Item {
  name: string
  path: string
  type: 'file' | 'directory'
  size?: number
}

const iconMap: Record<string, typeof FileCode2> = {
  ts: FileCode2, tsx: FileCode2, js: FileCode2, jsx: FileCode2,
  py: FileCode2, rs: FileCode2, go: FileCode2,
  css: FileType, scss: FileType, html: FileCode2,
  json: FileJson, toml: FileText, yml: FileText, yaml: FileText, md: FileText, xml: FileCode2,
}

const colorMap: Record<string, string> = {
  ts: 'text-blue-600', tsx: 'text-blue-600', js: 'text-yellow-500', jsx: 'text-yellow-500',
  py: 'text-blue-500', rs: 'text-orange-600', go: 'text-cyan-600',
  css: 'text-blue-600', scss: 'text-pink-600', html: 'text-orange-600',
  json: 'text-yellow-600', toml: 'text-gray-500', yml: 'text-red-500', yaml: 'text-red-500', md: 'text-blue-400', xml: 'text-orange-500',
  png: 'text-purple-500', jpg: 'text-purple-500', jpeg: 'text-purple-500', gif: 'text-purple-500', svg: 'text-orange-500', webp: 'text-purple-500', ico: 'text-purple-500',
  zip: 'text-yellow-700', tar: 'text-yellow-700', gz: 'text-yellow-700', rar: 'text-yellow-700', '7z': 'text-yellow-700',
  txt: 'text-gray-400', log: 'text-gray-400',
}

function getFileIcon(name: string) {
  const ext = name.split('.').pop()?.toLowerCase() || ''
  if (['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp', 'ico'].includes(ext)) return Image
  if (['zip', 'tar', 'gz', 'rar', '7z'].includes(ext)) return Archive
  return iconMap[ext] || File
}

function getFileColor(name: string) {
  const ext = name.split('.').pop()?.toLowerCase() || ''
  return colorMap[ext] || 'text-foreground/70'
}

function formatSize(bytes?: number) {
  if (!bytes) return ''
  if (bytes < 1024) return `${bytes}B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)}KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)}MB`
}

const ROOT_KEY = '__root__'

interface FileExplorerProps {
  onFileOpen?: (path: string) => void
}

export default function FileExplorer({ onFileOpen }: FileExplorerProps) {
  const [childrenMap, setChildrenMap] = useState<Record<string, Item[]>>({ [ROOT_KEY]: [] })
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [loadingMap, setLoadingMap] = useState<Record<string, boolean>>({})
  const [filter, setFilter] = useState('')
  // An empty value deliberately means the project's workspace folder.
  const [rootPath, setRootPath] = useState('')
  const [actualWorkspaceRoot, setActualWorkspaceRoot] = useState('')
  const [showFolderPicker, setShowFolderPicker] = useState(false)
  const [folderInput, setFolderInput] = useState('')
  const [creating, setCreating] = useState<{ parent: string; type: 'file' | 'folder' } | null>(null)
  const [createName, setCreateName] = useState('')
  const [renaming, setRenaming] = useState<string | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const [deleting, setDeleting] = useState<string | null>(null)
  const [cutPath, setCutPath] = useState<string | null>(null)
  const [editingFile, setEditingFile] = useState<{ path: string; content: string; original: string } | null>(null)
  const [saving, setSaving] = useState(false)
  const createRef = useRef<HTMLInputElement>(null)
  const renameRef = useRef<HTMLInputElement>(null)
  const uploadRef = useRef<HTMLInputElement>(null)
  const editorRef = useRef<HTMLTextAreaElement>(null)

  const fetchChildren = useCallback(async (parent: string) => {
    setLoadingMap(p => ({ ...p, [parent]: true }))
    try {
      const res = await api.fileTree(parent === ROOT_KEY ? rootPath : parent)
      const items = (res as any).items.map((i: any) => ({ ...i, path: i.path.replace(/\\/g, '/') }))
      setChildrenMap(p => ({ ...p, [parent]: items }))
    } catch { setChildrenMap(p => ({ ...p, [parent]: [] })) }
    finally { setLoadingMap(p => ({ ...p, [parent]: false })) }
  }, [rootPath])

  useEffect(() => { fetchChildren(ROOT_KEY) }, [fetchChildren, rootPath])
  useEffect(() => { if (creating) createRef.current?.focus() }, [creating])
  useEffect(() => { if (renaming) renameRef.current?.focus() }, [renaming])
  useEffect(() => { if (editingFile) editorRef.current?.focus() }, [editingFile])
  
  // Fetch actual workspace root to display correct folder name
  useEffect(() => {
    api.workspace().then((summary: any) => {
      if (summary?.root) {
        setActualWorkspaceRoot(summary.root)
      }
    }).catch(() => {})
  }, [])
  useEffect(() => {
    const refreshTree = () => {
      fetchChildren(ROOT_KEY)
      setChildrenMap(p => { const next = { ...p }; delete next[ROOT_KEY]; return next })
    }
    window.addEventListener('nexus-sandbox-folder', refreshTree)
    return () => window.removeEventListener('nexus-sandbox-folder', refreshTree)
  }, [fetchChildren])

  const refresh = (path: string) => {
    const parent = path === ROOT_KEY || !path.includes('/') ? ROOT_KEY : path.slice(0, path.lastIndexOf('/'))
    fetchChildren(parent)
    setChildrenMap(p => { const n = { ...p }; Object.keys(n).forEach(k => { if (k.startsWith(path) || k === parent) delete n[k] }); return n })
  }

  const selectFolder = async (event: React.FormEvent) => {
    event.preventDefault()
    const nextRoot = folderInput.trim()
    setRootPath(nextRoot)
    setChildrenMap({ [ROOT_KEY]: [] })
    setExpanded(new Set())
    setFilter('')
    setShowFolderPicker(false)
    // Update backend workspace root when custom folder is selected
    if (nextRoot) {
      try {
        await api.setSandbox('no_sandbox', nextRoot)
        setActualWorkspaceRoot(nextRoot)
      } catch (error) {
        console.error('Failed to set workspace root:', error)
      }
    }
    window.dispatchEvent(new CustomEvent('nexus-sandbox-folder', { detail: { path: nextRoot } }))
  }

  const resetToWorkspace = async () => {
    setRootPath('')
    setFolderInput('')
    setChildrenMap({ [ROOT_KEY]: [] })
    setExpanded(new Set())
    setFilter('')
    setShowFolderPicker(false)
    // Reset backend workspace root to default
    try {
      await api.setSandbox('no_sandbox', '')
      // Refresh actual workspace root from backend
      const summary = await api.workspace()
      if (summary?.root) {
        setActualWorkspaceRoot(summary.root)
      }
    } catch (error) {
      console.error('Failed to reset workspace root:', error)
    }
    window.dispatchEvent(new CustomEvent('nexus-sandbox-folder', { detail: { path: '' } }))
  }

  const rootName = rootPath
    ? rootPath.replace(/\\/g, '/').split('/').filter(Boolean).pop() || rootPath
    : (actualWorkspaceRoot
        ? actualWorkspaceRoot.replace(/\\/g, '/').split('/').filter(Boolean).pop() || actualWorkspaceRoot
        : 'Workspace')

  useEffect(() => {
    if (filter.trim()) {
      const items = childrenMap[ROOT_KEY] || []
      const toExpand = new Set<string>()
      const scan = (list: Item[], parent: string) => {
        for (const item of list) {
          if (itemMatches(item)) {
            if (parent !== ROOT_KEY) toExpand.add(parent)
            if (item.type === 'directory') toExpand.add(item.path)
          }
          const kids = childrenMap[item.path]
          if (kids) scan(kids, item.path)
        }
      }
      scan(items, ROOT_KEY)
      if (toExpand.size) {
        setExpanded(p => { const n = new Set(p); toExpand.forEach(x => n.add(x)); return n })
        toExpand.forEach(p => { if (!childrenMap[p] && p !== ROOT_KEY) fetchChildren(p) })
      }
    }
  }, [filter])

  const toggleExpand = (path: string) => {
    if (expanded.has(path)) { 
      setExpanded(p => { const n = new Set(p); n.delete(path); return n }) 
    }
    else { 
      setExpanded(p => new Set(p).add(path)); 
      if (!childrenMap[path]) fetchChildren(path) 
    }
  }

  const commitCreate = async () => {
    if (!creating || !createName.trim()) return
    const parent = creating.parent
    const path = parent && parent !== ROOT_KEY ? `${parent}/${createName}` : createName
    await api.createFile(path, creating.type).catch(() => {})
    setCreating(null); setCreateName('')
    refresh(parent)
    if (parent !== ROOT_KEY) setExpanded(p => new Set(p).add(parent))
  }

  const startRename = (e: React.MouseEvent, path: string, name: string) => {
    e.stopPropagation(); setRenaming(path); setRenameValue(name)
  }

  const commitRename = async () => {
    if (!renaming || !renameValue.trim()) return
    await api.renameFile(renaming, renameValue.trim()).catch(() => {})
    setRenaming(null)
    refresh(renaming)
  }

  const commitDelete = async (path: string) => {
    await api.deleteFile(path).catch(() => {})
    setDeleting(null)
    refresh(path)
  }

  const commitMove = async (destParent: string) => {
    if (!cutPath) return
    const name = cutPath.split('/').pop() || ''
    const dest = destParent && destParent !== ROOT_KEY ? `${destParent}/${name}` : name
    await api.moveFile(cutPath, dest).catch(() => {})
    setCutPath(null)
    refresh(destParent)
  }

  const openEditor = async (path: string) => {
    try {
      const res = await api.readFile(path)
      setEditingFile({ path, content: res.content, original: res.content })
      onFileOpen?.(path)
    } catch {}
  }

  const saveEditor = async () => {
    if (!editingFile) return
    setSaving(true)
    await api.writeFile(editingFile.path, editingFile.content).catch(() => {})
    setSaving(false)
    setEditingFile(null)
  }

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (!files?.length) return
    for (const file of files) {
      try {
        const text = await file.text()
        await api.writeFile(file.name, text)
      } catch {}
    }
    e.target.value = ''
    refresh(ROOT_KEY)
  }

  const matchesFilter = (name: string) => !filter.trim() || name.toLowerCase().includes(filter.toLowerCase())

  const itemMatches = (item: Item): boolean => {
    if (matchesFilter(item.name)) return true
    if (item.type === 'directory' && childrenMap[item.path]) {
      return childrenMap[item.path].some(c => itemMatches(c))
    }
    return false
  }

  const downloadFolder = async (path: string) => {
    try {
      const res = await api.zipFile(path)
      const a = document.createElement('a')
      a.href = `/api/files/read?path=${encodeURIComponent(res.path)}`
      a.download = res.path.split('/').pop() || 'archive.zip'
      a.click()
    } catch {}
  }

  const renderItem = (item: Item, level: number): React.ReactNode => {
    if (filter.trim() && !itemMatches(item)) return null
    const isDir = item.type === 'directory'
    const Icon = isDir ? Folder : getFileIcon(item.name)
    const isExpanded = expanded.has(item.path)
    const isLoading = loadingMap[item.path]
    const children = childrenMap[item.path] || []
    const isDeleting = deleting === item.path
    const isRenaming = renaming === item.path
    const isCut = cutPath === item.path
    const isZip = item.name.endsWith('.zip')

    return (
      <div key={item.path}>
        <div className={`group flex items-center gap-1 px-2 py-1 rounded transition text-left cursor-default ${isCut ? 'bg-secondary/50 opacity-60' : 'hover:bg-secondary'}`}
          style={{ paddingLeft: `${level * 14 + 8}px` }}
          onDragOver={e => { if (cutPath) e.preventDefault() }}
          onDrop={e => { if (cutPath && isDir) { e.preventDefault(); commitMove(item.path) } }}
        >
          {isDir ? (
            <button onClick={() => toggleExpand(item.path)} aria-label={`${isExpanded ? 'Collapse' : 'Expand'} folder ${item.name}`} aria-expanded={isExpanded} className="size-4 flex items-center justify-center shrink-0 text-muted-foreground/40 hover:text-muted-foreground">
              {isLoading ? <Loader2 size={10} className="animate-spin" /> : isExpanded ? <ChevronDown size={10} /> : <ChevronRight size={10} />}
            </button>
          ) : (
            <div className="size-4 shrink-0" />
          )}
          <Icon size={12} className={`shrink-0 ${isDir ? 'text-amber-500' : getFileColor(item.name)}`} />
          {isRenaming ? (
            <div className="flex items-center gap-1 flex-1 min-w-0">
              <input ref={renameRef} value={renameValue} onChange={e => setRenameValue(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') commitRename(); if (e.key === 'Escape') setRenaming(null) }}
                onClick={e => e.stopPropagation()}
                className="flex-1 bg-background border border-border rounded px-1 py-0.5 text-[11px] focus:outline-none focus:ring-1 focus:ring-ring/30 min-w-0" />
              <button onClick={e => { e.stopPropagation(); commitRename() }} className="size-5 flex items-center justify-center rounded hover:bg-secondary text-muted-foreground/60"><Check size={10} /></button>
              <button onClick={e => { e.stopPropagation(); setRenaming(null) }} className="size-5 flex items-center justify-center rounded hover:bg-secondary text-muted-foreground/60"><X size={10} /></button>
            </div>
          ) : (
            <span className={`text-xs truncate flex-1 ${isDir ? 'text-foreground/80 font-medium cursor-pointer' : 'text-foreground/70'}`}
              role="button"
              tabIndex={0}
              aria-label={isDir ? `Folder ${item.name}` : `Open file ${item.name}`}
              data-testid={`fe-item-${item.name}`}
              onClick={() => isDir ? toggleExpand(item.path) : openEditor(item.path)}
              onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); isDir ? toggleExpand(item.path) : openEditor(item.path) } }}
              title={item.path}
            >
              {item.name}
            </span>
          )}
          {!isDir && item.size ? <span className="text-[10px] text-muted-foreground/30 shrink-0">{formatSize(item.size)}</span> : null}

          {isDeleting ? (
            <div className="flex items-center gap-1 shrink-0">
              <span className="text-[10px] text-destructive/70">Delete?</span>
              <button onClick={() => commitDelete(item.path)} className="size-5 flex items-center justify-center rounded hover:bg-destructive/10 text-destructive/70"><Check size={10} /></button>
              <button onClick={() => setDeleting(null)} className="size-5 flex items-center justify-center rounded hover:bg-secondary text-muted-foreground/60"><X size={10} /></button>
            </div>
          ) : (
            <div className="hidden group-hover:flex items-center gap-0.5 shrink-0">
              {!isDir && <button onClick={() => openEditor(item.path)} aria-label={`Edit ${item.name}`} title={`Edit ${item.name}`} className="size-5 flex items-center justify-center rounded hover:bg-background text-muted-foreground/40 hover:text-muted-foreground"><FileInput size={10} /></button>}
              <button onClick={e => startRename(e, item.path, item.name)} aria-label={`Rename ${item.name}`} title={`Rename ${item.name}`} className="size-5 flex items-center justify-center rounded hover:bg-background text-muted-foreground/40 hover:text-muted-foreground"><Pencil size={10} /></button>
              <button onClick={e => { e.stopPropagation(); setCutPath(item.path) }} aria-label={`Cut ${item.name}`} title={`Cut ${item.name}`} className="size-5 flex items-center justify-center rounded hover:bg-background text-muted-foreground/40 hover:text-muted-foreground"><Scissors size={10} /></button>
              {isDir && <button onClick={e => { e.stopPropagation(); commitMove(item.path) }} aria-label={`Paste into ${item.name}`} title={`Paste into ${item.name}`} className="size-5 flex items-center justify-center rounded hover:bg-background text-muted-foreground/40 hover:text-muted-foreground"><ClipboardPaste size={10} /></button>}
              {!isDir && <button onClick={() => { const a = document.createElement('a'); a.href = `/api/files/read?path=${encodeURIComponent(item.path)}`; a.download = item.name; a.click() }} aria-label={`Download ${item.name}`} title={`Download ${item.name}`} className="size-5 flex items-center justify-center rounded hover:bg-background text-muted-foreground/40 hover:text-muted-foreground"><Download size={10} /></button>}
              {isDir && <button onClick={() => downloadFolder(item.path)} aria-label={`Download folder ${item.name}`} title={`Download folder ${item.name}`} className="size-5 flex items-center justify-center rounded hover:bg-background text-muted-foreground/40 hover:text-muted-foreground"><Download size={10} /></button>}
              {isZip && <button onClick={async () => { await api.unzipFile(item.path).catch(() => {}); refresh(item.path) }} aria-label={`Unzip ${item.name}`} title={`Unzip ${item.name}`} className="size-5 flex items-center justify-center rounded hover:bg-background text-muted-foreground/40 hover:text-muted-foreground"><FileArchive size={10} /></button>}
              {isDir && <button onClick={async () => { await api.zipFile(item.path).catch(() => {}); refresh(item.path) }} aria-label={`Zip folder ${item.name}`} title={`Zip folder ${item.name}`} className="size-5 flex items-center justify-center rounded hover:bg-background text-muted-foreground/40 hover:text-muted-foreground"><FileArchive size={10} /></button>}
              <button onClick={() => setDeleting(item.path)} aria-label={`Delete ${item.name}`} title={`Delete ${item.name}`} className="size-5 flex items-center justify-center rounded hover:bg-background text-muted-foreground/40 hover:text-destructive"><Trash2 size={10} /></button>
            </div>
          )}
        </div>

        {isDir && isExpanded && (
          <>
            {children.map(c => renderItem(c, level + 1))}
            {isLoading && <div className="flex items-center gap-2 px-2 py-1 text-muted-foreground/40 text-[11px]" style={{ paddingLeft: `${(level + 1) * 14 + 8}px` }}><Loader2 size={10} className="animate-spin" />Loading...</div>}
          </>
        )}
      </div>
    )
  }

  const rootItems = childrenMap[ROOT_KEY] || []

  return (
    <div className="flex flex-col h-full">
      <div className="px-3 pt-3 pb-2.5 border-b border-border space-y-2">
        <div className="flex items-center justify-between">
          <div className="min-w-0">
            <h2 className="truncate text-[10px] font-semibold tracking-wider text-muted-foreground uppercase" title={rootPath || actualWorkspaceRoot || 'Project workspace'}>{rootName}</h2>
            <p className="mt-0.5 truncate text-[10px] text-muted-foreground/45" title={rootPath || actualWorkspaceRoot || 'Project workspace'}>{rootPath || actualWorkspaceRoot || 'Project workspace'}</p>
          </div>
          <div className="flex items-center gap-0.5">
            <button onClick={() => { setFolderInput(rootPath); setShowFolderPicker(value => !value) }} aria-label="Choose folder" title="Choose folder" className="size-5 flex items-center justify-center rounded hover:bg-secondary text-muted-foreground/50 hover:text-muted-foreground">
              <FolderOpen size={12} />
            </button>
            {cutPath && <button onClick={() => { commitMove(ROOT_KEY) }} aria-label="Paste into workspace root" title="Paste into workspace root" data-testid="fe-paste-root" className="size-5 flex items-center justify-center rounded bg-foreground/10 text-foreground/70"><ClipboardPaste size={11} /></button>}
            <button onClick={() => uploadRef.current?.click()} aria-label="Upload files" title="Upload files" data-testid="fe-upload" className="size-5 flex items-center justify-center rounded hover:bg-secondary text-muted-foreground/40 hover:text-muted-foreground"><Upload size={11} /></button>
            <button onClick={() => setCreating({ parent: ROOT_KEY, type: 'file' })} aria-label="New file" title="New file" data-testid="fe-new-file" className="size-5 flex items-center justify-center rounded hover:bg-secondary text-muted-foreground/40 hover:text-muted-foreground"><Plus size={11} /></button>
            <button onClick={() => setCreating({ parent: ROOT_KEY, type: 'folder' })} aria-label="New folder" title="New folder" data-testid="fe-new-folder" className="size-5 flex items-center justify-center rounded hover:bg-secondary text-muted-foreground/40 hover:text-muted-foreground"><Folder size={11} /></button>
            <input ref={uploadRef} type="file" onChange={handleUpload} className="hidden" multiple aria-label="File upload input" />
          </div>
        </div>
        {showFolderPicker && (
          <form onSubmit={selectFolder} className="rounded-md border border-border bg-secondary/40 p-1.5">
            <label className="mb-1 block text-[10px] text-muted-foreground/65">Folder path (for example: C:\\Users\\himan\\Downloads)</label>
            <div className="flex items-center gap-1">
              <input value={folderInput} onChange={e => setFolderInput(e.target.value)} placeholder="Leave empty for workspace" autoFocus className="min-w-0 flex-1 rounded border border-border bg-background px-2 py-1 text-[11px] focus:outline-none focus:ring-1 focus:ring-ring/30" />
              <button type="submit" title="Open folder" className="flex size-6 items-center justify-center rounded bg-foreground text-background"><Check size={12} /></button>
              <button type="button" onClick={resetToWorkspace} title="Use workspace" className="flex size-6 items-center justify-center rounded hover:bg-background text-muted-foreground"><Folder size={12} /></button>
            </div>
          </form>
        )}
        <div className="relative">
          <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground/40 pointer-events-none" />
          <input type="text" value={filter} onChange={e => setFilter(e.target.value)} placeholder="Filter..." className="w-full pl-8 pr-3 py-1.5 bg-secondary border-0 rounded-lg text-xs focus:outline-none focus:ring-1 focus:ring-ring/20 transition placeholder:text-muted-foreground/40" />
        </div>
        {cutPath && (
          <div className="flex items-center gap-1.5 text-[10px] text-muted-foreground/60 bg-secondary/50 rounded px-2 py-1">
            <Scissors size={10} /> Cut: {cutPath.split('/').pop()}
            <button onClick={() => setCutPath(null)} className="ml-auto text-muted-foreground/40 hover:text-muted-foreground"><X size={10} /></button>
          </div>
        )}
      </div>

      <div className="flex-1 overflow-y-auto py-0.5">
        {loadingMap[ROOT_KEY] ? (
          <div className="flex items-center justify-center h-full gap-2 text-muted-foreground/40 text-xs"><Loader2 size={12} className="animate-spin" />Loading...</div>
        ) : (
          <>
            {creating?.parent === ROOT_KEY && (
              <div className="flex items-center gap-1 px-2 py-1 border-b border-border/30 mx-2" style={{ paddingLeft: '8px' }}>
                {creating.type === 'folder' ? <Folder size={12} className="text-muted-foreground/50 shrink-0" /> : <File size={12} className="text-muted-foreground/50 shrink-0" />}
                <input ref={createRef} value={createName} onChange={e => setCreateName(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') commitCreate(); if (e.key === 'Escape') setCreating(null) }} placeholder={`${creating.type} name...`} className="flex-1 bg-background border border-border rounded px-1.5 py-0.5 text-[11px] focus:outline-none focus:ring-1 focus:ring-ring/30" />
                <button onClick={commitCreate} className="size-5 flex items-center justify-center rounded hover:bg-secondary text-muted-foreground/60"><Check size={10} /></button>
                <button onClick={() => setCreating(null)} className="size-5 flex items-center justify-center rounded hover:bg-secondary text-muted-foreground/60"><X size={10} /></button>
              </div>
            )}
            {rootItems.length === 0 && !creating ? (
              <div className="flex flex-col items-center justify-center h-full px-6 text-center"><Folder size={18} className="text-muted-foreground/20 mb-2" /><p className="text-xs text-muted-foreground/50">No files.</p></div>
            ) : (
              rootItems.filter(i => !filter.trim() || matchesFilter(i.name)).map(item => renderItem(item, 0))
            )}
          </>
        )}
      </div>

      {editingFile && (
        <div className="border-t border-border bg-card">
          <div className="flex items-center justify-between px-3 py-1.5 border-b border-border">
            <span className="text-[11px] font-medium text-foreground/70 truncate">{editingFile.path}</span>
            <div className="flex items-center gap-1">
              <button onClick={saveEditor} disabled={saving} className="flex items-center gap-1 px-2 py-1 rounded bg-foreground text-background text-[10px] hover:opacity-80 transition disabled:opacity-40">
                {saving ? <Loader2 size={10} className="animate-spin" /> : <Save size={10} />}
                Save
              </button>
              <button onClick={() => setEditingFile(null)} className="size-6 flex items-center justify-center rounded hover:bg-secondary text-muted-foreground/50"><X size={12} /></button>
            </div>
          </div>
          <textarea
            ref={editorRef}
            value={editingFile.content}
            onChange={e => setEditingFile(p => p ? { ...p, content: e.target.value } : null)}
            className="w-full h-[200px] p-3 bg-background border-0 text-[11px] font-mono leading-relaxed resize-none focus:outline-none text-foreground/80 placeholder:text-muted-foreground/30"
            spellCheck={false}
          />
        </div>
      )}
    </div>
  )
}
