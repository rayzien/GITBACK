import os
import subprocess
import json
import sys
import argparse

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

import shutil
from .logger import BackupLogger

def get_glab_cmd():
    glab_in_path = shutil.which("glab")
    if glab_in_path:
        return glab_in_path
    default_path = r"C:\Users\Roset\AppData\Local\Programs\glab\glab.exe"
    if os.path.exists(default_path):
        return default_path
    return "glab"

GLAB_CMD = get_glab_cmd()


def get_github_token():
    try:
        res = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, encoding="utf-8", errors="replace")
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass
    return ""

def get_github_user():
    try:
        res = subprocess.run(["gh", "api", "user", "-q", ".login"], capture_output=True, text=True, encoding="utf-8", errors="replace")
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass
    return "pheonix14"


def check_network_allowed():
    try:
        res = subprocess.run(["getprop", "gsm.network.type"], capture_output=True, text=True)
        if res.returncode == 0:
            net_type = res.stdout.strip().upper()
            if "LTE" in net_type or "4G" in net_type:
                return False
    except Exception:
        pass
    return True

def ensure_auth():
    if "GITHUB_TOKEN" in os.environ:
        del os.environ["GITHUB_TOKEN"]
    try:
        user = get_github_user()
        subprocess.run(["gh", "auth", "switch", "-u", user], capture_output=True)
    except Exception:
        pass

def run_cmd(cmd, cwd=None, check=True, capture_output=True, retries=3):
    import time
    for attempt in range(retries):
        try:
            res = subprocess.run(cmd, cwd=cwd, check=check, capture_output=capture_output, text=True, encoding="utf-8", errors="replace")
            return res.stdout.strip() if res.stdout else ""
        except subprocess.CalledProcessError as e:
            err_msg = (e.stderr or "") + (e.output or "")
            if "no such host" in err_msg.lower() or "connection reset" in err_msg.lower() or "502" in err_msg or "503" in err_msg or "429" in err_msg:
                if attempt < retries - 1:
                    time.sleep(3)
                    continue
            if check:
                print(f"Error running command: {' '.join(cmd)}")
                print(f"Output: {e.output}")
                print(f"Error: {e.stderr}")
                sys.exit(1)
            return None
        except Exception:
            if attempt < retries - 1:
                time.sleep(3)
                continue
            return None


def sanitize_glab_name(name):
    """GitLab strictly forbids repo names starting/ending with hyphens, dots, or underscores, or having sequential hyphens."""
    import re
    sanitized = re.sub(r'[-._]+', '-', name).strip("-._").lower()
    return sanitized if sanitized else "repo-backup"

def check_gitlab_up_to_date(repo_path):
    """
    Verifies if all local branches (refs/heads/*) and tags (refs/tags/*)
    already exist on GitLab with matching commit SHAs.
    """
    local_refs_out = run_cmd(["git", "show-ref"], cwd=repo_path, check=False)
    if not local_refs_out:
        return True # empty local repo
        
    local_refs = {}
    for line in local_refs_out.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2:
            sha, ref = parts[0], parts[1]
            if ref.startswith("refs/heads/") or ref.startswith("refs/tags/"):
                local_refs[ref] = sha
                
    if not local_refs:
        return True
        
    remote_refs_out = run_cmd(["git", "ls-remote", "gitlab"], cwd=repo_path, check=False)
    if not remote_refs_out:
        return False # remote failed or empty
        
    remote_refs = {}
    for line in remote_refs_out.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2:
            sha, ref = parts[0], parts[1]
            remote_refs[ref] = sha
            
    for ref, sha in local_refs.items():
        if ref not in remote_refs or remote_refs[ref] != sha:
            return False
            
    return True

def get_glab_releases(glab_user, glab_repo_name):
    releases = []
    page = 1
    while True:
        res_json = run_cmd([GLAB_CMD, "api", f"/projects/{glab_user}%2F{glab_repo_name}/releases?per_page=100&page={page}"], check=False)
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

