import subprocess
import re
import sys

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeElapsedColumn, TimeRemainingColumn

class BackupLogger:
    def __init__(self, total_repos):
        self.stats = {"success": 0, "failed": 0, "retries": 0, "total": total_repos}
        self.progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
        )
        self.total_repos = total_repos
        self.overall_task = self.progress.add_task(self.get_overall_desc(), total=total_repos)
        self.current_task = self.progress.add_task("[cyan]Initializing...", total=100)

    def get_overall_desc(self):
        return f"[bold blue]Total: {self.stats['total']}[/] | [bold green]Success: {self.stats['success']}[/] | [bold yellow]Retries: {self.stats['retries']}[/] | [bold red]Failed: {self.stats['failed']}[/]"

    def update_stats(self, status="success", retries_used=0):
        if status in self.stats:
            self.stats[status] += 1
        self.stats["retries"] += retries_used
        self.progress.update(self.overall_task, description=self.get_overall_desc())

    def __enter__(self):
        self.progress.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.progress.stop()

    def update_overall(self, advance=1):
        self.progress.update(self.overall_task, advance=advance)

    def log_info(self, message):
        self.progress.console.print(f"[green][i][/green] {message}")

    def log_warning(self, message):
        self.progress.console.print(f"[yellow][!][/yellow] {message}")

    def log_error(self, message):
        self.progress.console.print(f"[red][x][/red] {message}")

    def run_command(self, cmd, cwd=None, description="Running..."):
        """Runs a command with progress parsing."""
        self.progress.update(self.current_task, description=f"[cyan]{description}", completed=0)
        self.log_info(description)
        process = subprocess.Popen(
            cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0
        )
        buffer = b""
        percent_re = re.compile(rb'(\d+)%')
        
        output_log = []
        
        while True:
            char = process.stdout.read(1)
            if not char and process.poll() is not None:
                break
            if char in (b'\r', b'\n'):
                # parse buffer
                matches = percent_re.findall(buffer)
                if matches:
                    try:
                        percent = int(matches[-1])
                        self.progress.update(self.current_task, completed=percent)
                    except ValueError:
                        pass
                if buffer:
                    output_log.append(buffer.decode('utf-8', errors='replace'))
                buffer = b""
            else:
                buffer += char
                
        process.wait()
        if process.returncode == 0:
            self.progress.update(self.current_task, completed=100)
        return process.returncode, "\n".join(output_log)
