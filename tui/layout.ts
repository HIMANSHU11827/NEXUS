export interface TuiLayoutOptions {
    paletteRows?: number;
    voiceVisible?: boolean;
}

export interface TuiLayout {
    width: number;
    height: number;
    isWide: boolean;
    sidebarWidth: number;
    mainWidth: number;
    chatContentWidth: number;
    headerHeight: number;
    composerHeight: number;
    footerHeight: number;
    paletteHeight: number;
    voiceHeight: number;
    chatViewportHeight: number;
    showComposerHints: boolean;
    chatStartRow: number;
}

const clamp = (value: number, minimum: number, maximum: number) =>
    Math.min(maximum, Math.max(minimum, value));

/**
 * Resolve every persistent row and column before rendering. Keeping this pure
 * makes resize behavior testable and prevents the transcript from being
 * measured against space already occupied by the composer or command palette.
 */
export const resolveTuiLayout = (
    columns: number,
    rows: number,
    options: TuiLayoutOptions = {}
): TuiLayout => {
    const width = Math.max(20, Math.floor(columns || 0));
    const height = Math.max(8, Math.floor(rows || 0));
    const isWide = width >= 120;
    const sidebarWidth = isWide
        ? clamp(Math.floor(width * 0.28), 36, Math.min(52, width - 48))
        : 0;
    const mainWidth = Math.max(1, width - sidebarWidth);
    const chatContentWidth = Math.max(1, mainWidth - 2);
    const headerHeight = 3;
    // Hint rows contain several shortcuts and must never be allowed to wrap
    // inside the fixed-height composer on compact terminals.
    const showComposerHints = height >= 12 && mainWidth >= 58;
    const composerHeight = showComposerHints ? 4 : 3;
    const footerHeight = 1;
    const paletteRows = Math.max(0, Math.min(10, options.paletteRows || 0));
    const baseRows = headerHeight + composerHeight + footerHeight;
    const dynamicBudget = Math.max(0, height - baseRows - 1);
    const voiceHeight = options.voiceVisible && dynamicBudget >= 1 ? 1 : 0;
    const paletteBudget = Math.max(0, dynamicBudget - voiceHeight);
    const requestedPaletteHeight = paletteRows > 0 ? paletteRows + 3 : 0;
    const paletteHeight = paletteBudget >= 4 ? Math.min(requestedPaletteHeight, paletteBudget) : 0;
    const reservedRows = headerHeight + composerHeight + footerHeight + paletteHeight + voiceHeight;
    const chatViewportHeight = Math.max(1, height - reservedRows);

    return {
        width,
        height,
        isWide,
        sidebarWidth,
        mainWidth,
        chatContentWidth,
        headerHeight,
        composerHeight,
        footerHeight,
        paletteHeight,
        voiceHeight,
        chatViewportHeight,
        showComposerHints,
        chatStartRow: headerHeight + 1
    };
};
