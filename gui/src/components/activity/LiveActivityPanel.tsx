import { useEffect, useRef, useState } from 'react';
import type { WorkEvent } from '../../types';
import { colors, radii, typography } from '../../theme/theme';
import { WorkEventCard } from '../cards/WorkEventCard';

interface LiveActivityPanelProps {
  workEvents: WorkEvent[];
  isStreaming: boolean;
  currentTurnId?: string;
  onEventClick?: (event: WorkEvent) => void;
  onClose?: () => void;
  visible?: boolean;
}

export function LiveActivityPanel({
  workEvents,
  isStreaming,
  currentTurnId,
  onEventClick,
  onClose,
  visible = true,
}: LiveActivityPanelProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [autoScroll, setAutoScroll] = useState(true);
  const prevCountRef = useRef(workEvents.length);

  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [workEvents.length, autoScroll]);

  useEffect(() => {
    if (workEvents.length > prevCountRef.current && isStreaming) {
      queueMicrotask(() => setAutoScroll(true));
    }
    prevCountRef.current = workEvents.length;
  }, [workEvents.length, isStreaming]);

  const handleScroll = () => {
    if (!scrollRef.current) return;
    const el = scrollRef.current;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
    setAutoScroll(atBottom);
  };

  const turnEvents = currentTurnId
    ? workEvents.filter(e => String(e.turn_id || e.conversation_id || '').includes(currentTurnId))
    : workEvents;

  if (!visible) return null;

  return (
    <div style={{
      width: 340,
      minWidth: 340,
      background: '#0c0c0f',
      borderLeft: `1px solid ${colors.border.dim}`,
      display: 'flex',
      flexDirection: 'column',
      height: '100vh',
      position: 'relative',
    }}>
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '12px 14px',
        borderBottom: `1px solid ${colors.border.dim}`,
        background: '#111115',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 14 }}>📡</span>
          <span style={{
            fontFamily: typography.fontFamily,
            fontSize: typography.sizes.sm,
            fontWeight: typography.weights.semibold,
            color: colors.text.main,
          }}>
            Activity
          </span>
          {isStreaming && (
            <span style={{
              width: 6,
              height: 6,
              borderRadius: '50%',
              background: colors.accent.green,
              boxShadow: `0 0 6px ${colors.accent.green}`,
              animation: 'pulse 1.5s ease-in-out infinite',
            }} />
          )}
        </div>
        <div style={{ display: 'flex', gap: 4 }}>
          <span style={{
            color: colors.text.dim,
            fontSize: typography.sizes.xs,
            fontFamily: typography.fontMono,
            padding: '2px 6px',
            background: 'rgba(255,255,255,0.04)',
            borderRadius: radii.sm,
          }}>
            {turnEvents.length}
          </span>
          {onClose && (
            <button
              onClick={onClose}
              style={{
                background: 'none',
                border: 'none',
                color: colors.text.muted,
                cursor: 'pointer',
                fontSize: 16,
                lineHeight: 1,
                padding: '0 4px',
              }}
            >
              ✕
            </button>
          )}
        </div>
      </div>

      <div
        ref={scrollRef}
        onScroll={handleScroll}
        style={{
          flex: 1,
          overflowY: 'auto',
          padding: '8px 10px',
        }}
      >
        {turnEvents.length === 0 && !isStreaming && (
          <div style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            height: '100%',
            color: colors.text.dim,
            fontSize: typography.sizes.sm,
            gap: 8,
            textAlign: 'center',
            padding: 24,
          }}>
            <span style={{ fontSize: 32, opacity: 0.3 }}>📡</span>
            <span>No activity yet</span>
            <span style={{ fontSize: typography.sizes.xs, color: colors.text.dim }}>
              Work events will appear here in real time
            </span>
          </div>
        )}

        {turnEvents.length === 0 && isStreaming && (
          <div style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            height: '100%',
            gap: 12,
            color: colors.text.muted,
          }}>
            <div style={{
              width: 24,
              height: 24,
              border: `2px solid ${colors.border.focus}`,
              borderTopColor: colors.accent.blue,
              borderRadius: '50%',
              animation: 'spin 0.8s linear infinite',
            }} />
            <span style={{ fontSize: typography.sizes.sm }}>Waiting for events...</span>
          </div>
        )}

        {turnEvents.map((event, i) => (
          <div
            key={event.id || event.event_id || i}
            onClick={() => onEventClick?.(event)}
            style={{ cursor: onEventClick ? 'pointer' : undefined }}
          >
            <WorkEventCard event={event} />
          </div>
        ))}

        {!autoScroll && turnEvents.length > 10 && (
          <button
            onClick={() => { setAutoScroll(true); }}
            style={{
              position: 'sticky',
              bottom: 4,
              width: '100%',
              padding: '6px',
              background: 'rgba(59, 130, 246, 0.15)',
              border: `1px solid ${colors.card.planning.border}`,
              borderRadius: radii.sm,
              color: colors.accent.blue,
              cursor: 'pointer',
              fontSize: typography.sizes.xs,
              fontFamily: typography.fontFamily,
            }}
          >
            ↓ Scroll to bottom
          </button>
        )}
      </div>

      {isStreaming && (
        <div style={{
          padding: '8px 14px',
          borderTop: `1px solid ${colors.border.dim}`,
          background: '#111115',
          display: 'flex',
          alignItems: 'center',
          gap: 8,
        }}>
          <div style={{
            width: 8,
            height: 8,
            borderRadius: '50%',
            background: colors.accent.green,
            boxShadow: `0 0 8px ${colors.accent.green}`,
            animation: 'pulse 1.5s ease-in-out infinite',
          }} />
          <span style={{
            color: colors.text.muted,
            fontSize: typography.sizes.xs,
            fontFamily: typography.fontMono,
          }}>
            Streaming...
          </span>
        </div>
      )}
    </div>
  );
}
