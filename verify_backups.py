import os
import sys
import json
import subprocess
import argparse

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

import shutil
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.panel import Panel

console = Console()

def get_glab_cmd():
    glab_in_path = shutil.which("glab")
    if glab_in_path:
        return glab_in_path
    default_path = r"C:\Users\Roset\AppData\Local\Programs\glab\glab.exe"
    if os.path.exists(default_path):
        return default_path
    return "glab"

GLAB_CMD = get_glab_cmd()

def get_github_user():
    try:
        res = subprocess.run(["gh", "api", "user", "-q", ".login"], capture_output=True, text=True, encoding="utf-8", errors="replace")
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass
    return "pheonix14"

def ensure_auth():
    if "GITHUB_TOKEN" in os.environ:
        del os.environ["GITHUB_TOKEN"]
    try:
        user = get_github_user()
        subprocess.run(["gh", "auth", "switch", "-u", user], capture_output=True)
    except Exception:
        pass

def run_cmd(cmd, check=False):
    try:
        res = subprocess.run(cmd, check=check, capture_output=True, text=True, encoding="utf-8", errors="replace")
        return res.stdout.strip() if res.stdout else ""
    except Exception:
        return ""

def sanitize_glab_name(name):
    """GitLab strictly forbids repo names starting/ending with hyphens, dots, or underscores, or having sequential hyphens."""
    import re
    sanitized = re.sub(r'[-._]+', '-', name).strip("-._").lower()
    return sanitized if sanitized else "repo-backup"

def get_all_glab_releases(glab_user, glab_repo_name):
    releases = []
    page = 1
    while True:
        res_json = run_cmd([GLAB_CMD, "api", f"/projects/{glab_user}%2F{glab_repo_name}/releases?per_page=100&page={page}"])
        if not res_json or "404" in res_json:
            break
        try:
            data = json.loads(res_json)
            if not isinstance(data, list) or not data:
                break
            releases.extend(data)
            if len(data) < 100:
                break
            page += 1
        except Exception:
            break
    return [r.get("tag_name") for r in releases if isinstance(r, dict) and "tag_name" in r]

