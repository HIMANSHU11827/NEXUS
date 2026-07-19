import { colors, radii, typography } from '../../theme/theme';

interface AgentStateCardProps {
  phase?: string;
  status?: string;
  thought?: string;
  model?: string;
  mode?: string;
}

export function AgentStateCard({ phase, status, thought, model, mode }: AgentStateCardProps) {
  const isThinking = status === 'thinking' || status === 'reasoning';
  return (
    <div style={{
      background: isThinking ? colors.card.planning.bg : colors.card.agent.bg,
      border: `1px solid ${isThinking ? colors.card.planning.border : colors.card.agent.border}`,
      borderRadius: radii.lg,
      padding: '10px 14px',
      marginBottom: 8,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
        <span style={{ fontSize: 14 }}>
          {isThinking ? '🧠' : status === 'error' ? '❌' : status === 'done' ? '✅' : '🤖'}
        </span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flex: 1 }}>
          {phase && (
            <span style={{
              color: colors.accent.blue,
              fontFamily: typography.fontFamily,
              fontSize: typography.sizes.sm,
              fontWeight: typography.weights.semibold,
            }}>
              {phase}
            </span>
          )}
          {model && (
            <span style={{
              color: colors.text.dim,
              fontFamily: typography.fontMono,
              fontSize: typography.sizes.xs,
              background: 'rgba(255,255,255,0.04)',
              padding: '1px 6px',
              borderRadius: radii.sm,
            }}>
              {model}
            </span>
          )}
          {mode && (
            <span style={{
              color: colors.text.dim,
              fontSize: typography.sizes.xs,
              marginLeft: 'auto',
            }}>
              {mode}
            </span>
          )}
        </div>
      </div>
      {thought && (
        <div style={{
          color: colors.text.muted,
          fontFamily: typography.fontMono,
          fontSize: typography.sizes.xs,
          fontStyle: 'italic',
          padding: '6px 0',
          whiteSpace: 'pre-wrap',
          maxHeight: 100,
          overflow: 'auto',
        }}>
          {thought}
        </div>
      )}
    </div>
  );
}
