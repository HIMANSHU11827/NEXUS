import { useEffect, useRef } from 'react';
import type { ChatMessage } from '../../types';
import { colors, radii, typography } from '../../theme/theme';

interface MessageListProps {
  messages: ChatMessage[];
  isStreaming: boolean;
  renderMessageMarkdown?: (content: string, index: number) => React.ReactNode;
  cleanUserMessage?: (content: string) => string;
  cleanAssistantText?: (content: string) => string;
}

export function MessageList({
  messages,
  isStreaming,
  renderMessageMarkdown,
  cleanUserMessage,
  cleanAssistantText,
}: MessageListProps) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const prevLengthRef = useRef(0);

  useEffect(() => {
    if (messages.length > prevLengthRef.current || isStreaming) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
    }
    prevLengthRef.current = messages.length;
  }, [messages.length, isStreaming]);

  if (messages.length === 0) {
    return (
      <div style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        height: '100%',
        color: colors.text.dim,
        gap: 16,
        textAlign: 'center',
        padding: 48,
      }}>
        <span style={{ fontSize: 48, opacity: 0.2 }}>⚡</span>
        <span style={{ fontSize: typography.sizes.lg, fontWeight: typography.weights.semibold, color: colors.text.muted }}>
          Start a conversation
        </span>
        <span style={{ fontSize: typography.sizes.sm, maxWidth: 300 }}>
          Type a message below or ask me to write code, research a topic, or solve a problem.
        </span>
      </div>
    );
  }

  return (
    <div style={{
      flex: 1,
      overflowY: 'auto',
      padding: '16px 24px',
      display: 'flex',
      flexDirection: 'column',
      gap: 4,
    }}>
      {messages.map((message, i) => {
        const isUser = message.role === 'user';
        const textToRender = isUser
          ? (cleanUserMessage?.(message.content || '') ?? message.content)
          : (cleanAssistantText?.(message.content || '') ?? message.content);

        return (
          <div
            key={message.id || i}
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: isUser ? 'flex-end' : 'flex-start',
              marginBottom: 8,
            }}
          >
            <div style={{
              maxWidth: '85%',
              background: isUser ? colors.bubble.user.bg : colors.bubble.assistant.bg,
              border: `1px solid ${isUser ? colors.bubble.user.border : colors.bubble.assistant.border}`,
              borderRadius: radii.lg,
              borderBottomRightRadius: isUser ? 4 : radii.lg,
              borderBottomLeftRadius: isUser ? radii.lg : 4,
              padding: '10px 14px',
              color: isUser ? colors.bubble.user.text : colors.bubble.assistant.text,
              fontFamily: typography.fontFamily,
              fontSize: typography.sizes.sm,
              lineHeight: 1.6,
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
            }}>
              {renderMessageMarkdown
                ? renderMessageMarkdown(textToRender, i)
                : textToRender
              }
              {message.isStreaming && (
                <span style={{
                  display: 'inline-block',
                  width: 6,
                  height: 14,
                  background: colors.accent.blue,
                  marginLeft: 2,
                  animation: 'blink 1s step-end infinite',
                  verticalAlign: 'middle',
                }} />
              )}
            </div>
            {message.events && message.events.length > 0 && (
              <div style={{ marginTop: 4, width: '100%' }}>
                {message.events.map((event, ei) => (
                  <div key={ei} style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 6,
                    padding: '3px 8px',
                    color: colors.text.muted,
                    fontFamily: typography.fontMono,
                    fontSize: typography.sizes.xs,
                    background: colors.work.bg,
                    borderRadius: radii.sm,
                    marginBottom: 2,
                  }}>
                    <span>•</span>
                    <span>{event.action || event.kind || 'event'}</span>
                    {event.target && <span style={{ color: colors.text.dim }}>{event.target}</span>}
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}
      <div ref={bottomRef} />
    </div>
  );
}