def ensure_gitlab_repo(glab_user, glab_repo_name, logger=None):
    glab_check = run_cmd([GLAB_CMD, "api", f"/projects/{glab_user}%2F{glab_repo_name}"], check=False)
    if glab_check and "message" in glab_check and "404" in glab_check:
        import time
        if logger:
            logger.log_info(f"Creating missing private GitLab repo: [bold]{glab_repo_name}[/bold]...")
        for attempt in range(5):
            res = subprocess.run([GLAB_CMD, "repo", "create", glab_repo_name, "--private"], capture_output=True, text=True, encoding="utf-8", errors="replace")
            if res.returncode == 0:
                return True
            if "429" in res.stderr or "too many times" in res.stderr.lower():
                if logger:
                    logger.log_warning(f"GitLab API rate limited when creating {glab_repo_name}. Retrying in 5 seconds (Attempt {attempt+1}/5)...")
                time.sleep(5)
            else:
                if logger:
                    logger.log_warning(f"GitLab repo create output for {glab_repo_name}: {res.stderr.strip() or res.stdout.strip()}")
                break
        return False
    return True

def migrate_releases(repo_name, github_user, glab_user, logger):
    import tempfile
    import shutil
    
    ensure_auth()

    if not ignore_network:
        if not check_network_allowed():
            print("Network detector: You are currently on 4G/LTE.")
            try:
                ans = input("Do you want to bypass this and use your mobile data anyway? (y/N): ")
                if ans.strip().lower() not in ['y', 'yes']:
                    print("Backup aborted to save data.")
                    sys.exit(0)
            except Exception:
                print("Backup aborted to save data.")
                sys.exit(0)

    
    # Fetch github releases
    try:
        releases_json = run_cmd(["gh", "release", "list", "-R", f"{github_user}/{repo_name}", "--json", "tagName,name", "--limit", "1000"], check=False)
        if not releases_json:
            return
        gh_releases = json.loads(releases_json)
    except Exception:
        return

    if not gh_releases:
        return

    # Fetch gitlab releases with pagination
    glab_repo_name = sanitize_glab_name(repo_name)
    glab_tags = get_glab_releases(glab_user, glab_repo_name)

    gh_tags = [r["tagName"] for r in gh_releases]
    already_exist = [t for t in gh_tags if t in glab_tags]
    missing = [t for t in gh_tags if t not in glab_tags]

    logger.log_info(f"Release versions found on GitHub for [bold]{repo_name}[/]: [cyan]{', '.join(gh_tags)}[/cyan]")
    if already_exist:
        logger.log_info(f"Release versions existing already on GitLab: [green]{', '.join(already_exist)}[/green] (Updated already / exists already)")
    
    if not missing:
        logger.log_info(f"All release versions for [bold]{repo_name}[/] exist already and updated already on GitLab.")
        return

    logger.log_info(f"Release versions to update/migrate to GitLab: [yellow]{', '.join(missing)}[/yellow]")

    for rel in gh_releases:
        tag = rel["tagName"]
        rel_name = rel.get("name", tag)
        if not rel_name:
            rel_name = tag
            
        if tag not in missing:
            continue
            
        logger.log_info(f"Updating missing Release version [bold]{tag}[/] for {repo_name}...")
        
        temp_dir = tempfile.mkdtemp()
        notes_file = os.path.join(temp_dir, "notes.md")
        
        try:
            # 1. Download assets (ignore errors if no assets exist)
            logger.run_command(["gh", "release", "download", tag, "-D", temp_dir, "-R", f"{github_user}/{repo_name}"], description=f"Downloading assets for {tag}")
            
            # 2. Get notes
            notes = run_cmd(["gh", "release", "view", tag, "--json", "body", "-q", ".body", "-R", f"{github_user}/{repo_name}"], check=False)
            with open(notes_file, "w", encoding="utf-8") as f:
                f.write(notes if notes else f"Release {tag}")
                
            # 3. Create on GitLab
            assets = [os.path.join(temp_dir, f) for f in os.listdir(temp_dir) if f != "notes.md"]
            glab_cmd = [GLAB_CMD, "release", "create", tag, "--name", rel_name, "--notes-file", notes_file, "-R", f"{glab_user}/{glab_repo_name}"] + assets
            
            code, out = logger.run_command(glab_cmd, description=f"Uploading release {tag}")
            if code == 0:
                logger.log_info(f"Release version [bold]{tag}[/] updated successfully on GitLab.")
            else:
                logger.log_warning(f"Failed to upload release {tag} to GitLab. (Ensure the git tag is pushed first)")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

