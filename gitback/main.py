import os
import sys
import json
import argparse
import subprocess

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt, Confirm

console = Console()

from .backup_script import run_backup, ensure_auth, GLAB_CMD, get_github_user
from .verify_backups import main as verify_main

def run_status_check():
    ensure_auth()
    console.print("\n[bold cyan]Checking System Status & Credentials...[/bold cyan]\n")
    
    gh_user = get_github_user()
    
    # Check GitLab CLI & User
    try:
        res = subprocess.run([GLAB_CMD, "api", "user"], capture_output=True, text=True, encoding="utf-8", errors="replace")
        if res.returncode == 0 and res.stdout.strip():
            glab_user = json.loads(res.stdout.strip()).get("username", "Unknown")
        else:
            glab_user = "[red]Not Authenticated[/red]"
    except Exception:
        glab_user = "[red]CLI Not Found[/red]"
        
    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    backup_dir = os.path.join(script_dir, "repos")
    local_mirrors_count = len([f for f in os.listdir(backup_dir) if f.endswith(".git")]) if os.path.exists(backup_dir) else 0

    table = Table(title="GITBACK Environment Overview", border_style="cyan")
    table.add_column("Component", style="yellow")
    table.add_column("Status / Info", style="white")

    table.add_row("GitHub User", f"[green]{gh_user}[/green]")
    table.add_row("GitLab User", f"[green]{glab_user}[/green]" if not glab_user.startswith("[red]") else glab_user)
    table.add_row("GitLab CLI Path", GLAB_CMD)
    table.add_row("Local Mirrors Folder", backup_dir)
    table.add_row("Mirrors Cached Locally", f"[bold cyan]{local_mirrors_count}[/bold cyan] repositories")

    console.print(table)
    console.print()

def interactive_menu():
    while True:
        console.print(Panel.fit(
            "[bold cyan]GITBACK - GitHub to GitLab Backup & Sync Tool[/bold cyan]\n"
            "[dim]Manage, backup, and verify your repository mirrors easily.[/dim]",
            border_style="cyan"
        ))

        console.print("[bold yellow]Please select an action:[/bold yellow]")
        console.print("  [cyan]1.[/cyan] Run Full Backup (GitHub -> GitLab)")

        console.print("  [cyan]2.[/cyan] Run Targeted Backup (Specific repositories)")
        console.print("  [cyan]d.[/cyan] Run Direct Import Backup (GitHub -> GitLab API)")

        console.print("  [cyan]3.[/cyan] Verify Backups & Sync Missing Repos")
        console.print("  [cyan]4.[/cyan] Quick Status Check")
        console.print("  [cyan]5.[/cyan] Exit\n")

        choice = Prompt.ask("Enter choice", choices=["1", "2", "d", "3", "4", "5"], default="1")

        if choice == "1":
            console.print("\n[bold cyan]Starting full repository backup...[/bold cyan]\n")
            run_backup(direct_import=args.direct, ignore_network=args.ignore_network)

        elif choice == "d":
            console.print("\n[bold cyan]Starting direct import backup (no local download)...[/bold cyan]\n")
            run_backup(direct_import=True, ignore_network=True)
        elif choice == "2":
            repos_input = Prompt.ask("\nEnter repository names separated by space (e.g. repo1 repo2)")
            repos_list = [r.strip() for r in repos_input.split() if r.strip()]
            if repos_list:
                console.print(f"\n[bold cyan]Starting targeted backup for {len(repos_list)} repositories...[/bold cyan]\n")
                run_backup(target_repos=repos_list, direct_import=args.direct, ignore_network=args.ignore_network)
            else:
                console.print("[yellow]No repository names entered.[/yellow]\n")
        elif choice == "3":
            console.print("\n[bold cyan]Starting backup verification...[/bold cyan]\n")
            auto_fix = Confirm.ask("Automatically back up any missing repos or releases found?", default=True)
            sys.argv = [sys.argv[0]] + (["-y"] if auto_fix else [])
            verify_main()
        elif choice == "4":
            run_status_check()
        elif choice == "5":
            console.print("[green]Goodbye![/green]")
            break

        if not Confirm.ask("\nPerform another action?", default=False):
            console.print("[green]Goodbye![/green]")
            break

def main():
    parser = argparse.ArgumentParser(
        description="GITBACK - Easy GitHub to GitLab Backup & Verification CLI",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("-b", "--backup", action="store_true", help="Run backup process for GitHub repositories to GitLab")
    parser.add_argument("-r", "--repos", nargs="*", help="Specific repository names to target for backup")
    parser.add_argument("-v", "--verify", action="store_true", help="Run verification report comparing GitHub and GitLab")
    parser.add_argument("-y", "--yes", action="store_true", help="Auto-confirm backing up missing repos when verifying")
    parser.add_argument("-s", "--status", action="store_true", help="Display system authentication and local cache status")
    parser.add_argument("-d", "--direct", action="store_true", help="Direct import from GitHub to GitLab without downloading locally")
    parser.add_argument("--ignore-network", action="store_true", help="Ignore network check (allow running on 4G)")


    args = parser.parse_args()

    # If any specific command flag is passed, execute command non-interactively
    if args.status:
        run_status_check()
    elif args.verify:
        new_args = [sys.argv[0]]
        if args.yes: new_args.append("-y")
        if args.direct: new_args.append("-d")
        if args.ignore_network: new_args.append("--ignore-network")
        sys.argv = new_args
        verify_main()
    elif args.backup or args.repos:
        run_backup(target_repos=args.repos if args.repos else None, direct_import=args.direct, ignore_network=args.ignore_network)
    else:
        # Fallback to interactive mode
        interactive_menu()

if __name__ == "__main__":
    main()
