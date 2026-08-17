import React, {useState, useEffect, useRef} from 'react';
import {existsSync} from 'node:fs';
import {mkdir, readFile, readdir, stat, writeFile} from 'node:fs/promises';
import path from 'node:path';
import {render, Box, Text, useApp, useInput} from 'ink';
import {resolveRetryPrompt} from './retry.js';
import {mcpServerActive} from './inline-activity.js';
import type {McpServerItem} from './inline-activity.js';
import {StatusBar} from './status-bar.js';
import {InputComposer} from './input-composer.js';
import {activeHiveAgents} from './live-agent-state.js';
import {appendToolOutput, isSyntheticAgentLifecycle, toolActivityIdentity, toolEventDeliveryIdentity} from './tool-call-state.js';
import {WorkingStatus, VoiceEqualizer} from './banner.js';
import {NexusWelcomeLogo} from './welcome-logo.js';
import {ChatLineView, activityIdsFromChatLines, buildChatLines, appendVoicePreviewLines, buildThinkingRows, nextActivityFocus, toggleActivityExpansion} from './chat-view.js';
import {CommandPalette} from './command-palette.js';
import {NexusWorkspacePanel} from './workspace-panel.js';
import {approvalDecisionFromInput} from './approval-state.js';
import {resolveTuiLayout} from './layout.js';
import {isExplicitInspectorShortcut, moveQuestionSelection, nextInspectorPanel, panelModeAfterActivitySelection, QuestionAnswerQueue, resolveQuestionAnswerSubmission, resolveQuestionSelection, resolveTabIntent} from './interaction-state.js';
import {
    API_BASE,
    DASHBOARD_TOKEN,
    API_AUTH_HEADERS,
    API_JSON_HEADERS,
    PROJECT_ROOT,
    PYTHON_EXECUTABLE,
    syncStopVoiceProcess,
    adaptCanonicalEvent,
    canonicalActivityFromSseFrame,
    normalizeSandboxTier,
    sandboxLabel,
    normalizePermissionMode,
    voicePhaseLabel,
    voicePhaseColor,
    commandDefinitionFor,
    commandMatches,
    normalizeCommandRegistry,
    canStartTurn,
    estimateTokens,
    formatTokens,
    formatContextPercent,
    fileStatusFromWorkEvent,
    normalizeActivityStatus,
    cleanPreview,
    cleanVisibleAssistantText,
    stripQuestionMarkers,
    parseQuestionMarker,
    questionFromToolEvent,
    activityFromWorkEvent,
    mergeActivityTargetFields,
    withActivityIdentity,
    inferWorkingPhaseFromTool,
    inferWorkingPhaseFromText,
    classifyTool,
    resolveInputAttachments,
    attachmentPrompt,
    cleanTaskSubject,
    taskItemsFromWorkItems,
    progressSummaryFromWorkEvent,
    progressSummaryText,
    mergePlanChecklistEvent,
    mergePlanChecklistTasks,
    mergeProgressIntoPlanChecklist,
    finalizePlanChecklist,
    planChecklistStatus,
    queueSnapshotLines,
    safeRelativePath,
    listDirectory,
    treeDirectory,
    readYamlSectionNames,
    saveClipboardImage,
    extractUrls,
    runLocal,
    runLocalResult,
    startDetached,
    commandExists,
    apiHasTuiCapabilities,
    sanitizeComposerInput,
    mouseWheelDirection,
    mouseWheelDirections,
    mousePointer,
    MAX_TIMELINE_ITEMS,
    clearTerminalForInk,
    THEME,
    PUBLIC_ACTIVITY_KINDS,
    CHAT_ACTIVITY_KINDS,
    type Message,
    type FileStatus,
    type TimelineEvent,
    type UsageStats,
    type AgentInfo,
    type TaskItem,
    type PlanChecklistItem,
    type ActivityItem,
    type PanelMode,
    type PendingQuestion,
    type PendingApproval,
    approvalFromWorkEvent,
    type WorkingPhase,
    type SandboxTier,
    type PermissionMode,
    type CommandDefinition
} from './helpers.js';

// ── [SESSION]
const INITIAL_HISTORY: Message[] = [];

