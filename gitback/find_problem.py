import subprocess
import os

repo_name = "Dark-catcher.git"
repo_path = os.path.join("repos", repo_name)

print(f"Diagnosing push issue for {repo_name}...")

if not os.path.exists(repo_path):
    print(f"Error: {repo_path} doesn't exist.")
    exit(1)

# Check remote
print("1. Checking remotes:")
remotes = subprocess.run(["git", "remote", "-v"], cwd=repo_path, capture_output=True, text=True)
print(remotes.stdout)

# Try pushing
print("2. Attempting to push with full output:")
push = subprocess.run(
    ["git", "push", "--mirror", "gitlab"],
    cwd=repo_path,
    capture_output=True,
    text=True
)

print(f"Exit Code: {push.returncode}")
print("STDOUT:")
print(push.stdout)
print("STDERR:")
print(push.stderr)
