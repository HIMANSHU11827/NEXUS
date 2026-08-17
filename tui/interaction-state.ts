import type {PanelMode, PendingQuestion} from './helpers.js';

export const INSPECTOR_PANES: PanelMode[] = ['workspace', 'plan', 'hive', 'mcp', 'activity'];

export const nextInspectorPanel = (current: PanelMode): PanelMode => {
    const index = INSPECTOR_PANES.indexOf(current);
    return INSPECTOR_PANES[(index + 1 + INSPECTOR_PANES.length) % INSPECTOR_PANES.length];
};

/** Plans should become visible in the inspector when they are created or selected. */
export const panelModeAfterActivitySelection = (current: PanelMode, activityKind?: string): PanelMode => {
    if (activityKind === 'plan') return 'plan';
    return current === 'activity' ? 'workspace' : current;
};

export type QuestionAnswerSubmission =
    | {kind: 'ignore'}
    | {kind: 'queue'; answer: string}
    | {kind: 'submit'; answer: string};

/** Keep question answers on the same serialized turn channel as normal prompts. */
export const resolveQuestionAnswerSubmission = (
    answer: string,
    turnInFlight: boolean
): QuestionAnswerSubmission => {
    const normalized = answer.trim();
    if (!normalized) return {kind: 'ignore'};
    return turnInFlight ? {kind: 'queue', answer: normalized} : {kind: 'submit', answer: normalized};
};

/** Small executable coordinator for answers that arrive during an active turn. */
export class QuestionAnswerQueue {
    private queuedAnswer: string | null = null;

    enqueue(answer: string): void {
        const normalized = answer.trim();
        if (normalized) this.queuedAnswer = normalized;
    }

    take(): string | null {
        const answer = this.queuedAnswer;
        this.queuedAnswer = null;
        return answer;
    }

    clear(): void {
        this.queuedAnswer = null;
    }
}

export const isExplicitInspectorShortcut = (value: string, ctrl: boolean): boolean =>
    ctrl && ['i', 'o'].includes(value.toLowerCase());

/**
 * Windows Terminal sends Ctrl+I as the same ASCII byte (0x09) as Tab, so Ink
 * reports it as a Tab keypress without a ctrl flag. Routing must therefore be
 * deterministic without trusting the ctrl bit: palette Tab always completes;
 * with no trace row to consume the byte it cycles the inspector; otherwise it
 * moves row focus. A ctrl bit that does survive parsing is treated as the
 * explicit inspector intent.
 */
export type TabIntent = 'complete-palette' | 'cycle-inspector' | 'cycle-activity';

export const resolveTabIntent = (
    options: {paletteOpen: boolean; hasActivityRows: boolean; ctrl?: boolean; shift?: boolean}
): TabIntent => {
    if (options.paletteOpen) return 'complete-palette';
    if (options.ctrl) return 'cycle-inspector';
    return options.hasActivityRows ? 'cycle-activity' : 'cycle-inspector';
};

export const questionChoiceCount = (question: PendingQuestion): number =>
    question.options.length + (question.allowCustom === false ? 0 : 1);

export const moveQuestionSelection = (
    question: PendingQuestion,
    current: number,
    direction: -1 | 1
): number => {
    const count = Math.max(1, questionChoiceCount(question));
    return (current + direction + count) % count;
};

export const resolveQuestionSelection = (
    question: PendingQuestion,
    selectedIndex: number
): {kind: 'answer'; answer: string} | {kind: 'custom'} | null => {
    if (selectedIndex >= 0 && selectedIndex < question.options.length) {
        return {kind: 'answer', answer: question.options[selectedIndex]};
    }
    if (question.allowCustom !== false && selectedIndex === question.options.length) {
        return {kind: 'custom'};
    }
    return null;
};
