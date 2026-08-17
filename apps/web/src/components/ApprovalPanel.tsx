import { useState } from 'react'
import { ShieldAlert, Check, X, Bookmark } from 'lucide-react'

export interface ApprovalPanelProps {
  tool: string
  action: string
  onRespond: (decision: 'yes' | 'no' | 'save') => void
}

const OPTIONS: Array<{ key: 'yes' | 'no' | 'save'; label: string; hint: string; icon: JSX.Element; tone: string }> = [
  { key: 'yes', label: 'Yes', hint: 'Run once', icon: <Check size={15} />, tone: 'text-emerald-300' },
  { key: 'no', label: 'No', hint: 'Deny', icon: <X size={15} />, tone: 'text-rose-300' },
  { key: 'save', label: 'Yes & save', hint: 'Run + add to allowlist', icon: <Bookmark size={15} />, tone: 'text-amber-300' },
]

/**
 * Co-Pilot (ask mode) interactive tool-approval prompt.
 * Mirrors the TUI ApprovalPanelBody: three choices, including
 * "Yes & save" which runs the command and remembers it for next time.
 */
export default function ApprovalPanel({ tool, action, onRespond }: ApprovalPanelProps) {
  const [selected, setSelected] = useState(0)

  return (
    <div className="mx-auto w-full px-4 pb-2" style={{ maxWidth: 'var(--composer-width)' }}>
      <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-3">
        <div className="flex items-center gap-2 mb-2">
          <ShieldAlert size={16} className="text-amber-300" />
          <span className="text-sm font-semibold text-amber-200">Approval required (Co-Pilot)</span>
        </div>
        <div className="text-xs text-muted-foreground mb-1">
          Run <span className="text-foreground font-medium">{tool}</span>?
        </div>
        {action ? (
          <pre className="text-[11px] leading-snug text-muted-foreground bg-black/20 border border-border/40 rounded-md p-2 mb-3 whitespace-pre-wrap break-words max-h-32 overflow-auto">
{action.length > 400 ? `${action.slice(0, 400)}…` : action}
          </pre>
        ) : null}

        <div className="flex flex-col gap-1.5">
          {OPTIONS.map((opt, i) => (
            <button
              key={opt.key}
              onClick={() => onRespond(opt.key)}
              onMouseEnter={() => setSelected(i)}
              className={`w-full flex items-center gap-2 rounded-lg px-3 py-2 text-left text-sm border transition ${
                selected === i
                  ? 'border-amber-400/50 bg-amber-400/10 ' + opt.tone
                  : 'border-border/40 bg-secondary/40 text-foreground/80 hover:bg-secondary/70'
              }`}
            >
              <span className={opt.tone}>{opt.icon}</span>
              <span className="font-medium">{opt.label}</span>
              <span className="text-xs text-muted-foreground">— {opt.hint}</span>
              <span className="ml-auto text-[10px] text-muted-foreground/60">{i + 1}</span>
            </button>
          ))}
        </div>
        <div className="mt-2 text-[10px] text-muted-foreground/60">
          Click an option, or press 1 / 2 / 3
        </div>
      </div>
    </div>
  )
}
