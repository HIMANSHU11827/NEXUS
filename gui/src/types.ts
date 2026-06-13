import type { ReactNode } from 'react';

export interface HiveTask {
  id: string;
  role: string;
  objective: string;
  status: string;
  attempts?: number;
  error?: string;
  result?: string;
  updated_at?: number;
}

export interface NexusState {
  hive: { id: string; persona?: string; status?: string; total?: number; active_agents?: number; paused_agents?: number; by_status?: Record<string, number>; roles?: string[]; conflict_count?: number; weak_artifact_count?: number; updated_at?: number; tasks?: HiveTask[]; signals?: { sender: string; message: string; timestamp: number }[] }[];
  skills: { name: string; description: string; active?: boolean; config?: Record<string, unknown> }[];
  tools: { name: string; description: string; active?: boolean; config?: Record<string, unknown> }[];
  providers: { name: string; status: string; description: string; endpoint?: string; config_source?: string; has_api_key?: boolean }[];
  provider_instances: { id: string; parent: string; model: string; api_key?: string; endpoint?: string; config_source?: string; has_api_key?: boolean; status?: string }[];
  plugins?: { id: string; name: string; source: string; category?: string; install_kind?: string; version?: string; source_url?: string; installed_at?: number; path: string; display_path?: string; description: string; active?: boolean; installed?: boolean; removable?: boolean; disk_removable?: boolean; skills?: string[]; tools?: string[]; counts?: { skills: number; tools: number } }[];
  mcp: { connected: number; total: number; servers?: unknown[] };
  health: {
    cpu: string;
    ram: string;
    status: string;
    updated_at?: number;
    uptime_seconds?: number;
    host_uptime_seconds?: number;
    os?: string;
    python?: string;
    cpu_detail?: { usage_pct?: number; cores_physical?: number; cores_logical?: number; frequency_mhz?: number | null };
    memory?: { usage_pct?: number; used_gb?: number; available_gb?: number; total_gb?: number };
    disk?: { usage_pct?: number; free_gb?: number; total_gb?: number; path?: string };
    process?: { pid?: number; memory_mb?: number; threads?: number; open_files?: number };
    power?: { battery_pct?: number | null; plugged?: boolean; label?: string };
    thermal?: { status?: string; temp_c?: number | null; source?: string };
    gpus?: { name: string; vendor?: string; driver?: string; vram_gb?: number | null }[];
    problems?: string[];
    checks?: { name: string; value: string; status: string; detail?: string }[];
    recent_failures?: { path?: string; status?: string; detail?: string; time?: number }[];
  };
  session: { active: boolean; turns: number };
  reminders: { id?: string; text: string; time: string; due_at?: number; done?: boolean; notified?: boolean; created_at?: number }[];
  audit?: {
    unified_graph?: { nodes: number; edges: number; by_source?: Record<string, number>; by_kind?: Record<string, number> };
    roadmap?: { total: number; counts: Record<string, number>; completion_ratio: number; remaining_top?: unknown[] };
    evidence?: { total: number; by_status: Record<string, number>; unsupported_claims?: unknown[] };
    mission_replay?: unknown[];
    tool_economy?: unknown[];
  };
}

export interface SessionSummary {
  id: string;
  title: string;
  updated_at?: number;
}

export interface WorkEvent {
  id?: string;
  session_id?: string;
  kind?: string;
  type?: string;
  action?: string;
  title?: string;
  tool?: string;
  target?: string;
  path?: string;
  command?: string;
  status?: string;
  result?: string;
  output?: string;
  stdout?: string;
  stderr?: string;
  preview?: string;
  preview_error?: string;
  created_at?: number;
  // Work events are produced by multiple tools with tool-specific metadata.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  [key: string]: any;
}

export type ChatMessage = { role: string; content: string };

export type NavItem = {
  id: string;
  label: string;
  icon: ReactNode;
};

export type SessionNotice = { kind: 'error' | 'success'; message: string };
