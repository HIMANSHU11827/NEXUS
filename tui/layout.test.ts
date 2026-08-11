import assert from 'node:assert/strict';
import {resolveTuiLayout} from './layout.js';

const widths = [20, 39, 40, 57, 58, 80, 110, 111, 119, 120, 160, 192];
const heights = [8, 12, 24, 36, 50];

for (const width of widths) {
    for (const height of heights) {
        for (const options of [
            {},
            {paletteRows: 10},
            {voiceVisible: true},
            {paletteRows: 4, voiceVisible: true}
        ]) {
            const layout = resolveTuiLayout(width, height, options);
            assert.equal(layout.mainWidth + layout.sidebarWidth, layout.width);
            assert.ok(layout.mainWidth > 0);
            assert.ok(layout.chatContentWidth > 0);
            assert.ok(layout.chatViewportHeight > 0);
            assert.ok(layout.sidebarWidth === 0 || layout.sidebarWidth <= layout.width - 48);
            if (width < 120) assert.equal(layout.sidebarWidth, 0);
            if (width >= 120) assert.ok(layout.sidebarWidth >= 36);

            const usedRows = layout.headerHeight
                + layout.composerHeight
                + layout.footerHeight
                + layout.paletteHeight
                + layout.voiceHeight
                + layout.chatViewportHeight;
            // Extremely short terminals retain a one-row transcript even when
            // a large palette is open; normal states always fit exactly.
            if (!options.paletteRows || height >= 24) assert.ok(usedRows <= layout.height);
        }
    }
}

const below = resolveTuiLayout(119, 30);
const at = resolveTuiLayout(120, 30);
assert.equal(below.isWide, false);
assert.equal(at.isWide, true);
assert.equal(below.sidebarWidth, 0);
assert.ok(at.sidebarWidth >= 36);

console.log('TUI layout tests passed');
