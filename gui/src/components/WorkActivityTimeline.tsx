import {
   ChevronDown, ChevronRight,
   TerminalSquare, Edit2, RefreshCw, Eye, Trash2, PlusCircle,
   Search, BrainCircuit, Database, Brain, CheckCircle2,
   FolderOpen, ShieldAlert, RotateCcw, GraduationCap, Puzzle,
   Users, HeartPulse
} from 'lucide-react'
import { useMemo, useState } from 'react'
import type { ComponentType } from 'react'
import type { ChatMessage, WorkEvent } from '../types'

type WorkActivityTimelineProps = {
   allWorkActivities: WorkEvent[]
   collapseWorkActivities: (rows: WorkEvent[]) => WorkEvent[]
   getWorkActivityIcon: (kind?: string) => ComponentType<{ size?: number }>
   getWorkActivityLabel: (row: WorkEvent) => string
   getWorkActivityTarget: (row: WorkEvent) => string
   isPlanningArtifact: (row: WorkEvent) => boolean
   messages: ChatMessage[]
   openWorkEvent: (event: WorkEvent, playbackIndex?: number) => void
   phaseLabel?: string
   rows: WorkEvent[]
   compact?: boolean
}

const rowKind = (row: WorkEvent) => String(row.kind || row.type || 'tool').toLowerCase();
const rowStatus = (row: WorkEvent) => String(row.status || '').toLowerCase();
const isDoneStatus = (status: string) => status === 'done' || status === 'completed' || status === 'success';
const isRunningStatus = (status: string) => status === 'running' || status === 'working';
const isErrorStatus = (status: string) => status === 'error' || status === 'failed' || status === 'failure';

