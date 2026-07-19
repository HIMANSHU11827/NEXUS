import { colors, radii, typography } from '../../theme/theme';

interface PlanningCardProps {
  title?: string;
  steps?: string[];
  currentStep?: number;
  done?: boolean;
}

export function PlanningCard({ title, steps, currentStep, done }: PlanningCardProps) {
  return (
    <div style={{
      background: colors.card.planning.bg,
      border: `1px solid ${colors.card.planning.border}`,
      borderRadius: radii.lg,
      padding: '12px 16px',
      marginBottom: 8,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <span style={{ fontSize: 16 }}>{done ? '✅' : '🧠'}</span>
        <span style={{
          color: colors.text.main,
          fontFamily: typography.fontFamily,
          fontSize: typography.sizes.sm,
          fontWeight: typography.weights.semibold,
        }}>
          {title || 'Planning'}
        </span>
      </div>
      {steps && steps.length > 0 && (
        <div style={{ paddingLeft: 24 }}>
          {steps.map((step, i) => (
            <div key={i} style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              padding: '2px 0',
              color: currentStep !== undefined && i < currentStep
                ? colors.accent.green
                : i === currentStep
                  ? colors.accent.blue
                  : colors.text.muted,
              fontFamily: typography.fontMono,
              fontSize: typography.sizes.xs,
            }}>
              <span>{i < (currentStep ?? -1) ? '✓' : i === currentStep ? '→' : '○'}</span>
              <span>{step}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
