export interface LiveAgent {
    id: string;
    name: string;
    status: string;
    description?: string;
}

const ACTIVE_HIVE_STATUSES = new Set(['running', 'pending', 'active', 'working', 'in_progress']);
const ACTIVE_AGENT_STATUSES = new Set(['running', 'pending', 'active', 'working', 'busy', 'spawned', 'in_progress']);

/** Project `/api/hives` into only currently executing sub-agents. */
export function activeHiveAgents(payload: unknown): LiveAgent[] {
    const hives = (payload as {hives?: unknown[]})?.hives;
    if (!Array.isArray(hives)) return [];

    return hives
        .filter((hive: any) => ACTIVE_HIVE_STATUSES.has(String(hive?.status || '').toLowerCase()))
        .flatMap((hive: any) => Array.isArray(hive?.agents) ? hive.agents : [])
        .map((agent: any) => ({
            id: String(agent?.id || agent?.name || ''),
            name: String(agent?.name || agent?.persona || agent?.id || 'Agent'),
            status: String(agent?.status || 'pending'),
            description: agent?.description || agent?.task
                ? String(agent.description || agent.task)
                : undefined
        }))
        .filter((agent: LiveAgent) => agent.id && ACTIVE_AGENT_STATUSES.has(agent.status.toLowerCase()));
}
