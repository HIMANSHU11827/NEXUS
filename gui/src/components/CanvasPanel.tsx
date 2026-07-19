import type { CSSProperties, ReactNode } from 'react';
import { Copy, Edit2, Maximize2, SkipBack, SkipForward, Play, Pause, Terminal, Globe, Cpu, Brain } from 'lucide-react';
import type { WorkEvent } from '../types';

type CanvasPanelProps = {
  canvasPlaybackTime: number | null;
  isPlaying: boolean;
  setIsPlaying: (playing: boolean) => void;
  activePlaybackIndex: number;
  allWorkActivities: WorkEvent[];
  canvasCanRunHtml: boolean;
  canvasEditorCode: string;
  canvasEditorLang: string;
  canvasEditorLineCount: number;
  canvasFileName: string;
  canvasFileStatus: string;
  canvasProgress: number;
  canvasStatusText: string;
  canvasViewMode: 'source' | 'preview';
  isCanvasRealtime: boolean;
  renderCanvasMain: () => ReactNode;
  setCanvasPlaybackTime: (time: number | null) => void;
  setCanvasViewMode: (mode: 'source' | 'preview') => void;
  setSelectedWorkEvent: (event: WorkEvent | null) => void;
};

const canvasTrackStyle = (progress: number): CSSProperties => ({
  ['--canvas-progress' as string]: `${progress}%`,
});

export function CanvasPanel({
  canvasPlaybackTime,
  isPlaying,
  setIsPlaying,
  activePlaybackIndex,
  allWorkActivities,
  canvasCanRunHtml,
  canvasEditorCode,
  canvasEditorLang,
  canvasEditorLineCount,
  canvasFileName,
  canvasFileStatus,
  canvasProgress,
  canvasStatusText,
  canvasViewMode,
  isCanvasRealtime,
  renderCanvasMain,
  setCanvasPlaybackTime,
  setCanvasViewMode,
  setSelectedWorkEvent,
}: CanvasPanelProps) {
  const returnToRealtime = () => {
    setSelectedWorkEvent(null);
    setCanvasPlaybackTime(null);
    setIsPlaying(false);
  };

  return (
    <div className="canvas-panel" data-viewmode={canvasViewMode} data-has-setter={!!setCanvasViewMode}>
      <div className="canvas-computer-head">
        <div className="canvas-app-icon">
          {(() => {
            const text = canvasStatusText.toLowerCase();
            if (text.includes('terminal')) return <Terminal size={20} />;
            if (text.includes('browser')) return <Globe size={20} />;
            if (text.includes('mcp')) return <Cpu size={20} />;
            if (text.includes('planning') || text.includes('thinking')) return <Brain size={20} />;
            return <Edit2 size={20} />;
          })()}
        </div>
        <div>
          <div className="canvas-computer-title">{canvasStatusText}</div>
          <div className="canvas-file-pill">{canvasFileStatus}</div>
        </div>
      </div>

      <div className="canvas-editor-window">
        <div className="canvas-editor-titlebar">
          <span>{canvasFileName}</span>
          <div className="canvas-editor-actions">
            <button type="button" onClick={() => navigator.clipboard.writeText(canvasEditorCode)} title="Copy visible file" aria-label="Copy visible file"><Copy size={14} /></button>
            {canvasCanRunHtml && (
              <button type="button" aria-label="Open HTML preview in browser" onClick={() => {
                const blob = new Blob([canvasEditorCode], { type: 'text/html' });
                const url = URL.createObjectURL(blob);
                window.open(url, '_blank', 'noopener,noreferrer');
                window.setTimeout(() => URL.revokeObjectURL(url), 30000);
              }} title="Open preview in browser"><Maximize2 size={14} /></button>
            )}
          </div>
        </div>
        {renderCanvasMain()}
        {canvasPlaybackTime !== null && (
          <button
            type="button"
            className="canvas-floating-jump"
            onClick={returnToRealtime}
            title="Jump back to live activity"
            aria-label="Jump back to live activity"
          >
            Jump to Realtime
          </button>
        )}
        <div className="canvas-editor-footer" data-lang={canvasEditorLang} data-lines={canvasEditorLineCount}>
          <div className="canvas-playback-controls">
            <button
              type="button"
              className="canvas-playback-btn"
              title="Previous activity"
              aria-label="Previous activity"
              disabled={allWorkActivities.length === 0}
              onClick={() => {
                setSelectedWorkEvent(null);
                const prevIndex = Math.max(0, activePlaybackIndex - 1);
                setCanvasPlaybackTime(prevIndex);
              }}
            >
              <SkipBack size={15} />
            </button>
            <button
              type="button"
              className="canvas-playback-btn"
              title={isPlaying ? "Pause" : "Play"}
              aria-label={isPlaying ? "Pause activity replay" : "Play activity replay"}
              disabled={allWorkActivities.length === 0}
              onClick={() => {
                if (!isPlaying) {
                  setSelectedWorkEvent(null);
                }
                setIsPlaying(!isPlaying);
              }}
            >
              {isPlaying ? <Pause size={15} /> : <Play size={15} />}
            </button>
            <button
              type="button"
              className="canvas-playback-btn"
              title="Next activity"
              aria-label="Next activity"
              disabled={allWorkActivities.length === 0 || activePlaybackIndex >= allWorkActivities.length - 1}
              onClick={() => {
                setSelectedWorkEvent(null);
                const nextIndex = Math.min(allWorkActivities.length - 1, activePlaybackIndex + 1);
                setCanvasPlaybackTime(nextIndex);
              }}
            >
              <SkipForward size={15} />
            </button>
          </div>
          <input
            className="canvas-track"
            type="range"
            min={0}
            max={Math.max(1, allWorkActivities.length - 1)}
            step={1}
            value={canvasPlaybackTime !== null ? canvasPlaybackTime : Math.max(0, allWorkActivities.length - 1)}
            disabled={allWorkActivities.length === 0}
            onChange={(event) => {
              setSelectedWorkEvent(null);
              setIsPlaying(false);
              setCanvasPlaybackTime(Number(event.target.value));
            }}
            style={canvasTrackStyle(canvasProgress)}
            aria-label="Canvas activity playback"
          />
          <div className={`canvas-status-indicator ${isCanvasRealtime ? 'realtime' : 'playback'}`}>
            <span className="status-dot"></span>
            <span className="status-text">
              {isCanvasRealtime 
                ? 'Realtime' 
                : `Event ${Math.min(allWorkActivities.length, Math.floor(canvasPlaybackTime ?? 0) + 1)} of ${allWorkActivities.length}`}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
