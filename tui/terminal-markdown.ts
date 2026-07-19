const stripInlineMarkdown = (value: string) => value
    .replace(/\*\*(.*?)\*\*/g, '$1')
    .replace(/`([^`]*)`/g, '$1')
    .trim();

const wrapCell = (value: string, width: number): string[] => {
    const words = stripInlineMarkdown(value).split(/\s+/).filter(Boolean);
    if (words.length === 0) return [''];
    const lines: string[] = [];
    let line = '';
    for (const word of words) {
        if (!line) {
            line = word.length > width ? word.slice(0, width) : word;
        } else if (line.length + word.length + 1 <= width) {
            line += ` ${word}`;
        } else {
            lines.push(line);
            line = word.length > width ? word.slice(0, width) : word;
        }
    }
    if (line) lines.push(line);
    return lines;
};

const parseRow = (line: string): string[] => line.trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map(stripInlineMarkdown);

const isSeparator = (cells: string[]) => cells.length > 0
    && cells.every(cell => /^:?-{3,}:?$/.test(cell.replace(/\s/g, '')));

const renderTable = (rows: string[][], maxWidth: number): string[] => {
    const columnCount = Math.max(...rows.map(row => row.length));
    const normalized = rows.map(row => Array.from({length: columnCount}, (_, index) => row[index] || ''));
    const available = Math.max(columnCount * 6, maxWidth - (columnCount * 3 + 1));
    const widths = Array.from({length: columnCount}, (_, column) => Math.max(
        5,
        Math.min(32, Math.max(...normalized.map(row => stripInlineMarkdown(row[column]).length)))
    ));
    while (widths.reduce((sum, value) => sum + value, 0) > available) {
        const largest = widths.indexOf(Math.max(...widths));
        if (widths[largest] <= 5) break;
        widths[largest] -= 1;
    }

    const border = (left: string, middle: string, right: string) =>
        left + widths.map(width => '─'.repeat(width + 2)).join(middle) + right;
    const output = [border('┌', '┬', '┐')];
    normalized.forEach((row, rowIndex) => {
        const wrapped = row.map((cell, column) => wrapCell(cell, widths[column]));
        const height = Math.max(...wrapped.map(lines => lines.length));
        for (let lineIndex = 0; lineIndex < height; lineIndex += 1) {
            output.push('│' + wrapped.map((lines, column) => {
                const content = lines[lineIndex] || '';
                return ` ${content.padEnd(widths[column])} `;
            }).join('│') + '│');
        }
        if (rowIndex < normalized.length - 1) output.push(border('├', '┼', '┤'));
    });
    output.push(border('└', '┴', '┘'));
    return output;
};

export const renderTerminalMarkdown = (source: string, maxWidth: number): string => {
    let normalized = source.replace(/\r/g, '');
    if (/\|\s*:?-{3,}/.test(normalized)) {
        normalized = normalized
            .replace(/\s*\|\|\s*/g, '|\n|')
            .replace(/(#{1,6}\s+[^|\n]+)\|/g, '$1\n|');
    }

    const lines = normalized.split('\n');
    const output: string[] = [];
    for (let index = 0; index < lines.length;) {
        if (!lines[index].trim().startsWith('|')) {
            output.push(lines[index]);
            index += 1;
            continue;
        }
        const tableLines: string[] = [];
        while (index < lines.length && lines[index].trim().startsWith('|')) {
            tableLines.push(lines[index]);
            index += 1;
        }
        const parsed = tableLines.map(parseRow);
        const dataRows = parsed.filter(row => !isSeparator(row));
        if (parsed.some(isSeparator) && dataRows.length >= 2) {
            output.push(...renderTable(dataRows, maxWidth));
        } else {
            output.push(...tableLines);
        }
    }
    return output.join('\n');
};
