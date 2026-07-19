import React from 'react';
import { clsx } from 'clsx';
import { FileMinus, FilePlus, Copy, Check } from 'lucide-react';

interface DiffViewerProps {
    diffString: string;
    filename?: string;
    onApply?: () => void;
    onReject?: () => void;
}

export function DiffViewer({ diffString, filename, onApply, onReject }: DiffViewerProps) {
    const [copied, setCopied] = React.useState(false);

    // Basic parser for unified diff strings
    const lines = (diffString || '').split('\n');
    const hasAdditions = lines.some(line => line.startsWith('+') && !line.startsWith('+++'));
    const hasDeletions = lines.some(line => line.startsWith('-') && !line.startsWith('---'));

    const parsedLines = lines.map((line, idx) => {
        const isAddition = line.startsWith('+') && !line.startsWith('+++');
        const isDeletion = line.startsWith('-') && !line.startsWith('---');
        const isHeader = line.startsWith('@@') || line.startsWith('---') || line.startsWith('+++');

        return {
            content: line,
            type: isAddition ? 'addition' : isDeletion ? 'deletion' : isHeader ? 'header' : 'context',
            id: idx
        };
    });

    const handleCopy = () => {
        navigator.clipboard.writeText(diffString);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
    };

    return (
        <div className="w-full bg-[#111111] rounded-lg border border-white/10 overflow-hidden flex flex-col font-mono text-sm shadow-xl shadow-black/50 my-2">
            {/* Header */}
            <div className="flex items-center justify-between px-4 py-2 bg-black/40 border-b border-white/5">
                <div className="flex items-center gap-3">
                    <div className="flex items-center gap-1.5 px-2 py-0.5 rounded bg-[#1A1A1A] text-xs font-semibold text-white/70">
                        <span className="text-emerald-400"><FilePlus className="w-3 h-3 inline mr-1" />{hasAdditions ? 'Additions' : ''}</span>
                        <span className="text-rose-400 ml-2"><FileMinus className="w-3 h-3 inline mr-1" />{hasDeletions ? 'Deletions' : ''}</span>
                    </div>
                    {filename && <span className="text-white/80 text-xs truncate max-w-[200px]" title={filename}>{filename}</span>}
                </div>
                <div className="flex items-center gap-2">
                    <button 
                        onClick={handleCopy}
                        className="p-1.5 hover:bg-white/10 rounded text-white/50 hover:text-white transition-colors"
                        title="Copy Diff"
                    >
                        {copied ? <Check className="w-4 h-4 text-emerald-400" /> : <Copy className="w-4 h-4" />}
                    </button>
                    {onApply && (
                        <button 
                            onClick={onApply}
                            className="px-3 py-1 bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-400 rounded text-xs font-semibold transition-colors border border-emerald-500/30"
                        >
                            Apply
                        </button>
                    )}
                    {onReject && (
                        <button 
                            onClick={onReject}
                            className="px-3 py-1 bg-rose-500/20 hover:bg-rose-500/30 text-rose-400 rounded text-xs font-semibold transition-colors border border-rose-500/30"
                        >
                            Reject
                        </button>
                    )}
                </div>
            </div>

            {/* Code Content */}
            <div className="overflow-x-auto max-h-[400px] overflow-y-auto">
                <table className="w-full text-left border-collapse">
                    <tbody>
                        {parsedLines.map((line) => (
                            <tr 
                                key={line.id} 
                                className={clsx(
                                    "hover:bg-white/5 transition-colors",
                                    line.type === 'addition' && "bg-emerald-500/10 text-emerald-300",
                                    line.type === 'deletion' && "bg-rose-500/10 text-rose-300",
                                    line.type === 'header' && "bg-blue-500/10 text-blue-300 italic opacity-80",
                                    line.type === 'context' && "text-white/60"
                                )}
                            >
                                <td className="w-8 select-none text-right pr-4 text-white/20 border-r border-white/5 py-0.5 text-[11px]">
                                    {line.type === 'addition' ? '+' : line.type === 'deletion' ? '-' : ''}
                                </td>
                                <td className="px-4 py-0.5 whitespace-pre font-mono text-[13px] leading-relaxed">
                                    {line.content}
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
}
