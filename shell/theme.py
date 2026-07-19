"""NEXUS TUI Theme — centralized colors, icons, text styles, and spacing.

Single source of truth for all visual elements in the terminal UI.
Change one value here to update the entire shell.
"""

from dataclasses import dataclass, field
from typing import Dict


@dataclass(frozen=True)
class Colors:
    primary         = "bold magenta"
    secondary       = "bold blue"
    accent          = "bold cyan"
    success         = "bold green"
    warning         = "yellow"
    error           = "bold red"
    muted           = "grey50"
    dim             = "grey70"
    bright_white    = "bold white"
    info            = "cyan"
    agent           = "bold cyan"
    user            = "bold blue"
    system          = "italic grey50"
    tool            = "italic grey70"
    task            = "bold yellow"
    skill           = "bold green"
    nexus           = "bold magenta"
    highlight       = "bold yellow"
    code            = "bold green"
    path            = "underline blue"
    duration        = "cyan"
    thinking        = "italic grey50"
    separator       = "dim"
    heading         = "bold white"
    subtitle        = "grey70"
    label           = "dim"
    value           = "white"


@dataclass(frozen=True)
class Icons:
    thinking        = "🧠"
    plan            = "📋"
    tool            = "🔧"
    file            = "📄"
    search          = "🔍"
    command         = "💻"
    message         = "💬"
    subagent        = "🧠"
    handoff         = "🔄"
    error           = "❌"
    success         = "✓"
    failure         = "✗"
    separator       = "─"
    prompt          = "◈"
    arrow           = "▸"
    created         = "🟢"
    modified        = "🟡"
    deleted         = "🔴"
    clock           = "⏱"
    phase           = "▶"
    waiting         = "⏳"
    blocked         = "🚫"
    approved        = "✅"
    cancelled       = "🚫"


@dataclass(frozen=True)
class TextStyles:
    heading         = "bold white"
    subtitle        = "grey70 italic"
    label           = "dim"
    value           = "white"
    caption         = "grey50 italic"
    code            = "bold green"
    path            = "underline blue"
    duration        = "cyan"
    error           = "bold red"
    warning         = "yellow"
    success         = "bold green"
    info            = "cyan"
    muted           = "grey50"
    dim             = "grey70"
    highlight       = "bold yellow"


@dataclass(frozen=True)
class Spacing:
    compact     = 0
    normal      = 1
    relaxed     = 2
    section_gap = 1


@dataclass(frozen=True)
class Borders:
    normal   = "grey50"
    info     = "blue"
    success  = "green"
    error    = "red"
    warning  = "yellow"
    accent   = "cyan"
    primary  = "bold magenta"
    agent    = "bold cyan"
    task     = "bold yellow"
    muted    = "grey30"


@dataclass(frozen=True)
class Panels:
    thinking_border_style    = "grey50"
    thinking_title           = "grey50 italic"
    planning_border_style    = "blue"
    planning_title           = "bold blue"
    tool_border_style        = "cyan"
    tool_title               = "bold cyan"
    command_border_style     = "yellow"
    command_title            = "bold yellow"
    file_border_style        = "green"
    file_title               = "bold green"
    error_border_style       = "red"
    error_title              = "bold red"
    agent_border_style       = "cyan"
    agent_title              = "bold cyan"
    user_border_style        = "blue"
    user_title               = "bold blue"
    assistant_border_style   = "magenta"
    assistant_title          = "bold magenta"
    done_border_style        = "grey50"
    done_title               = "bold green"
    detail_border_style      = "blue"


@dataclass(frozen=True)
class NexusTheme:
    """Centralized styling for the NEXUS TUI."""

    Colors: type = Colors
    Icons: type = Icons
    TextStyles: type = TextStyles
    Spacing: type = Spacing
    Borders: type = Borders
    Panels: type = Panels

    status_colors: Dict[str, str] = field(default_factory=lambda: {
        "success":  "green",
        "running":  "cyan",
        "failed":   "red",
        "error":    "red",
        "pending":  "grey50",
        "started":  "cyan",
        "blocked":  "yellow",
        "aborted":  "red",
        "waiting":  "yellow",
        "approved": "green",
        "cancelled":"red",
    })

    agent_states: Dict[str, str] = field(default_factory=lambda: {
        "idle":         "grey50",
        "thinking":     "cyan",
        "planning":     "blue",
        "running":      "cyan",
        "awaiting_tool":"yellow",
        "editing":      "green",
        "running_cmd":  "yellow",
        "blocked":      "red",
        "waiting_user": "yellow",
        "completed":    "green",
        "failed":       "red",
    })

    kind_icons: Dict[str, str] = field(default_factory=lambda: {
        "file": "📄", "edit": "📄", "read": "📖",
        "search": "🔍", "web": "🔍",
        "command": "💻", "bash": "💻",
        "plan": "📋", "phase": "📋",
        "run": "▶", "message": "💬",
        "subagent": "🧠", "hive": "🧠",
        "handoff": "🔄",
        "error": "❌",
        "tool": "🔧",
        "test": "🧪",
        "retry": "🔄",
        "approval": "✅",
        "question": "❓",
        "file_edit": "📝",
        "think": "💭",
        "observe": "👁",
    })

    file_action_colors: Dict[str, str] = field(default_factory=lambda: {
        "created":  "green",
        "modified": "yellow",
        "deleted":  "red",
        "read":     "cyan",
    })

    mode_colors: Dict[str, str] = field(default_factory=lambda: {
        "auto":         "green",
        "plan":         "cyan",
        "acceptEdits":  "magenta",
        "dontAsk":      "red",
        "bypass":       "bold red",
        "pre_authorized":"yellow",
        "approve":      "blue",
        "default":      "grey50",
    })

    # ── Backward-compatible aliases ───────────────────────────────────────────
    @property
    def panel_border(self) -> str:
        return self.Borders.normal
    @property
    def detail_border(self) -> str:
        return self.Borders.info
    @property
    def done_border(self) -> str:
        return self.Borders.normal


THEME = NexusTheme()
