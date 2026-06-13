import { Activity, Bell, Clock, Cpu, Database, HeartPulse, Monitor, PauseCircle, PlayCircle, PlusCircle, Power, Shield, ShieldAlert, StopCircle, Trash2 } from 'lucide-react';
import type { NexusState } from '../types';

type HiveDrawerProps = {
  hive: NexusState['hive'];
  hiveStarting: boolean;
  newHiveMission: string;
  controlHive: (hiveId: string, action: 'pause' | 'resume' | 'stop') => void | Promise<void>;
  controlHiveTask: (hiveId: string, taskId: string, action: 'resume' | 'stop' | 'remove') => void | Promise<void>;
  formatCardName: (value: string) => string;
  removeHive: (hiveId: string) => void;
  setNewHiveMission: (value: string) => void;
  startHiveMission: (mission?: string) => void;
};

export function HiveDrawer({
  hive,
  hiveStarting,
  newHiveMission,
  controlHive,
  controlHiveTask,
  formatCardName,
  removeHive,
  setNewHiveMission,
  startHiveMission,
}: HiveDrawerProps) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '15px' }}>
      <div className="hive-launcher-card">
        <div className="hive-launcher-head">
          <div>
            <div className="hive-launcher-title">Start Hive Mission</div>
            <div className="hive-launcher-sub">Creates real Hive worker tasks and starts the local Hive queue.</div>
          </div>
          <Activity size={20} />
        </div>
        <textarea
          className="hive-mission-input"
          value={newHiveMission}
          onChange={(event) => setNewHiveMission(event.target.value)}
          placeholder="Describe work for the hive..."
        />
        <div className="hive-launcher-actions">
          <button onClick={() => startHiveMission()} disabled={hiveStarting || !newHiveMission.trim()}>
            <PlusCircle size={14} /> {hiveStarting ? 'Starting...' : 'Start Hive'}
          </button>
          <button onClick={() => startHiveMission('Review gui health, hive, and reminder panels for UI problems and list fixes.')}>UI Review</button>
          <button onClick={() => startHiveMission('Run diagnostics for the NEXUS gui and summarize failures.')}>Diagnostics</button>
        </div>
      </div>
      {hive && hive.length > 0 ? hive.map((agent, index) => (
        <div key={index} className="drawer-item hive-control-card">
          <div className="hive-control-head">
            <div>
              <div className="hive-control-title">{agent.id}</div>
              <div className="hive-control-sub">{agent.active_agents || 0} active / {agent.paused_agents || 0} paused / {agent.total || 0} total</div>
            </div>
            <span className="hive-count-pill">{agent.total || 0} tasks</span>
          </div>
          <div className="hive-control-actions">
            <button onClick={() => controlHive(agent.id, 'pause')} title="Pause pending queue"><PauseCircle size={14} /> Pause</button>
            <button onClick={() => controlHive(agent.id, 'resume')} title="Resume paused or pending work"><PlayCircle size={14} /> Resume</button>
            <button className="danger" onClick={() => controlHive(agent.id, 'stop')} title="Stop full hive"><StopCircle size={14} /> Stop</button>
            <button className="danger" onClick={() => removeHive(agent.id)} title="Remove full hive"><Trash2 size={14} /> Remove</button>
          </div>
          <div className="drawer-mini-grid">
            {Object.entries(agent.by_status || {}).map(([status, count]) => (
              <span key={status}>{status}: <b>{count}</b></span>
            ))}
            <span>conflicts: <b>{agent.conflict_count || 0}</b></span>
            <span>weak: <b>{agent.weak_artifact_count || 0}</b></span>
          </div>
          <div className="hive-agent-list">
            {(agent.tasks || []).slice(0, 8).map(task => (
              <div className="hive-agent-card" key={task.id}>
                <div className="hive-agent-top">
                  <div>
                    <div className="hive-agent-role">{formatCardName(task.role || 'Worker')}</div>
                    <div className={`hive-agent-status status-${task.status}`}>{task.status}</div>
                  </div>
                  <div className="hive-agent-buttons">
                    <button onClick={() => controlHiveTask(agent.id, task.id, 'resume')} title="Resume this Hive worker"><PlayCircle size={13} /></button>
                    <button onClick={() => controlHiveTask(agent.id, task.id, 'stop')} title="Stop this Hive worker"><StopCircle size={13} /></button>
                    <button className="danger" onClick={() => controlHiveTask(agent.id, task.id, 'remove')} title="Remove this Hive worker"><Trash2 size={13} /></button>
                  </div>
                </div>
                <div className="hive-agent-task">{task.objective || 'No task summary recorded.'}</div>
                {(task.result || task.error) && (
                  <div className="hive-agent-note">{task.error || task.result}</div>
                )}
              </div>
            ))}
          </div>
          {(agent.signals || []).length > 0 && (
            <div className="hive-signal-stack">
              {(agent.signals || []).slice(-3).map((signal, signalIndex) => (
                <div key={signalIndex} className="hive-signal-line">
                  <b>{signal.sender}</b> {signal.message}
                </div>
              ))}
            </div>
          )}
        </div>
      )) : (
        <div className="hive-empty-state">
          <Activity size={24} />
          <b>No hive mission running</b>
          <span>Start a mission above. NEXUS will create Hive worker cards for architect, engineer, auditor, QA, and librarian work when the hive starts.</span>
        </div>
      )}
    </div>
  );
}

