export interface DetectedChoiceQuestion {
    id: string;
    prompt: string;
    options: string[];
    allowCustom?: boolean;
}

const cleanMarkdown = (value: string) => value
    .replace(/\*\*/g, '')
    .replace(/\s+/g, ' ')
    .trim();

const cleanOption = (value: string) => cleanMarkdown(value).replace(
    /\s*(?:pick|choose|select|press)\s+(?:a\s+)?(?:number|option).*$/i,
    ''
).trim();

export const formatChoiceQuestionForChat = (question: DetectedChoiceQuestion): string => [
    question.prompt,
    '',
    ...question.options.map((option, index) => `${index + 1}. ${option}`),
    '',
    'Press a number to choose, or type your own answer.'
].join('\n');

export const detectChoiceQuestion = (text: string): DetectedChoiceQuestion | null => {
    const normalized = text.replace(/\r/g, '').replace(/\*\*/g, '');
    const markerPattern = /(^|[\s?!:.])\(?([A-Ha-h1-8])\)?[.)]\s+/gm;
    const markers = Array.from(normalized.matchAll(markerPattern)).slice(0, 8);
    if (markers.length < 2) return null;

    const labels = markers.map(match => String(match[2]).toUpperCase());
    const alphabetic = /^[A-H]$/.test(labels[0]);
    const expected = labels.map((_, index) => alphabetic
        ? String.fromCharCode(labels[0].charCodeAt(0) + index)
        : String(Number(labels[0]) + index));
    if (!labels.every((label, index) => label === expected[index])) return null;

    const first = markers[0];
    const firstIndex = first.index ?? 0;
    const promptEnd = firstIndex + (/[?!:]/.test(first[1]) ? first[1].length : 0);
    const prompt = cleanMarkdown(normalized.slice(0, promptEnd)) || 'Choose how Nexus should continue.';
    const promptLooksLikeQuestion = /[?]/.test(prompt)
        || /\b(choose|pick|select|option|which|what|question)\b/i.test(prompt);
    if (!promptLooksLikeQuestion) return null;

    const options = markers.map((marker, index) => {
        const start = (marker.index ?? 0) + marker[0].length;
        const end = index + 1 < markers.length ? (markers[index + 1].index ?? normalized.length) : normalized.length;
        return cleanOption(normalized.slice(start, end));
    }).filter(Boolean);
    if (options.length < 2) return null;

    return {
        id: `question-${Date.now()}`,
        prompt,
        options,
        allowCustom: true
    };
};
