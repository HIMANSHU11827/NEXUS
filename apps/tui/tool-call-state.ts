export type ToolEvent = Record<string, any>;

const payloadOf = (event: ToolEvent): ToolEvent =>
    event.payload && typeof event.payload === 'object' ? event.payload : {};

/** Run/message/status lifecycle events are not Hive workers unless linked to one. */
export function isSyntheticAgentLifecycle(event: ToolEvent): boolean {
    const payload = payloadOf(event);
    const kind = String(event.kind || event.type || '').toLowerCase();
    const relatedSubagent = event.related_subagent
        || event.subagent_id
        || event.agent_id
        || payload.related_subagent
        || payload.subagent_id
        || payload.agent_id;
    return kind === 'agent'
        && !relatedSubagent
        && !event.related_tool
        && !event.tool
        && !payload.related_tool
        && !payload.tool;
}

/** Stable identity for one logical tool call, separate from event delivery IDs. */
export function toolActivityIdentity(event: ToolEvent, fallback = 'session'): string {
    const payload = payloadOf(event);
    return String(
        event.call_id
        || event.tool_call_id
        || event.toolCallId
        || payload.call_id
        || payload.tool_call_id
        || event.activity_id
        || event.activityId
        || event.id
        || `${event.kind || event.type || 'tool'}:${event.action || event.title || ''}:${event.target || event.command || ''}:${fallback}`
    );
}

/** Identity for one delivered event version; lifecycle updates must not collide. */
export function toolEventDeliveryIdentity(event: ToolEvent, fallback = 'session'): string {
    const base = String(event.event_id || event.id || toolActivityIdentity(event, fallback));
    const sequence = event.sequence ?? payloadOf(event).sequence;
    if (sequence !== undefined && sequence !== null) return `${base}:sequence:${sequence}`;

    return [
        base,
        event.event_type || event.type || event.kind || '',
        event.status || '',
        event.part_type || '',
        event.stream || '',
        event.append ? 'append' : '',
        event.chunk ?? event.output ?? event.stdout ?? event.error ?? event.stderr ?? ''
    ].join(':');
}

export function appendToolOutput(previous: string | undefined, incoming: string | undefined, maxChars = 4000, maxLines = 80): string | undefined {
    if (!incoming) return previous;
    if (!previous) return incoming;
    if (previous.endsWith(incoming)) return previous;
    const combined = `${previous}${incoming}`;
    const bounded = combined.length > maxChars ? combined.slice(-maxChars) : combined;
    return bounded.split('\n').slice(-maxLines).join('\n');
}