const App = () => {
    const [input, setInput] = useState('');
    const [commandIndex, setCommandIndex] = useState(0);
    const [commandRegistry, setCommandRegistry] = useState<CommandDefinition[]>([]);
    const [history, setHistory] = useState<Message[]>(INITIAL_HISTORY);
    const [sessionId, setSessionId] = useState(() => `tui_${Date.now()}`);
    const [provider, setProvider] = useState('');
    const [model, setModel] = useState('');
    const [providerUsage, setProviderUsage] = useState<UsageStats | null>(null);
    const [extraDirs, setExtraDirs] = useState<string[]>([]);
    const [activities, setActivities] = useState<string[]>([]);
    const [touchedFiles, setTouchedFiles] = useState<FileStatus[]>([]);
    const [lastChange, setLastChange] = useState<string>('');
    const [panelMode, setPanelMode] = useState<PanelMode>('workspace');
    const [voiceMode, setVoiceMode] = useState<'off' | 'auto' | 'manual' | 'text'>('off');
    const [voicePhase, setVoicePhase] = useState('off');
    const [sandboxTier, setSandboxTier] = useState<SandboxTier>('normal');
    const [permissionMode, setPermissionMode] = useState<PermissionMode>('auto');
    const [voiceTranscriptPreview, setVoiceTranscriptPreview] = useState('');
    const [voiceReplyPreview, setVoiceReplyPreview] = useState('');
    const [connectionState, setConnectionState] = useState<'connecting' | 'online' | 'offline'>('connecting');
    const [startupReady, setStartupReady] = useState(false);
    const voiceSessionIdRef = useRef<string | null>(null);
    const voiceShutdownRef = useRef(false);
    const [agents, setAgents] = useState<AgentInfo[]>([]);
    const [tasks, setTasks] = useState<TaskItem[]>([]);
    const [queuePending, setQueuePending] = useState<number | null>(null);
    const [queueWorker, setQueueWorker] = useState<string>('unknown');
    const [mcpConnectedCount, setMcpConnectedCount] = useState(0);
    const [mcpServers, setMcpServers] = useState<McpServerItem[]>([]);
    const [activityItems, setActivityItems] = useState<ActivityItem[]>([]);
    const [pendingQuestion, setPendingQuestion] = useState<PendingQuestion | null>(null);
    const [pendingApproval, setPendingApproval] = useState<PendingApproval | null>(null);
    const pendingApprovalRef = useRef<PendingApproval | null>(null);
    const [questionCustomMode, setQuestionCustomMode] = useState(false);
    const [selectedQuestionIndex, setSelectedQuestionIndex] = useState(0);
    const [planItems, setPlanItems] = useState<PlanChecklistItem[]>([]);
    const [planStatus, setPlanStatus] = useState('planning');
    const [planExpanded, setPlanExpanded] = useState(false);
    const activePlanRef = useRef(false);
    const questionSubmitRef = useRef<(answer: string) => void>(() => {});
    const queuedQuestionAnswerRef = useRef(new QuestionAnswerQueue());
    const [selectedActivityId, setSelectedActivityId] = useState<string | null>(null);
    const [focusedChatActivityId, setFocusedChatActivityId] = useState<string | null>(null);
    const [expandedChatActivityId, setExpandedChatActivityId] = useState<string | null>(null);
    const [showActivitySources, setShowActivitySources] = useState(false);
    const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
    const [timeline, setTimeline] = useState<TimelineEvent[]>([
        {kind: 'step', weight: 1, label: 'Session ready'}
    ]);
    const [chatScroll, setChatScroll] = useState(0);
    const activityCounter = useRef(0);
    const streamedActivityIds = useRef(new Set<string>());
    // Track the first observed wall-clock time per task id so the task list can
    // show real elapsed duration across /tasks polls, never a fabricated value.
    const taskStartTimesRef = useRef(new Map<string, number>());
    const panelRefreshRef = useRef<Promise<{agents: AgentInfo[]; tasks: TaskItem[]}> | null>(null);
    const apiBootstrapRef = useRef<Promise<boolean> | null>(null);
    const sessionEpochRef = useRef(0);
    // SSE reconnects and server history replay can deliver the same canonical
    // event more than once. Keep a bounded identity set so replay is harmless
    // before it reaches timeline/history side effects.
    const seenWorkEventIds = useRef(new Set<string>());
    const previousChatLineCount = useRef(0);
    const voiceJustStartedRef = useRef(0);
    const chatAbortControllerRef = useRef<AbortController | null>(null);
    // The browser/Ink stream is only a transport. Keep the server-owned run
    // identity so Stop can cancel provider and tool work as well.
    const activeRunIdRef = useRef<string | null>(null);
    const turnInFlightRef = useRef(false);
    const [isThinking, setIsThinking] = useState(false);
    const [workingPhase, setWorkingPhase] = useState<WorkingPhase>('thinking');
    const [expandedThinking, setExpandedThinking] = useState(false);
    const [thinkingPrompt, setThinkingPrompt] = useState('');
    const [thinkingStartedAt, setThinkingStartedAt] = useState<number | null>(null);
    const [motionFrame, setMotionFrame] = useState(0);
    const [terminalSize, setTerminalSize] = useState({
        width: Math.max(process.stdout.columns || 100, 20),
        height: Math.max(process.stdout.rows || 30, 8)
    });
    const {exit} = useApp();

    const cancelActiveTurn = () => {
        queuedQuestionAnswerRef.current.clear();
        const runId = activeRunIdRef.current;
        const suffix = runId ? `?turn_id=${encodeURIComponent(runId)}` : '';
        void fetch(`${API_BASE}/chat/${encodeURIComponent(sessionId)}/cancel${suffix}`, {
            method: 'POST',
            headers: API_AUTH_HEADERS
        }).catch(() => {
            // The local stream still stops if the backend has already finished
            // or is temporarily unreachable; the backend owns final state.
        });
        chatAbortControllerRef.current?.abort();
        activeRunIdRef.current = null;
    };
    const slashInput = input.trimStart();
    const slashToken = slashInput.startsWith('/') && !slashInput.includes(' ') ? slashInput : '';
    const slashMatches = slashToken ? commandMatches(slashToken, commandRegistry) : [];
    const showCommandPalette = slashMatches.length > 0;
    const {width, height} = terminalSize;
    const layout = resolveTuiLayout(width, height, {
        paletteRows: showCommandPalette ? slashMatches.length : 0,
        voiceVisible: voiceMode !== 'off'
    });
    const {isWide, sidebarWidth, mainWidth: leftPanelWidth, chatContentWidth, chatViewportHeight} = layout;
    const elapsedMs = isThinking && thinkingStartedAt ? Math.max(0, Date.now() - thinkingStartedAt) : 0;
    const currentTask = thinkingPrompt || [...history].reverse().find(message => message.role === 'user')?.content || '';
    const activeActivity = activityItems.find(activity =>
        ['running', 'queued', 'pending', 'in_progress', 'working', 'active'].includes(activity.status.toLowerCase())
    );
    const baseChatLines = buildChatLines(
        history,
        activityItems,
        chatContentWidth,
        focusedChatActivityId,
        expandedChatActivityId,
        showActivitySources
    );
    const chatLines = appendVoicePreviewLines(
        [...baseChatLines],
        chatContentWidth,
        voiceMode,
        voicePhase,
        voiceTranscriptPreview,
        voiceReplyPreview,
        history
    );
    const thinkingDetailRows = isThinking && expandedThinking
        ? buildThinkingRows(chatContentWidth, workingPhase, thinkingPrompt, thinkingStartedAt, motionFrame)
        : [];
    const thinkingLineCount = isThinking ? 1 + thinkingDetailRows.length : 0;
    const visibleChatLineCount = Math.max(1, chatViewportHeight - thinkingLineCount);
    const maxChatScroll = Math.max(0, chatLines.length - visibleChatLineCount);
    const safeChatScroll = Math.min(chatScroll, maxChatScroll);
    // Inspector content is a user choice. A new plan or agent may update its
    // data, but it must not unexpectedly steal the user's current view.
    const displayedPanelMode: PanelMode = pendingApproval ? 'approval' : pendingQuestion ? 'question' : panelMode;
    // A custom answer needs the normal composer even though its question body
    // lives in the inspector on narrow terminals.
    const showNarrowInspector = !isWide
        && displayedPanelMode !== 'workspace'
        && !(pendingQuestion && questionCustomMode);
    const chatEnd = chatLines.length - safeChatScroll;
    const visibleChatLines = chatLines.slice(Math.max(0, chatEnd - visibleChatLineCount), chatEnd);
    const showWelcomeLogo = history.length === 0
        && activityItems.length === 0
        && !isThinking
        && voiceMode === 'off';
    const cycleInspectorPane = () => {
        setPanelMode(current => nextInspectorPanel(current));
    };

    useEffect(() => {
        setCommandIndex(0);
    }, [slashToken]);

    useEffect(() => {
        const previous = previousChatLineCount.current;
        const delta = chatLines.length - previous;
        previousChatLineCount.current = chatLines.length;

        setChatScroll(scroll => {
            if (delta > 0 && scroll > 0) {
                return Math.min(maxChatScroll, scroll + delta);
            }
            return Math.min(scroll, maxChatScroll);
        });
    }, [chatLines.length, maxChatScroll]);

    useEffect(() => {
        if (!process.stdout.isTTY) return;
        process.stdout.write('\x1b[?1000h\x1b[?1002h\x1b[?1003h\x1b[?1006h');
        return () => {
            process.stdout.write('\x1b[?1000l\x1b[?1002l\x1b[?1003l\x1b[?1006l');
        };
    }, []);

    const shouldAnimate = isThinking || voiceMode !== 'off' || Boolean(activeActivity);

    useEffect(() => {
        if (!shouldAnimate) return;
        const timer = setInterval(() => {
            setMotionFrame(frame => (frame + 1) % 10000);
        }, 350);
        return () => clearInterval(timer);
    }, [shouldAnimate]);

    useEffect(() => {
        if (!process.stdin.isTTY || pendingQuestion) return;
        let mouseBuffer = '';
        const handleMouseInput = (chunk: Buffer | string) => {
            mouseBuffer = (mouseBuffer + chunk.toString('latin1')).slice(-256);
            const directions = mouseWheelDirections(mouseBuffer, leftPanelWidth);
            if (directions.length > 0) {
                const delta = directions.reduce((total, direction) => total + direction, 0) * 3;
                setChatScroll(scroll => Math.max(0, Math.min(maxChatScroll, scroll + delta)));
                mouseBuffer = '';
                return;
            }
            const pointer = mousePointer(mouseBuffer, terminalSize.width);
            if (!pointer || !(pointer.button === 35 || (pointer.button === 0 && pointer.pressed))) return;
            if (pointer.x > leftPanelWidth) {
                if (panelMode === 'plan' && pointer.button === 0) {
                    setPlanExpanded(expanded => !expanded);
                }
                mouseBuffer = '';
                return;
            }
            const lineIndex = pointer.y - layout.chatStartRow;
            const activityId = visibleChatLines[lineIndex]?.activityId;
            if (activityId) {
                setFocusedChatActivityId(activityId);
                if (pointer.button === 0) {
                    setSelectedActivityId(activityId);
                    setExpandedChatActivityId(current => toggleActivityExpansion(current, activityId));
                    const activity = activityItems.find(item => item.id === activityId);
                    setPanelMode(current => panelModeAfterActivitySelection(current, activity?.kind));
                }
            } else if (isThinking && lineIndex >= visibleChatLines.length && lineIndex < visibleChatLines.length + thinkingLineCount) {
                setFocusedChatActivityId(null);
                if (pointer.button === 0) {
                    setExpandedThinking(expanded => !expanded);
                }
            } else if (pointer.button === 35) {
                setFocusedChatActivityId(null);
            }
            mouseBuffer = '';
        };
        process.stdin.on('data', handleMouseInput);
        return () => {
            process.stdin.off('data', handleMouseInput);
        };
    }, [isThinking, layout.chatStartRow, leftPanelWidth, maxChatScroll, panelMode, pendingQuestion, showActivitySources, terminalSize.width, thinkingLineCount, visibleChatLines]);

    const stopVoiceIfRunning = async () => {
        if (voiceShutdownRef.current) return;
        voiceShutdownRef.current = true;
        try {
            const statusRes = await fetch(`${API_BASE}/voice/status`, {headers: API_AUTH_HEADERS});
            const statusData = await statusRes.json();
            if (statusData?.running) {
                await fetch(`${API_BASE}/voice/stop`, {method: 'POST', headers: API_AUTH_HEADERS});
            }
        } catch {
            // Best effort shutdown.
        } finally {
            setVoiceMode('off');
            setVoicePhase('off');
            setVoiceTranscriptPreview('');
            setVoiceReplyPreview('');
            voiceSessionIdRef.current = null;
            voiceShutdownRef.current = false;
        }
    };

    useEffect(() => {
        const handleProcessShutdown = () => {
            syncStopVoiceProcess();
        };

        process.once('SIGINT', handleProcessShutdown);
        process.once('SIGTERM', handleProcessShutdown);
        process.once('SIGHUP', handleProcessShutdown);
        process.once('beforeExit', handleProcessShutdown);
        process.once('exit', handleProcessShutdown);

        return () => {
            process.removeListener('SIGINT', handleProcessShutdown);
            process.removeListener('SIGTERM', handleProcessShutdown);
            process.removeListener('SIGHUP', handleProcessShutdown);
            process.removeListener('beforeExit', handleProcessShutdown);
            process.removeListener('exit', handleProcessShutdown);
            handleProcessShutdown();
        };
    }, []);

    useInput((value, key) => {
        const scrollPage = Math.max(1, visibleChatLineCount - 2);
        const wheelDirection = mouseWheelDirection(value, leftPanelWidth);

        if (pendingApproval) {
            const decision = approvalDecisionFromInput(value, key.escape);
            if (decision) {
                void resolveApproval(decision);
            }
            return;
        }

        if (panelMode === 'question' && pendingQuestion) {
            if (questionCustomMode && key.escape) {
                setQuestionCustomMode(false);
                setInput('');
                return;
            }
            const questionWheel = mouseWheelDirection(value, terminalSize.width);
            if (key.upArrow || questionWheel > 0) {
                setSelectedQuestionIndex(index => moveQuestionSelection(pendingQuestion, index, -1));
                return;
            }
            if (key.downArrow || questionWheel < 0) {
                setSelectedQuestionIndex(index => moveQuestionSelection(pendingQuestion, index, 1));
                return;
            }
            if (key.return && !questionCustomMode) {
                const selected = resolveQuestionSelection(pendingQuestion, selectedQuestionIndex);
                if (selected?.kind === 'custom') {
                    setInput('');
                    setQuestionCustomMode(true);
                } else if (selected?.kind === 'answer') {
                    questionSubmitRef.current(selected.answer);
                }
                return;
            }
        }

        if (panelMode === 'question' && pendingQuestion && /^[1-9]$/.test(value)) {
            const selectedIndex = Number(value) - 1;
            const selected = resolveQuestionSelection(pendingQuestion, selectedIndex);
            if (selected?.kind === 'answer') {
                setSelectedQuestionIndex(selectedIndex);
                questionSubmitRef.current(selected.answer);
            } else if (selected?.kind === 'custom') {
                setSelectedQuestionIndex(selectedIndex);
                setInput('');
                setQuestionCustomMode(true);
            }
            return;
        }

        if (key.escape && isThinking) {
            cancelActiveTurn();
            pushCommand('cancelling current turn...');
            return;
        }

        if (key.escape && showNarrowInspector) {
            setPanelMode('workspace');
            return;
        }

        if (key.ctrl && value.toLowerCase() === 'k') {
            if (input.startsWith('/')) {
                setInput('/');
            } else {
                setInput('/');
            }
            return;
        }

        if (isExplicitInspectorShortcut(value, key.ctrl) && !showCommandPalette) {
            cycleInspectorPane();
            return;
        }

        if (key.tab && !showCommandPalette) {
            const activityIds = activityIdsFromChatLines(visibleChatLines);
            // Ctrl+I and Tab are the same ASCII control byte. Ink therefore
            // reports Ctrl+I as Tab in Windows Terminal. Route the byte
            // deterministically: with rows present it moves row focus (Shift
            // goes backwards); otherwise it honors the documented inspector
            // key; a surviving ctrl bit always means inspector intent.
            const intent = resolveTabIntent({
                paletteOpen: showCommandPalette,
                hasActivityRows: activityIds.length > 0,
                ctrl: Boolean(key.ctrl),
                shift: Boolean(key.shift)
            });
            if (intent === 'cycle-inspector') {
                cycleInspectorPane();
                return;
            }
            if (intent === 'cycle-activity') {
                const nextId = nextActivityFocus(activityIds, focusedChatActivityId, key.shift);
                if (!nextId) return;
                setFocusedChatActivityId(nextId);
                setSelectedActivityId(nextId);
                return;
            }
            return;
        }

        if (key.return && !showCommandPalette && input.length === 0 && focusedChatActivityId) {
            setExpandedChatActivityId(current => toggleActivityExpansion(current, focusedChatActivityId));
            return;
        }

        // Mouse-wheel scrolling is handled from raw stdin above because Windows
        // Terminal can split one SGR mouse packet across multiple Ink inputs.
        if (wheelDirection !== 0) return;

        if (key.pageUp || (key.ctrl && value === 'u')) {
            setChatScroll(scroll => Math.min(maxChatScroll, scroll + scrollPage));
            return;
        }

        if (key.pageDown || (key.ctrl && value === 'd')) {
            setChatScroll(scroll => Math.max(0, scroll - scrollPage));
            return;
        }

        if (!showCommandPalette && input.length === 0 && key.upArrow) {
            setChatScroll(scroll => Math.min(maxChatScroll, scroll + 1));
            return;
        }

        if (!showCommandPalette && input.length === 0 && key.downArrow) {
            setChatScroll(scroll => Math.max(0, scroll - 1));
            return;
        }

        if (!showCommandPalette) return;

        if (key.upArrow) {
            setCommandIndex(index => (index <= 0 ? slashMatches.length - 1 : index - 1));
            return;
        }

        if (key.downArrow) {
            setCommandIndex(index => (index + 1) % slashMatches.length);
            return;
        }

        if (key.tab) {
            const selected = slashMatches[Math.min(commandIndex, slashMatches.length - 1)];
            if (selected) {
                setInput(`${selected.name} `);
            }
        }
    });

    useEffect(() => {
        const handleResize = () => setTerminalSize({
            width: Math.max(process.stdout.columns || 100, 20),
            height: Math.max(process.stdout.rows || 30, 8)
        });
        process.stdout.on('resize', handleResize);
        return () => { process.stdout.off('resize', handleResize); };
    }, []);

    const refreshPanelData = async () => {
        const refreshEpoch = sessionEpochRef.current;
        const isCurrentSession = () => refreshEpoch === sessionEpochRef.current;
        // Approval events can be missed during an SSE reconnect. Rehydrate the
        // durable broker row so the TUI can always present a live decision.
        try {
            const approvalResponse = await fetch(
                `${API_BASE}/approve/pending?session_id=${encodeURIComponent(sessionId)}`,
                {headers: API_AUTH_HEADERS}
            );
            if (approvalResponse.ok) {
                const approvalData = await approvalResponse.json();
                const approval = Array.isArray(approvalData.pending) && approvalData.pending.length > 0
                    ? approvalFromWorkEvent(approvalData.pending[0])
                    : null;
                if (!isCurrentSession()) return {agents: [], tasks: []};
                if (approval) {
                    pendingApprovalRef.current = approval;
                    setPendingApproval(approval);
                    setPanelMode('approval');
                } else {
                    if (pendingApprovalRef.current?.sessionId === sessionId) {
                        pendingApprovalRef.current = null;
                    }
                    setPendingApproval(current => current && current.sessionId === sessionId ? null : current);
                    setPanelMode(current => current === 'approval' ? 'workspace' : current);
                }
            }
        } catch {
            // The SSE path remains authoritative while the broker endpoint is
            // temporarily unavailable.
        }

        // `/agents` is a catalog of configured personas and commonly contains
        // idle entries. The Hive panel must show live execution only, so use
        // `/hives` as the source of truth for currently running sub-agents.
        let nextAgents: AgentInfo[] = [];
        let nextTasks = tasks;
        try {
            const hivesResponse = await fetch(`${API_BASE}/hives`, {headers: API_AUTH_HEADERS});
            const hivesData = await hivesResponse.json();
            if (Array.isArray(hivesData.hives)) {
                nextAgents = activeHiveAgents(hivesData) as AgentInfo[];
            }
            if (isCurrentSession()) setAgents(nextAgents);
        } catch {
            // Do not retain a stale live-agent list when the live endpoint is
            // unavailable; the panel should fail closed instead of claiming
            // that sub-agents are still running.
            if (isCurrentSession()) setAgents([]);
        }

        const liveTaskIds = new Set<string>();
        try {
            // Tasks are session-owned. The legacy /tasks endpoint is a global
            // task registry and would leak the previous session's plan into a
            // freshly started TUI session.
            const tasksResponse = await fetch(
                `${API_BASE}/work-items?session_id=${encodeURIComponent(sessionId)}&limit=100`,
                {headers: API_AUTH_HEADERS}
            );
            const tasksData = await tasksResponse.json();
            if (Array.isArray(tasksData.work_items)) {
                nextTasks = taskItemsFromWorkItems(tasksData.work_items).map(task => {
                    const id = task.id;
                    liveTaskIds.add(id);
                    if (!taskStartTimesRef.current.has(id)) {
                        taskStartTimesRef.current.set(id, task.startedAt || Date.now());
                    }
                    return {
                        ...task,
                        startedAt: taskStartTimesRef.current.get(id)
                    };
                });
                if (isCurrentSession()) {
                    setTasks(nextTasks);
                    setPlanItems(previous => {
                        const restoredPlan = tasksData.active_plan && typeof tasksData.active_plan === 'object'
                            ? tasksData.active_plan as {plan_id?: unknown; steps?: unknown}
                            : null;
                        const restoredTasks = taskItemsFromWorkItems(restoredPlan?.steps);
                        const source = !activePlanRef.current && restoredTasks.length > 0
                            ? []
                            : previous;
                        const overlay = !activePlanRef.current && restoredTasks.length > 0
                            ? restoredTasks
                            : nextTasks;
                        const merged = mergePlanChecklistTasks(
                            source,
                            overlay,
                            !activePlanRef.current
                        ).map(item => restoredPlan?.plan_id && !item.planId
                            ? {...item, planId: String(restoredPlan.plan_id)}
                            : item
                        );
                        setPlanStatus(planChecklistStatus(merged));
                        return merged;
                    });
                }
            }
        } catch {
            // Session tasks are optional; clear rather than retaining a stale
            // previous-session list after a restart or API reconnect.
            nextTasks = [];
            if (isCurrentSession()) setTasks([]);
        }
        // Drop start-times for tasks that disappeared server-side so elapsed time
        // stays honest when a task id is later reused.
        for (const key of [...taskStartTimesRef.current.keys()]) {
            if (!liveTaskIds.has(key)) taskStartTimesRef.current.delete(key);
        }

        try {
            // This is deliberately separate from session work-items above:
            // queued cron/autonomous work can exist before it has a session
            // work-item projection, and must remain observable after restart.
            const queueResponse = await fetch(
                `${API_BASE}/queue?session_id=${encodeURIComponent(sessionId)}&include_global=false&limit=20`,
                {headers: API_AUTH_HEADERS}
            );
            if (!queueResponse.ok) throw new Error(`queue returned ${queueResponse.status}`);
            const queueData = await queueResponse.json();
            if (isCurrentSession()) {
                setQueuePending(Number.isFinite(Number(queueData.pending)) ? Number(queueData.pending) : null);
                setQueueWorker(String(queueData.worker || 'unknown'));
            }
        } catch {
            // Queue status is optional for interactive chat. Do not retain a
            // stale count after an API restart or a session reconnect.
            if (isCurrentSession()) {
                setQueuePending(null);
                setQueueWorker('unknown');
            }
        }

        try {
            const mcpResponse = await fetch(`${API_BASE}/mcp`, {headers: API_AUTH_HEADERS});
            const mcpData = await mcpResponse.json();
            if (Array.isArray(mcpData.mcp)) {
                const servers = mcpData.mcp.map((server: any) => ({
                    id: String(server.id || server.name || ''),
                    command: server.command ? String(server.command) : undefined,
                    args: server.args ? String(server.args) : undefined,
                    description: server.description ? String(server.description) : undefined,
                    active: Boolean(server.active),
                    connected: Boolean(server.connected),
                    status: server.status ? String(server.status) : undefined
                })).filter((server: {id: string}) => server.id);
                if (isCurrentSession()) {
                    setMcpServers(servers);
                    setMcpConnectedCount(servers.filter(mcpServerActive).length);
                }
            }
        } catch {
            // Keep the last verified MCP list while the API is unavailable.
        }

        try {
            const commandResponse = await fetch(`${API_BASE}/commands`, {headers: API_AUTH_HEADERS});
            if (!commandResponse.ok) throw new Error(`command registry returned ${commandResponse.status}`);
            if (isCurrentSession()) setCommandRegistry(normalizeCommandRegistry(await commandResponse.json()));
        } catch {
            // Never invent a second client-side command catalog. Keep the last
            // verified registry snapshot until the backend is reachable again.
        }

        try {
            const status = await apiJson('/status');
            if (isCurrentSession()) {
                setConnectionState('online');
                setSandboxTier(normalizeSandboxTier(String(status.sandbox_tier || 'no_sandbox')));
                setPermissionMode(normalizePermissionMode(String(status.mode || 'auto')));
            }
            // The status bar shows the ACTIVE provider/model from the backend, not
            // a cached override. Local /model and /provider overrides win when set.
            if (isCurrentSession()) {
                if (status.model) setModel(String(status.model));
                if (status.provider) setProvider(String(status.provider));
            }
        } catch {
            // Keep connection failure visible without adding noisy polling rows to chat.
            if (isCurrentSession()) setConnectionState('offline');
        }

        try {
            const voiceResponse = await fetch(`${API_BASE}/voice/status`, {headers: API_AUTH_HEADERS});
            const voiceData = await voiceResponse.json();
            if (voiceData.running) {
                if (isCurrentSession()) {
                    setVoiceMode(voiceData.mode || 'auto');
                    setVoicePhase(String(voiceData.phase || 'idle'));
                    setVoiceTranscriptPreview(String(voiceData.transcript_preview || ''));
                    setVoiceReplyPreview(String(voiceData.reply_preview || ''));
                }
            } else {
                if (isCurrentSession()) {
                    setVoiceMode('off');
                    setVoicePhase('off');
                    setVoiceTranscriptPreview('');
                    setVoiceReplyPreview('');
                }
            }
        } catch {
            // Ignore errors querying voice status
        }

        return {agents: nextAgents, tasks: nextTasks};
    };

    const loadPanelData = () => {
        if (panelRefreshRef.current) return panelRefreshRef.current;
        const refresh = refreshPanelData();
        panelRefreshRef.current = refresh;
        return refresh.finally(() => {
            if (panelRefreshRef.current === refresh) panelRefreshRef.current = null;
        });
    };

    useEffect(() => {
        sessionEpochRef.current += 1;
        if (!startupReady) return;
        void loadPanelData();
        const timer = setInterval(() => {
            void loadPanelData();
        }, 6000);
        return () => clearInterval(timer);
    }, [sessionId, startupReady]);

    useEffect(() => {
        const startFreshSession = async () => {
            try {
                const apiReady = await ensureApiAvailable();
                if (!apiReady) {
                    setConnectionState('offline');
                    setStartupReady(true);
                    return;
                }
                const created = await apiJson('/sessions/new', {method: 'POST'});
                if (created?.id) {
                    setSessionId(String(created.id));
                    setHistory(INITIAL_HISTORY);
                    resetSessionView();
                }
                setStartupReady(true);
            } catch {
                // Keep local defaults if the API is still starting; the panel
                // poll will retry state hydration without fabricating a turn.
                setConnectionState('offline');
                setStartupReady(true);
            }
        };

        void startFreshSession();
    }, []);

    // Real-time chat + voice sync during voice mode
    useEffect(() => {
        if (voiceMode === 'off') return;
        
        const syncHistory = async () => {
            try {
                // Skip history loading for 3s after voice starts (voice status still updates)
                const skipUntil = voiceJustStartedRef.current;
                const inGracePeriod = skipUntil && Date.now() < skipUntil;
                if (skipUntil && !inGracePeriod) voiceJustStartedRef.current = 0;
                const voiceData = await apiJson('/voice/status').catch(() => null);
                if (voiceData && voiceData.running) {
                    setVoiceMode(voiceData.mode || 'auto');
                    setVoicePhase(String(voiceData.phase || 'idle'));
                    setVoiceTranscriptPreview(String(voiceData.transcript_preview || ''));
                    setVoiceReplyPreview(String(voiceData.reply_preview || ''));
                } else if (voiceData && !voiceData.running) {
                    setVoiceMode('off');
                    setVoicePhase('off');
                    setVoiceTranscriptPreview('');
                    setVoiceReplyPreview('');
                    return;
                }

                // Only fetch history after grace period (prevents old history flash on voice start)
                if (!inGracePeriod) {
                    const loaded = await apiJson(`/history?session_id=${encodeURIComponent(sessionId)}`);
                    if (Array.isArray(loaded)) {
                        const loadedHistory = loaded.map((msg: any) => ({
                            role: msg.role,
                            content: msg.role === 'assistant'
                                ? cleanVisibleAssistantText(String(msg.content || ''))
                                : String(msg.content || '')
                        }));
                        setHistory(prev => {
                            const hasChanged = loadedHistory.length !== prev.length ||
                                loadedHistory.some((msg, i) => !prev[i] || msg.role !== prev[i].role || msg.content !== prev[i].content);
                            return hasChanged ? loadedHistory : prev;
                        });
                    }
                }
            } catch {
                // Ignore history load errors
            }
        };

        void syncHistory();
        const interval = setInterval(syncHistory, 350);
        return () => clearInterval(interval);
    }, [voiceMode, sessionId]);

    const usage: UsageStats = providerUsage || {
        contextTokens: 0,
        contextLimit: 0,
        inputTokens: 0,
        outputTokens: 0,
        source: 'unavailable'
    };

    const appendTimeline = (event: TimelineEvent) => {
        setTimeline(prev => [...prev, event].slice(-MAX_TIMELINE_ITEMS));
    };

    const addActivityItem = (activity: Omit<ActivityItem, 'id' | 'number'>) => {
        activityCounter.current += 1;
        const identified = withActivityIdentity(activity);
        const item: ActivityItem = {
            ...identified,
            status: normalizeActivityStatus(identified.status, identified.error),
            startedAt: Date.now(),
            id: `activity-${activityCounter.current}`,
            number: activityCounter.current
        };

        setActivityItems(prev => [item, ...prev].slice(0, 80));
        setSelectedActivityId(item.id);

        return item;
    };

    const upsertWorkEventActivity = (event: Record<string, any>, focusPanel = true) => {
        const normalized = withActivityIdentity(activityFromWorkEvent(event));
        const isPlanActivity = normalized.toolName === 'plan';
        const hiveMember = normalized.kind === 'hive'
            ? String(event.related_subagent || event.subagent_id || event.worker_id || event.agent_id || '')
            : '';
        const serverId = isPlanActivity
            ? `plan-${event.run_id || event.turn_id || sessionId}`
            : hiveMember
                ? `hive-${event.run_id || event.turn_id || sessionId}-${hiveMember}`
                : toolActivityIdentity(event, sessionId);
        const id = `work-${serverId}`;
        const sourceType = String(event.event_type || event.type || '').toLowerCase();
        const isLifecycleNoise = /^(run|conversation|message|status|phase)\./.test(sourceType);
        let number = 0;
        if (!streamedActivityIds.current.has(id)) {
            streamedActivityIds.current.add(id);
            activityCounter.current += 1;
            number = activityCounter.current;
            if (CHAT_ACTIVITY_KINDS.has(normalized.kind) && !isLifecycleNoise) {
                setHistory(prev => {
                    const next = [...prev];
                    const assistantIndex = next.findLastIndex(message => message.role === 'assistant');
                    const activityMessage = {role: 'activity', content: normalized.title, activityId: id};
                    if (assistantIndex >= 0) next.splice(assistantIndex, 0, activityMessage);
                    else next.push(activityMessage);
                    return next;
                });
            }
        }
        setActivityItems(prev => {
            const existing = prev.find(item => item.id === id);
            let item: ActivityItem;
            if (existing && isPlanActivity) {
                const priorSteps = existing.detail === 'Resolving planning steps…'
                    ? []
                    : String(existing.detail || '').split('\n').map(line => line.replace(/^\d+\.\s*/, '').trim()).filter(Boolean);
                const incomingSteps = normalized.detail === 'Resolving planning steps…'
                    ? []
                    : String(normalized.detail || '').split('\n').map(line => line.replace(/^\d+\.\s*/, '').trim()).filter(Boolean);
                const steps = [...new Set([...priorSteps, ...incomingSteps])];
                item = {
                    ...existing,
                    ...normalized,
                    id,
                    number: existing.number,
                    startedAt: existing.startedAt,
                    durationMs: normalized.durationMs ?? existing.durationMs,
                    title: steps.length > 1 ? 'Advanced Planning' : 'Simple Planning',
                    summary: `${steps.length || 1} step${steps.length === 1 ? '' : 's'}`,
                    detail: steps.length > 0
                        ? steps.map((step, index) => `${index + 1}. ${step}`).join('\n')
                        : existing.detail || 'Resolving planning steps…'
                };
            } else {
                    const isOutputChunk = Boolean(
                        event.append
                        || event.chunk != null
                        || event.stream
                        || String(event.part_type || '').toLowerCase().includes('chunk')
                        || sourceType.includes('stdout')
                        || sourceType.includes('stderr')
                        || sourceType.includes('.delta')
                    );
                    item = existing
                        ? {
                            ...existing,
                            ...normalized,
                            ...mergeActivityTargetFields(existing, normalized),
                            id,
                            number: existing.number,
                            output: isOutputChunk
                                ? appendToolOutput(existing.output, normalized.output)
                                : normalized.output ?? existing.output,
                            error: isOutputChunk
                                ? appendToolOutput(existing.error, normalized.error)
                                : normalized.error ?? existing.error
                        }
                        : {...normalized, id, number, startedAt: Date.now()};
                if (existing) {
                    item.startedAt = existing.startedAt;
                    item.durationMs = normalized.durationMs ?? existing.durationMs;
                    item.sources = [...new Set([...(existing.sources || []), ...(normalized.sources || [])])];
                    item.status = existing.status === 'error' ? 'error' : normalizeActivityStatus(item.status, item.error);
                }
            }
            return [item, ...prev.filter(candidate => candidate.id !== id)].slice(0, 80);
        });
        if (focusPanel) {
            setSelectedActivityId(id);
        }
    };

    const acceptWorkEvent = (event: Record<string, any>): boolean => {
        const identity = String(
            toolEventDeliveryIdentity(event, sessionId)
        );
        if (seenWorkEventIds.current.has(identity)) return false;
        seenWorkEventIds.current.add(identity);
        // Avoid unbounded growth across a long-lived TUI session while still
        // covering normal reconnect/replay windows.
        if (seenWorkEventIds.current.size > 1024) {
            const oldest = seenWorkEventIds.current.values().next().value;
            if (oldest) seenWorkEventIds.current.delete(oldest);
        }
        return true;
    };

    const completeRunningActivities = (status: 'done' | 'error' | 'cancelled', reason = '') => {
        setActivityItems(prev => prev.map(activity => (
            activity.status === 'running'
                ? {
                    ...activity,
                    status: activity.error || reason ? 'error' : status,
                    error: activity.error || reason || undefined,
                    durationMs: activity.durationMs ?? (activity.startedAt ? Date.now() - activity.startedAt : undefined)
                }
                : activity
        )));
    };

    const updateLatestActivityForTool = (toolName: string, result: {output?: string; error?: string}) => {
        setActivityItems(prev => {
            const next = [...prev];
            const index = next.findIndex(activity => activity.toolName === toolName && activity.status === 'running');
            if (index === -1) return prev;

            const output = cleanPreview(result.output || '', 30);
            const error = cleanPreview(result.error || '', 16);
            next[index] = {
                ...next[index],
                output: output || next[index].output,
                error: error || next[index].error,
                sources: [...new Set([...(next[index].sources || []), ...extractUrls(output), ...extractUrls(error)])],
                durationMs: next[index].durationMs ?? (next[index].startedAt ? Date.now() - next[index].startedAt : undefined),
                status: normalizeActivityStatus(error || output.toLowerCase().startsWith('[error]') ? 'error' : 'done', error)
            };
            return next;
        });
    };

    const pushCommand = (content: string) => {
        setHistory(prev => [...prev, {role: 'command', content}]);
    };

    const pushSystem = (content: string) => {
        setHistory(prev => [...prev, {role: 'system', content}]);
    };

    const resetSessionView = () => {
        // Session-scoped projections must not survive /new or /resume. The
        // backend owns persistence; this only clears the old session's local
        // view before the next panel refresh arrives.
        seenWorkEventIds.current.clear();
        streamedActivityIds.current.clear();
        taskStartTimesRef.current.clear();
        activityCounter.current = 0;
        queuedQuestionAnswerRef.current.clear();
        setTasks([]);
        setQueuePending(null);
        setQueueWorker('unknown');
        setActivityItems([]);
        setActivities([]);
        setTouchedFiles([]);
        setLastChange('');
        setTimeline([{kind: 'step', weight: 1, label: 'Session ready'}]);
        setPendingQuestion(null);
        pendingApprovalRef.current = null;
        setPendingApproval(null);
        activePlanRef.current = false;
        setPlanItems([]);
        setPlanStatus('planning');
        setPlanExpanded(false);
        setSelectedActivityId(null);
        setFocusedChatActivityId(null);
        setExpandedChatActivityId(null);
        setSelectedAgentId(null);
        setPanelMode('workspace');
        setProviderUsage(null);
        setChatScroll(0);
    };

    const ensureApiAvailable = async () => {
        if (apiBootstrapRef.current) return apiBootstrapRef.current;
        const bootstrap = (async () => {
            if (await apiHasTuiCapabilities()) return true;

            // Never kill an unknown process merely because it owns the default
            // port. Direct TUI use may only start a new one. When the TUI owns
            // the launch, enable the embedded durable worker so cron/queued
            // work is not left in SQLite with no consumer. An explicit caller
            // setting still wins.
            startDetached(PYTHON_EXECUTABLE, ['-m', 'server'], PROJECT_ROOT, {
                NEXUS_DASHBOARD_TOKEN: DASHBOARD_TOKEN,
                NEXUS_EMBED_QUEUE_DRIVER: process.env.NEXUS_EMBED_QUEUE_DRIVER || 'true'
            });

            for (let attempt = 0; attempt < 30; attempt += 1) {
                await new Promise(resolve => setTimeout(resolve, 400));
                if (await apiHasTuiCapabilities()) return true;
            }
            return false;
        })();
        apiBootstrapRef.current = bootstrap;
        try {
            return await bootstrap;
        } finally {
            if (apiBootstrapRef.current === bootstrap) apiBootstrapRef.current = null;
        }
    };

    const apiJson = async (endpoint: string, init?: RequestInit) => {
        const response = await fetch(`${API_BASE}${endpoint}`, {
            ...init,
            headers: {
                ...API_JSON_HEADERS,
                ...(init?.headers || {})
            }
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            const detail = data.detail || data.error || response.statusText;
            throw new Error(String(detail));
        }
        return data;
    };

    const postJson = (endpoint: string, body: Record<string, any>) => apiJson(endpoint, {
        method: 'POST',
        body: JSON.stringify(body)
    });

    const resolveApproval = async (decision: 'allow' | 'allow_always' | 'deny') => {
        const approval = pendingApproval;
        if (!approval) return;
        try {
            const result = await postJson('/approve', {
                request_id: approval.requestId,
                decision
            });
            if (result.matched === false) {
                pushSystem('Approval was already resolved or expired.');
            }
            pendingApprovalRef.current = null;
            setPendingApproval(null);
            setPanelMode(current => current === 'approval' ? 'workspace' : current);
        } catch (error) {
            pushSystem(`APPROVAL_ERROR: ${error instanceof Error ? error.message : String(error)}`);
        }
    };

    const formatRows = (rows: string[]) => rows.length > 0 ? rows.join('\n') : 'No results.';
    const providerDiagnosticsRows = (diagnostics: any) => {
        const active = diagnostics?.active || {};
        const rows = [`active: ${active.provider || 'unknown'}${active.profile ? `/${active.profile}` : ''} · ${active.model || 'unknown'}`, `fallback attempts: ${Number(diagnostics?.fallback_attempts || 0)}`];
        const failure = diagnostics?.last_failure;
        if (failure) rows.push(`last failure: ${failure.provider || 'provider'}${failure.profile ? `/${failure.profile}` : ''} · ${failure.failure_class || 'unknown'}${failure.reason ? ` · ${failure.reason}` : ''}`);
        const cooldowns = Array.isArray(diagnostics?.cooldowns) ? diagnostics.cooldowns : [];
        if (cooldowns.length) rows.push(`cooldowns: ${cooldowns.slice(0, 8).map((item: any) => `${item.provider}/${item.profile} ${Math.ceil(Number(item.cooldown_seconds || 0))}s${item.reason ? ` (${item.reason})` : ''}`).join(', ')}`);
        return rows;
    };
    const manageJson = (action: string, type: string, name = '', value?: any) => postJson('/manage', {action, type, name, value});
    const formatEnabled = (value: boolean | undefined) => value ? 'enabled' : 'disabled';
    const lastAssistantText = () => [...history].reverse().find(msg => msg.role === 'assistant' && msg.content.trim())?.content.trim() || '';
    const conversationText = () => history
        .filter(msg => ['user', 'assistant', 'command'].includes(msg.role) && msg.content.trim())
        .map(msg => `${msg.role.toUpperCase()}: ${msg.content.trim()}`)
        .join('\n\n');
    const usageLines = () => [
        usage.source === 'provider'
            ? `context: ${formatContextPercent(usage.contextTokens, usage.contextLimit)} (${formatTokens(usage.contextTokens)} / ${formatTokens(usage.contextLimit)})`
            : 'context: unavailable (provider did not report token usage)',
        usage.source === 'provider' ? `input: ${formatTokens(usage.inputTokens)}` : 'input: unavailable',
        usage.source === 'provider' ? `output: ${formatTokens(usage.outputTokens)}` : 'output: unavailable',
        `messages: ${history.filter(msg => msg.role === 'user' || msg.role === 'assistant').length}`,
        `activities: ${activityItems.length}`
    ];
    const contextLines = () => [
        ...usageLines(),
        'recent activity:',
        ...timeline.slice(-12).map(event => `${event.kind} ${formatTokens(event.weight)} - ${event.label}`)
    ];
    const unsupportedCommand = (name: string, reason: string) => {
        pushCommand(formatRows([
            `${name}: not available in this local NEXUS runtime`,
            reason,
            'No fake action was run.'
        ]));
    };
    const formatManageResult = (result: any) => {
        if (result.type === 'config') return `config set: ${result.path} = ${JSON.stringify(result.value)}`;
        if (result.type === 'provider') return `provider ${result.name}: ${result.active ? 'active' : 'inactive'}${result.model ? ` model=${result.model}` : ''}`;
        if (result.type === 'feature') return `feature ${result.name}: ${formatEnabled(result.enabled)}`;
        if (result.type) return `${result.type} ${result.name}: ${formatEnabled(result.enabled ?? result.active)}`;
        if (result.reloaded_loops !== undefined) return `${result.target || 'runtime'} reset/reload: ${result.reloaded_loops} loops cleared`;
        return JSON.stringify(result);
    };

    const parseManageArgs = (args: string) => {
        const [type = '', name = '', ...rest] = args.trim().split(/\s+/).filter(Boolean);
        return {type: type.toLowerCase(), name, rest, value: rest.join(' ')};
    };

    const handlePanelCommand = async (value: string) => {
        const normalized = value.trim().toLowerCase();
        if (!normalized.startsWith('/')) return false;

        if (normalized === '/close') {
            setPanelMode('workspace');
            setSelectedAgentId(null);
            setSelectedActivityId(null);
            return true;
        }

        if (normalized.startsWith('/panel')) {
            const requested = normalized.split(/\s+/, 2)[1] as PanelMode | undefined;
            const valid: PanelMode[] = ['workspace', 'plan', 'hive', 'mcp', 'activity'];
            if (requested && valid.includes(requested)) {
                setPanelMode(requested);
                if (requested !== 'activity') setSelectedActivityId(null);
                if (requested !== 'hive') setSelectedAgentId(null);
            } else {
                setPanelMode('workspace');
                setSelectedAgentId(null);
                setSelectedActivityId(null);
            }
            return true;
        }

        if (normalized === '/back') {
            if (panelMode === 'agent') {
                setPanelMode('hive');
                setSelectedAgentId(null);
            } else {
                setPanelMode('workspace');
                setSelectedActivityId(null);
            }
            return true;
        }

        if (normalized.startsWith('/open') || normalized.startsWith('/detail')) {
            const [, rawNumber] = normalized.split(/\s+/, 2);
            const number = rawNumber ? Number(rawNumber) : activityItems[0]?.number;
            const item = activityItems.find(activity => activity.number === number);
            if (item) {
                setSelectedActivityId(item.id);
                setSelectedAgentId(null);
                setPanelMode('activity');
            }
            return true;
        }

        if (normalized.startsWith('/hive')) {
            const {agents: latestAgents} = await loadPanelData();
            const [, rawIndex] = normalized.split(/\s+/, 2);
            const index = rawIndex ? Number(rawIndex) : NaN;
            if (Number.isInteger(index) && index > 0 && latestAgents[index - 1]) {
                setSelectedAgentId(latestAgents[index - 1].id);
                setSelectedActivityId(null);
                setPanelMode('agent');
            } else {
                setSelectedAgentId(null);
                setSelectedActivityId(null);
                setPanelMode('hive');
            }
            return true;
        }

        return false;
    };

    const handleSlashCommand = async (value: string) => {
        if (!value.trim().startsWith('/')) return false;

        const trimmed = value.trim();
        const [rawCommand, ...parts] = trimmed.split(/\s+/);
        const typedCommand = rawCommand.toLowerCase();
        const matchedCommand = commandDefinitionFor(typedCommand, commandRegistry);
        if (!matchedCommand) {
            pushCommand(`Unknown command: ${rawCommand}. Type /help.`);
            return true;
        }
        const command = matchedCommand.name;
        const args = trimmed.slice(rawCommand.length).trim();

        try {
            if (await handlePanelCommand(value)) return true;

            if (command === '/clear') {
                setHistory([]);
                return true;
            }

            if (command === '/exit') {
                await stopVoiceIfRunning();
                exit();
                return true;
            }

            if (command === '/usage') {
                pushCommand(formatRows(usageLines()));
                return true;
            }

            if (command === '/context') {
                pushCommand(formatRows(contextLines()));
                return true;
            }

            if (command === '/sources') {
                const value = parts[0]?.toLowerCase();
                if (value === 'on' || value === 'true' || value === 'show') {
                    setShowActivitySources(true);
                    pushCommand('activity sources: on');
                } else if (value === 'off' || value === 'false' || value === 'hide') {
                    setShowActivitySources(false);
                    pushCommand('activity sources: off');
                } else {
                    pushCommand(`activity sources: ${showActivitySources ? 'on' : 'off'} — use /sources on or /sources off`);
                }
                return true;
            }

            if (command === '/compact') {
                const keepCount = Math.max(4, Number(parts[0]) || 12);
                const before = history.length;
                setHistory(prev => prev.slice(-keepCount));
                pushCommand(`compacted visible TUI history: kept ${Math.min(before, keepCount)} of ${before} rows`);
                return true;
            }

            if (command === '/copy') {
                const text = args === 'all' ? conversationText() : lastAssistantText();
                if (!text) {
                    pushCommand('nothing to copy yet');
                } else {
                    const tempDir = path.join(PROJECT_ROOT, 'workspace', 'exports');
                    await mkdir(tempDir, {recursive: true});
                    const tempFile = path.join(tempDir, 'clipboard.txt');
                    await writeFile(tempFile, text, 'utf8');
                    await runLocal('powershell.exe', ['-NoProfile', '-Command', `Get-Content -Raw ${JSON.stringify(tempFile)} | Set-Clipboard`], PROJECT_ROOT, 20000);
                    pushCommand(`copied ${args === 'all' ? 'conversation' : 'last assistant response'} to clipboard`);
                }
                return true;
            }

            if (command === '/export') {
                const exportDir = path.join(PROJECT_ROOT, 'workspace', 'exports');
                await mkdir(exportDir, {recursive: true});
                const fileName = args || `${sessionId}-${Date.now()}.txt`;
                const target = safeRelativePath(path.join('workspace', 'exports', fileName));
                await writeFile(target, conversationText() || 'No conversation history.', 'utf8');
                pushCommand(`exported conversation: ${target}`);
                return true;
            }

            if (command === '/enable' || command === '/disable') {
                const action = command === '/enable' ? 'enable' : 'disable';
                const {type, name} = parseManageArgs(args);
                if (!type) {
                    pushCommand(`usage: ${command} <tool|skill|mcp|plugin|provider|hive|evolution|scheduler|reminders|health> [name]`);
                } else {
                    const result = await manageJson(action, type, name);
                    pushCommand(formatManageResult(result));
                }
                return true;
            }

            if (command === '/reset') {
                const target = parts[0]?.toLowerCase() || 'nexus';
                const result = await manageJson('reset', target);
                if (target === 'tasks') setTasks([]);
                if (target === 'nexus' || target === 'runtime' || target === 'all') {
                    setHistory([]);
                    setProvider('');
                    setModel('');
                    setSelectedActivityId(null);
                    setSelectedAgentId(null);
                    setPanelMode('workspace');
                }
                pushCommand(formatManageResult(result));
                return true;
            }

            if (command === '/features') {
                const data = await apiJson('/features');
                pushCommand(formatRows(Object.entries(data.features || {}).map(([key, value]) => `${key}: ${value ? 'enabled' : 'disabled'}`)));
                return true;
            }

            if (command === '/goal') {
                const sub = parts[0]?.toLowerCase();
                if (!args || sub === 'status') {
                    const data = await apiJson('/goal');
                    pushCommand(data.active ? `goal: ${data.goal}` : 'goal: none');
                } else {
                    const result = await postJson('/goal', {goal: args});
                    pushCommand(result.active ? `goal set: ${result.goal}` : 'goal cleared');
                }
                return true;
            }

            if (command === '/health') {
                const [apiHealth, status, features] = await Promise.all([
                    apiJson('/health'),
                    apiJson('/status'),
                    apiJson('/features')
                ]);
                pushCommand(formatRows([
                    `api: ${apiHealth.status}`,
                    `service: ${apiHealth.service}`,
                    `runtime: ${status.health}`,
                    `sessions: ${status.session_count}`,
                    `tasks: ${status.task_count}`,
                    `health feature: ${(features.features || {}).health ? 'enabled' : 'disabled'}`
                ]));
                return true;
            }

            if (command === '/evolution' || command === '/scheduler' || command === '/reminders' || command === '/schedule' || command === '/loop') {
                const featureName = command === '/schedule' || command === '/loop' ? 'scheduler' : command.slice(1);
                const data = await apiJson('/features');
                const enabled = Boolean((data.features || {})[featureName]);
                pushCommand(formatRows([
                    `${featureName}: ${enabled ? 'enabled' : 'disabled'}`,
                    `enable: /enable ${featureName}`,
                    `disable: /disable ${featureName}`,
                    `reload: /reload nexus`
                ]));
                return true;
            }

            if (command === '/pwd') {
                pushCommand(PROJECT_ROOT);
                return true;
            }

            if (command === '/voice') {
                const sub = parts[0]?.toLowerCase();
                const apiReady = await ensureApiAvailable();
                if (!apiReady) {
                    pushSystem('COMMAND_ERROR: voice API did not start in time');
                    return true;
                }
                const ensureCleanVoiceSession = async () => {
                    if (sessionId !== 'default' && history.length === 0) {
                        voiceSessionIdRef.current = sessionId;
                        return sessionId;
                    }
                    if (sessionId !== 'default' && history.length > 0) {
                        voiceSessionIdRef.current = sessionId;
                        return sessionId;
                    }
                    const created = await apiJson('/sessions/new', {method: 'POST'});
                    const nextSessionId = String(created.id || sessionId);
                    setSessionId(nextSessionId);
                    setHistory([]);
                    voiceSessionIdRef.current = nextSessionId;
                    pushCommand(`voice session: ${nextSessionId}`);
                    return nextSessionId;
                };
                if (!sub) {
                    const defaultMode = 'auto';
                    // Toggle: if running stop, if stopped start listening immediately
                    const statusRes = await fetch(`${API_BASE}/voice/status`, {headers: API_AUTH_HEADERS});
                    const statusData = await statusRes.json();
                    if (statusData.running) {
                        pushCommand('🎙️ stopping voice...');
                        await fetch(`${API_BASE}/voice/stop`, { method: 'POST', headers: API_AUTH_HEADERS });
                        setVoiceMode('off');
                        setVoicePhase('off');
                        setVoiceTranscriptPreview('');
                        setVoiceReplyPreview('');
                        voiceSessionIdRef.current = null;
                        pushCommand('🎙️ voice stopped');
                    } else {
                        const targetSessionId = await ensureCleanVoiceSession();
                        setHistory([]);
                        voiceJustStartedRef.current = Date.now() + 3000;
                        pushCommand(`🎙️ starting voice (${defaultMode})...`);
                        const startRes = await fetch(`${API_BASE}/voice/start`, {
                            method: 'POST',
                            headers: API_JSON_HEADERS,
                            body: JSON.stringify({ mode: defaultMode, session_id: targetSessionId, owner_pid: process.pid })
                        });
                        const startData = await startRes.json();
                        if (startData.status === 'success') {
                            setVoiceMode(defaultMode as any);
                            setVoicePhase(String(startData.phase || 'starting'));
                            pushCommand(`✓ voice active (${defaultMode}) — speak now, NEXUS is listening`);
                        } else {
                            pushCommand(`✗ voice failed: ${startData.detail || 'unknown error'}`);
                            if (defaultMode === 'auto') {
                                pushCommand('retry with /voice manual if your mic driver does not like auto mode');
                            }
                        }
                    }
                } else if (sub === 'status') {
                    const statusRes = await fetch(`${API_BASE}/voice/status`, {headers: API_AUTH_HEADERS});
                    const statusData = await statusRes.json();
                    if (statusData.running) {
                        pushCommand(`🎙️ voice active — mode: ${statusData.mode}  phase: ${statusData.phase || 'idle'}  pid: ${statusData.pid}`);
                    } else {
                        pushCommand('🎙️ voice off');
                    }
                } else if (sub === 'off' || sub === 'stop') {
                    pushCommand('🎙️ stopping voice...');
                    await fetch(`${API_BASE}/voice/stop`, { method: 'POST', headers: API_AUTH_HEADERS });
                    setVoiceMode('off');
                    setVoicePhase('off');
                    setVoiceTranscriptPreview('');
                    setVoiceReplyPreview('');
                    voiceSessionIdRef.current = null;
                    pushCommand('🎙️ voice stopped');
                } else if (sub === 'auto' || sub === 'manual' || sub === 'text') {
                    const targetSessionId = await ensureCleanVoiceSession();
                    setHistory([]);
                    voiceJustStartedRef.current = Date.now() + 3000;
                    pushCommand(`🎙️ starting voice (${sub})...`);
                    const startRes = await fetch(`${API_BASE}/voice/start`, {
                        method: 'POST',
                            headers: API_JSON_HEADERS,
                        body: JSON.stringify({ mode: sub, session_id: targetSessionId, owner_pid: process.pid })
                    });
                    const startData = await startRes.json();
                    if (startData.status === 'success') {
                        setVoiceMode(sub as any);
                        setVoicePhase(String(startData.phase || 'starting'));
                        pushCommand(`✓ voice active (${sub}) — speak now, NEXUS is listening`);
                    } else {
                        pushCommand(`✗ voice failed: ${startData.detail || 'unknown error'}`);
                    }
                } else {
                    pushCommand('usage: /voice [auto|manual|text|off|status]');
                }
                return true;
            }

            if (command === '/where') {
                pushCommand(formatRows([
                    `project: ${PROJECT_ROOT}`,
                    `cli: ${process.cwd()}`,
                    `session: ${sessionId}`,
                    `extra dirs: ${extraDirs.length ? extraDirs.join(', ') : 'none'}`,
                    `api: ${API_BASE}`,
                    `gui: http://127.0.0.1:5173`
                ]));
                return true;
            }

            if (command === '/add-dir') {
                if (!args) {
                    pushCommand('usage: /add-dir <directory>');
                } else {
                    const result = await postJson('/add-dir', {path: args});
                    setExtraDirs((result.additional_dirs || []).map((item: any) => String(item)));
                    pushCommand(`added working directory: ${result.path}`);
                }
                return true;
            }

            if (command === '/cd') {
                if (!args) {
                    pushCommand(`cwd: ${process.cwd()}`);
                } else {
                    const target = safeRelativePath(args);
                    const info = await stat(target);
                    if (!info.isDirectory()) {
                        pushCommand(`not a directory: ${target}`);
                    } else {
                        process.chdir(target);
                        pushCommand(`cwd: ${process.cwd()}`);
                    }
                }
                return true;
            }

            if (command === '/ls') {
                const target = safeRelativePath(args || '.');
                pushCommand(await listDirectory(target));
                return true;
            }

            if (command === '/tree') {
                const target = safeRelativePath(args || '.');
                const lines = await treeDirectory(target, 2);
                pushCommand(formatRows(lines));
                return true;
            }

            if (command === '/cat') {
                if (!args) {
                    pushCommand('usage: /cat <workspace-file>');
                } else {
                    const target = safeRelativePath(args);
                    const info = await stat(target);
                    if (info.isDirectory()) {
                        pushCommand('Cannot preview a directory.');
                    } else {
                        const content = await readFile(target, 'utf8');
                        pushCommand(cleanPreview(content, 80));
                    }
                }
                return true;
            }

            if (command === '/readme') {
                pushCommand(cleanPreview(await readFile(path.join(PROJECT_ROOT, 'README.md'), 'utf8'), 80));
                return true;
            }

            if (command === '/reload') {
                const target = typedCommand === '/reload-plugins'
                    ? 'plugins'
                    : typedCommand === '/reload-skills'
                        ? 'skills'
                        : parts[0]?.toLowerCase() || 'all';
                if (target === 'session' || target === 'history') {
                    const loaded = await apiJson(`/history?session_id=${encodeURIComponent(sessionId)}`);
                    const loadedHistory = Array.isArray(loaded)
                        ? loaded.map((msg: any) => ({
                            role: String(msg.role || 'assistant'),
                            content: String(msg.role || 'assistant') === 'assistant'
                                ? cleanVisibleAssistantText(String(msg.content || ''))
                                : String(msg.content || '')
                        }))
                        : [];
                    setHistory(loadedHistory);
                    pushCommand(`reloaded session: ${sessionId}`);
                } else if (target === 'tasks' || target === 'todo') {
                    const {tasks: latestTasks} = await loadPanelData();
                    pushCommand(`reloaded tasks: ${latestTasks.length}`);
                } else if (target === 'plugins' || target === 'plugin') {
                    await manageJson('reload', 'plugins');
                    const data = await apiJson('/plugins');
                    pushCommand(formatRows((data.plugins || []).map((plugin: any) => `${plugin.id} - ${plugin.enabled ? 'enabled' : 'disabled'}`)));
                } else if (target === 'skills' || target === 'skill') {
                    await manageJson('reload', 'skills');
                    const data = await apiJson('/skills');
                    pushCommand(formatRows((data.skills || []).map((skill: any) => `${skill.name} - ${skill.enabled ? 'enabled' : 'disabled'} - ${skill.description}`)));
                } else if (target === 'tools' || target === 'tool') {
                    await manageJson('reload', 'tools');
                    const data = await apiJson('/tools');
                    pushCommand(formatRows((data.tools || []).map((tool: any) =>
                        `${tool.name} - ${tool.enabled ? 'enabled' : 'disabled'} - ${tool.description}${tool.read_only ? ' [read]' : ''}${tool.safe ? ' [safe]' : ''}`
                    )));
                } else if (target === 'mcp' || target === 'mcps' || target === 'mpc') {
                    await manageJson('reload', 'mcp');
                    const data = await apiJson('/mcp');
                    pushCommand(formatRows((data.mcp || []).map((item: any) => `${item.id} - ${item.active ? 'active' : 'inactive'} - ${item.description}`)));
                } else if (target === 'providers' || target === 'provider') {
                    await manageJson('reload', 'providers');
                    const data = await apiJson('/providers');
                    pushCommand(formatRows((data.providers || []).map((item: any) => `${item.group}.${item.id} - ${item.active ? 'active' : 'inactive'} - ${item.model || 'no model'}`)));
                } else if (target === 'nexus' || target === 'runtime' || target === 'all') {
                    const result = await manageJson('reload', target);
                    pushCommand(formatManageResult(result));
                } else {
                    const {tasks: latestTasks} = await loadPanelData();
                    const [plugins, skills, tools] = await Promise.all([
                        apiJson('/plugins'),
                        apiJson('/skills'),
                        apiJson('/tools')
                    ]);
                    pushCommand(formatRows([
                        `tasks: ${latestTasks.length}`,
                        `plugins: ${(plugins.plugins || []).length}`,
                        `skills: ${(skills.skills || []).length}`,
                        `tools: ${(tools.tools || []).length}`,
                        `session: ${sessionId}`
                    ]));
                }
                return true;
            }

            if (command === '/docs') {
                const docsDir = path.join(PROJECT_ROOT, 'docs');
                pushCommand(await listDirectory(docsDir, 60));
                return true;
            }

            if (command === '/env') {
                pushCommand(formatRows([
                    `node: ${process.version}`,
                    `platform: ${process.platform}`,
                    `cwd: ${process.cwd()}`,
                    `OPENAI_API_KEY: ${process.env.OPENAI_API_KEY ? 'set' : 'not set'}`,
                    `ANTHROPIC_API_KEY: ${process.env.ANTHROPIC_API_KEY ? 'set' : 'not set'}`,
                    `OPENROUTER_API_KEY: ${process.env.OPENROUTER_API_KEY ? 'set' : 'not set'}`
                ]));
                return true;
            }

            if (command === '/version') {
                const [nodeVersion, npmVersion, pythonVersion, gitVersion] = await Promise.allSettled([
                    runLocal('node', ['--version']),
                    runLocal('npm', ['--version']),
                    runLocal('python', ['--version']),
                    runLocal('git', ['--version'])
                ]);
                const value = (result: PromiseSettledResult<string>) => result.status === 'fulfilled' ? result.value : result.reason.message;
                pushCommand(formatRows([
                    `nexus-tui: 2.0.0`,
                    `node: ${value(nodeVersion)}`,
                    `npm: ${value(npmVersion)}`,
                    `python: ${value(pythonVersion)}`,
                    `git: ${value(gitVersion)}`
                ]));
                return true;
            }

            if (command === '/ide') {
                const action = parts[0]?.toLowerCase() || 'open';
                const targetArg = action === 'open' || action === 'status' ? parts.slice(1).join(' ') : args;
                const target = targetArg ? safeRelativePath(targetArg) : PROJECT_ROOT;
                const hasCode = await commandExists('code');
                if (action === 'status') {
                    pushCommand(formatRows([
                        `vscode cli: ${hasCode ? 'available' : 'missing'}`,
                        `target: ${target}`,
                        `cwd: ${process.cwd()}`
                    ]));
                } else if (hasCode) {
                    startDetached('cmd.exe', ['/c', 'code', target], PROJECT_ROOT);
                    pushCommand(`opened in VS Code: ${target}`);
                } else {
                    pushCommand('VS Code command `code` was not found on PATH.');
                }
                return true;
            }

            if (command === '/init') {
                const claudePath = path.join(PROJECT_ROOT, 'CLAUDE.md');
                const nexusPath = path.join(PROJECT_ROOT, 'NEXUS.md');
                const created: string[] = [];
                if (!existsSync(claudePath)) {
                    await writeFile(claudePath, `# CLAUDE.md\n\nProject guidance for coding agents working in ${path.basename(PROJECT_ROOT)}.\n\n- Prefer real, verified behavior over mock status.\n- Keep changes scoped and test them.\n`, 'utf8');
                    created.push('CLAUDE.md');
                }
                if (!existsSync(nexusPath)) {
                    await writeFile(nexusPath, `# NEXUS.md\n\nNEXUS project memory.\n\n- Workspace: ${PROJECT_ROOT}\n- TUI: Ink + TypeScript\n- API: FastAPI\n`, 'utf8');
                    created.push('NEXUS.md');
                }
                pushCommand(created.length ? `initialized: ${created.join(', ')}` : 'memory files already exist');
                return true;
            }

            if (command === '/memory') {
                const subcommand = parts[0]?.toLowerCase();
                if (subcommand === 'stats' || subcommand === 'status') {
                    const result = await apiJson('/memory/statistics');
                    const stats = result.statistics || {};
                    pushCommand(formatRows([
                        'Memory inspector',
                        ...Object.entries(stats).map(([key, value]) => `${key}: ${typeof value === 'object' ? JSON.stringify(value) : String(value)}`),
                        'Use /memory search <query> to inspect matching memory.'
                    ]));
                    return true;
                }
                if (subcommand === 'search') {
                    const query = parts.slice(1).join(' ').trim();
                    if (!query) {
                        pushCommand('usage: /memory search <query>');
                        return true;
                    }
                    const result = await postJson('/memory/search', {query});
                    const rows = Array.isArray(result.results) ? result.results : [];
                    pushCommand(rows.length
                        ? formatRows(rows.slice(0, 12).map((item: any, index: number) =>
                            `${index + 1}. ${item.type || 'memory'} | ${cleanPreview(String(item.content || item.text || JSON.stringify(item)), 4)}`
                        ))
                        : `No memory matched: ${query}`);
                    return true;
                }
                if (subcommand === 'export') {
                    const format = parts[1]?.toLowerCase() === 'text' ? 'text' : 'json';
                    const result = await postJson('/memory/export', {format});
                    const exportDir = path.join(PROJECT_ROOT, 'workspace', 'exports');
                    await mkdir(exportDir, {recursive: true});
                    const target = path.join(exportDir, `memory-${sessionId}.${format === 'text' ? 'txt' : 'json'}`);
                    await writeFile(target, String(result.data || ''), 'utf8');
                    pushCommand(`memory exported: ${target}`);
                    return true;
                }
                const targetName = parts[0]?.toLowerCase() === 'claude' ? 'CLAUDE.md' : parts[0]?.toLowerCase() === 'nexus' ? 'NEXUS.md' : 'NEXUS.md';
                const target = path.join(PROJECT_ROOT, targetName);
                const action = parts[0]?.toLowerCase() === 'open' || parts[1]?.toLowerCase() === 'open' ? 'open' : 'show';
                if (!existsSync(target)) {
                    pushCommand(`${targetName} not found. Run /init first.`);
                } else if (action === 'open' && await commandExists('code')) {
                    startDetached('cmd.exe', ['/c', 'code', target], PROJECT_ROOT);
                    pushCommand(`opened memory: ${target}`);
                } else {
                    pushCommand(cleanPreview(await readFile(target, 'utf8'), 80));
                }
                return true;
            }

            if (command === '/keybindings' || command === '/terminal-setup') {
                pushCommand(formatRows([
                    'NEXUS TUI keybindings',
                    'Tab: accept highlighted slash command',
                    'Up/Down: move slash command selection',
                    'Enter: send message or command',
                    'Ctrl+C: exit terminal process'
                ]));
                return true;
            }

            if (command === '/open-gui') {
                startDetached('powershell.exe', ['-NoProfile', '-Command', 'Start-Process', 'http://127.0.0.1:5173'], PROJECT_ROOT);
                pushCommand('opened GUI: http://127.0.0.1:5173');
                return true;
            }

            if (command === '/api') {
                const action = parts[0]?.toLowerCase() || 'status';
                if (action === 'start') {
                    startDetached(PYTHON_EXECUTABLE, ['-m', 'server'], PROJECT_ROOT, {
                        NEXUS_DASHBOARD_TOKEN: DASHBOARD_TOKEN,
                        NEXUS_EMBED_QUEUE_DRIVER: process.env.NEXUS_EMBED_QUEUE_DRIVER || 'true'
                    });
                    pushCommand('started TUI API on http://127.0.0.1:8000');
                } else {
                    const health = await apiJson('/health');
                    pushCommand(`${health.service}: ${health.status}`);
                }
                return true;
            }

            if (command === '/gui') {
                const action = parts[0]?.toLowerCase() || 'status';
                if (action === 'start') {
                    startDetached('powershell.exe', ['-ExecutionPolicy', 'Bypass', '-File', path.join(PROJECT_ROOT, 'scripts', 'run-gui.ps1')], PROJECT_ROOT);
                    pushCommand('starting GUI via scripts/run-gui.ps1');
                } else if (action === 'open') {
                    startDetached('powershell.exe', ['-NoProfile', '-Command', 'Start-Process', 'http://127.0.0.1:5173'], PROJECT_ROOT);
                    pushCommand('opened GUI: http://127.0.0.1:5173');
                } else if (action === 'build') {
                    pushCommand(await runLocal('npm', ['--prefix', 'gui', 'run', 'build'], PROJECT_ROOT, 120000));
                } else if (action === 'logs') {
                    const logsDir = path.join(PROJECT_ROOT, 'logs');
                    const entries = (await readdir(logsDir)).filter(name => name.includes('gui-')).slice(-12);
                    pushCommand(formatRows(entries));
                } else {
                    const [apiState, webState] = await Promise.allSettled([
                        fetch('http://127.0.0.1:8000/api/health').then(res => res.status),
                        fetch('http://127.0.0.1:5173').then(res => res.status)
                    ]);
                    pushCommand(formatRows([
                        `api: ${apiState.status === 'fulfilled' ? apiState.value : 'offline'}`,
                        `web: ${webState.status === 'fulfilled' ? webState.value : 'offline'}`,
                        'usage: /gui start | /gui open | /gui build | /gui logs'
                    ]));
                }
                return true;
            }

            if (command === '/git') {
                const action = parts[0]?.toLowerCase() || 'status';
                const gitArgs = action === 'diff'
                    ? ['diff', '--stat']
                    : action === 'log'
                        ? ['log', '--oneline', '-12']
                        : action === 'branch'
                            ? ['branch', '--show-current']
                            : ['status', '--short'];
                pushCommand(await runLocal('git', gitArgs));
                return true;
            }

            if (command === '/diff') {
                pushCommand(await runLocal('git', ['diff', '--stat']));
                return true;
            }

            if (command === '/branch') {
                pushCommand(await runLocal('git', ['branch', '--show-current']));
                return true;
            }

            if (command === '/log') {
                pushCommand(await runLocal('git', ['log', '--oneline', '-12']));
                return true;
            }

            if (command === '/config' || command === '/settings') {
                const configPath = path.join(PROJECT_ROOT, 'config', 'settings.yml');
                if (parts[0]?.toLowerCase() === 'set') {
                    const configPathArg = parts[1];
                    const value = parts.slice(2).join(' ');
                    if (!configPathArg || !value) {
                        pushCommand('usage: /config set <dotted.path> <value>');
                    } else {
                        const result = await manageJson('set', 'config', configPathArg, value);
                        pushCommand(formatManageResult(result));
                    }
                } else if (!args) {
                    pushCommand(formatRows(await readYamlSectionNames(configPath)));
                } else {
                    const content = await readFile(configPath, 'utf8');
                    const lines = content.split(/\r?\n/);
                    const start = lines.findIndex(line => line.trim() === `${args}:`);
                    if (start === -1) {
                        pushCommand(`config section not found: ${args}`);
                    } else {
                        const sectionLines = lines.slice(start, start + 80);
                        pushCommand(sectionLines.join('\n'));
                    }
                }
                return true;
            }

            if (command === '/providers') {
                const data = await apiJson('/providers');
                pushCommand(formatRows([
                    ...((data.providers || []).map((item: any) => `${item.group}.${item.id} - ${item.active ? 'active' : 'inactive'} - ${item.model || 'no model'}`)),
                    ...providerDiagnosticsRows(data.diagnostics)
                ]));
                return true;
            }

            if (command === '/mcp') {
                const sub = parts[0]?.toLowerCase();
                if ((sub === 'enable' || sub === 'disable') && parts[1]) {
                    if (parts[1].toLowerCase() === 'all') {
                        const data = await apiJson('/mcp');
                        const results = await Promise.all((data.mcp || []).map((item: any) => manageJson(sub, 'mcp', item.id)));
                        pushCommand(formatRows(results.map(formatManageResult)));
                    } else {
                        const result = await manageJson(sub, 'mcp', parts[1]);
                        pushCommand(formatManageResult(result));
                    }
                } else if (sub === 'reload' || sub === 'reconnect') {
                    const result = await manageJson('reload', 'mcp');
                    pushCommand(formatManageResult(result));
                } else {
                    const data = await apiJson('/mcp');
                    pushCommand(formatRows((data.mcp || []).map((item: any) =>
                        `${item.id} - ${item.active ? 'active' : 'inactive'} - ${item.command || 'no command'} - ${item.description || ''}`
                    )));
                    setPanelMode('mcp');
                }
                return true;
            }

            if (command === '/logs') {
                const logsDir = path.join(PROJECT_ROOT, 'logs');
                const entries = (await readdir(logsDir)).slice(-30);
                pushCommand(formatRows(entries));
                return true;
            }

            if (command === '/work') {
                const workDir = path.join(PROJECT_ROOT, 'workspace', 'work_events');
                const file = path.join(workDir, `${sessionId}.jsonl`);
                if (!existsSync(file)) {
                    pushCommand(`No work events for ${sessionId}`);
                } else {
                    const lines = (await readFile(file, 'utf8')).trim().split(/\r?\n/).slice(-12);
                    pushCommand(formatRows(lines.map(line => {
                        try {
                            const event = JSON.parse(line);
                            return `${event.kind || 'event'} ${event.status || ''} ${event.title || event.action || event.path || ''}`.trim();
                        } catch {
                            return line;
                        }
                    })));
                }
                return true;
            }

            if (command === '/check') {
                const target = parts[0]?.toLowerCase() || 'cli';
                if (target === 'cli') {
                    pushCommand(await runLocal('npx', ['tsc', '--noEmit'], path.join(PROJECT_ROOT, 'tui'), 120000));
                } else if (target === 'py' || target === 'python') {
                    pushCommand(await runLocal('python', ['-m', 'py_compile', 'orchestrators\\v5\\core.py'], PROJECT_ROOT, 120000));
                } else if (target === 'gui') {
                    pushCommand(await runLocal('npm', ['--prefix', 'gui', 'run', 'build'], PROJECT_ROOT, 120000));
                } else {
                    pushCommand('usage: /check cli | /check py | /check gui');
                }
                return true;
            }

            if (command === '/build') {
                const target = parts[0]?.toLowerCase() || 'gui';
                if (target === 'cli') {
                    pushCommand(await runLocal('npx', ['tsc', '--noEmit'], path.join(PROJECT_ROOT, 'tui'), 120000));
                } else {
                    pushCommand(await runLocal('npm', ['--prefix', 'gui', 'run', 'build'], PROJECT_ROOT, 120000));
                }
                return true;
            }

            if (command === '/doctor') {
                const checks = await Promise.allSettled([
                    apiJson('/health').then((health: any) => `api: ${health.status}`),
                    runLocal('git', ['status', '--short']).then(output => `git changes:\n${output || 'clean'}`),
                    runLocalResult('npx', ['tsc', '--noEmit'], path.join(PROJECT_ROOT, 'tui'), 120000).then(result =>
                        result.ok ? 'cli ts: ok' : `cli ts: failed\n${result.output}`
                    ),
                    runLocalResult('python', ['-m', 'py_compile', 'orchestrators\\v5\\core.py'], PROJECT_ROOT, 120000).then(result =>
                        result.ok ? 'python compile: ok' : `python compile: failed\n${result.output}`
                    )
                ]);
                pushCommand(formatRows(checks.map(result => result.status === 'fulfilled' ? result.value : `check failed: ${result.reason.message}`)));
                return true;
            }

            if (command === '/debug') {
                const [status, health] = await Promise.all([apiJson('/status'), apiJson('/health')]);
                pushCommand(formatRows([
                    `api: ${health.status}`,
                    `session: ${sessionId}`,
                    `cwd: ${process.cwd()}`,
                    `provider: ${status.provider}`,
                    `model: ${status.model}`,
                    `mode: ${status.mode}`,
                    `goal: ${status.goal || 'none'}`,
                    `extra dirs: ${(status.additional_dirs || []).join(', ') || 'none'}`,
                    `logs: ${path.join(PROJECT_ROOT, 'logs')}`
                ]));
                return true;
            }

            if (command === '/hooks') {
                const settingsPath = path.join(PROJECT_ROOT, '.claude', 'settings.json');
                if (!existsSync(settingsPath)) {
                    pushCommand('No .claude/settings.json found.');
                } else {
                    try {
                        const settings = JSON.parse(await readFile(settingsPath, 'utf8'));
                        pushCommand(formatRows(Object.keys(settings.hooks || {}).map(key => `${key}: ${JSON.stringify(settings.hooks[key]).slice(0, 160)}`)));
                    } catch (error) {
                        pushCommand(`Cannot read hooks because .claude/settings.json is malformed: ${error instanceof Error ? error.message : String(error)}`);
                    }
                }
                return true;
            }

            if (command === '/login') {
                pushCommand(formatRows([
                    `OPENAI_API_KEY: ${process.env.OPENAI_API_KEY ? 'set' : 'not set'}`,
                    `ANTHROPIC_API_KEY: ${process.env.ANTHROPIC_API_KEY ? 'set' : 'not set'}`,
                    `OPENROUTER_API_KEY: ${process.env.OPENROUTER_API_KEY ? 'set' : 'not set'}`,
                    'Use /provider list and /model list to choose configured providers.'
                ]));
                return true;
            }

            if (command === '/logout') {
                setProvider('');
                setModel('');
                await postJson('/provider', {provider: ''});
                pushCommand('cleared local provider/model overrides');
                return true;
            }

            if (command === '/fast') {
                const value = args || 'status';
                if (value === 'status') {
                    pushCommand('fast mode is config-backed. Use /fast on or /fast off.');
                } else {
                    const result = await manageJson('set', 'config', 'runtime.fast', value.toLowerCase() === 'on');
                    pushCommand(formatManageResult(result));
                }
                return true;
            }

            if (command === '/heapdump') {
                const exportDir = path.join(PROJECT_ROOT, 'workspace', 'exports');
                await mkdir(exportDir, {recursive: true});
                const target = path.join(exportDir, `node-memory-${Date.now()}.json`);
                await writeFile(target, JSON.stringify(process.memoryUsage(), null, 2), 'utf8');
                pushCommand(`wrote memory snapshot: ${target}`);
                return true;
            }

            if (command === '/theme' || command === '/color' || command === '/statusline' || command === '/tui' || command === '/output-style') {
                pushCommand(formatRows([
                    `${command}: current NEXUS TUI renderer`,
                    `theme: static dark sovereign`,
                    `background: ${THEME.appBg}`,
                    `panel: ${THEME.panelBg}`,
                    `input: ${THEME.inputBg}`,
                    'Changing these live needs a renderer theme refactor; no fake theme switch was applied.'
                ]));
                return true;
            }

            if (command === '/status') {
                const status = await apiJson('/status');
                pushCommand(formatRows([
                    `health: ${status.health}`,
                    `model: ${status.model}`,
                    `provider: ${status.provider}`,
                    `mode: ${status.mode}`,
                    `agent: ${status.agent || 'none'}`,
                    `goal: ${status.goal || 'none'}`,
                    `sessions: ${status.session_count}`,
                    `agents: ${status.agent_count}`,
                    `tasks: ${status.task_count}`,
                    `version: ${status.version}`,
                    ...providerDiagnosticsRows(status.provider_diagnostics)
                ]));
                return true;
            }

            if (command === '/model') {
                const sub = parts[0]?.toLowerCase();
                if (!args || sub === 'status') {
                    const status = await apiJson('/status');
                    pushCommand(`model: ${status.model}`);
                } else if (sub === 'list') {
                    const data = await apiJson('/providers');
                    pushCommand(formatRows((data.providers || []).map((item: any) => `${item.id}: ${item.model || 'no model'} ${item.active ? '[active]' : ''}`)));
                } else if (sub === 'set' && parts.length >= 3) {
                    const result = await manageJson('model', 'provider', parts[1], parts.slice(2).join(' '));
                    pushCommand(formatManageResult(result));
                } else {
                    const separator = args.indexOf(':');
                    const provider = separator > 0 ? args.slice(0, separator).trim() : '';
                    const model = separator > 0 ? args.slice(separator + 1).trim() : args;
                    const result = await postJson('/model', {model, ...(provider ? {provider} : {}), session_id: sessionId});
                    setModel(result.model);
                    pushCommand(`model set: ${result.model}`);
                }
                return true;
            }

            if (command === '/provider') {
                const sub = parts[0]?.toLowerCase();
                if (!args || sub === 'status') {
                    const status = await apiJson('/status');
                    pushCommand(formatRows([`provider: ${status.provider}`, ...providerDiagnosticsRows(status.provider_diagnostics)]));
                } else if (sub === 'list') {
                    const data = await apiJson('/providers');
                    pushCommand(formatRows((data.providers || []).map((item: any) => `${item.group}.${item.id} - ${item.active ? 'active' : 'inactive'} - ${item.model || 'no model'}`)));
                } else if ((sub === 'enable' || sub === 'disable') && parts[1]) {
                    const result = await manageJson(sub, 'provider', parts[1]);
                    pushCommand(formatManageResult(result));
                } else if (sub === 'model' && parts.length >= 3) {
                    const result = await manageJson('model', 'provider', parts[1], parts.slice(2).join(' '));
                    pushCommand(formatManageResult(result));
                } else if ((sub === 'add' || sub === 'set') && parts[1]) {
                    const providerName = parts[1];
                    const modelValue = parts.slice(2).join(' ');
                    const value = modelValue ? {active: true, model: modelValue} : {active: true};
                    const result = await manageJson('set', 'provider', providerName, value);
                    pushCommand(formatManageResult(result));
                } else {
                    const result = await postJson('/provider', {provider: args, session_id: sessionId});
                    setProvider(result.provider);
                    pushCommand(result.provider ? `provider set: ${result.provider}` : 'provider override cleared');
                }
                return true;
            }

            if (command === '/mode' || command === '/permissions') {
                const sub = parts[0]?.toLowerCase();
                if (!args) {
                    const status = await apiJson('/status');
                    pushCommand(`permission: ${normalizePermissionMode(String(status.mode || 'auto'))}`);
                } else if (command === '/permissions' && ['list', 'allowlist', 'allowed'].includes(sub || '')) {
                    const result = await apiJson('/permissions');
                    const entries = Array.isArray(result.allowlist) ? result.allowlist : [];
                    pushCommand(formatRows([
                        `permission: ${normalizePermissionMode(String(result.mode || 'auto'))}`,
                        'allow list:',
                        ...(entries.length ? entries.map((entry: string) => `- ${entry}`) : ['- empty'])
                    ]));
                } else if (command === '/permissions' && sub === 'add') {
                    const entry = parts.slice(1).join(' ').trim();
                    if (!entry) {
                        pushCommand('usage: /permissions add <tool-or-command>');
                    } else {
                        const result = await postJson('/permissions', {mode: 'allowlist', add: entry});
                        setPermissionMode(normalizePermissionMode(String(result.mode || 'allowlist')));
                        pushCommand(`allow-list added: ${entry}`);
                    }
                } else if (command === '/permissions' && ['remove', 'rm', 'delete'].includes(sub || '')) {
                    const entry = parts.slice(1).join(' ').trim();
                    if (!entry) {
                        pushCommand('usage: /permissions remove <tool-or-command>');
                    } else {
                        const result = await postJson('/permissions', {mode: permissionMode, remove: entry});
                        setPermissionMode(normalizePermissionMode(String(result.mode || permissionMode)));
                        pushCommand(`allow-list removed: ${entry}`);
                    }
                } else {
                    const result = await postJson('/mode', {mode: args});
                    const nextMode = normalizePermissionMode(String(result.mode || args));
                    setPermissionMode(nextMode);
                    pushCommand(`permission set: ${nextMode}`);
                }
                return true;
            }

            if (command === '/plan') {
                const result = await postJson('/mode', {mode: 'ask'});
                const nextMode = normalizePermissionMode(String(result.mode || 'ask'));
                setPermissionMode(nextMode);
                pushCommand(args ? `permission set: ${nextMode}\nplan prompt: ${args}` : `permission set: ${nextMode}`);
                return true;
            }

            if (command === '/sandbox') {
                if (!args) {
                    const status = await apiJson('/sandbox');
                    pushCommand(`sandbox: ${sandboxLabel(normalizeSandboxTier(String(status.tier || 'normal')))}`);
                } else {
                    const normalized = String(args).trim().toLowerCase().replace(/\s+/g, '_');
                    const aliases: Record<string, SandboxTier> = {
                        no_sandbox: 'no_sandbox', none: 'no_sandbox', off: 'no_sandbox', no: 'no_sandbox',
                        'no-sandbox': 'no_sandbox', nosandbox: 'no_sandbox',
                        normal: 'normal', simple: 'normal', on: 'normal', safe: 'normal',
                        docker: 'docker', advanced: 'docker'
                    };
                    const requested = aliases[normalized];
                    if (!requested) {
                        pushCommand('invalid sandbox tier: use no_sandbox, normal, or docker');
                        return true;
                    }
                    const result = await postJson('/sandbox', {tier: requested});
                    const nextTier = normalizeSandboxTier(String(result.tier || requested));
                    setSandboxTier(nextTier);
                    pushCommand(`sandbox set: ${sandboxLabel(nextTier)}`);
                }
                return true;
            }

            if (command === '/effort') {
                if (!args || args.toLowerCase() === 'status') {
                    const result = await apiJson('/effort');
                    pushCommand(`effort: ${result.effort}`);
                } else {
                    const result = await postJson('/effort', {effort: args});
                    pushCommand(`effort set: ${result.effort}`);
                }
                return true;
            }

            if (command === '/agents') {
                if (args) {
                    const result = await postJson('/agent', {agent: args});
                    pushCommand(`agent set: ${result.agent}`);
                } else {
                    const data = await apiJson('/agents');
                    pushCommand(formatRows((data.agents || []).map((agent: any) => `${agent.id} - ${agent.status} - ${agent.description}`)));
                }
                return true;
            }

            if (command === '/new') {
                const created = await apiJson('/sessions/new', {method: 'POST'});
                setSessionId(created.id);
                setHistory(INITIAL_HISTORY);
                resetSessionView();
                setSelectedActivityId(null);
                setSelectedAgentId(null);
                setPanelMode('workspace');
                pushCommand(`new conversation: ${created.id}`);
                return true;
            }

            if (command === '/conversations' || command === '/sessions') {
                const sessions = await apiJson('/sessions');
                pushCommand(formatRows((Array.isArray(sessions) ? sessions : []).slice(0, 15).map((item: any, index: number) =>
                    `${index + 1}. ${item.id} - ${item.title}`
                )));
                return true;
            }

            if (command === '/resume' || command === '/load') {
                if (!args) {
                    pushCommand('usage: /resume <conversation-id>');
                } else {
                    const loaded = await postJson('/sessions/load', {id: args});
                    setSessionId(loaded.id);
                    const loadedHistory = Array.isArray(loaded.history)
                        ? loaded.history.map((msg: any) => ({
                            role: String(msg.role || 'assistant'),
                            content: String(msg.role || 'assistant') === 'assistant'
                                ? cleanVisibleAssistantText(String(msg.content || ''))
                                : String(msg.content || '')
                        }))
                        : [];
                    setHistory(loadedHistory);
                    resetSessionView();
                    pushCommand(`resumed: ${loaded.id}`);
                }
                return true;
            }

            if (command === '/rename') {
                if (!args) {
                    pushCommand('usage: /rename <new title>');
                } else {
                    const result = await postJson('/sessions/rename', {id: sessionId, title: args});
                    pushCommand(result.status === 'success' ? `renamed: ${args}` : 'rename failed');
                }
                return true;
            }

            if (command === '/delete-session') {
                const target = args || sessionId;
                const result = await apiJson(`/sessions/${encodeURIComponent(target)}`, {method: 'DELETE'});
                pushCommand(`${result.deleted || result.cleared ? 'deleted' : 'not deleted'}: ${target}`);
                return true;
            }

            if (command === '/history') {
                const loaded = await apiJson(`/history?session_id=${encodeURIComponent(sessionId)}`);
                const loadedHistory = Array.isArray(loaded)
                    ? loaded.map((msg: any) => ({
                        role: String(msg.role || 'assistant'),
                        content: String(msg.role || 'assistant') === 'assistant'
                            ? cleanVisibleAssistantText(String(msg.content || ''))
                            : String(msg.content || '')
                    }))
                    : [];
                setHistory(loadedHistory);
                pushCommand(`history loaded: ${sessionId}`);
                return true;
            }

            if (command === '/recap' || command === '/insights' || command === '/team-onboarding') {
                const sessions = await apiJson('/sessions');
                const userCount = history.filter(msg => msg.role === 'user').length;
                const assistantCount = history.filter(msg => msg.role === 'assistant').length;
                const changedFiles = touchedFiles.map(file => `${file.status}:${file.name}`).slice(0, 8);
                pushCommand(formatRows([
                    `session: ${sessionId}`,
                    `messages: ${userCount} user, ${assistantCount} assistant`,
                    `tasks: ${tasks.length}`,
                    `activities: ${activityItems.length}`,
                    `recent sessions: ${(Array.isArray(sessions) ? sessions : []).slice(0, 5).map((item: any) => item.id).join(', ') || 'none'}`,
                    `files: ${changedFiles.length ? changedFiles.join(', ') : 'none'}`
                ]));
                return true;
            }

            if (command === '/skills') {
                const data = await apiJson('/skills');
                const query = args.replace(/^reload\s*/i, '').trim().toLowerCase();
                const rows = (data.skills || [])
                    .filter((skill: any) => !query || String(skill.name).toLowerCase().includes(query))
                    .map((skill: any) => `${skill.name} - ${skill.enabled ? 'enabled' : 'disabled'} - ${skill.description}`);
                pushCommand(formatRows(rows));
                return true;
            }

            if (command === '/tools') {
                const data = await apiJson('/tools');
                const query = args.replace(/^reload\s*/i, '').trim().toLowerCase();
                pushCommand(formatRows((data.tools || [])
                    .filter((tool: any) => !query || String(tool.name).toLowerCase().includes(query))
                    .map((tool: any) =>
                    `${tool.name} - ${tool.enabled ? 'enabled' : 'disabled'} - ${tool.description}${tool.read_only ? ' [read]' : ''}${tool.safe ? ' [safe]' : ''}`
                )));
                return true;
            }

            if (command === '/plugins') {
                const sub = parts[0]?.toLowerCase();
                if ((sub === 'enable' || sub === 'disable' || sub === 'remove') && parts[1]) {
                    const result = await manageJson(sub, 'plugin', parts[1]);
                    pushCommand(formatManageResult(result));
                } else if (sub === 'reload') {
                    const result = await manageJson('reload', 'plugins');
                    pushCommand(formatManageResult(result));
                } else {
                    const data = await apiJson('/plugins');
                    const query = args.replace(/^(reload|list)\s*/i, '').trim().toLowerCase();
                    pushCommand(formatRows((data.plugins || [])
                        .filter((plugin: any) => !query || String(plugin.id).toLowerCase().includes(query) || String(plugin.name || '').toLowerCase().includes(query))
                        .map((plugin: any) => `${plugin.id} - ${plugin.enabled ? 'enabled' : 'disabled'}`)));
                }
                return true;
            }

            if (command === '/queue') {
                const apiReady = await ensureApiAvailable();
                if (!apiReady) {
                    pushSystem('QUEUE_ERROR: API is offline');
                } else {
                    const snapshot = await apiJson(`/queue?session_id=${encodeURIComponent(sessionId)}&include_global=false&limit=50`);
                    pushCommand(queueSnapshotLines(snapshot).join('\n'));
                }
                return true;
            }

            if (command === '/tasks') {
                const {tasks: latestTasks} = await loadPanelData();
                pushCommand(formatRows(latestTasks.map(task => `${task.id} - ${task.status} - ${task.subject}`)));
                return true;
            }

            if (command === '/todo') {
                const action = parts[0]?.toLowerCase();
                if (action === 'add') {
                    const subject = args.slice(parts[0].length).trim();
                    if (!subject) {
                        pushCommand('usage: /todo add <text>');
                    } else {
                        const result = await postJson('/tasks', {subject});
                        await loadPanelData();
                        addActivityItem({
                            kind: 'todo',
                            title: 'Updated todo list',
                            summary: subject,
                            status: 'done',
                            detail: `created: ${result.task.id}\n${subject}`,
                            toolName: 'todo'
                        });
                        pushCommand(`todo created: ${result.task.id}`);
                    }
                } else if (action === 'done') {
                    const taskId = parts[1];
                    if (!taskId) {
                        pushCommand('usage: /todo done <task-id>');
                    } else {
                        await apiJson(`/tasks/${encodeURIComponent(taskId)}`, {
                            method: 'PATCH',
                            body: JSON.stringify({status: 'completed'})
                        });
                        await loadPanelData();
                        addActivityItem({
                            kind: 'todo',
                            title: 'Updated todo list',
                            summary: taskId,
                            status: 'done',
                            detail: `completed: ${taskId}`,
                            toolName: 'todo'
                        });
                        pushCommand(`todo completed: ${taskId}`);
                    }
                } else {
                    pushCommand('usage: /todo add <text> | /todo done <task-id>');
                }
                return true;
            }

            if (command === '/review' || command === '/code-review' || command === '/security-review' || command === '/simplify' || command === '/ultrareview') {
                const [statResult, diffResult] = await Promise.all([
                    runLocal('git', ['diff', '--stat'], PROJECT_ROOT, 120000),
                    runLocal('git', ['diff', '--', args || '.'], PROJECT_ROOT, 120000)
                ]);
                const header = command === '/security-review'
                    ? 'security review input'
                    : command === '/simplify'
                        ? 'simplification review input'
                        : 'code review input';
                pushCommand(formatRows([
                    header,
                    statResult || 'No uncommitted diff found.',
                    diffResult ? cleanPreview(diffResult, 60) : 'Nothing to review.'
                ]));
                return true;
            }

            if (command === '/batch' || command === '/fork') {
                if (!args) {
                    pushCommand(`usage: ${command} <instruction>`);
                } else {
                    const result = await postJson('/multi_agent', {command, prompt: args});
                    pushCommand(`${result.status}: ${result.result}`);
                }
                return true;
            }

            if (command === '/files') {
                const data = await apiJson(`/files?q=${encodeURIComponent(args)}`);
                pushCommand(formatRows((data.files || []).map((file: string) => file)));
                return true;
            }

            if (command === '/run') {
                if (!args) {
                    pushCommand('usage: /run <command>');
                } else {
                    const started = addActivityItem({
                        kind: 'run',
                        title: 'Ran command',
                        summary: args,
                        status: 'running',
                        command: args,
                        toolName: 'run'
                    });
                    const result = await postJson('/run', {command: args});
                    const output = cleanPreview(result.output || '', 30);
                    const error = cleanPreview(result.error || '', 16);
                    setActivityItems(prev => prev.map(activity => activity.id === started.id ? {
                        ...activity,
                        status: result.returncode === 0 ? 'done' : 'error',
                        output,
                        error
                    } : activity));
                    setSelectedActivityId(started.id);
                    setPanelMode('activity');
                }
                return true;
            }

            if (command === '/multi-agent' || command === '/multi_agent') {
                const result = await postJson('/multi_agent', {command: parts[0] || '/run', prompt: args});
                pushCommand(`${result.status}: ${result.result}`);
                return true;
            }

            if (command === '/stop') {
                if (!chatAbortControllerRef.current && !activeRunIdRef.current) {
                    pushCommand('no active turn to stop');
                    return true;
                }
                cancelActiveTurn();
                return true;
            }

            if (command === '/retry') {
                // Retry must reuse the ORIGINAL user prompt, never a rebuilt or
                // truncated one, and must not resend slash commands.
                const retryPrompt = resolveRetryPrompt(history);
                if (!retryPrompt) {
                    pushCommand('no previous prompt to retry');
                    return true;
                }
                if (chatAbortControllerRef.current) {
                    cancelActiveTurn();
                }
                void handleSubmit(retryPrompt);
                return true;
            }

            if (command === '/btw') {
                pushCommand(args ? `side note recorded locally: ${args}` : 'usage: /btw <side question>');
                return true;
            }

            if (command === '/advisor' || command === '/focus' || command === '/fewer-permission-prompts') {
                pushCommand(formatRows([
                    `${command}: local status`,
                    `mode: ${(await apiJson('/status')).mode}`,
                    'Use /permissions auto|all|allowlist|ask and /sandbox none|simple|advanced. Permissions and sandbox are separate controls.'
                ]));
                return true;
            }

            if (command === '/background' || command === '/desktop' || command === '/mobile' || command === '/teleport' || command === '/remote-control' || command === '/remote-env') {
                unsupportedCommand(command, 'This command depends on Claude cloud/mobile/remote-control services. NEXUS can keep local sessions with /resume, /conversations, and /new.');
                return true;
            }

            if (command === '/chrome' || command === '/install-github-app' || command === '/install-slack-app') {
                unsupportedCommand(command, 'This needs an external browser/account integration. NEXUS local TUI can still inspect /env, /plugins, /mcp, and /health.');
                return true;
            }

            if (command === '/passes' || command === '/powerup' || command === '/privacy-settings' || command === '/radio' || command === '/stickers' || command === '/upgrade' || command === '/usage-credits') {
                unsupportedCommand(command, 'This is an Anthropic account/product command, not a local NEXUS runtime action.');
                return true;
            }

            if (command === '/claude-api' || command === '/run-skill-generator') {
                unsupportedCommand(command, 'This bundled Claude skill is not installed in this NEXUS workspace. Use /skills and /plugins to inspect what is actually available.');
                return true;
            }

            if (command === '/deep-research' || command === '/ultraplan') {
                pushCommand(args
                    ? `Use normal chat for this prompt so NEXUS can answer with the active provider: ${args}`
                    : `usage: ${command} <prompt>`);
                return true;
            }

            if (command === '/rewind') {
                const checkpoints = await apiJson(`/checkpoints?session_id=${encodeURIComponent(sessionId)}`);
                const items = Array.isArray(checkpoints.checkpoints) ? checkpoints.checkpoints : [];
                const checkpointId = args.trim();
                if (!checkpointId) {
                    pushCommand(items.length
                        ? formatRows([
                            'Workspace checkpoints (newest first)',
                            ...items.slice(0, 12).map((item: any, index: number) =>
                                `${index + 1}. ${item.checkpoint_id} | ${item.file_count || 0} files | run ${item.run_id || 'unknown'}`
                            ),
                            'Use /rewind <checkpoint-id> to restore a checkpoint.'
                        ])
                        : 'No workspace checkpoints exist for this session yet.');
                    return true;
                }
                const selected = items.find((item: any) => String(item.checkpoint_id) === checkpointId);
                if (!selected) {
                    pushCommand(`Checkpoint not found in this session: ${checkpointId}`);
                    return true;
                }
                const restored = await postJson(`/checkpoints/${encodeURIComponent(checkpointId)}/restore`, {session_id: sessionId});
                addActivityItem({
                    kind: 'file',
                    title: 'Restored workspace checkpoint',
                    summary: checkpointId,
                    status: 'done',
                    detail: String(restored.message || `Restored ${restored.restored || 0} files.`),
                    toolName: 'rewind'
                });
                pushCommand(`restored checkpoint ${checkpointId}: ${restored.message || `${restored.restored || 0} files restored`}`);
                void loadPanelData();
                return true;
            }

            if (command === '/scroll-speed') {
                unsupportedCommand(command, 'Scroll speed belongs to the terminal emulator, not the Ink app runtime.');
                return true;
            }

            if (command === '/setup-bedrock' || command === '/setup-vertex') {
                unsupportedCommand(command, 'Provider setup is config-backed here. Use /provider add <name> <model>, /provider enable <name>, and /config set for real NEXUS configuration.');
                return true;
            }

            if (command === '/paste') {
                try {
                    const pastedPath = await saveClipboardImage();
                    const info = await stat(pastedPath);
                    addActivityItem({
                        kind: 'file',
                        title: 'Attached clipboard image',
                        summary: path.basename(pastedPath),
                        status: 'done',
                        files: [pastedPath],
                        detail: `${pastedPath}\n${formatTokens(info.size)}B`,
                        toolName: 'paste'
                    });
                    setInput(current => `${current}${current.trim() ? ' ' : ''}"${pastedPath}"`);
                    pushCommand(`attached clipboard image: ${pastedPath}`);
                } catch {
                    pushSystem('No clipboard image found. Copy an image first, or paste/drag a file path into the chat box.');
                }
                return true;
            }

            const result = await postJson('/command', {command, args: trimmed});
            const output = String(result.output || result.error || '').trim();
            pushCommand(output || `${command}: completed`);
            return true;
        } catch (error) {
            pushSystem(`COMMAND_ERROR: ${error instanceof Error ? error.message : String(error)}`);
            return true;
        }
    };

    const handleSubmit = async (value: string) => {
        if (!value) return;
        let streamTerminalStatus: 'done' | 'error' | 'cancelled' | null = null;
        const normalizedValue = value.trim().toLowerCase();
        const wasTurnInFlight = turnInFlightRef.current;
        // A session accepts one live turn. Preserve the draft instead of adding
        // a second user row that the backend will reject with a confusing 409.
        if (!canStartTurn(turnInFlightRef.current, value)) {
            pushCommand('A turn is already running. Press Esc or use /stop before sending another message.');
            return;
        }
        if (value.toLowerCase() === 'exit' || value.toLowerCase() === 'quit') {
            await stopVoiceIfRunning();
            exit();
            return;
        }

        turnInFlightRef.current = true;
        // Do not carry the previous turn's measured usage into a new active
        // request. Until the provider reports this turn, show unavailable.
        setProviderUsage(null);
        if (await handleSlashCommand(value)) {
            // A live /stop is still waiting for the server stream to finish.
            if (!wasTurnInFlight) turnInFlightRef.current = false;
            setInput('');
            return;
        }

        const attachedFiles = await resolveInputAttachments(value);
        const prompt = attachmentPrompt(value, attachedFiles);
        const userMsg: Message = { role: 'user', content: value };
        setHistory(prev => [...prev, userMsg]);
        if (attachedFiles.length > 0) {
            addActivityItem({
                kind: 'file',
                title: `Attached ${attachedFiles.length} file${attachedFiles.length === 1 ? '' : 's'}`,
                summary: attachedFiles.map(file => file.name).join(', '),
                status: 'done',
                files: attachedFiles.map(file => file.path),
                detail: attachedFiles.map(file => `${file.name} (${file.kind}, ${formatTokens(file.size)}B)\n${file.path}`).join('\n\n'),
                toolName: 'attachment'
            });
            appendTimeline({kind: 'read', weight: 40 * attachedFiles.length, label: 'Attached files'});
        }
        appendTimeline({kind: 'text', weight: estimateTokens(value), label: 'User prompt'});
        setInput('');
        setIsThinking(true);
        setExpandedThinking(false);
        setThinkingPrompt(value);
        setThinkingStartedAt(Date.now());
        activePlanRef.current = false;
        setPlanExpanded(false);
        setWorkingPhase('querying');
        const controller = new AbortController();
        chatAbortControllerRef.current = controller;
        activeRunIdRef.current = null;
        try {
            const response = await fetch(`${API_BASE}/chat`, {
                method: 'POST',
                headers: API_JSON_HEADERS,
                signal: controller.signal,
                body: JSON.stringify({
                    prompt,
                    session_id: sessionId,
                    provider,
                    model,
                    stream: true,
                    canonical_events: true
                })
            });

            if (!response.ok) {
                const detail = await response.text();
                throw new Error(detail || `Chat request failed (${response.status})`);
            }
            if (!response.body) throw new Error("No response body");
            
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            
            let assistantContent = '';
            let streamBuffer = '';
            setHistory(prev => [...prev, { role: 'assistant', content: '' }]);
            appendTimeline({kind: 'text', weight: 12, label: 'Assistant stream'});

            const processStreamText = (text: string) => {
                if (!text) return;

                const markerQuestion = parseQuestionMarker(text);
                if (markerQuestion) {
                    setSelectedQuestionIndex(0);
                    setPendingQuestion(markerQuestion);
                    setPanelMode('question');
                    appendTimeline({kind: 'step', weight: 20, label: 'Question pending'});
                    text = stripQuestionMarkers(text);
                    if (!text.trim()) return;
                }

                // ── [INTELLIGENCE_EXTRACTION]: Robust marker parsing
                if (text.includes("[TOOL_START:")) {
                    try {
                        const markerMatch = text.match(/\[TOOL_START:([^:]+):(.*)\]/);
                        if (markerMatch) {
                            const [_, toolName, paramsStr] = markerMatch;
                            const params = JSON.parse(paramsStr);
                            setWorkingPhase(inferWorkingPhaseFromTool(toolName, params));
                            const toolKind = classifyTool(toolName);
                            const normalizedToolName = toolName.toLowerCase();
                            appendTimeline({kind: toolKind, weight: 40, label: toolName});
                            // Canonical work events own visible tool rows. The legacy
                            // TOOL_START marker only updates phase/timeline state;
                            // rendering it here duplicates the same logical action.
                            
                            // Track file changes for sidebar
                            const fileCommand = String(params.command || '').toLowerCase();
                            const isFileMutation = normalizedToolName === 'write_file'
                                || (normalizedToolName === 'file_edit' && fileCommand !== 'view');
                            if (isFileMutation) {
                                const filename = params.filename || params.path;
                                if (filename) {
                                    const fileNameOnly = filename.split(/[/\\]/).pop() || filename;
                                    setTouchedFiles(prev => {
                                        const filtered = prev.filter(f => f.name !== fileNameOnly);
                                        return [{name: fileNameOnly, status: 'MODIFIED'}, ...filtered.slice(0, 7)];
                                    });
                                    setActivities(prev => [`Δ Modifying ${fileNameOnly}`, ...prev.slice(0, 2)]);
                                    appendTimeline({kind: 'write', weight: 90, label: fileNameOnly});
                                    
                                    if (params.new_string || params.content) {
                                        const content = params.new_string || params.content;
                                        setLastChange(content.split('\n').slice(0, 8).join('\n'));
                                    }
                                }
                            } else {
                                setActivities(prev => [`⚙ Executing ${toolName}`, ...prev.slice(0, 2)]);
                            }
                        }
                    } catch(e) {
                        // Silent fail for malformed markers during streaming
                    }
                }

                if (text.includes("[TOOL_RESULT:")) {
                    try {
                        const resultMatch = text.match(/\[TOOL_RESULT:([^:]+):(.*)\]/);
                        if (resultMatch) {
                            const [, toolName, resultStr] = resultMatch;
                            const result = JSON.parse(resultStr);
                            setWorkingPhase(inferWorkingPhaseFromTool(toolName, result));
                            updateLatestActivityForTool(toolName, result);
                        }
                    } catch(e) {
                        // Tool result markers are best-effort UI telemetry.
                    }
                }

                // Append to visible content only if it's not a pure marker chunk
                const visibleChunk = text.trim();
                if (
                    !visibleChunk.startsWith("[TOOL_START:")
                    && !visibleChunk.startsWith("[TOOL_RESULT:")
                    && !visibleChunk.startsWith("[TOOL_END:")
                ) {
                    setWorkingPhase(inferWorkingPhaseFromText(visibleChunk) || 'streaming');
                    assistantContent += text;
                    setHistory(prev => {
                        const newHist = [...prev];
                        const assistantIndex = newHist.findLastIndex(message => message.role === 'assistant');
                        if (assistantIndex >= 0) {
                            newHist[assistantIndex] = {...newHist[assistantIndex], content: assistantContent};
                        }
                        return newHist;
                    });
                }

                // Keep the run visibly active until the stream reaches its
                // terminal frame. Individual text/tool chunks are not the end
                // of a turn, especially when tools execute in parallel.
                setIsThinking(true);
            };

            const processSseFrame = (frame: string) => {
                const lines = frame.replace(/\r/g, '').split('\n');
                const eventType = lines.find(line => line.startsWith('event:'))?.slice(6).trim() || 'message';
                if (eventType === 'heartbeat') return;
                const raw = lines.filter(line => line.startsWith('data:'))
                    .map(line => line.replace(/^data:\s?/, '')).join('\n');
                if (!raw) return;
                if (eventType === 'message') {
                    let text = raw;
                    try {
                        const payload = JSON.parse(raw);
                        text = String(payload.content ?? payload.data ?? raw);
                    } catch {
                        // Legacy raw text stream.
                    }
                    processStreamText(text);
                    return;
                }
                if (eventType === 'done') {
                    let donePayload: any = {};
                    try { donePayload = JSON.parse(raw); } catch { /* legacy empty done frame */ }
                    const doneStatus = String(donePayload?.status || '').toLowerCase();
                    if (doneStatus === 'error' || doneStatus === 'failed') {
                        streamTerminalStatus = 'error';
                        completeRunningActivities('error', String(donePayload?.message || donePayload?.error || 'Operation failed'));
                    } else if (doneStatus === 'cancelled' || doneStatus === 'canceled') {
                        streamTerminalStatus = 'cancelled';
                        completeRunningActivities('cancelled');
                    } else {
                        streamTerminalStatus = 'done';
                        completeRunningActivities('done');
                    }
                    setIsThinking(false);
                    return;
                }
                if (eventType === 'usage') {
                    let usagePayload: any;
                    try {
                        usagePayload = JSON.parse(raw);
                    } catch {
                        throw new Error('Malformed usage event from NEXUS API');
                    }
                    if (usagePayload?.source === 'provider' && usagePayload?.available === true) {
                        const inputTokens = Number(usagePayload.input_tokens || 0);
                        const outputTokens = Number(usagePayload.output_tokens || 0);
                        const contextTokens = Number(usagePayload.context_tokens || 0);
                        const contextLimit = Number(usagePayload.context_window || 0);
                        if (inputTokens >= 0 && outputTokens >= 0 && contextTokens >= 0 && contextLimit > 0) {
                            setProviderUsage({
                                source: 'provider',
                                inputTokens,
                                outputTokens,
                                contextTokens,
                                contextLimit
                            });
                        }
                    }
                    return;
                }
                if (eventType === 'error') {
                    let message = raw;
                    try {
                        const errorPayload = JSON.parse(raw);
                        message = String(errorPayload.message || errorPayload.content || errorPayload.error || raw);
                    } catch {
                        // The NEXUS API sends plain-text error frames.
                    }
                    streamTerminalStatus = 'error';
                    throw new Error(message);
                }
                let payload: any;
                try {
                    payload = JSON.parse(raw);
                } catch {
                    throw new Error(`Malformed ${eventType} event from NEXUS API`);
                }
                if (eventType === 'work_event' || eventType === 'nexus.event') {
                    const event = canonicalActivityFromSseFrame(frame) || adaptCanonicalEvent(payload.event || payload);
                    const observedRunId = event.run_id || event.turn_id;
                    if (observedRunId) {
                        activeRunIdRef.current = String(observedRunId);
                    }
                    if (!acceptWorkEvent(event)) return;
                    const toolQuestion = questionFromToolEvent(event);
                    if (toolQuestion) {
                        setSelectedQuestionIndex(0);
                        setPendingQuestion(toolQuestion);
                        setPanelMode('question');
                        appendTimeline({kind: 'step', weight: 20, label: 'Question pending'});
                    }
                    const approval = approvalFromWorkEvent(event);
                    const approvalRequestId = String(event.request_id || event.requestId || event.approval_id || event.id || '');
                    const approvalStatus = String(event.status || '').toLowerCase();
                    if (approval) {
                        setPendingApproval(approval);
                        setPanelMode('approval');
                        appendTimeline({kind: 'step', weight: 30, label: 'Approval required'});
                    } else if (
                        pendingApprovalRef.current?.requestId === approvalRequestId
                        && ['done', 'success', 'succeeded', 'completed', 'failed', 'denied', 'rejected', 'cancelled', 'canceled'].includes(approvalStatus)
                    ) {
                        pendingApprovalRef.current = null;
                        setPendingApproval(null);
                        setPanelMode(current => current === 'approval' ? 'workspace' : current);
                    }
                    const eventKind = String(event.kind || event.type || '').toLowerCase();
                    const eventTypeName = String(event.event_type || event.type || '').toLowerCase();
                    if (eventTypeName === 'run.completed') {
                        setPlanStatus('done');
                        setPlanItems(previous => finalizePlanChecklist(previous, 'done'));
                        setPlanExpanded(false);
                    } else if (eventTypeName === 'run.failed' || eventTypeName === 'run.cancelled' || eventTypeName === 'run.timed_out') {
                        setPlanStatus('failed');
                        setPlanItems(previous => finalizePlanChecklist(
                            previous,
                            eventTypeName === 'run.cancelled' ? 'cancelled' : 'failed'
                        ));
                        setPlanExpanded(false);
                    }
                    const progress = progressSummaryFromWorkEvent(event);
                    if (progress) {
                        const progressMessage = {
                            role: 'progress',
                            content: progressSummaryText(progress),
                            progress
                        };
                        setHistory(previous => {
                            if (previous.some(message => message.role === 'progress' && message.progress?.id === progress.id)) {
                                return previous;
                            }
                            const next = [...previous];
                            const assistantIndex = next.findLastIndex(message => message.role === 'assistant');
                            if (assistantIndex >= 0) next.splice(assistantIndex, 0, progressMessage);
                            else next.push(progressMessage);
                            return next;
                        });
                        setPlanItems(previous => {
                            const merged = mergeProgressIntoPlanChecklist(previous, progress);
                            if (merged !== previous) setPlanStatus(planChecklistStatus(merged));
                            return merged;
                        });
                        setWorkingPhase(inferWorkingPhaseFromTool(progress.tool || 'tool', event) || 'working');
                        setIsThinking(true);
                        return;
                    }
                    if (eventTypeName === 'assistant.progress') return;
                    if (isSyntheticAgentLifecycle(event)) return;
                    const partType = String(event.part_type || event.payload?.part_type || '').toLowerCase();
                    const hasStructuredToolIdentity = Boolean(
                        event.tool
                        || event.related_tool
                        || event.name
                        || partType.includes('tool')
                        || partType.includes('command')
                    );
                    // Some canonical/provider adapters preserve the tool
                    // identity but omit a normalized public kind. Keep those
                    // real tool events visible in the activity rail; only
                    // lifecycle noise without a tool identity is filtered.
                    if ((event.visibility && event.visibility !== 'public') || (!PUBLIC_ACTIVITY_KINDS.has(eventKind) && !hasStructuredToolIdentity)) return;
                    const label = String(event.action || event.label || event.kind || 'Agent activity');
                    const status = String(event.status || 'running');
                    setWorkingPhase(
                        inferWorkingPhaseFromTool(String(event.tool || event.related_tool || eventKind || 'tool'), event)
                        || inferWorkingPhaseFromText(`${event.kind || ''} ${label}`)
                        || 'working'
                    );
                    appendTimeline({kind: status === 'error' ? 'error' : 'tool', weight: 30, label});
                    setActivities(prev => [`${status === 'error' ? '!' : '⚙'} ${label}`, ...prev.slice(0, 2)]);
                    const fileStatus = fileStatusFromWorkEvent(event);
                    if (fileStatus) {
                        const fileTarget = String(event.target || event.path || event.related_files?.[0] || '').trim();
                        if (fileTarget) {
                            setTouchedFiles(previous => [{
                                name: fileStatus.name,
                                status: fileStatus.status,
                                additions: fileStatus.additions,
                                deletions: fileStatus.deletions
                            }, ...previous.filter(file => file.name !== fileStatus.name)].slice(0, 8));
                        }
                    }
                    if (eventKind === 'plan') {
                        activePlanRef.current = true;
                        setPlanItems(previous => {
                            const merged = mergePlanChecklistEvent(previous, event);
                            setPlanStatus(planChecklistStatus(
                                merged,
                                ['error', 'failed'].includes(status.toLowerCase()) ? 'failed' : 'planning'
                            ));
                            return merged;
                        });
                        setPlanExpanded(true);
                        // A plan is an inspector view, not only a transcript row.
                        // Focus it when the server creates/updates the plan so the
                        // right pane shows the steps immediately.
                        setPanelMode(current => panelModeAfterActivitySelection(current, 'plan'));
                        setSelectedActivityId(null);
                        setSelectedAgentId(null);
                        upsertWorkEventActivity(event, false);
                        setIsThinking(true);
                        return;
                    }
                    upsertWorkEventActivity(event);
                    setIsThinking(true);
                    return;
                }
                processStreamText(String(payload.content || ''));
            };

            while (true) {
                const { done, value: chunk } = await reader.read();
                if (done) break;

                streamBuffer += decoder.decode(chunk, {stream: true});
                const frames = streamBuffer.split(/\r?\n\r?\n/);
                streamBuffer = frames.pop() || '';

                for (const frame of frames) {
                    processSseFrame(frame);
                }
            }

            streamBuffer += decoder.decode();
            if (streamBuffer.trim()) {
                processSseFrame(streamBuffer);
            }
            if (streamTerminalStatus === null) streamTerminalStatus = 'done';
            completeRunningActivities(streamTerminalStatus);
            appendTimeline({kind: 'success', weight: 24, label: 'Turn complete'});
        } catch (err) {
            if (err instanceof Error && err.name === 'AbortError') {
                streamTerminalStatus = 'cancelled';
                completeRunningActivities('cancelled');
                appendTimeline({kind: 'error', weight: 24, label: 'Turn cancelled'});
                pushCommand('current turn cancelled');
                return;
            }
            const message = err instanceof Error ? err.message : String(err);
            streamTerminalStatus = 'error';
            setHistory(prev => [...prev, { role: 'system', content: `SYSTEM_ERROR: ${message}` }]);
            completeRunningActivities('error');
            appendTimeline({kind: 'error', weight: 90, label: message});
        } finally {
            if (chatAbortControllerRef.current === controller) {
                chatAbortControllerRef.current = null;
                activeRunIdRef.current = null;
                turnInFlightRef.current = false;
                const queuedAnswer = queuedQuestionAnswerRef.current.take();
                if (queuedAnswer) {
                    setTimeout(() => { void handleSubmit(queuedAnswer); }, 0);
                }
            }
            void loadPanelData();
            setIsThinking(false);
            setExpandedThinking(false);
            setThinkingStartedAt(null);
        }
    };

    questionSubmitRef.current = (answer: string) => {
        const submission = resolveQuestionAnswerSubmission(answer, turnInFlightRef.current);
        if (submission.kind === 'ignore') return;
        setQuestionCustomMode(false);
        setPendingQuestion(null);
        setPanelMode('workspace');
        setSelectedQuestionIndex(0);
        setInput('');
        if (submission.kind === 'queue') {
            queuedQuestionAnswerRef.current.enqueue(submission.answer);
            return;
        }
        void handleSubmit(submission.answer);
    };

    return (
        <Box flexDirection="row" width={width} height={height} minHeight={height} backgroundColor={THEME.appBg}>
            {showNarrowInspector ? (
                <NexusWorkspacePanel
                    timeline={timeline}
                    usage={usage}
                    mode={displayedPanelMode}
                    agents={agents}
                    tasks={tasks}
                    touchedFiles={touchedFiles}
                    activityItems={activityItems}
                    pendingQuestion={pendingQuestion}
                    pendingApproval={pendingApproval}
                    selectedQuestionIndex={selectedQuestionIndex}
                    questionCustomMode={questionCustomMode}
                    planItems={planItems}
                    planStatus={planStatus}
                    planExpanded={planExpanded}
                    mcpConnectedCount={mcpConnectedCount}
                    mcpServers={mcpServers}
                    selectedActivityId={selectedActivityId}
                    selectedAgentId={selectedAgentId}
                    motionFrame={motionFrame}
                    voiceMode={voiceMode}
                    voicePhase={voicePhase}
                    voiceTranscriptPreview={voiceTranscriptPreview}
                    voiceReplyPreview={voiceReplyPreview}
                    width={width}
                    height={height}
                    currentTask={currentTask}
                    isWorking={isThinking}
                    workingPhase={workingPhase}
                    elapsedMs={elapsedMs}
                />
            ) : (
            <Box
                flexDirection="column"
                width={leftPanelWidth}
                flexShrink={1}
                height={height}
                backgroundColor={THEME.panelAltBg}
            >
                <Box flexDirection="column" height={chatViewportHeight} width={chatContentWidth + 2} paddingX={1} backgroundColor={THEME.panelAltBg}>
                    {showWelcomeLogo && (
                        <NexusWelcomeLogo
                            width={chatContentWidth}
                            height={chatViewportHeight}
                        />
                    )}
                    {visibleChatLines.map(line => (
                        <ChatLineView
                            key={line.key}
                            line={line}
                            width={chatContentWidth}
                            frame={line.activity ? motionFrame : 0}
                        />
                    ))}
                    {isThinking && (
                        <WorkingStatus
                            frame={motionFrame}
                            width={chatContentWidth}
                            phase={workingPhase}
                            activity={activeActivity}
                            elapsedMs={elapsedMs}
                        />
                    )}
                    {isThinking && expandedThinking && thinkingDetailRows.map(line => (
                        <ChatLineView
                            key={line.key}
                            line={line}
                            width={chatContentWidth}
                            frame={motionFrame}
                        />
                    ))}
                </Box>

                {showCommandPalette && layout.paletteHeight > 0 && (
                    <CommandPalette
                        matches={slashMatches.slice(0, Math.max(1, layout.paletteHeight - 3))}
                        selectedIndex={Math.min(commandIndex, Math.max(0, layout.paletteHeight - 4))}
                    />
                )}

                {voiceMode !== 'off' && layout.voiceHeight > 0 && (
                    <Box paddingX={1} paddingY={0} justifyContent="space-between" backgroundColor={THEME.panelAltBg}>
                        <Box>
                            <Text color={voicePhaseColor(voicePhase)} bold>🎙 {voiceMode} · {voicePhaseLabel(voicePhase)} </Text>
                            <VoiceEqualizer phase={voicePhase} frame={motionFrame} bars={18} />
                        </Box>
                    </Box>
                )}

                {/* PROMPT BOX */}
                <Box flexDirection="column" marginBottom={0} backgroundColor={THEME.inputBg}>
                    <InputComposer
                        value={pendingApproval ? '' : input}
                        onChange={value => { if (!pendingApproval) setInput(sanitizeComposerInput(value)); }}
                        onSubmit={pendingApproval
                            ? () => {}
                            : questionCustomMode && pendingQuestion
                                ? (value) => questionSubmitRef.current(value)
                                : handleSubmit}
                        placeholder={pendingApproval
                            ? 'Approval required · y allow · a always · n deny'
                            : questionCustomMode
                                ? 'Type your answer · Enter to submit · Esc to cancel'
                                : 'Message NEXUS...'}
                        isBusy={isThinking}
                        showHints={layout.showComposerHints && !showCommandPalette}
                        width={leftPanelWidth}
                    />
                </Box>

                {/* APP FOOTER */}
                <StatusBar
                    width={leftPanelWidth}
                    usage={{tokens: usage.contextTokens, inputTokens: usage.inputTokens, outputTokens: usage.outputTokens, contextWindow: usage.contextLimit, model: model ? `${provider}/${model}` : provider || undefined}}
                    sandboxTier={sandboxTier}
                    permissionMode={permissionMode}
                    voiceMode={voiceMode}
                    voicePhase={voicePhase}
                    mcpCount={mcpConnectedCount}
                    agentCount={agents.length}
                    taskCount={tasks.length}
                    queuePending={queuePending}
                    queueWorker={queueWorker}
                    activeTool={activityItems.find(activity =>
                        ['running', 'queued', 'pending', 'in_progress', 'working'].includes(activity.status.toLowerCase())
                    )?.toolName || ''}
                    connectionState={connectionState}
                />
            </Box>
            )}

            {isWide && (
                <Box width={sidebarWidth} height={height} backgroundColor={THEME.panelBg}>
                    <NexusWorkspacePanel
                        timeline={timeline}
                        usage={usage}
                        mode={displayedPanelMode}
                        agents={agents}
                        tasks={tasks}
                        touchedFiles={touchedFiles}
                        activityItems={activityItems}
                        pendingQuestion={pendingQuestion}
                        pendingApproval={pendingApproval}
                        selectedQuestionIndex={selectedQuestionIndex}
                        questionCustomMode={questionCustomMode}
                        planItems={planItems}
                        planStatus={planStatus}
                        planExpanded={planExpanded}
                        mcpConnectedCount={mcpConnectedCount}
                        mcpServers={mcpServers}
                        selectedActivityId={selectedActivityId}
                        selectedAgentId={selectedAgentId}
                        motionFrame={motionFrame}
                        voiceMode={voiceMode}
                        voicePhase={voicePhase}
                        voiceTranscriptPreview={voiceTranscriptPreview}
                        voiceReplyPreview={voiceReplyPreview}
                        width={sidebarWidth}
                        height={height}
                        currentTask={currentTask}
                        isWorking={isThinking}
                        workingPhase={workingPhase}
                        elapsedMs={elapsedMs}
                    />
                </Box>
            )}
        </Box>
    );
};

clearTerminalForInk();
render(<App />);
