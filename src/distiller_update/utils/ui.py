"""UI utilities for professional command-line output."""

from typing import Any

from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn
from rich.table import Table

# Global console instance for consistent output
console = Console()


def get_spinner(text: str, style: str = "cyan") -> Any:  # noqa: ANN401
    """Create a consistent spinner for status messages."""
    return console.status(f"[{style}]{text}[/{style}]", spinner="dots")


def show_step(message: str, success: bool = False, error: bool = False) -> None:
    """Show a step with appropriate indicator."""
    if success:
        console.print(f"[green]✓[/green] {message}")
    elif error:
        console.print(f"[red]✗[/red] {message}")
    else:
        console.print(f"[blue]→[/blue] {message}")


def format_package_table(packages: list[Any], show_size: bool = True) -> Table:
    """Format packages in a nice table."""
    table = Table(show_header=True, header_style="bold cyan")

    table.add_column("Package", style="white", no_wrap=True)
    table.add_column("Current", style="yellow")
    table.add_column("Available", style="green")
    if show_size:
        table.add_column("Size", style="cyan", justify="right")

    for pkg in packages:
        row = [
            pkg.name,
            pkg.current_version or "(new)",
            pkg.new_version,
        ]
        if show_size:
            row.append(pkg.display_size if hasattr(pkg, "display_size") else str(pkg.size))
        table.add_row(*row)

    return table


def get_progress_bar() -> Progress:
    """Get a consistent progress bar configuration."""
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    )


def format_time(seconds: float) -> str:
    """Format elapsed time in a human-readable way."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        minutes = seconds / 60
        return f"{minutes:.1f}m"
    else:
        hours = seconds / 3600
        return f"{hours:.1f}h"


class ProgressCallback:
    """Callback handler for progress updates."""

    def __init__(self, total_steps: int = 0) -> None:
        self.current_step = 0
        self.total_steps = total_steps
        self.progress: Progress | None = None
        self.task_id: Any = None

    def start(self, description: str = "Processing...") -> None:
        """Start the progress tracking."""
        if self.total_steps > 0:
            self.progress = get_progress_bar()
            self.progress.__enter__()
            self.task_id = self.progress.add_task(description, total=self.total_steps)

    def update(self, step_description: str | None = None, advance: int = 1) -> None:
        """Update progress."""
        if self.progress and self.task_id is not None:
            if step_description:
                self.progress.update(self.task_id, description=step_description)
            self.progress.update(self.task_id, advance=advance)
            self.current_step += advance

    def finish(self) -> None:
        """Finish progress tracking."""
        if self.progress:
            self.progress.__exit__(None, None, None)
            self.progress = None


def print_summary(message: str, style: str = "bold cyan") -> None:
    """Print a summary message with consistent styling."""
    console.print(f"\n[{style}]{message}[/{style}]\n")
