import type {PanelMode, PendingQuestion} from './helpers.js';

export const INSPECTOR_PANES: PanelMode[] = ['workspace', 'plan', 'hive', 'mcp', 'activity'];

export const nextInspectorPanel = (current: PanelMode): PanelMode => {
    const index = INSPECTOR_PANES.indexOf(current);
    return INSPECTOR_PANES[(index + 1 + INSPECTOR_PANES.length) % INSPECTOR_PANES.length];
};

export const isExplicitInspectorShortcut = (value: string, ctrl: boolean): boolean =>
    ctrl && ['i', 'o'].includes(value.toLowerCase());

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