export function WorkActivityTimeline({
   allWorkActivities,
   collapseWorkActivities,
   compact,
   getWorkActivityIcon,
   getWorkActivityLabel,
   getWorkActivityTarget,
   isPlanningArtifact,
   messages,
   openWorkEvent,
   phaseLabel,
   rows,
}: WorkActivityTimelineProps) {
   const [collapsedTimeline, setCollapsedTimeline] = useState(false);

   const timeline = useMemo(() => {
      const collapsedRows = collapseWorkActivities(rows);
      const compactLimit = compact ? 8 : 18;
      const planRows = collapsedRows
         .filter(row => rowKind(row) === 'todo' && Number(row.phase_index))
         .sort((a, b) => (Number(a.phase_index) || 999) - (Number(b.phase_index) || 999));
      const tailRows = collapsedRows.slice(-compactLimit);
      const compactRows = Array.from(
         new Map([...planRows, ...tailRows].map(row => [
            row.id || `${row.kind}|${row.phase_index || ''}|${row.phase || ''}|${getWorkActivityTarget(row)}`,
            row,
         ])).values()
      );

      // Sort helper: use position in allWorkActivities (real order, same as canvas slider)
      const realOrder = (row: WorkEvent): number => {
         const idx = allWorkActivities.findIndex(item =>
            item.id && row.id ? item.id === row.id : item === row
         );
         // Fallback to created_at if not found in allWorkActivities
         return idx >= 0 ? idx : (Number(row.created_at) || 999999);
      };

      const chronologicalRows = compactRows.sort((a, b) => realOrder(a) - realOrder(b));

      return { chronologicalRows, compactRows, planRows, realOrder };
   }, [allWorkActivities, collapseWorkActivities, compact, getWorkActivityTarget, rows]);

   const { chronologicalRows, compactRows, planRows } = timeline;
   if (compactRows.length === 0) return null;

   const hasPlannedPhases = planRows.length > 0;
   // Bubbles in same order as canvas slider — position in allWorkActivities is the source of truth
   const visibleRowsWithoutPlanning = chronologicalRows.filter(row => !isPlanningArtifact(row));
   const hasRunning = compactRows.some(row => isRunningStatus(rowStatus(row)));

   const headingLabel = phaseLabel || (hasRunning ? 'Realtime work' : 'Completed work');

   const taskName = useMemo(() => {
      const fromRows = rows.find(r => r.task);
      if (fromRows && fromRows.task) return fromRows.task;
      const fromAll = allWorkActivities.find(r => r.task);
      if (fromAll && fromAll.task) return fromAll.task;
      return '';
   }, [rows, allWorkActivities]);

   const isResumedTask = useMemo(() => (
      rows.some(row => row.resumed || row.resumed_from_turn_id || row.resume_label) ||
      allWorkActivities.some(row => row.resumed || row.resumed_from_turn_id || row.resume_label)
   ), [rows, allWorkActivities]);

   const headingLabelElement = useMemo(() => {
      if (taskName) {
         return (
            <span className="workflow-heading-title">
               {isResumedTask && <span className="workflow-kicker">Continuing</span>}
               <span>{taskName}</span>
            </span>
         );
      }
      return <span>{headingLabel}</span>;
   }, [headingLabel, isResumedTask, taskName]);

   const findPlaybackIndex = (row: WorkEvent) => {
      const timelineWorkActivities = allWorkActivities
         .filter(item => !isPlanningArtifact(item));
         
      const byId = row.id ? timelineWorkActivities.findIndex(item => item.id && item.id === row.id) : -1;
      if (byId >= 0) return byId;
      const target = getWorkActivityTarget(row);
      const kind = rowKind(row);
      const byShape = timelineWorkActivities.findIndex(item => rowKind(item) === kind && getWorkActivityTarget(item) === target);
      return Math.max(0, byShape);
   };

   const openThinking = () => {
      const latestAssistant = [...messages].reverse().find(message => message.role === 'assistant');
      let thinkingText = 'No captured reasoning yet.';
      if (latestAssistant && latestAssistant.content) {
         const thinkingLines = latestAssistant.content.split('\n')
            .filter(line => {
               const trim = line.trim();
               return trim.startsWith('[THINKING:') || trim.startsWith('[NEXUS_BOOT]');
            })
            .map(line => {
               const match = line.match(/^\[(?:THINKING:[^\]]*|NEXUS_BOOT)\](.*)/i);
               return match ? match[1].trim() : line;
            })
            .filter(Boolean);
         if (thinkingLines.length > 0) thinkingText = thinkingLines.join('\n');
      }
      openWorkEvent({
         id: 'evt_thinking_virtual',
         kind: 'reflection',
         type: 'reflection',
         action: 'Thinking',
         title: 'Thinking',
         target: 'Reasoning Log',
         name: 'thinking',
         lang: 'thinking',
         status: 'running',
         preview: thinkingText,
      });
   };

   const renderActionRow = (row: WorkEvent, index: number, extraClass = '') => {
      const kind = rowKind(row);
      const targetLabel = getWorkActivityTarget(row);
      const planningFile = isPlanningArtifact(row);
      const subItems = Array.isArray(row.items)
         ? row.items.map(item => String(item || '').trim()).filter(Boolean)
         : [];
      const visibleSubItems = kind === 'todo' || planningFile
         ? []
         : subItems.filter(item => item !== targetLabel && item !== row.action && item !== row.title).slice(0, 5);
      const status = rowStatus(row);
      const rowDone = isDoneStatus(status);
      const rowError = isErrorStatus(status);
      const rowRunning = isRunningStatus(status);
      const rowDeleted = status === 'deleted' || String(row.operation || '').toLowerCase() === 'delete';

      const resolvedActivityClass = (() => {
         const k = String(row.kind || row.type || '').toLowerCase();
         const act = String(row.action || row.title || row.tool || '').toLowerCase();
         
         if (k === 'todo' || k === 'planning' || planningFile) return 'todo';
         
         if (k === 'file') {
            if (act.includes('delete') || act.includes('remove')) return 'file-delete';
            if (act.includes('create')) return 'file-create';
            if (act.includes('read') || act.includes('view')) return 'file-read';
            if (act.includes('replace')) return 'file-replace';
            return 'file-edit';
         }
         
         if (k === 'command' || k === 'bash' || k === 'exec' || k === 'terminal' || k === 'shell' || k === 'cmd' || k === 'health' || act.includes('run_command') || act.includes('command') || act.includes('terminal') || act.includes('shell') || act.includes('health')) return 'command';
         
         if (k === 'search' || k === 'browser' || act.includes('search_web') || act.includes('browser')) return 'search';
         
         if (k === 'rag' || k === 'kb' || k === 'knowledge' || act.includes('rag') || act.includes('knowledge')) return 'rag';
         
         if (k === 'mcp' || k === 'mpc' || k === 'mcp-tool' || act.startsWith('mcp_') || act.includes('mcp') || act.includes('mpc')) return 'mcp';
         
         if (k === 'reflection' || k === 'thought' || k === 'thinking' || act.includes('reflection') || act.includes('thinking')) return 'reflection';
         
         if (k === 'location' || k === 'cd' || k === 'folder' || act.includes('cd') || act.includes('location_change') || act.includes('cwd') || act.includes('directory')) return 'location';
         
         if (k === 'test' || k === 'pytest' || k === 'diagnostic' || act.includes('test') || act.includes('pytest') || act.includes('diagnostic')) return 'test';
         
         if (k === 'rollback' || k === 'patch' || act.includes('rollback') || act.includes('patch')) return 'rollback';
         
         if (k === 'skill' || k === 'plugin' || act.includes('skill') || act.includes('plugin')) return 'skill';
         
         if (k === 'hive' || k === 'delegate' || k === 'handoff' || act.includes('hive') || act.includes('delegate') || act.includes('handoff')) return 'hive';
         
         return k || 'tool';
      })();

      const ActivityIcon = (() => {
         switch (resolvedActivityClass) {
            case 'command': return TerminalSquare;
            case 'file-edit': return Edit2;
            case 'file-replace': return RefreshCw;
            case 'file-read': return Eye;
            case 'file-delete': return Trash2;
            case 'file-create': return PlusCircle;
            case 'search': return Search;
            case 'rag': return BrainCircuit;
            case 'mcp': return Database;
            case 'reflection': return Brain;
            case 'todo': return CheckCircle2;
            case 'location': return FolderOpen;
            case 'test': return ShieldAlert;
            case 'rollback': return RotateCcw;
            case 'skill': return GraduationCap;
            case 'plugin': return Puzzle;
            case 'hive': return Users;
            case 'health': return HeartPulse;
            default: return getWorkActivityIcon(row.kind || row.type);
         }
      })();

      return (
         <button
            type="button"
            className={`work-row lemon-row ${resolvedActivityClass} ${kind === 'todo' ? 'phase-action' : 'child-action'} ${row.status || 'done'} ${rowDeleted ? 'deleted' : ''} ${rowRunning ? 'running' : ''} ${planningFile ? 'plan-file' : ''} ${extraClass}`}
            key={row.id || `${row.tool || row.action || row.title}-${targetLabel}-${index}`}
            onClick={() => openWorkEvent(row, findPlaybackIndex(row))}
         >
            <span className="work-row-icon"><ActivityIcon size={14} /></span>
            <span className="work-row-main">
               <span className="work-row-headline">
                  <span className="work-row-action">{getWorkActivityLabel(row)}</span>
                  <code title={targetLabel}>{targetLabel}</code>
               </span>
               {visibleSubItems.length > 0 && (
                  <span className="work-subtasks">
                     {visibleSubItems.map((item, subIndex) => (
                        <span className="work-subtask" key={`${item}-${subIndex}`}>
                           <span>{rowDeleted ? '-' : rowError ? '!' : rowDone ? '✓' : rowRunning ? '...' : '•'}</span>
                           <span>{item}</span>
                        </span>
                     ))}
                  </span>
               )}
            </span>
         </button>
      );
   };

   const renderThinkingRow = (label = 'Thinking', planRow?: WorkEvent) => {
      const ActivityIcon = label === 'Planning' ? CheckCircle2 : Brain;
      return (
         <button
            type="button"
            className={`work-row lemon-row child-action running ${label === 'Planning' ? 'todo plan-file' : 'reflection thinking-row'}`}
            onClick={label === 'Planning' && planRow ? () => openWorkEvent(planRow, findPlaybackIndex(planRow)) : openThinking}
         >
            <span className="work-row-icon"><ActivityIcon size={14} /></span>
            <span className="work-row-main">
               <span className="work-row-headline">
                  <span className="work-row-action">{label}</span>
                  <code>next action</code>
               </span>
            </span>
         </button>
      );
   };


   if (!hasPlannedPhases) {
      if (visibleRowsWithoutPlanning.length === 0 && !hasRunning) return null;
      return (
         <div className={`work-timeline direct-work-timeline ${collapsedTimeline ? 'collapsed' : ''} ${compact ? 'canvas-work-timeline' : ''}`}>
            <button
               type="button"
               className="work-direct-head"
               onClick={() => setCollapsedTimeline(!collapsedTimeline)}
               style={{
                  cursor: 'pointer',
                  width: '100%',
                  border: 'none',
                  background: 'transparent',
                  textAlign: 'left',
                  padding: 0
               }}
            >
               <span className="work-phase-dot">{hasRunning ? '...' : '✓'}</span>
               {headingLabelElement}
               {collapsedTimeline ? <ChevronRight size={13} style={{ opacity: 0.6 }} /> : <ChevronDown size={13} style={{ opacity: 0.6 }} />}
            </button>
            {!collapsedTimeline && (
               <div className="work-rows direct-work-rows">
                  {visibleRowsWithoutPlanning.length > 0
                     ? visibleRowsWithoutPlanning.map((row, index) => renderActionRow(row, index, 'direct-action'))
                     : renderThinkingRow()}
               </div>
            )}
         </div>
      );
   }

   return (
      <div className={`work-timeline direct-work-timeline ${collapsedTimeline ? 'collapsed' : ''} ${compact ? 'canvas-work-timeline' : ''}`}>
         <button
            type="button"
            className="work-direct-head"
            onClick={() => setCollapsedTimeline(!collapsedTimeline)}
            style={{
               cursor: 'pointer',
               width: '100%',
               border: 'none',
               background: 'transparent',
               textAlign: 'left',
               padding: 0
            }}
         >
            <span className="work-phase-dot">{hasRunning ? '...' : '✓'}</span>
            {headingLabelElement}
            {collapsedTimeline ? <ChevronRight size={13} style={{ opacity: 0.6 }} /> : <ChevronDown size={13} style={{ opacity: 0.6 }} />}
         </button>
         {!collapsedTimeline && (
            <div className="work-rows direct-work-rows">
               {visibleRowsWithoutPlanning.length > 0
                  ? visibleRowsWithoutPlanning.map((row, index) => renderActionRow(row, index, 'direct-action'))
                  : renderThinkingRow()}
            </div>
         )}
      </div>
   );
}
