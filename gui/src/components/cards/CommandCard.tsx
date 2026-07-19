import { colors, radii, typography } from '../../theme/theme';

interface CommandCardProps {
  command: string;
  stdout?: string;
  stderr?: string;
  exitCode?: number;
  status?: string;
  durationMs?: number;
}

export function CommandCard({ command, stdout, stderr, exitCode, status, durationMs }: CommandCardProps) {
  const isError = status === 'error' || (exitCode != null && exitCode !== 0);
  const isRunning = status === 'running';
  return (
    <div style={{
      background: isError ? colors.card.error.bg : colors.card.command.bg,
      border: `1px solid ${isError ? colors.card.error.border : colors.card.command.border}`,
      borderRadius: radii.lg,
      padding: '10px 14px',
      marginBottom: 8,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
        <span style={{ fontSize: 14 }}>{isError ? '❌' : isRunning ? '⏳' : isError ? '⚠️' : '💻'}</span>
        <code style={{
          color: isError ? colors.accent.red : colors.accent.green,
          fontFamily: typography.fontMono,
          fontSize: typography.sizes.sm,
          fontWeight: typography.weights.medium,
        }}>
          {command}
        </code>
        {durationMs != null && (
          <span style={{ color: colors.text.dim, fontSize: typography.sizes.xs, marginLeft: 'auto' }}>
            {durationMs}ms
          </span>
        )}
      </div>
      {stderr && (
        <div style={{
          background: 'rgba(239, 68, 68, 0.1)',
          border: `1px solid ${colors.card.error.border}`,
          borderRadius: radii.sm,
          padding: '6px 10px',
          marginTop: 4,
          color: colors.accent.red,
          fontFamily: typography.fontMono,
          fontSize: typography.sizes.xs,
          whiteSpace: 'pre-wrap',
          maxHeight: 100,
          overflow: 'auto',
        }}>
          {stderr}
        </div>
      )}
      {stdout && (
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
          maxHeight: 150,
          overflow: 'auto',
        }}>
          {stdout}
        </div>
      )}
      {exitCode != null && (
        <div style={{ marginTop: 4, color: exitCode === 0 ? colors.accent.green : colors.accent.red, fontSize: typography.sizes.xs }}>
          Exit code: {exitCode}
        </div>
      )}
    </div>
  );
}
