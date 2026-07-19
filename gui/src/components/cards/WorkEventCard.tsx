import type { WorkEvent } from '../../types';
import { colors, radii, typography } from '../../theme/theme';
import { PlanningCard } from './PlanningCard';
import { ToolCallCard } from './ToolCallCard';
import { CommandCard } from './CommandCard';
import { FileEditCard } from './FileEditCard';
import { ErrorCard } from './ErrorCard';
import { AgentStateCard } from './AgentStateCard';

interface WorkEventCardProps {
  event: WorkEvent;
  compact?: boolean;
}

function getEventKind(event: WorkEvent): string {
  return String(event.kind || event.type || event.event_type || '').toLowerCase();
}

function parseSteps(event: WorkEvent): string[] | undefined {
  const preview = event.preview || event.output || event.result || '';
  if (!preview) return undefined;
  const lines = preview.split('\n').filter(l => l.trim().startsWith('-') || l.trim().match(/^\d+\./));
  return lines.length > 0 ? lines.map(l => l.replace(/^[-*\d.]+\s*/, '').trim()).filter(Boolean) : undefined;
}

export function WorkEventCard({ event, compact }: WorkEventCardProps) {
  const kind = getEventKind(event);
  const status = String(event.status || '').toLowerCase();

  if (kind === 'plan' || kind === 'planning' || kind === 'todo') {
    return (
      <PlanningCard
        title={event.title || event.action || 'Plan'}
        steps={parseSteps(event)}
        done={status === 'done' || status === 'completed'}
      />
    );
  }

  if (kind === 'tool' || kind === 'tool_call' || kind === 'function_call') {
    return (
      <ToolCallCard
        tool={String(event.tool || event.name || event.action || 'tool')}
        args={typeof event.args === 'string' ? event.args : event.args ? JSON.stringify(event.args, null, 2) : undefined}
        result={event.result || event.output}
        status={status}
        durationMs={event.duration_ms}
      />
    );
  }

  if (kind === 'command' || kind === 'run' || kind === 'bash') {
    return (
      <CommandCard
        command={String(event.command || event.target || event.action || '')}
        stdout={event.stdout || event.output}
        stderr={event.stderr}
        exitCode={event.exit_code}
        status={status}
        durationMs={event.duration_ms}
      />
    );
  }

  if (kind === 'file' || kind === 'file_edit' || kind === 'write' || kind === 'read') {
    return (
      <FileEditCard
        path={String(event.path || event.target || '')}
        action={event.action || kind}
        diff={event.diff || event.patch}
        preview={event.preview}
        status={status}
      />
    );
  }

  if (kind === 'error' || kind === 'failure' || status === 'error') {
    return (
      <ErrorCard
        title={event.title || event.action}
        message={event.result || event.output || event.stderr || event.error || 'Unknown error'}
        detail={event.preview || event.detail}
      />
    );
  }

  if (kind === 'agent' || kind === 'subagent' || kind === 'state' || kind === 'thinking' || kind === 'reasoning') {
    return (
      <AgentStateCard
        phase={event.phase || event.action || event.title}
        status={status}
        thought={event.thought || event.output || event.result}
        model={event.model}
        mode={event.mode}
      />
    );
  }

  if (kind === 'browser' || kind === 'search' || kind === 'web') {
    return (
      <div style={{
        background: colors.card.search.bg,
        border: `1px solid ${colors.card.search.border}`,
        borderRadius: radii.lg,
        padding: '10px 14px',
        marginBottom: 8,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
          <span style={{ fontSize: 14 }}>{kind === 'search' ? '🔍' : '🌐'}</span>
          <span style={{
            color: colors.card.search.icon,
            fontFamily: typography.fontFamily,
            fontSize: typography.sizes.sm,
            fontWeight: typography.weights.medium,
          }}>
            {event.action || event.title || (kind === 'search' ? 'Search' : 'Browse')}
          </span>
          {event.target && (
            <span style={{
              color: colors.text.dim,
              fontSize: typography.sizes.xs,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
              maxWidth: 200,
            }}>
              {event.target}
            </span>
          )}
        </div>
        {event.result && (
          <div style={{
            color: colors.text.muted,
            fontSize: typography.sizes.xs,
            whiteSpace: 'pre-wrap',
            maxHeight: 80,
            overflow: 'auto',
          }}>
            {event.result}
          </div>
        )}
      </div>
    );
  }

  if (kind === 'mcp' || kind === 'mcp_server') {
    return (
      <div style={{
        background: colors.card.mcp.bg,
        border: `1px solid ${colors.card.mcp.border}`,
        borderRadius: radii.lg,
        padding: '10px 14px',
        marginBottom: 8,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 14 }}>🔌</span>
          <span style={{
            color: colors.card.mcp.icon,
            fontFamily: typography.fontFamily,
            fontSize: typography.sizes.sm,
            fontWeight: typography.weights.medium,
          }}>
            {event.server || event.name || event.action || 'MCP'}
          </span>
          {event.tool && (
            <span style={{ color: colors.text.dim, fontSize: typography.sizes.xs }}>
              → {event.tool}
            </span>
          )}
        </div>
      </div>
    );
  }

  if (kind === 'reflection' || kind === 'think') {
    return (
      <AgentStateCard
        phase="Reflection"
        status={status}
        thought={event.output || event.result || event.preview}
      />
    );
  }

  if (compact) {
    return (
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: 6,
        padding: '4px 8px',
        color: colors.text.muted,
        fontSize: typography.sizes.xs,
        fontFamily: typography.fontMono,
        borderBottom: `1px solid ${colors.border.dim}`,
      }}>
        <span>{status === 'running' || status === 'started' ? '⋯' : '•'}</span>
        <span>{event.action || event.kind || event.type || 'event'}</span>
        {event.target && <span style={{ color: colors.text.dim }}>{event.target}</span>}
      </div>
    );
  }

  return (
    <div style={{
      background: colors.work.bg,
      border: `1px solid ${colors.work.border}`,
      borderRadius: radii.lg,
      padding: '10px 14px',
      marginBottom: 8,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 2 }}>
        <span style={{ fontSize: 14 }}>📋</span>
        <span style={{
          color: colors.work.text,
          fontFamily: typography.fontMono,
          fontSize: typography.sizes.xs,
        }}>
          {event.action || event.kind || event.type || 'Work Event'}
        </span>
        {event.target && (
          <span style={{ color: colors.text.dim, fontSize: typography.sizes.xs, marginLeft: 8 }}>
            {event.target}
          </span>
        )}
      </div>
      {event.output && (
        <div style={{
          color: colors.work.muted,
          fontSize: typography.sizes.xs,
          whiteSpace: 'pre-wrap',
          maxHeight: 60,
          overflow: 'auto',
          marginTop: 2,
        }}>
          {event.output}
        </div>
      )}
    </div>
  );
}
