import React, { useEffect, useState } from 'react';
import type { ChatMessage, WorkEvent } from '../../types';
import { isDisplayableWorkActivity } from '../../utils/workActivityUtils';

export interface MessageBubbleProps {
    message: ChatMessage;
    index: number;
    isUser: boolean;
    showChatAvatars: boolean;
    userAvatar: React.ReactNode;
    assistantAvatar: React.ReactNode;
    hoveredMsgId: number | null;
    setHoveredMsgId: (id: number | null) => void;
    copiedMsgId: number | null;
    setCopiedMsgId: (id: number | null) => void;
    renderMessageMarkdown: (content: string, isUserMsg: boolean) => React.ReactNode;
    cleanUserMessage: (text: string) => string;
    cleanAssistantText: (text: string) => string;
    msgEvents: WorkEvent[];
    isStreaming: boolean;
    onRegenerate?: () => void;
    onWorkEventClick?: (event: WorkEvent) => void;
    renderWorkActivityTimeline?: (events: WorkEvent[]) => React.ReactNode;
}

export const MessageBubble: React.FC<MessageBubbleProps> = ({
    message, index, isUser, showChatAvatars, userAvatar, assistantAvatar,
    hoveredMsgId, setHoveredMsgId, copiedMsgId, setCopiedMsgId,
    renderMessageMarkdown, cleanUserMessage, cleanAssistantText, msgEvents, isStreaming, onRegenerate,
    renderWorkActivityTimeline
}) => {
    const [elapsedSeconds, setElapsedSeconds] = useState(0);
    useEffect(() => {
        if (!isStreaming) return;
        const startedAt = Number(message.workflowStart || message.createdAt || Date.now() / 1000);
        const update = () => setElapsedSeconds(Math.max(0, Math.floor(Date.now() / 1000 - startedAt)));
        update();
        const timer = window.setInterval(update, 1000);
        return () => window.clearInterval(timer);
    }, [isStreaming, message.createdAt, message.workflowStart]);

    const cleanedAssistantContent = !isUser ? cleanAssistantText(message.content) : message.content;
    const assistantPlaceholderContent = !isUser && /^(thinking|getting answer|working|\[working\])\.{0,3}$/i.test(cleanedAssistantContent.trim());
    const visibleAssistantContent = assistantPlaceholderContent ? '' : cleanedAssistantContent;
    const visibleWorkEvents = !isUser ? msgEvents.filter(isDisplayableWorkActivity) : [];
    const latestWorkEvent = visibleWorkEvents.length > 0 ? visibleWorkEvents[visibleWorkEvents.length - 1] : null;
    const latestWorkStatus = String(latestWorkEvent?.status || '').toLowerCase();
    const isActivelyWorking = Boolean(latestWorkEvent) && ['queued', 'pending', 'running', 'in_progress', 'started'].includes(latestWorkStatus);
    const currentAction = String(latestWorkEvent?.action || latestWorkEvent?.title || latestWorkEvent?.tool || '').trim();
    const liveAgentState = isActivelyWorking && currentAction ? `${currentAction}…` : 'Waiting for agent activity…';
    const hasVisibleTimeline = visibleWorkEvents.length > 0 && Boolean(renderWorkActivityTimeline);
    const hasFailedWork = visibleWorkEvents.some(event => ['failed', 'error', 'blocked'].includes(String(event.status || '').toLowerCase()));

    // Mount an empty assistant row only while this exact message is live. Its
    // label comes from real streamed work events, never a timer or mock state.
    if (!isUser && !visibleAssistantContent.trim() && !isStreaming && !hasVisibleTimeline) return null;
    return (
        <div
            key={index}
            className={`message-row ${isUser ? 'user' : 'assistant'}`}
            onMouseEnter={() => setHoveredMsgId(index)}
            onMouseLeave={() => setHoveredMsgId(null)}
            style={{
                display: 'flex',
                flexDirection: isUser ? 'row-reverse' : 'row',
                alignItems: 'flex-start',
                gap: '14px',
                width: '100%',
                animation: 'fadeIn 0.3s ease-out'
            }}
        >
            {showChatAvatars && (
                <div className="avatar" style={{
                    width: '34px',
                    height: '34px',
                    borderRadius: '50%',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontSize: '1.25rem',
                    background: isUser ? 'var(--avatar-user-bg)' : 'var(--avatar-assistant-bg)',
                    border: '1px solid ' + (isUser ? 'var(--avatar-user-border)' : 'var(--avatar-assistant-border)'),
                    flexShrink: 0,
                    boxShadow: '0 2px 4px rgba(0,0,0,0.05)'
                }}>
                    {isUser ? userAvatar : assistantAvatar}
                </div>
            )}

            <div style={{ display: 'flex', flexDirection: 'column', flex: '1 1 auto', minWidth: 0, alignItems: isUser ? 'flex-end' : 'flex-start' }}>
                {(isUser || visibleAssistantContent.trim() || isStreaming) && <div className={`message-bubble ${isUser ? 'user-bubble' : 'assistant-bubble'}`} style={{
                    padding: '12px 18px',
                    borderRadius: '16px',
                    background: isUser ? 'var(--user-bubble-bg)' : 'var(--assistant-bubble-bg)',
                    border: '1px solid ' + (isUser ? 'var(--user-bubble-border)' : 'var(--assistant-bubble-border)'),
                    color: isUser ? 'var(--user-bubble-text)' : 'var(--assistant-bubble-text)',
                    width: 'fit-content',
                    maxWidth: '88%',
                    boxShadow: '0 1px 3px rgba(0,0,0,0.02)',
                    wordBreak: 'break-word',
                    fontSize: '0.96rem',
                    lineHeight: '1.6'
                }}>
                    {isUser ? renderMessageMarkdown(cleanUserMessage(message.content), isUser) : renderMessageMarkdown(visibleAssistantContent, isUser)}
                    {!isUser && isStreaming && !visibleAssistantContent.trim() && (
                        <div
                            className="live-agent-state"
                            data-agent-state={isActivelyWorking ? 'working' : 'thinking'}
                            role="status"
                            aria-live="polite"
                            aria-label={liveAgentState}
                            style={{ display: 'flex', alignItems: 'center', gap: '7px', color: 'var(--muted-text, #94a3b8)', fontWeight: 600, fontSize: '0.9rem' }}
                        >
                            <span aria-hidden="true" style={{ width: '7px', height: '7px', borderRadius: '50%', background: isActivelyWorking ? '#38bdf8' : '#a78bfa', boxShadow: `0 0 10px ${isActivelyWorking ? '#38bdf8' : '#a78bfa'}` }} />
                            <span>{liveAgentState}</span>
                            <span aria-hidden="true" className="live-agent-elapsed">{elapsedSeconds}s</span>
                        </div>
                    )}

                </div>}

                {!isUser && visibleAssistantContent && (
                    <div className="message-actions" style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '8px',
                        marginTop: '6px',
                        opacity: hoveredMsgId === index ? 0.8 : 0,
                        transition: 'opacity 0.2s ease',
                        minHeight: '20px'
                    }}>
                        <button
                            type="button"
                            aria-label="Copy assistant response"
                            title="Copy"
                            onClick={() => { navigator.clipboard.writeText(visibleAssistantContent); setCopiedMsgId(index); setTimeout(() => setCopiedMsgId(null), 2000); }}
                            style={{ background: 'transparent', border: 'none', borderRadius: '4px', cursor: 'pointer', padding: '2px 6px', display: 'inline-flex', alignItems: 'center', color: copiedMsgId === index ? '#10b981' : '#888', transition: 'all 0.2s', outline: 'none' }}
                        >
                            {copiedMsgId === index ? (
                                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3"><polyline points="20 6 9 17 4 12" /></svg>
                            ) : (
                                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="9" y="9" width="13" height="13" rx="2" /><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" /></svg>
                            )}
                        </button>
                        {!isStreaming && onRegenerate && (
                            <button
                                type="button"
                                aria-label="Regenerate assistant response"
                                title="Regenerate"
                                onClick={onRegenerate}
                                style={{ background: 'transparent', border: 'none', cursor: 'pointer', padding: '2px 4px', display: 'inline-flex', alignItems: 'center', color: '#888', outline: 'none' }}
                                onMouseEnter={e => (e.currentTarget.style.color='#3b82f6')}
                                onMouseLeave={e => (e.currentTarget.style.color='#888')}
                            >
                                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 102.13-9.36L1 10"/></svg>
                            </button>
                        )}
                    </div>
                )}

                {isUser && message.content && (
                    <div className="message-actions" style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '8px',
                        marginTop: '6px',
                        opacity: hoveredMsgId === index ? 0.8 : 0,
                        transition: 'opacity 0.2s ease',
                        minHeight: '20px'
                    }}>
                        <button
                            type="button"
                            aria-label="Copy user message"
                            title="Copy"
                            onClick={() => { navigator.clipboard.writeText(cleanUserMessage(message.content)); setCopiedMsgId(index); setTimeout(() => setCopiedMsgId(null), 2000); }}
                            style={{ background: 'transparent', border: 'none', borderRadius: '4px', cursor: 'pointer', padding: '2px 6px', display: 'inline-flex', alignItems: 'center', color: copiedMsgId === index ? '#10b981' : '#888', transition: 'all 0.2s', outline: 'none' }}
                        >
                            {copiedMsgId === index ? (
                                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3"><polyline points="20 6 9 17 4 12"/></svg>
                            ) : (
                                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>
                            )}
                        </button>
                    </div>
                )}

                {!isUser && hasVisibleTimeline && (
                    <div className="work-timeline-wrapper" style={{ marginTop: '14px', width: '100%', maxWidth: '760px' }}>
                        {renderWorkActivityTimeline?.(msgEvents)}
                        {hasFailedWork && !isStreaming && onRegenerate && (
                            <button type="button" className="work-retry-button" onClick={onRegenerate} aria-label="Retry failed turn">
                                Retry failed turn
                            </button>
                        )}
                    </div>
                )}
            </div>
        </div>
    );
};