def main():
    parser = argparse.ArgumentParser(description="GitBack Verification Script")

    parser.add_argument("-y", "--yes", action="store_true", help="Automatically confirm backing up missing repositories")
    parser.add_argument("-d", "--direct", action="store_true", help="Use direct import for fixing missing backups")
    parser.add_argument("--ignore-network", action="store_true", help="Ignore network limits")

    args = parser.parse_args()

    ensure_auth()
    console.print(Panel.fit("[bold cyan]GitBack Verifier[/bold cyan]\nVerifying that all repositories and releases are backed up to GitLab.", border_style="cyan"))
    
    # 1. Get Github User
    gh_user_output = run_cmd(["gh", "api", "user", "-q", ".login"])
    if not gh_user_output:
        console.print("[red]Error: Could not get GitHub user. Make sure you are authenticated with `gh auth login`.[/red]")
        sys.exit(1)
    github_user = gh_user_output.strip()

    # 2. Get GitLab User
    glab_user_output = run_cmd([GLAB_CMD, "api", "user"])
    if not glab_user_output:
        console.print("[red]Error: Could not get GitLab user. Make sure you are authenticated with `glab auth login`.[/red]")
        sys.exit(1)
    
    try:
        glab_user = json.loads(glab_user_output)["username"]
    except:
        console.print("[red]Error: Failed to parse GitLab user.[/red]")
        sys.exit(1)

    console.print(f"[green][OK][/green] Authenticated as GitHub: [bold]{github_user}[/] | GitLab: [bold]{glab_user}[/]")
    
    # 3. Get all Github repos
    console.print("Fetching list of all GitHub repositories...")
    gh_repos_json = run_cmd(["gh", "repo", "list", github_user, "--json", "name", "--limit", "1000"])
    
    if not gh_repos_json:
        console.print("[red]No repositories found or failed to fetch.[/red]")
        sys.exit(1)
        
    repos = json.loads(gh_repos_json)
    
    table = Table(title="Backup Verification Report")
    table.add_column("Repository", justify="left", style="cyan")
    table.add_column("Code Backup", justify="center")
    table.add_column("Releases Synced", justify="center")
    
    missing_repos = []
    missing_releases_dict = {}

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("[cyan]Verifying backups...", total=len(repos))
        
        for repo in repos:
            name = repo["name"]
            progress.update(task, description=f"[cyan]Verifying {name}...")
            
            glab_repo_name = sanitize_glab_name(name)
            
            # Check if repo exists on GitLab
            glab_repo_check = run_cmd([GLAB_CMD, "api", f"/projects/{glab_user}%2F{glab_repo_name}"])
            if "message" in glab_repo_check and "404" in glab_repo_check:
                repo_status = "[red][MISSING][/red]"
                missing_repos.append(name)
                release_status = "-"
            else:
                repo_status = "[green][SYNCED][/green]"
                
                # Check Releases
                gh_releases_json = run_cmd(["gh", "release", "list", "-R", f"{github_user}/{name}", "--json", "tagName", "--limit", "1000"])
                if gh_releases_json:
                    gh_releases = json.loads(gh_releases_json)
                    if gh_releases:
                        gh_tags = [r["tagName"] for r in gh_releases]
                        glab_tags = get_all_glab_releases(glab_user, glab_repo_name)
                            
                        missing_tags = [t for t in gh_tags if t not in glab_tags]
                        
                        if missing_tags:
                            release_status = f"[red][MISSING {len(missing_tags)}/{len(gh_tags)}][/red]"
                            missing_releases_dict[name] = missing_tags
                        else:
                            release_status = f"[green][SYNCED {len(gh_tags)}/{len(gh_tags)}][/green]"
                    else:
                        release_status = "[dim]No Releases[/dim]"
                else:
                    release_status = "[dim]No Releases[/dim]"
                    
            table.add_row(name, repo_status, release_status)
            progress.advance(task)

    console.print(table)
    
    if missing_repos or missing_releases_dict:
        console.print("\n[bold red]Action Required:[/bold red]")
        if missing_repos:
            console.print(f" - The following {len(missing_repos)} repositories are NOT backed up to GitLab:")
            for m in missing_repos:
                console.print(f"   - {m}")
        if missing_releases_dict:
            console.print(" - The following repositories have missing releases on GitLab:")
            for m, tags in missing_releases_dict.items():
                console.print(f"   - {m}: Missing {', '.join(tags)}")
                
        target_repos = sorted(list(set(missing_repos + list(missing_releases_dict.keys()))))
        console.print(f"\n[yellow]Found {len(target_repos)} repositories requiring backup/sync: {', '.join(target_repos)}[/yellow]")
        
        do_backup = False
        if args.yes:
            do_backup = True
        else:
            try:
                answer = input(f"\nDo you want to back up these {len(target_repos)} specific repositories now? (y/N): ").strip().lower()
                if answer in ("y", "yes"):
                    do_backup = True
            except (EOFError, KeyboardInterrupt):
                do_backup = False
                
        if do_backup:
            console.print("\n[bold cyan]Starting targeted backup for missing repositories/releases...[/bold cyan]\n")
            from backup_script import run_backup
            run_backup(target_repos=target_repos, direct_import=args.direct, ignore_network=args.ignore_network)
            console.print("\n[bold green]Targeted backup complete! Running re-verification...[/bold green]\n")
            subprocess.run([sys.executable, __file__, "--yes", "-d"] + (["--ignore-network"] if args.ignore_network else []))
        else:
            console.print("\n[yellow]Skipped targeted backup. You can run `python verify_backups.py -y` anytime to perform automated backup.[/yellow]")
    else:
        console.print("\n[bold green]Verification Complete! 100% of your code and releases are safely backed up on GitLab![/bold green]")

if __name__ == "__main__":
    main()