def run_backup(target_repos=None, direct_import=False, ignore_network=False):
    ensure_auth()

    if not ignore_network:
        if not check_network_allowed():
            print("Network detector: You are currently on 4G/LTE.")
            try:
                ans = input("Do you want to bypass this and use your mobile data anyway? (y/N): ")
                if ans.strip().lower() not in ['y', 'yes']:
                    print("Backup aborted to save data.")
                    sys.exit(0)
            except Exception:
                print("Backup aborted to save data.")
                sys.exit(0)

    
    if subprocess.run(["gh", "--version"], capture_output=True).returncode != 0:
        print("Error: GitHub CLI (gh) is not installed or not found in PATH.")
        sys.exit(1)

    if subprocess.run([GLAB_CMD, "--version"], capture_output=True).returncode != 0:
        print("Error: GitLab CLI (glab) is not found at the expected path.")
        sys.exit(1)

    try:
        glab_user_json = run_cmd([GLAB_CMD, "api", "user"])
        glab_user = json.loads(glab_user_json)["username"]
    except Exception as e:
        print("Error getting GitLab user. Are you logged in? Run the login command first.")
        sys.exit(1)
        
    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    backup_dir = os.path.join(script_dir, "repos")
    if not os.path.exists(backup_dir):
        os.makedirs(backup_dir)
        
    github_user = get_github_user()
    repos_json = run_cmd(["gh", "repo", "list", github_user, "--limit", "1000", "--json", "name,visibility,url,diskUsage"])
    repos = json.loads(repos_json)
    
    if target_repos:
        target_set = set(target_repos)
        repos = [r for r in repos if r["name"] in target_set]
        if not repos:
            print(f"No matching repositories found on GitHub for targets: {target_repos}")
            return
            
    # Initialize the rich logger
    with BackupLogger(total_repos=len(repos)) as logger:
        logger.log_info("Starting GitHub to GitLab Backup Script...")
        logger.log_info(f"Authenticated as GitLab user: {glab_user}")
        if target_repos:
            logger.log_info(f"Targeted backup for {len(repos)} specific repositories: [bold]{', '.join([r['name'] for r in repos])}[/bold]")
        else:
            logger.log_info(f"Found {len(repos)} repositories to process.")
        
        for repo in repos:
            name = repo["name"]
            visibility = repo["visibility"].lower()
            github_url = repo["url"]
            
            size_kb = repo.get("diskUsage", 0)
            if size_kb > 1024:
                size_str = f"{size_kb / 1024:.1f} MB"
            else:
                size_str = f"{size_kb} KB"
                
            logger.log_info(f"Processing: [bold]{name}[/] ({visibility}) - Size: [yellow]{size_str}[/]")
            
            # Setup GitLab repo cleanly

            glab_repo_name = sanitize_glab_name(name)
            
            if direct_import:
                logger.log_info(f"Direct import selected for [bold]{name}[/]. Triggering GitLab API...")
                token = get_github_token()
                if not token:
                    logger.log_error(f"Failed to get GitHub token for direct import of {name}")
                    logger.update_overall()
                    continue
                import_url = f"https://oauth2:{token}@github.com/{github_user}/{name}.git"
                
                glab_check = run_cmd([GLAB_CMD, "api", f"/projects/{glab_user}%2F{glab_repo_name}"], check=False)
                if glab_check and "message" in glab_check and "404" in glab_check:
                    res = subprocess.run([GLAB_CMD, "api", "/projects", "-X", "POST", "-f", f"path={glab_repo_name}", "-f", f"name={glab_repo_name}", "-f", f"import_url={import_url}", "-f", "visibility=private"], capture_output=True, text=True)
                    if res.returncode == 0:
                        logger.log_info(f"Successfully started direct import for {name} on GitLab servers.")
                        logger.update_stats(status="success", retries_used=0)
                    else:
                        logger.log_error(f"Failed to trigger direct import: {res.stderr}")
                        logger.update_stats(status="failed", retries_used=0)
                else:
                    logger.log_info(f"Repo {name} already exists on GitLab. Skipping direct import (it handles initial copy).")
                    logger.update_stats(status="success", retries_used=0)
                logger.update_overall()
                continue

            ensure_gitlab_repo(glab_user, glab_repo_name, logger=logger)

            
            repo_path = os.path.join(backup_dir, f"{name}.git")
            retries_used = 0
            is_failed = False
            
            # 1. Verification of GitHub -> Local
            is_valid_repo = os.path.exists(repo_path) and os.path.exists(os.path.join(repo_path, "HEAD"))
            
            if not is_valid_repo:
                logger.log_info(f"Local mirror for [bold]{name}[/] does not exist. Cloning from GitHub...")
                if os.path.exists(repo_path):
                    try:
                        import shutil
                        shutil.rmtree(repo_path, ignore_errors=True)
                    except:
                        pass
                        
                for attempt in range(3):
                    code, out = logger.run_command(["git", "clone", "--mirror", "--progress", github_url, f"{name}.git"], cwd=backup_dir, description=f"Cloning {name} (Attempt {attempt+1})")
                    if code == 0:
                        break
                    retries_used += 1
                    logger.log_warning(f"Clone attempt {attempt+1} failed for {name}.")
                    try:
                        import shutil
                        shutil.rmtree(repo_path, ignore_errors=True)
                    except:
                        pass
                
                if code != 0:
                    logger.log_error(f"Failed to clone {name} after 3 attempts. Skipping.")
                    logger.update_stats(status="failed", retries_used=retries_used)
                    logger.update_overall()
                    continue
            else:
                code, out = logger.run_command(["git", "fetch", "--tags", "--prune", "origin"], cwd=repo_path, description=f"Verifying & fetching updates for {name}")
                if code != 0:
                    logger.log_error(f"Failed to update {name}. Skipping.")
                    logger.update_stats(status="failed", retries_used=retries_used)
                    logger.update_overall()
                    continue
                logger.log_info(f"Local mirror for [bold]{name}[/] exists already and updated already (GitHub -> Local).")
                
            remotes = run_cmd(["git", "remote"], cwd=repo_path).splitlines()
            gitlab_url = f"https://gitlab.com/{glab_user}/{glab_repo_name}.git"
            
            if "gitlab" not in remotes:
                run_cmd(["git", "remote", "add", "gitlab", gitlab_url], cwd=repo_path)
            else:
                run_cmd(["git", "remote", "set-url", "gitlab", gitlab_url], cwd=repo_path)
                
            # 2. Verification of Local -> GitLab
            has_commits = run_cmd(["git", "rev-list", "-n", "1", "--all"], cwd=repo_path)
            if not has_commits:
                logger.log_info(f"Repository [bold]{name}[/] is empty. Skipping code push.")
            else:
                glab_is_up_to_date = check_gitlab_up_to_date(repo_path)
                if glab_is_up_to_date:
                    logger.log_info(f"GitLab remote for [bold]{name}[/] exists already and updated already (Local -> GitLab). Skipping push.")
                else:
                    logger.log_info(f"GitLab remote for [bold]{name}[/] is missing refs or out of date. Pushing updates...")
                    for attempt in range(3):
                        code, out = logger.run_command(["git", "push", "gitlab", "+refs/heads/*:refs/heads/*", "+refs/tags/*:refs/tags/*", "--progress"], cwd=repo_path, description=f"Pushing {name} (Attempt {attempt+1})")
                        if code == 0:
                            break
                        retries_used += 1
                        logger.log_warning(f"Push attempt {attempt+1} failed for {name}.")
                    
                    if code != 0:
                        logger.log_error(f"Failed to push {name} after 3 attempts. See logs for details.")
                        is_failed = True
                
            if is_failed:
                logger.update_stats(status="failed", retries_used=retries_used)
            else:
                logger.update_stats(status="success", retries_used=retries_used)
                # Successfully verified / pushed, now check & migrate releases!
                migrate_releases(name, github_user, glab_user, logger)
                
            logger.update_overall()
            
        logger.log_info(f"Backup complete! All local mirrors are kept in: {backup_dir}")

def main():
    parser = argparse.ArgumentParser(description="Backup GitHub repos to GitLab")
    parser.add_argument("--repos", nargs="*", help="Specific repository names to backup")
    args, unknown = parser.parse_known_args()
    
    target_repos = args.repos if args.repos else unknown
    run_backup(target_repos=target_repos if target_repos else None)

if __name__ == "__main__":
    main()


