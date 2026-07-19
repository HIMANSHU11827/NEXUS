import { colors, radii, typography } from '../../theme/theme';

interface ErrorCardProps {
  title?: string;
  message: string;
  detail?: string;
}

export function ErrorCard({ title, message, detail }: ErrorCardProps) {
  return (
    <div style={{
      background: colors.card.error.bg,
      border: `1px solid ${colors.card.error.border}`,
      borderRadius: radii.lg,
      padding: '12px 16px',
      marginBottom: 8,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
        <span style={{ fontSize: 16 }}>❌</span>
        <span style={{
          color: colors.accent.red,
          fontFamily: typography.fontFamily,
          fontSize: typography.sizes.sm,
          fontWeight: typography.weights.semibold,
        }}>
          {title || 'Error'}
        </span>
      </div>
      <div style={{
        color: colors.accent.red,
        fontFamily: typography.fontFamily,
        fontSize: typography.sizes.sm,
        marginBottom: detail ? 8 : 0,
      }}>
        {message}
      </div>
      {detail && (
        <div style={{
          background: 'rgba(239, 68, 68, 0.1)',
          border: `1px solid ${colors.card.error.border}`,
          borderRadius: radii.sm,
          padding: '6px 10px',
          color: colors.text.muted,
          fontFamily: typography.fontMono,
          fontSize: typography.sizes.xs,
          whiteSpace: 'pre-wrap',
          maxHeight: 100,
          overflow: 'auto',
        }}>
          {detail}
        </div>
      )}
    </div>
  );
}
