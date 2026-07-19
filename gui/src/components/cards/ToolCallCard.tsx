import { colors, radii, typography } from '../../theme/theme';

interface ToolCallCardProps {
  tool: string;
  args?: string;
  result?: string;
  status?: string;
  durationMs?: number;
}

export function ToolCallCard({ tool, args, result, status, durationMs }: ToolCallCardProps) {
  const isError = status === 'error';
  const isRunning = status === 'running' || status === 'started';
  const isDone = status === 'done' || status === 'success';
  return (
    <div style={{
      background: isError ? colors.card.error.bg : colors.card.tool.bg,
      border: `1px solid ${isError ? colors.card.error.border : colors.card.tool.border}`,
      borderRadius: radii.lg,
      padding: '10px 14px',
      marginBottom: 8,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
        <span style={{ fontSize: 14 }}>{isError ? '❌' : isRunning ? '⏳' : '🔧'}</span>
        <span style={{
          color: isError ? colors.accent.red : colors.accent.purple,
          fontFamily: typography.fontFamily,
          fontSize: typography.sizes.sm,
          fontWeight: typography.weights.medium,
        }}>
          {tool}
        </span>
        {durationMs != null && (
          <span style={{ color: colors.text.dim, fontSize: typography.sizes.xs, marginLeft: 'auto' }}>
            {durationMs}ms
          </span>
        )}
      </div>
      {args && (
        <div style={{
          background: colors.work.codeBg,
          border: `1px solid ${colors.work.codeBorder}`,
          borderRadius: radii.sm,
          padding: '6px 10px',
          marginTop: 4,
          color: colors.work.codeText,
          fontFamily: typography.fontMono,
          fontSize: typography.sizes.xs,
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-all',
          maxHeight: 120,
          overflow: 'auto',
        }}>
          {args}
        </div>
      )}
      {result && isDone && (
        <div style={{
          color: colors.work.muted,
          fontFamily: typography.fontMono,
          fontSize: typography.sizes.xs,
          marginTop: 4,
          whiteSpace: 'pre-wrap',
          maxHeight: 80,
          overflow: 'auto',
        }}>
          {result}
        </div>
      )}
    </div>
  );
}
