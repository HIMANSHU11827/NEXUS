import { useState } from 'react'
import { ChevronDown, ChevronRight, Code, FileEdit, X } from 'lucide-react'

interface QueuedTask {
  id: string
  prompt: string
  attachments: Array<{ path: string; name: string }>
}

interface QueuePanelProps {
  tasks: QueuedTask[]
  onSteer: (task: QueuedTask) => void
  onRemove: (id: string) => void
  onSave: (id: string, prompt: string) => void
}

export default function QueuePanel({ tasks, onSteer, onRemove, onSave }: QueuePanelProps) {
  const [expanded, setExpanded] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editingPrompt, setEditingPrompt] = useState('')

  const handleEdit = (task: QueuedTask) => {
    setEditingId(task.id)
    setEditingPrompt(task.prompt)
  }

  const handleSave = (id: string) => {
    const prompt = editingPrompt.trim()
    if (prompt) {
      onSave(id, prompt)
    }
    setEditingId(null)
  }

  const handleCancel = () => {
    setEditingId(null)
  }

  if (tasks.length === 0) return null

  return (
    <div className="mb-1 border border-border bg-secondary/25 text-[11px] text-muted-foreground">
      <button
        type="button"
        onClick={() => setExpanded(value => !value)}
        aria-expanded={expanded}
        className="flex w-full items-center gap-2 px-2 py-1.5 text-left hover:bg-secondary/45"
      >
        {expanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
        <span className="flex w-3 shrink-0 items-center justify-center"><Code size={12} className="text-amber-500" aria-hidden="true" /></span>
        <span className="font-medium text-foreground/85">{tasks.length} Queued request{tasks.length !== 1 ? 's' : ''}</span>
      </button>
      {expanded && (
        <div className="border-t border-border">
          <div className="flex items-center gap-2 px-3 py-1.5">
            <span className="min-w-0 truncate text-[10px] text-muted-foreground/70">Requests waiting for current task to complete.</span>
          </div>
          <div className="px-3 py-1.5">
            {tasks.map((task, index) => {
              const editing = editingId === task.id
              return (
                <div key={task.id} className="flex items-center gap-2 py-1.5">
                  <span className="text-muted-foreground/70 w-4">{index + 1}.</span>
                  {editing ? (
                    <input
                      autoFocus
                      value={editingPrompt}
                      onChange={event => setEditingPrompt(event.target.value)}
                      onKeyDown={event => {
                        if (event.key === 'Enter') handleSave(task.id)
                        if (event.key === 'Escape') handleCancel()
                      }}
                      className="min-w-0 flex-1 border border-border bg-background px-1.5 py-1 text-[11px] text-foreground outline-none focus:ring-1 focus:ring-ring/30"
                      aria-label="Edit queued request"
                    />
                  ) : (
                    <span className="min-w-0 flex-1 truncate text-foreground/90">{task.prompt}</span>
                  )}
                  <div className="flex shrink-0 items-center gap-1">
                    {editing ? (
                      <>
                        <button
                          type="button"
                          onClick={() => handleSave(task.id)}
                          className="px-1.5 py-1 text-[10px] hover:bg-secondary rounded"
                        >
                          Save
                        </button>
                        <button
                          type="button"
                          onClick={handleCancel}
                          className="px-1.5 py-1 text-[10px] hover:bg-secondary rounded"
                        >
                          Cancel
                        </button>
                      </>
                    ) : (
                      <>
                        <button
                          type="button"
                          onClick={() => onSteer(task)}
                          className="px-1.5 py-1 text-[10px] hover:bg-secondary rounded"
                          title="Steer this request to input"
                        >
                          Steer
                        </button>
                        <button
                          type="button"
                          onClick={() => handleEdit(task)}
                          className="flex size-6 items-center justify-center hover:bg-secondary rounded"
                          aria-label={`Edit queued request: ${task.prompt}`}
                          title="Edit request"
                        >
                          <FileEdit size={13} />
                        </button>
                        <button
                          type="button"
                          onClick={() => onRemove(task.id)}
                          className="flex size-6 items-center justify-center hover:bg-destructive/30 text-destructive rounded"
                          aria-label="Remove queued request"
                          title="Remove request"
                        >
                          <X size={13} />
                        </button>
                      </>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