type HealthDrawerProps = {
  health: NexusState['health'];
  formatDuration: (seconds?: number) => string;
};

export function HealthDrawer({ health, formatDuration }: HealthDrawerProps) {
  return (
    <div className="health-panel">
      <div className={`health-hero ${health?.status === 'CRITICAL' ? 'critical' : health?.status === 'DEGRADED' ? 'degraded' : ''}`}>
        <div>
          <div className="health-eyebrow">NEXUS Health</div>
          <div className="health-status-title">{health?.status || 'UNKNOWN'}</div>
          <div className="health-status-sub">
            Live local telemetry. Updated {health?.updated_at ? new Date(health.updated_at * 1000).toLocaleTimeString() : 'now'}.
          </div>
        </div>
        <HeartPulse size={28} />
      </div>

      <div className="health-grid">
        <div className="health-metric-card">
          <Cpu size={18} />
          <span>CPU</span>
          <b>{health?.cpu}</b>
          <small>{health?.cpu_detail?.cores_logical || 0} threads · {health?.cpu_detail?.frequency_mhz ? `${health.cpu_detail.frequency_mhz} MHz` : 'freq n/a'}</small>
        </div>
        <div className="health-metric-card">
          <Activity size={18} />
          <span>RAM</span>
          <b>{health?.ram}</b>
          <small>{health?.memory?.available_gb ?? '?'}GB free / {health?.memory?.total_gb ?? '?'}GB</small>
        </div>
        <div className="health-metric-card">
          <Database size={18} />
          <span>DISK</span>
          <b>{health?.disk?.usage_pct ?? '?'}%</b>
          <small>{health?.disk?.free_gb ?? '?'}GB free</small>
        </div>
        <div className="health-metric-card">
          <Power size={18} />
          <span>POWER</span>
          <b>{health?.power?.label || 'AC'}</b>
          <small>{health?.power?.plugged ? 'Plugged in' : 'On battery'}</small>
        </div>
      </div>

      <div className="health-section-card">
        <div className="health-section-title"><Monitor size={16} /> GPU / iGPU</div>
        {(health?.gpus || []).length > 0 ? (health.gpus || []).map((gpu, index) => (
          <div className="health-row" key={`${gpu.name}-${index}`}>
            <span>{gpu.name}</span>
            <b>{gpu.vram_gb ? `${gpu.vram_gb}GB` : gpu.vendor || 'Detected'}</b>
          </div>
        )) : (
          <div className="health-muted">GPU telemetry unavailable on this host.</div>
        )}
      </div>

      <div className="health-section-card">
        <div className="health-section-title"><Shield size={16} /> Runtime</div>
        <div className="health-row"><span>NEXUS uptime</span><b>{formatDuration(health?.uptime_seconds)}</b></div>
        <div className="health-row"><span>Host uptime</span><b>{formatDuration(health?.host_uptime_seconds)}</b></div>
        <div className="health-row"><span>Backend PID</span><b>{health?.process?.pid || '?'}</b></div>
        <div className="health-row"><span>Backend memory</span><b>{health?.process?.memory_mb ?? '?'}MB</b></div>
        <div className="health-row"><span>Threads</span><b>{health?.process?.threads ?? '?'}</b></div>
        <div className="health-row"><span>Python</span><b>{health?.python || '?'}</b></div>
      </div>

      <div className="health-section-card">
        <div className="health-section-title"><Activity size={16} /> System Checks</div>
        <div className="health-check-grid">
          {(health?.checks || []).map((check, index) => (
            <div className={`health-check-card ${check.status}`} key={`${check.name}-${index}`}>
              <span>{check.name}</span>
              <b>{check.value}</b>
              <small>{check.detail}</small>
            </div>
          ))}
        </div>
      </div>

      <div className="health-section-card">
        <div className="health-section-title"><ShieldAlert size={16} /> Problems</div>
        {(health?.problems || []).length > 0 ? (health.problems || []).map((problem, index) => (
          <div className="health-problem" key={index}>{problem}</div>
        )) : (
          <div className="health-ok">No current health problems detected.</div>
        )}
        <div className="health-muted" style={{ marginTop: 10 }}>
          Thermal: {health?.thermal?.status || 'UNAVAILABLE'}{health?.thermal?.temp_c ? ` · ${health.thermal.temp_c}°C` : ''}
        </div>
      </div>
      {(health?.recent_failures || []).length > 0 && (
        <div className="health-section-card">
          <div className="health-section-title"><ShieldAlert size={16} /> Recent Failures</div>
          {(health.recent_failures || []).map((failure, index) => (
            <div className="health-failure-row" key={index}>
              <div>
                <b>{failure.path || 'gui api'}</b>
                <span>{failure.detail || `HTTP ${failure.status}`}</span>
              </div>
              <small>{failure.time ? new Date(failure.time * 1000).toLocaleTimeString() : failure.status}</small>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

type RemindersDrawerProps = {
  reminders: NexusState['reminders'];
  newReminderDue: string;
  newReminderText: string;
  notificationPermission: string;
  nowSeconds: number;
  createReminder: () => void;
  deleteReminder: (id?: string) => void;
  requestReminderNotifications: () => void;
  setNewReminderDue: (value: string) => void;
  setNewReminderText: (value: string) => void;
};

export function RemindersDrawer({
  reminders,
  newReminderDue,
  newReminderText,
  notificationPermission,
  nowSeconds,
  createReminder,
  deleteReminder,
  requestReminderNotifications,
  setNewReminderDue,
  setNewReminderText,
}: RemindersDrawerProps) {
  return (
    <div className="reminders-panel">
      <div className="reminder-hero">
        <div>
          <div className="reminder-hero-title">Reminders</div>
          <div className="reminder-hero-sub">Set a reminder and NEXUS will notify you when it is due.</div>
        </div>
        <Bell size={22} />
      </div>
      <button className={`reminder-permission ${notificationPermission}`} onClick={requestReminderNotifications}>
        <Bell size={15} />
        {notificationPermission === 'granted' ? 'Notifications enabled' : notificationPermission === 'denied' ? 'Notifications blocked in browser' : notificationPermission === 'unsupported' ? 'Notifications unavailable' : 'Enable reminder notifications'}
      </button>
      <div className="reminder-create-row">
        <input
          className="reminder-input"
          value={newReminderText}
          onChange={(event) => setNewReminderText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') createReminder();
          }}
          placeholder="Add reminder..."
        />
        <input
          className="reminder-input reminder-date-input"
          type="datetime-local"
          value={newReminderDue}
          onChange={(event) => setNewReminderDue(event.target.value)}
          title="Reminder time"
        />
        <button className="reminder-add-btn" onClick={createReminder}>
          <PlusCircle size={16} />
        </button>
      </div>
      {reminders && reminders.length > 0 ? reminders.map((reminder, index) => (
        <div key={index} className={`reminder-card ${reminder.due_at && reminder.due_at <= nowSeconds ? 'due' : ''}`}>
          <Clock size={16} color="#fbbf24" style={{ marginTop: '2px' }} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: '0.8rem', fontWeight: 700, color: '#fff' }}>{reminder.text}</div>
            <div style={{ fontSize: '0.65rem', color: '#fbbf24', marginTop: '5px', opacity: 0.7 }}>
              {reminder.due_at ? `Due ${new Date(reminder.due_at * 1000).toLocaleString()}` : reminder.time}
            </div>
          </div>
          <button className="reminder-delete-btn" onClick={() => deleteReminder(reminder.id)} aria-label="Delete reminder">
            <Trash2 size={14} />
          </button>
        </div>
      )) : (
        <div className="reminder-empty-state">
          <Bell size={24} />
          <b>No reminders yet</b>
          <span>Add one above with a time. When it becomes due, NEXUS will trigger a browser notification.</span>
        </div>
      )}
    </div>
  );
}
