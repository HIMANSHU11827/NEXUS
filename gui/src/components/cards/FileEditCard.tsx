import { colors, radii, typography } from '../../theme/theme';

interface FileEditCardProps {
  path: string;
  action?: string;
  diff?: string;
  preview?: string;
  status?: string;
}

export function FileEditCard({ path, action, diff, preview, status }: FileEditCardProps) {
  const isError = status === 'error';
  const isNew = action === 'create' || action === 'write';
  const isDelete = action === 'delete';
  const icon = isError ? '❌' : isDelete ? '🗑️' : isNew ? '✨' : '📝';
  const fileName = path.split(/[\\/]/).pop() || path;
  return (
    <div style={{
      background: colors.card.file.bg,
      border: `1px solid ${isError ? colors.card.error.border : colors.card.file.border}`,
      borderRadius: radii.lg,
      padding: '10px 14px',
      marginBottom: 8,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
        <span style={{ fontSize: 14 }}>{icon}</span>
        <span style={{
          color: isError ? colors.accent.red : colors.accent.cyan,
          fontFamily: typography.fontMono,
          fontSize: typography.sizes.sm,
          fontWeight: typography.weights.medium,
        }}>
          {fileName}
        </span>
        <span style={{ color: colors.text.dim, fontSize: typography.sizes.xs, marginLeft: 8, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 200 }}>
          {path}
        </span>
        {action && (
          <span style={{
            background: isNew ? 'rgba(34, 197, 94, 0.15)' : 'rgba(6, 182, 212, 0.15)',
            color: isNew ? colors.accent.green : colors.accent.cyan,
            fontSize: typography.sizes.xs,
            padding: '1px 6px',
            borderRadius: radii.sm,
            marginLeft: 'auto',
          }}>
            {action}
          </span>
        )}
      </div>
      {diff && (
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
          maxHeight: 200,
          overflow: 'auto',
        }}>
          {diff}
        </div>
      )}
      {preview && !diff && (
        <div style={{
          background: colors.work.codeBg,
          border: `1px solid ${colors.work.codeBorder}`,
          borderRadius: radii.sm,
          padding: '6px 10px',
          marginTop: 4,
          color: colors.work.muted,
          fontFamily: typography.fontMono,
          fontSize: typography.sizes.xs,
          whiteSpace: 'pre-wrap',
          maxHeight: 150,
          overflow: 'auto',
        }}>
          {preview}
        </div>
      )}
    </div>
  );
}
