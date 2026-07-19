"""Info panels, status cards, and rich message card types for the NEXUS TUI.

Single file containing all card/panel renderers.  Every card uses
THEME for colors so the entire look updates from one place.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from rich.columns import Columns
from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.markup import escape
from rich.layout import Layout
from rich.syntax import Syntax
from rich.rule import Rule

from shell.theme import THEME


# ═══════════════════════════════════════════════════════════════════════════════
# Legacy card helpers (kept for backward compatibility)
# ═══════════════════════════════════════════════════════════════════════════════

def info_card(title: str, items: list[tuple[str, str]], border_style: str = "grey50") -> Panel:
    """A compact key-value card."""
    lines = []
    for key, val in items:
        lines.append(f"[{THEME.TextStyles.label}]{escape(key)}:[/{THEME.TextStyles.label}] [{THEME.TextStyles.value}]{escape(str(val) if val else '—')}[/{THEME.TextStyles.value}]")
    return Panel(
        "\n".join(lines),
        title=f"[bold]{escape(title)}[/bold]",
        border_style=border_style,
        padding=(1, 2),
    )


def status_card(title: str, items: list[tuple[str, str, str]]) -> Panel:
    """A status card with colored values. Items: (label, value, color)."""
    lines = []
    for label, val, color in items:
        val_str = escape(str(val) if val else "—")
        lines.append(f"  [{THEME.TextStyles.label}]{escape(label)}:[/{THEME.TextStyles.label}] [{color}]{val_str}[/{color}]")
    return Panel(
        "\n".join(lines),
        title=f"[bold]{escape(title)}[/bold]",
        border_style=THEME.panel_border,
        padding=(1, 2),
    )


def section_header(title: str, icon: str = "") -> Text:
    """A section header with optional icon."""
    txt = Text()
    if icon:
        txt.append(f"{icon} ", style=THEME.Colors.accent)
    txt.append(title, style=THEME.Colors.accent)
    return txt


def tool_table(tools: list[tuple[str, str, str]]) -> Table:
    """Tools list table: (name, description, category)."""
    table = Table(box=None, show_header=False, padding=(0, 1))
    table.add_column(style=THEME.Colors.info)
    table.add_column(style="grey70")
    table.add_column(style="dim")
    for name, desc, cat in tools:
        table.add_row(name, desc[:50], cat)
    return table


def provider_table(providers: list[tuple[str, str, str]]) -> Table:
    """Providers list table: (name, model, status)."""
    table = Table(box=None, show_header=False, padding=(0, 1))
    table.add_column(style=THEME.Colors.info)
    table.add_column(style=THEME.Colors.bright_white)
    table.add_column(style="dim")
    for name, model, status in providers:
        status_color = THEME.Colors.success if status == "available" else THEME.Colors.muted
        table.add_row(name, model[:40] if model else "—", f"[{status_color}]{status}[/]")
    return table


def agent_table(agents: list[tuple[str, str, str, str]]) -> Table:
    """Sub-agent list table: (id, persona, status, task)."""
    table = Table(box=None, show_header=False, padding=(0, 1))
    table.add_column(style=THEME.Colors.info)
    table.add_column(style=THEME.Colors.accent)
    table.add_column(style="dim")
    table.add_column(style="grey70")
    for aid, persona, status, task in agents:
        sc = THEME.status_colors.get(status, THEME.Colors.muted)
        table.add_row(aid[:12], persona, f"[{sc}]{status}[/]", task[:40])
    return table


def status_row(label: str, value: str, value_color: str = "white") -> str:
    """A single status row for use in a panel."""
    return f"  [{THEME.TextStyles.label}]{escape(label)}:[/{THEME.TextStyles.label}] [{value_color}]{escape(value)}[/{value_color}]"


# ═══════════════════════════════════════════════════════════════════════════════
# Rich Message Card Functions
# ═══════════════════════════════════════════════════════════════════════════════

def message_card(role: str, content: str, meta: Optional[str] = None) -> Panel:
    """User or assistant message card.
    
    Args:
        role: "user" or "assistant" 
        content: Message text content.
        meta: Optional metadata string (e.g. time, tokens).
    """
    icon = "💬" if role == "user" else "🤖"
    title_style = THEME.Panels.user_title if role == "user" else THEME.Panels.assistant_title
    border_style = THEME.Panels.user_border_style if role == "user" else THEME.Panels.assistant_border_style
    subtitle = f"[dim]{meta}[/dim]" if meta else None
    return Panel(
        f"[white]{escape(content)}[/white]",
        title=f"{icon}[{title_style}] {role.title()}[/{title_style}]",
        border_style=border_style,
        subtitle=subtitle,
        padding=(1, 2),
    )


def planning_card(
    steps: List[str],
    current_idx: int = -1,
    completed_idx: int = -1,
    goal: Optional[str] = None,
) -> Panel:
    """Plan step progression card.
    
    Shows all plan steps with completed/active/pending indicators.
    """
    lines = []
    if goal:
        lines.append(f"  [{THEME.TextStyles.heading}]Goal:[/{THEME.TextStyles.heading}] {escape(goal)}")
        lines.append("")
    for i, step in enumerate(steps):
        if i <= completed_idx:
            prefix = f"[{THEME.Colors.success}]✓[/{THEME.Colors.success}]"
            style = THEME.TextStyles.success
        elif i == current_idx:
            prefix = f"[{THEME.TextStyles.highlight}]▶[/{THEME.TextStyles.highlight}]"
            style = THEME.TextStyles.highlight
        else:
            prefix = f"[{THEME.TextStyles.dim}]○[/{THEME.TextStyles.dim}]"
            style = THEME.TextStyles.dim
        lines.append(f"  {prefix} [{style}]{escape(step[:100])}[/{style}]")
    return Panel(
        "\n".join(lines),
        title=f"[{THEME.Panels.planning_title}]📋 Plan ({len(steps)} steps)[/{THEME.Panels.planning_title}]",
        border_style=THEME.Panels.planning_border_style,
        padding=(1, 2),
    )


def tool_card(
    name: str,
    args: Optional[str] = None,
    status: str = "running",
    duration_ms: Optional[int] = None,
    result: Optional[str] = None,
    error: Optional[str] = None,
) -> Panel:
    """Tool execution card.
    
    Shows the tool being called, its arguments, status, duration, and result.
    """
    icon = THEME.kind_icons.get(name, "🔧")
    status_color = THEME.status_colors.get(status, THEME.Colors.muted)
    dur_str = f" [{THEME.TextStyles.duration}]{duration_ms}ms[/{THEME.TextStyles.duration}]" if duration_ms is not None else ""
    
    lines = []
    if args:
        lines.append(f"  [{THEME.TextStyles.label}]args:[/{THEME.TextStyles.label}] {escape(args[:200])}")
    if result:
        lines.append(f"  [{THEME.TextStyles.label}]result:[/{THEME.TextStyles.label}] {escape(result[:300])}")
    if error:
        lines.append(f"  [{THEME.TextStyles.error}]error:[/{THEME.TextStyles.error}] {escape(error[:300])}")
    if not lines:
        lines.append(f"  [{status_color}]{status}[/{status_color}]{dur_str}")
    
    subtitle = f"[{status_color}]{status}[/{status_color}]{dur_str}"
    return Panel(
        "\n".join(lines),        
        title=f"{icon}[{THEME.Panels.tool_title}] {name}[/{THEME.Panels.tool_title}]",
        border_style=THEME.Panels.tool_border_style,
        subtitle=subtitle,
        padding=(1, 2),
    )


def command_card(
    command: str,
    exit_code: Optional[int] = None,
    duration_ms: Optional[int] = None,
    output: Optional[str] = None,
    status: str = "running",
    error: Optional[str] = None,
) -> Panel:
    """Terminal command execution card.
    
    Shows the command, exit code, duration, output preview, and status.
    """
    if exit_code is not None:
        status = "success" if exit_code == 0 else "failed"
        ec_color = THEME.Colors.success if exit_code == 0 else THEME.Colors.error
        ec_str = f"[{ec_color}]exit {exit_code}[/{ec_color}]"
    else:
        ec_str = ""
    
    dur_str = f" [{THEME.TextStyles.duration}]{duration_ms}ms[/{THEME.TextStyles.duration}]" if duration_ms is not None else ""
    status_color = THEME.status_colors.get(status, THEME.Colors.muted)
    
    lines = [f"  [{THEME.Colors.bright_white}]$ {escape(command[:300])}[/{THEME.Colors.bright_white}]"]
    if output:
        out_lines = output.strip().split("\n")[:5]
        for l in out_lines:
            lines.append(f"  [{THEME.TextStyles.dim}]{escape(l[:200])}[/{THEME.TextStyles.dim}]")
        if len(output.strip().split("\n")) > 5:
            lines.append(f"  [{THEME.TextStyles.caption}]... ({len(output)} chars total)[/{THEME.TextStyles.caption}]")
    if error:
        lines.append(f"  [{THEME.TextStyles.error}]{escape(error[:300])}[/{THEME.TextStyles.error}]")
    
    subtitle_parts = [f"[{status_color}]{status}[/{status_color}]", ec_str, dur_str]
    subtitle = " · ".join(p for p in subtitle_parts if p)
    
    return Panel(
        "\n".join(lines),
        title=f"[{THEME.Panels.command_title}]💻 Command[/{THEME.Panels.command_title}]",
        border_style=THEME.Panels.command_border_style,
        subtitle=subtitle if subtitle else None,
        padding=(1, 2),
    )


def file_card(
    path: str,
    action: str = "modified",
    summary: Optional[str] = None,
    diff: Optional[str] = None,
    status: str = "completed",
    error: Optional[str] = None,
) -> Panel:
    """File operation card.
    
    Shows file changes: created/modified/deleted with optional diff preview.
    """
    action_color = THEME.file_action_colors.get(action, THEME.Colors.muted)
    action_icon = {"created": "🟢", "modified": "🟡", "deleted": "🔴", "read": "📖"}.get(action, "📄")
    
    lines = [f"  [{action_color}]{action_icon} {escape(path)}[/{action_color}]"]
    if summary:
        lines.append(f"  [{THEME.TextStyles.dim}]{escape(summary[:200])}[/{THEME.TextStyles.dim}]")
    if diff:
        try:
            syntax = Syntax(diff[:2000], "diff", theme="ansi_dark", line_numbers=False)
            lines.append(str(syntax))
        except Exception:
            lines.append(f"  {escape(diff[:200])}")
    if error:
        lines.append(f"  [{THEME.TextStyles.error}]{escape(error[:300])}[/{THEME.TextStyles.error}]")
    
    status_color = THEME.status_colors.get(status, THEME.Colors.muted)
    return Panel(
        "\n".join(lines),
        title=f"[{THEME.Panels.file_title}]{action_icon} {action.title()}[/{THEME.Panels.file_title}]",
        border_style=THEME.Panels.file_border_style,
        subtitle=f"[{status_color}]{status}[/{status_color}]" if status else None,
        padding=(1, 2),
    )


def error_card(
    message: str,
    context: Optional[str] = None,
    retryable: bool = False,
    details: Optional[str] = None,
) -> Panel:
    """Error display card.
    
    Shows error message, context, and whether retry is possible.
    """
    lines = [f"  [{THEME.TextStyles.error}]❌ {escape(message)}[/{THEME.TextStyles.error}]"]
    if context:
        lines.append(f"  [{THEME.TextStyles.label}]during:[/{THEME.TextStyles.label}] {escape(context)}")
    if details:
        lines.append(f"  [{THEME.TextStyles.dim}]{escape(details[:500])}[/{THEME.TextStyles.dim}]")
    if retryable:
        lines.append(f"  [{THEME.TextStyles.warning}]↻ Retry available[/{THEME.TextStyles.warning}]")
    subtitle = f"[{THEME.TextStyles.warning}]retryable[/{THEME.TextStyles.warning}]" if retryable else None
    return Panel(
        "\n".join(lines),
        title=f"[{THEME.Panels.error_title}]Error[/{THEME.Panels.error_title}]",
        border_style=THEME.Panels.error_border_style,
        subtitle=subtitle,
        padding=(1, 2),
    )


def agent_card(
    persona: str,
    status: str = "idle",
    task: str = "",
    agent_id: str = "",
    duration_ms: Optional[int] = None,
) -> Panel:
    """Agent status card.
    
    Shows agent persona, current status, task, and duration.
    """
    state_color = THEME.agent_states.get(status, THEME.Colors.muted)
    dur_str = f" [{THEME.TextStyles.duration}]{duration_ms}ms[/{THEME.TextStyles.duration}]" if duration_ms is not None else ""
    
    lines = []
    if persona:
        lines.append(f"  [{THEME.TextStyles.label}]persona:[/{THEME.TextStyles.label}] [{THEME.Colors.accent}]{escape(persona)}[/{THEME.Colors.accent}]")
    if task:
        lines.append(f"  [{THEME.TextStyles.label}]task:[/{THEME.TextStyles.label}] {escape(task[:120])}")
    if agent_id:
        lines.append(f"  [{THEME.TextStyles.label}]id:[/{THEME.TextStyles.label}] [{THEME.TextStyles.dim}]{escape(agent_id[:16])}[/{THEME.TextStyles.dim}]")
    
    return Panel(
        "\n".join(lines) if lines else f"  [{state_color}]{status}[/{state_color}]{dur_str}",
        title=f"🧠[{THEME.Panels.agent_title}] {persona or 'Agent'}[/{THEME.Panels.agent_title}]",
        border_style=THEME.Panels.agent_border_style,
        subtitle=f"[{state_color}]{status}[/{state_color}]{dur_str}",
        padding=(1, 2),
    )


def model_card(
    provider: str,
    model: str,
    status: str = "available",
    context_length: Optional[int] = None,
    speed_label: Optional[str] = None,
    is_active: bool = False,
) -> Panel:
    """Provider/model status card.
    
    Shows provider name, model, health status, context length, speed.
    """
    status_color = THEME.Colors.success if status == "available" else THEME.Colors.muted
    if is_active:
        border_style = THEME.Borders.primary
    else:
        border_style = THEME.panel_border
    
    items = [
        (f"[{THEME.TextStyles.label}]model:[/{THEME.TextStyles.label}]", f"[{THEME.Colors.bright_white}]{escape(model)}[/{THEME.Colors.bright_white}]"),
    ]
    if context_length:
        items.append((f"[{THEME.TextStyles.label}]context:[/{THEME.TextStyles.label}]", f"{context_length:,}"))
    if speed_label:
        items.append((f"[{THEME.TextStyles.label}]speed:[/{THEME.TextStyles.label}]", speed_label))
    
    lines = [f"  {k} {v}" for k, v in items]
    return Panel(
        "\n".join(lines) if lines else f"  [{status_color}]{status}[/{status_color}]",
        title=f"⚡[{THEME.Panels.assistant_title}] {escape(provider)}[/{THEME.Panels.assistant_title}]",
        border_style=border_style,
        subtitle=f"[{status_color}]{'● active' if is_active else status}[/{status_color}]",
        padding=(1, 2),
    )


def summary_card(
    text: str = "",
    char_count: Optional[int] = None,
    tools: Optional[list[str]] = None,
    files: Optional[list[dict]] = None,
    errors: Optional[int] = None,
    plan_steps: Optional[int] = None,
    total_time_s: Optional[float] = None,
    interrupted: bool = False,
) -> Panel:
    """End-of-response summary card showing stats and state."""
    lines = []
    if not interrupted and text:
        n = len(text)
        lines.append(f"[{THEME.TextStyles.label}]Response:[/{THEME.TextStyles.label}] [{THEME.TextStyles.value}]{n} char{'s' if n != 1 else ''}[/{THEME.TextStyles.value}]")
    if tools:
        lines.append(f"[{THEME.TextStyles.info}]Tools:[/{THEME.TextStyles.info}] {escape(', '.join(tools))}")
    if files:
        file_parts = []
        for f in files[:5]:
            c = THEME.file_action_colors.get(f.get("action", ""), "white")
            file_parts.append(f"[{c}]{escape(f.get('path', '?'))}[/{c}]")
        lines.append(f"[{THEME.TextStyles.info}]Files:[/{THEME.TextStyles.info}] {' '.join(file_parts)}{' …' if len(files) > 5 else ''}")
    if errors:
        lines.append(f"[{THEME.TextStyles.error}]Errors:[/{THEME.TextStyles.error}] {errors}")
    if plan_steps:
        lines.append(f"[{THEME.TextStyles.info}]Steps:[/{THEME.TextStyles.info}] {plan_steps}")
    if interrupted:
        lines.append(f"[{THEME.TextStyles.warning}]Interrupted[/{THEME.TextStyles.warning}]")
    if total_time_s is not None:
        lines.append(f"[{THEME.TextStyles.duration}]⏱ {total_time_s:.1f}s[/{THEME.TextStyles.duration}]")
    
    title_style = THEME.Panels.done_title
    return Panel(
        "\n".join(lines) if lines else "[dim]No output[/dim]",
        title=f"[{title_style}]Done[/{title_style}]",
        border_style=THEME.done_border,
        padding=(1, 2),
    )


def empty_card(title: str, message: str = "Nothing to show.", icon: str = "📭") -> Panel:
    """Empty state card for when no data is available."""
    return Panel(
        f"  [{THEME.TextStyles.dim}]{icon} {escape(message)}[/{THEME.TextStyles.dim}]",
        title=f"[bold]{escape(title)}[/bold]",
        border_style=THEME.panel_border,
        padding=(1, 2),
    )


def loading_card(title: str, message: str = "Loading...") -> Panel:
    """Loading state card."""
    return Panel(
        f"  [{THEME.TextStyles.info}]⏳ {escape(message)}[/{THEME.TextStyles.info}]",
        title=f"[bold]{escape(title)}[/bold]",
        border_style=THEME.Borders.info,
        padding=(1, 2),
    )


def observation_card(observations: list[str]) -> Panel:
    """Observations from tool execution."""
    lines = []
    for obs in observations[:8]:
        text = str(obs)
        lines.append(f"  [{THEME.TextStyles.dim}]{escape(text[:300])}{'…' if len(text) > 300 else ''}[/{THEME.TextStyles.dim}]")
    if len(observations) > 8:
        lines.append(f"  [{THEME.TextStyles.caption}]... {len(observations) - 8} more[/{THEME.TextStyles.caption}]")
    return Panel(
        "\n".join(lines) if lines else f"  [{THEME.TextStyles.dim}]no observations[/{THEME.TextStyles.dim}]",
        title=f"[{THEME.TextStyles.info}]👁 Observations[/{THEME.TextStyles.info}]",
        border_style=THEME.panel_border,
        padding=(1, 2),
    )


def subagent_event_card(
    action: str,
    status: str = "running",
    target: str = "",
    duration_ms: Optional[int] = None,
    result_len: Optional[int] = None,
) -> Panel:
    """Sub-agent lifecycle event card."""
    icon = "🧠"
    status_color = THEME.status_colors.get(status, THEME.Colors.muted)
    dur_str = f" [{THEME.TextStyles.duration}]{duration_ms}ms[/{THEME.TextStyles.duration}]" if duration_ms is not None else ""
    result_str = f" · {result_len} chars" if result_len else ""
    
    lines = [f"  [{status_color}]{icon} {escape(action)}[/{status_color}]"]
    if target:
        lines.append(f"  [{THEME.TextStyles.dim}]{escape(target[:200])}[/{THEME.TextStyles.dim}]")
    
    subtitle = f"[{status_color}]{status}[/{status_color}]{dur_str}{result_str}"
    return Panel(
        "\n".join(lines),
        title=f"[{THEME.Panels.agent_title}]🧠 Sub-Agent[/{THEME.Panels.agent_title}]",
        border_style=THEME.Panels.agent_border_style,
        subtitle=subtitle if subtitle else None,
        padding=(1, 2),
    )


def rule_line(text: str = "", style: str = "dim") -> Rule:
    """A horizontal rule with optional text."""
    return Rule(text, style=style)


def section_line(text: str, icon: str = "─") -> None:
    """A section separator line for use in streaming output."""
    pass  # Use rule_line instead for printable renderable


# ═══════════════════════════════════════════════════════════════════════════════
# Specialized Dashboard Components
# ═══════════════════════════════════════════════════════════════════════════════

def mcp_server_card(
    name: str,
    status: str = "disconnected",
    tools_count: int = 0,
    last_call: Optional[str] = None,
    last_error: Optional[str] = None,
    server_version: Optional[str] = None,
) -> Panel:
    """MCP server status card with tools count and health."""
    status_icon = {"connected": "🟢", "disconnected": "🔴", "error": "❌", "connecting": "🟡"}.get(status, "⚪")
    status_color = THEME.status_colors.get(status, THEME.Colors.muted)

    lines = []
    if tools_count > 0:
        lines.append(f"  [{THEME.TextStyles.label}]tools:[/{THEME.TextStyles.label}] [{THEME.Colors.info}]{tools_count} registered[/{THEME.Colors.info}]")
    if server_version:
        lines.append(f"  [{THEME.TextStyles.label}]version:[/{THEME.TextStyles.label}] [{THEME.TextStyles.dim}]{escape(server_version)}[/{THEME.TextStyles.dim}]")
    if last_call:
        lines.append(f"  [{THEME.TextStyles.label}]last call:[/{THEME.TextStyles.label}] [{THEME.TextStyles.dim}]{escape(last_call[:120])}[/{THEME.TextStyles.dim}]")
    if last_error:
        lines.append(f"  [{THEME.TextStyles.error}]last error:[/{THEME.TextStyles.error}] [{THEME.TextStyles.dim}]{escape(last_error[:200])}[/{THEME.TextStyles.dim}]")
    if not lines:
        lines.append(f"  [{status_color}]{status_icon} {status}[/{status_color}]")

    return Panel(
        "\n".join(lines),
        title=f"{status_icon}[{THEME.Colors.info}] {escape(name)}[/{THEME.Colors.info}]",
        border_style=THEME.Borders.info if status == "connected" else THEME.Borders.normal,
        subtitle=f"[{status_color}]{status}[/{status_color}]",
        padding=(1, 2),
    )


def plugin_card(
    name: str,
    description: str = "",
    enabled: bool = False,
    version: Optional[str] = None,
    author: Optional[str] = None,
    last_used: Optional[str] = None,
) -> Panel:
    """Plugin status card showing name, purpose, and enable state."""
    enabled_icon = f"[{THEME.Colors.success}]●[/{THEME.Colors.success}]" if enabled else f"[{THEME.Colors.muted}]○[/{THEME.Colors.muted}]"
    enabled_label = f"[{THEME.Colors.success}]{'Enabled' if enabled else 'Disabled'}[/{THEME.Colors.success}]" if enabled else f"[{THEME.Colors.muted}]Disabled[/{THEME.Colors.muted}]"

    lines = []
    if description:
        lines.append(f"  [{THEME.TextStyles.dim}]{escape(description[:120])}[/{THEME.TextStyles.dim}]")
    if version:
        lines.append(f"  [{THEME.TextStyles.label}]version:[/{THEME.TextStyles.label}] [{THEME.TextStyles.dim}]{escape(version)}[/{THEME.TextStyles.dim}]")
    if author:
        lines.append(f"  [{THEME.TextStyles.label}]author:[/{THEME.TextStyles.label}] [{THEME.TextStyles.dim}]{escape(author)}[/{THEME.TextStyles.dim}]")
    if last_used:
        lines.append(f"  [{THEME.TextStyles.label}]last used:[/{THEME.TextStyles.label}] [{THEME.TextStyles.dim}]{escape(last_used)}[/{THEME.TextStyles.dim}]")

    return Panel(
        "\n".join(lines) if lines else f"  [{THEME.TextStyles.dim}]no details[/{THEME.TextStyles.dim}]",
        title=f"{enabled_icon}[{THEME.Colors.skill}] {escape(name)}[/{THEME.Colors.skill}]",
        border_style=THEME.Borders.success if enabled else THEME.panel_border,
        subtitle=enabled_label,
        padding=(1, 2),
    )


def skill_card(
    name: str,
    description: str = "",
    enabled: bool = True,
    tool_count: int = 0,
    last_used: Optional[str] = None,
) -> Panel:
    """Skill status card."""
    icon = f"[{THEME.Colors.success}]●[/{THEME.Colors.success}]" if enabled else f"[{THEME.Colors.muted}]○[/{THEME.Colors.muted}]"
    lines = []
    if description:
        lines.append(f"  [{THEME.TextStyles.dim}]{escape(description[:120])}[/{THEME.TextStyles.dim}]")
    if tool_count > 0:
        lines.append(f"  [{THEME.TextStyles.label}]tools:[/{THEME.TextStyles.label}] [{THEME.Colors.info}]{tool_count}[/{THEME.Colors.info}]")
    if last_used:
        lines.append(f"  [{THEME.TextStyles.label}]last used:[/{THEME.TextStyles.label}] [{THEME.TextStyles.dim}]{escape(last_used)}[/{THEME.TextStyles.dim}]")
    return Panel(
        "\n".join(lines) if lines else f"  [{THEME.TextStyles.dim}]no details[/{THEME.TextStyles.dim}]",
        title=f"{icon}[{THEME.Colors.skill}] {escape(name)}[/{THEME.Colors.skill}]",
        border_style=THEME.Borders.success if enabled else THEME.panel_border,
        padding=(1, 2),
    )


def agent_monitor_card(
    agents: List[Dict[str, Any]],
) -> Panel:
    """Multi-agent status dashboard showing all agents in a compact grid."""
    from rich.table import Table
    table = Table(box=None, show_header=True, header_style=THEME.TextStyles.label, padding=(0, 2))
    table.add_column("Agent", style=THEME.Colors.agent, no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Task", style=THEME.TextStyles.dim)
    table.add_column("Duration", style=THEME.TextStyles.caption)
    table.add_column("Actions", style=THEME.TextStyles.dim)

    for a in agents:
        name = a.get("persona", a.get("name", "?"))[:20]
        status = a.get("status", "idle")
        sc = THEME.agent_states.get(status, THEME.Colors.muted)
        status_dot = "●" if status in ("running", "thinking", "planning") else "○"
        task = a.get("task", "")[:40]
        dur = a.get("duration_ms")
        dur_str = f"{dur}ms" if dur else ""
        actions = a.get("actions", 0)
        actions_str = f"{actions} acts" if actions else ""

        table.add_row(
            name,
            f"[{sc}]{status_dot} {status}[/{sc}]",
            task,
            f"[{THEME.TextStyles.caption}]{dur_str}[/{THEME.TextStyles.caption}]",
            f"[{THEME.TextStyles.caption}]{actions_str}[/{THEME.TextStyles.caption}]",
        )

    return Panel(
        table,
        title=f"[{THEME.Colors.agent}]🤖 Agent Monitor ({len(agents)} active)[/{THEME.Colors.agent}]",
        border_style=THEME.Borders.agent,
        padding=(1, 1),
    )


def provider_dashboard_card(
    providers: List[Dict[str, Any]],
) -> Panel:
    """Provider status dashboard showing all providers with health."""
    from rich.table import Table
    table = Table(box=None, show_header=True, header_style=THEME.TextStyles.label, padding=(0, 2))
    table.add_column("Provider", style=THEME.Colors.info, no_wrap=True)
    table.add_column("Model", style=THEME.Colors.bright_white)
    table.add_column("Status", no_wrap=True)
    table.add_column("Context", style=THEME.TextStyles.caption)
    table.add_column("Speed", style=THEME.TextStyles.caption)
    table.add_column("Active", no_wrap=True)

    for p in providers:
        name = p.get("name", "?")
        model = p.get("model", "—")
        status = p.get("status", "unknown")
        sc = THEME.Colors.success if status == "available" else THEME.Colors.muted
        ctx = p.get("context_length", "")
        ctx_str = f"{ctx:,}" if ctx else ""
        speed = p.get("speed_label", "")
        is_active = p.get("is_active", False)
        active_mark = f"[{THEME.Colors.success}]● active[/{THEME.Colors.success}]" if is_active else ""

        table.add_row(
            name,
            model[:30],
            f"[{sc}]{status}[/{sc}]",
            ctx_str,
            speed,
            active_mark,
        )

    return Panel(
        table,
        title=f"[{THEME.Colors.primary}]⚡ Provider Dashboard ({len(providers)} configured)[/{THEME.Colors.primary}]",
        border_style=THEME.Borders.primary,
        padding=(1, 1),
    )


def forge_card(
    name: str,
    status: str = "inactive",
    description: str = "",
    last_run: Optional[str] = None,
    improvements: int = 0,
) -> Panel:
    """Forge/evolution subsystem status card."""
    status_color = THEME.Colors.success if status == "active" else THEME.Colors.muted
    dot = f"[{status_color}]●[/{status_color}]" if status == "active" else f"[{THEME.Colors.muted}]○[/{THEME.Colors.muted}]"

    lines = []
    if description:
        lines.append(f"  [{THEME.TextStyles.dim}]{escape(description[:100])}[/{THEME.TextStyles.dim}]")
    if last_run:
        lines.append(f"  [{THEME.TextStyles.label}]last run:[/{THEME.TextStyles.label}] [{THEME.TextStyles.dim}]{escape(last_run)}[/{THEME.TextStyles.dim}]")
    if improvements > 0:
        lines.append(f"  [{THEME.TextStyles.label}]improvements:[/{THEME.TextStyles.label}] [{THEME.Colors.success}]{improvements}[/{THEME.Colors.success}]")
    if not lines:
        lines.append(f"  [{status_color}]{status}[/{status_color}]")

    return Panel(
        "\n".join(lines),
        title=f"{dot}[{THEME.Colors.skill}] {escape(name)}[/{THEME.Colors.skill}]",
        border_style=THEME.Borders.success if status == "active" else THEME.panel_border,
        subtitle=f"[{THEME.TextStyles.caption}]evolution[/{THEME.TextStyles.caption}]" if status == "active" else None,
        padding=(1, 2),
    )


def config_card(
    category: str,
    items: List[Tuple[str, str, str]],
    border_style: str = "grey50",
) -> Panel:
    """Configuration panel with colored key/value pairs.
    
    Args:
        category: Panel title
        items: List of (key, value, value_style) tuples
        border_style: Panel border style
    """
    lines = []
    for key, val, style in items:
        val_str = escape(str(val) if val else "—")
        lines.append(f"  [{THEME.TextStyles.label}]{escape(key)}:[/{THEME.TextStyles.label}] [{style}]{val_str}[/{style}]")
    return Panel(
        "\n".join(lines),
        title=f"[bold]{escape(category)}[/bold]",
        border_style=border_style,
        padding=(1, 2),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Tool Detail Panel — expandable inline detail for any tool call
# ═══════════════════════════════════════════════════════════════════════════════

def _fmt_duration(ms: Optional[float], as_markup: bool = False) -> str:
    if ms is None:
        return ""
    if as_markup:
        if ms < 1000:
            return f"[{THEME.TextStyles.duration}]{ms:.0f}ms[/{THEME.TextStyles.duration}]"
        return f"[{THEME.TextStyles.duration}]{ms/1000:.1f}s[/{THEME.TextStyles.duration}]"
    if ms < 1000:
        return f"{ms:.0f}ms"
    return f"{ms/1000:.1f}s"


def _fmt_time(ts: Optional[float]) -> str:
    if ts is None:
        return "—"
    import datetime
    return datetime.datetime.fromtimestamp(ts).strftime("%H:%M:%S")


def _safe(val: Any, maxlen: int = 2000) -> str:
    s = str(val) if val is not None else ""
    if len(s) > maxlen:
        s = s[:maxlen] + f"… ({len(s)} chars total)"
    return escape(s)


def _wrap_lines(label: str, content: str, max_lines: int = 20) -> list[str]:
    lines = content.split("\n")
    result = []
    for i, line in enumerate(lines[:max_lines]):
        result.append(f"  [{THEME.TextStyles.dim}]{escape(line[:300])}[/{THEME.TextStyles.dim}]")
    if len(lines) > max_lines:
        result.append(f"  [{THEME.TextStyles.caption}]… {len(lines) - max_lines} more lines ({len(content)} chars)[/{THEME.TextStyles.caption}]")
    return result


def _metadata_row(key: str, value: str, val_style: str = "white") -> str:
    return f"  [{THEME.TextStyles.label}]{escape(key)}:[/{THEME.TextStyles.label}] [{val_style}]{escape(value)}[/{val_style}]"


def tool_detail_panel(tool: dict) -> Panel:
    """Render a bordered detail panel for any tool event.

    Normalizes all tool event shapes (web_search, command, file_ops,
    git, sub-agent, etc.) into a common detail layout with tool-specific
    metadata rendered intelligently.
    """
    name = tool.get("name", tool.get("kind", tool.get("type", "tool")))
    kind = tool.get("kind", tool.get("type", ""))
    status = tool.get("status", "running")
    sc = THEME.status_colors.get(status, THEME.Colors.muted)
    icon = THEME.kind_icons.get(kind, THEME.kind_icons.get(name, "🔧"))
    duration_ms = tool.get("duration_ms") or tool.get("duration")
    started_at = tool.get("started_at") or tool.get("startedAt")
    ended_at = tool.get("ended_at") or tool.get("endedAt")
    error = tool.get("error") or tool.get("error_message")
    retry_count = tool.get("retry_count") or tool.get("retryCount", 0)

    lines = []
    meta_lines = []

    meta_lines.append(_metadata_row("Tool", f"{icon} {name}"))
    if kind and kind != name:
        meta_lines.append(_metadata_row("Type", kind))
    meta_lines.append(_metadata_row("Status", status, sc))
    if started_at:
        meta_lines.append(_metadata_row("Started", _fmt_time(started_at)))
    if ended_at:
        meta_lines.append(_metadata_row("Ended", _fmt_time(ended_at)))
    if duration_ms is not None:
        meta_lines.append(_metadata_row("Duration", _fmt_duration(duration_ms), THEME.TextStyles.duration))
    if retry_count > 0:
        meta_lines.append(_metadata_row("Retries", str(retry_count), THEME.Colors.warning))

    # ── Tool-specific rendering ────────────────────────────────────────────
    kind_lower = kind.lower()

    # Web Search / Search
    if kind_lower in ("search", "web", "web_search"):
        query = tool.get("query") or tool.get("target") or tool.get("args", "")
        urls = tool.get("urls") or tool.get("sources") or tool.get("results_urls", [])
        response = tool.get("response") or tool.get("output") or tool.get("result", "")
        sources_text = tool.get("sources_text") or tool.get("response_text", "")

        if query:
            lines.append(_metadata_row("Query", _safe(query, 500)))
        if urls and isinstance(urls, list):
            lines.append(f"  [{THEME.TextStyles.label}]Sources:[/{THEME.TextStyles.label}]")
            for i, url in enumerate(urls[:10]):
                lines.append(f"    [{THEME.TextStyles.dim}]{i+1}. {_safe(url, 200)}[/{THEME.TextStyles.dim}]")
            if len(urls) > 10:
                lines.append(f"    [{THEME.TextStyles.caption}]… {len(urls) - 10} more[/{THEME.TextStyles.caption}]")
        if sources_text:
            lines.append(f"  [{THEME.TextStyles.label}]Content:[/{THEME.TextStyles.label}]")
            lines.extend(_wrap_lines("Content", sources_text))
        if response:
            lines.append(f"  [{THEME.TextStyles.label}]Response:[/{THEME.TextStyles.label}]")
            lines.extend(_wrap_lines("Response", response))

    # Shell / Command / Bash / Terminal
    elif kind_lower in ("command", "bash", "terminal", "shell"):
        command = tool.get("command") or tool.get("target") or tool.get("args", "")
        cwd = tool.get("cwd") or tool.get("workdir", "")
        stdout_val = tool.get("stdout") or tool.get("output", "")
        stderr_val = tool.get("stderr", "")
        exit_code = tool.get("exit_code") or tool.get("exitCode")

        if command:
            lines.append(f"  [{THEME.Colors.bright_white}]$ {_safe(command, 1000)}[/{THEME.Colors.bright_white}]")
        if cwd:
            lines.append(_metadata_row("cwd", cwd, THEME.TextStyles.path))
        if exit_code is not None:
            ec_color = THEME.Colors.success if exit_code == 0 else THEME.Colors.error
            lines.append(_metadata_row("Exit code", str(exit_code), ec_color))
        if stdout_val:
            lines.append(f"  [{THEME.TextStyles.label}]stdout:[/{THEME.TextStyles.label}]")
            lines.extend(_wrap_lines("stdout", stdout_val))
        if stderr_val:
            lines.append(f"  [{THEME.TextStyles.error}]stderr:[/{THEME.TextStyles.error}]")
            lines.extend(_wrap_lines("stderr", stderr_val))

    # File operations: Read / Write / Edit / Create / Delete
    elif kind_lower in ("file", "read", "edit", "creating", "modifying", "deleting", "file_ops"):
        path = tool.get("path") or tool.get("target") or tool.get("file_path", "")
        action = tool.get("action") or tool.get("file_action") or kind
        content = tool.get("content") or tool.get("new_string", "")
        old_string = tool.get("old_string", "")
        diff = tool.get("diff") or tool.get("diff_text", "")
        summary = tool.get("summary", "")
        preview = tool.get("preview") or tool.get("output", "")

        if path:
            lines.append(_metadata_row("Path", path, THEME.TextStyles.path))
        if action:
            lines.append(_metadata_row("Action", action))
        if summary:
            lines.append(_metadata_row("Summary", _safe(summary, 500)))
        if old_string and content:
            lines.append(f"  [{THEME.TextStyles.label}]Edit:[/{THEME.TextStyles.label}]")
            lines.append(f"    [{THEME.TextStyles.dim}]old: {_safe(old_string, 300)}[/{THEME.TextStyles.dim}]")
            lines.append(f"    [{THEME.TextStyles.dim}]new: {_safe(content, 300)}[/{THEME.TextStyles.dim}]")
        if diff:
            lines.append(f"  [{THEME.TextStyles.label}]Diff:[/{THEME.TextStyles.label}]")
            lines.extend(_wrap_lines("diff", diff[:2000]))
        elif preview:
            lines.append(f"  [{THEME.TextStyles.label}]Content:[/{THEME.TextStyles.label}]")
            lines.extend(_wrap_lines("content", preview))

    # Git operations
    elif kind_lower in ("git", "git_ops"):
        command = tool.get("command") or tool.get("target") or tool.get("args", "")
        action = tool.get("action", "")
        branch = tool.get("branch", "")
        changes = tool.get("changes") or tool.get("changed_files", [])
        output = tool.get("output") or tool.get("result", "")

        if action:
            lines.append(_metadata_row("Action", action))
        if command:
            lines.append(f"  [{THEME.Colors.bright_white}]$ git {_safe(command, 500)}[/{THEME.Colors.bright_white}]")
        if branch:
            lines.append(_metadata_row("Branch", branch))
        if changes and isinstance(changes, list):
            lines.append(f"  [{THEME.TextStyles.label}]Changed files ({len(changes)}):[/{THEME.TextStyles.label}]")
            for f in changes[:15]:
                fname = f if isinstance(f, str) else f.get("path", str(f))
                lines.append(f"    [{THEME.TextStyles.dim}]{_safe(fname, 200)}[/{THEME.TextStyles.dim}]")
            if len(changes) > 15:
                lines.append(f"    [{THEME.TextStyles.caption}]… {len(changes) - 15} more[/{THEME.TextStyles.caption}]")
        if output:
            lines.append(f"  [{THEME.TextStyles.label}]Output:[/{THEME.TextStyles.label}]")
            lines.extend(_wrap_lines("output", output))

    # Build / Test
    elif kind_lower in ("build", "test", "test_runner"):
        command = tool.get("command") or tool.get("target") or tool.get("args", "")
        framework = tool.get("framework", "")
        result = tool.get("result") or tool.get("output", "")
        failed = tool.get("failed") or tool.get("failures", [])
        passed = tool.get("passed", 0)
        total = tool.get("total", 0)

        if command:
            lines.append(f"  [{THEME.Colors.bright_white}]$ {_safe(command, 500)}[/{THEME.Colors.bright_white}]")
        if framework:
            lines.append(_metadata_row("Framework", framework))
        if total:
            passed_str = f"{passed}/{total}"
            pcolor = THEME.Colors.success if passed == total else THEME.Colors.warning
            lines.append(_metadata_row("Tests", passed_str, pcolor))
        if failed and isinstance(failed, list):
            lines.append(f"  [{THEME.TextStyles.error}]Failed tests ({len(failed)}):[/{THEME.TextStyles.error}]")
            for ft in failed[:10]:
                ft_name = ft if isinstance(ft, str) else ft.get("name", str(ft))
                lines.append(f"    [{THEME.TextStyles.error}]✗ {_safe(ft_name, 200)}[/{THEME.TextStyles.error}]")
        if result:
            lines.append(f"  [{THEME.TextStyles.label}]Output:[/{THEME.TextStyles.label}]")
            lines.extend(_wrap_lines("output", result))

    # Sub-agent / Hive
    elif kind_lower in ("subagent", "hive", "agent"):
        agent_name = tool.get("agent_name") or tool.get("persona") or tool.get("action", "")
        task = tool.get("task") or tool.get("target", "")
        result = tool.get("result") or tool.get("output", "")
        agent_id = tool.get("agent_id") or tool.get("id", "")

        if agent_name:
            lines.append(_metadata_row("Agent", agent_name, THEME.Colors.agent))
        if agent_id:
            lines.append(_metadata_row("ID", agent_id[:20], THEME.TextStyles.dim))
        if task:
            lines.append(_metadata_row("Task", _safe(task, 500)))
        if result:
            lines.append(f"  [{THEME.TextStyles.label}]Result:[/{THEME.TextStyles.label}]")
            lines.extend(_wrap_lines("result", result))

    # MCP / Plugin
    elif kind_lower in ("mcp", "plugin"):
        server = tool.get("server") or tool.get("mcp_server", "")
        plugin_name = tool.get("plugin_name") or tool.get("plugin", "")
        tool_name = tool.get("tool_name") or tool.get("mcp_tool", "")
        args = tool.get("arguments") or tool.get("args", {})
        result = tool.get("result") or tool.get("output", "")

        if server:
            lines.append(_metadata_row("MCP Server", server))
        if plugin_name:
            lines.append(_metadata_row("Plugin", plugin_name))
        if tool_name:
            lines.append(_metadata_row("Tool", tool_name))
        if args:
            args_str = str(args) if isinstance(args, str) else str(args)
            lines.append(_metadata_row("Arguments", _safe(args_str, 500)))
        if result:
            lines.append(f"  [{THEME.TextStyles.label}]Result:[/{THEME.TextStyles.label}]")
            lines.extend(_wrap_lines("result", result))

    # Generic tool / default
    else:
        args = tool.get("args") or tool.get("arguments") or tool.get("parameters") or tool.get("input", "")
        result = tool.get("result") or tool.get("output") or tool.get("response", "")
        target = tool.get("target", "")
        action = tool.get("action", "")

        if action:
            lines.append(_metadata_row("Action", action))
        if target:
            lines.append(_metadata_row("Target", _safe(target, 500)))
        if args:
            args_str = str(args) if isinstance(args, str) else str(args)
            lines.append(_metadata_row("Arguments", _safe(args_str, 1000)))
        if result:
            lines.append(f"  [{THEME.TextStyles.label}]Output:[/{THEME.TextStyles.label}]")
            lines.extend(_wrap_lines("output", result))

    # ── Error block (always shown if present) ──────────────────────────────
    if error:
        err_text = str(error)
        if isinstance(error, dict):
            err_text = error.get("message", str(error))
        lines.append(f"")
        lines.append(f"  [{THEME.TextStyles.error}]── Error ──────────────────────[/{THEME.TextStyles.error}]")
        lines.append(f"  [{THEME.TextStyles.error}]❌ {_safe(err_text, 2000)}[/{THEME.TextStyles.error}]")
        traceback_val = tool.get("traceback") or (error.get("traceback", "") if isinstance(error, dict) else "")
        if traceback_val:
            lines.extend(_wrap_lines("traceback", str(traceback_val), max_lines=10))

    # ── AI model info (token/cost/model) ───────────────────────────────────
    model = tool.get("model") or tool.get("llm_model", "")
    tokens_in = tool.get("tokens_in") or tool.get("prompt_tokens") or tool.get("input_tokens")
    tokens_out = tool.get("tokens_out") or tool.get("completion_tokens") or tool.get("output_tokens")
    cost = tool.get("cost") or tool.get("estimated_cost")
    if model or tokens_in is not None or cost is not None:
        meta_lines.append(f"")
        ai_parts = []
        if model:
            ai_parts.append(f"model: {model}")
        if tokens_in is not None:
            ai_parts.append(f"in: {tokens_in}")
        if tokens_out is not None:
            ai_parts.append(f"out: {tokens_out}")
        if cost:
            ai_parts.append(f"cost: ${cost}")
        meta_lines.append(f"  [{THEME.TextStyles.label}]AI:[/{THEME.TextStyles.label}] [{THEME.TextStyles.dim}]{' · '.join(ai_parts)}[/{THEME.TextStyles.dim}]")

    # ── Assemble ───────────────────────────────────────────────────────────
    all_lines = meta_lines
    if lines:
        all_lines.append(f"")
        all_lines.extend(lines)

    status_color = THEME.status_colors.get(status, THEME.Colors.muted)
    border = THEME.Panels.tool_border_style if status != "error" else THEME.Panels.error_border_style
    subtitle = f"[{status_color}]{status}[/{status_color}]"
    if duration_ms is not None:
        subtitle += f" · {_fmt_duration(duration_ms)}"

    return Panel(
        "\n".join(all_lines) if all_lines else f"  [{THEME.TextStyles.dim}]no details available[/{THEME.TextStyles.dim}]",
        title=f"{icon}[{THEME.Panels.tool_title}] {name} Details[/{THEME.Panels.tool_title}]",
        border_style=border,
        subtitle=subtitle,
        padding=(1, 2),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Tool Row (compact one-line representation for tool lists)
# ═══════════════════════════════════════════════════════════════════════════════

def tool_row(tool: dict, selected: bool = False, expanded: bool = False) -> str:
    """Compact one-line tool row for interactive lists.

    Collapsed:  ▸ Web Search   success   "query here"   2.8s
    Expanded:   ▾ Web Search   success   "query here"   2.8s
    """
    name = tool.get("name", tool.get("kind", tool.get("type", "tool")))
    status = tool.get("status", "running")
    sc = THEME.status_colors.get(status, THEME.Colors.muted)
    icon = THEME.kind_icons.get(name.lower(), THEME.kind_icons.get(name, "🔧"))
    duration_ms = tool.get("duration_ms") or tool.get("duration")

    # Build summary text
    summary = ""
    kind_lower = name.lower()

    # Web search
    if kind_lower in ("search", "web", "web_search"):
        summary = tool.get("query", tool.get("target", tool.get("args", "")))
    # Shell/command
    elif kind_lower in ("command", "bash", "terminal", "shell"):
        summary = tool.get("command", tool.get("target", tool.get("args", "")))
    # File ops
    elif kind_lower in ("file", "read", "edit", "creating", "modifying", "deleting"):
        summary = tool.get("path", tool.get("target", ""))
    # Git
    elif kind_lower in ("git", "git_ops"):
        action = tool.get("action", "")
        target = tool.get("target", tool.get("command", ""))
        summary = f"{action}: {target}" if action else target
    # Test/build
    elif kind_lower in ("test", "build", "test_runner"):
        summary = tool.get("target", tool.get("command", ""))
    # Sub-agent
    elif kind_lower in ("subagent", "hive", "agent"):
        summary = tool.get("persona", tool.get("task", tool.get("action", "")))
    # Generic
    else:
        summary = tool.get("target", tool.get("args", tool.get("action", "")))

    summary_str = _safe(summary, 120) if summary else ""
    dur_str = _fmt_duration(duration_ms, as_markup=True) if duration_ms is not None else ""
    prefix = "▾" if expanded else "▸"
    sel_marker = "▸" if selected else " "
    style = THEME.Colors.bright_white if selected else THEME.Colors.muted

    parts = [f"[{style}]{sel_marker} {prefix}[/{style}]", f"[{style}]{icon}[/{style}]", f"[{sc}]{name}[/{sc}]", f"[{style}]{summary_str}[/{style}]"]
    if dur_str:
        parts.append(dur_str)
    return "  ".join(parts)


def turn_separator(turn_number: int, width: int = 80) -> Panel:
    """Turn separator with turn number centered."""
    sep = THEME.Icons.separator
    label = f" turn {turn_number} "
    side = (width - len(label)) // 2
    line = sep * max(2, side)
    return Panel(
        f"[{THEME.TextStyles.dim}]{line}{label}{line}[/{THEME.TextStyles.dim}]",
        border_style=THEME.Borders.muted,
        padding=(0, 0),
    )