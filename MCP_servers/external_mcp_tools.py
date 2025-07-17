import os
from dotenv import load_dotenv
from github import Github
from mcp.server.fastmcp import FastMCP
from fastapi import HTTPException

mcp = FastMCP("github MCP")

load_dotenv()

@mcp.tool("push_local_folder")
def push_local_folder(github_token: str, folder_path: str, repo: str, branch: str = "main", target_dir: str = "") -> str:
    """
    Pushes all files from a local folder (under generated_code/) to a GitHub repository.
    """
    pushed_files = []
    folder_path = os.path.join("generated_code", folder_path)
    g = Github(github_token)
    
    if not os.path.isdir(folder_path):
        raise HTTPException(status_code=400, detail=f"Local folder `{folder_path}` does not exist.")

    try:
        repository = g.get_repo(repo)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"GitHub repository `{repo}` not found or inaccessible: {e}")

    for root, _, files in os.walk(folder_path):
        for file in files:
            full_path = os.path.join(root, file)
            relative_path = os.path.relpath(full_path, folder_path)
            repo_path = os.path.join(target_dir, relative_path).replace("\\", "/")

            with open(full_path, "rb") as f:
                content = f.read()

            try:
                existing = repository.get_contents(repo_path, ref=branch)
                repository.update_file(existing.path, f"Update {repo_path}", content, existing.sha, branch=branch)
            except Exception:
                try:
                    repository.create_file(repo_path, f"Create {repo_path}", content, branch=branch)
                except Exception as inner_e:
                    print(f"Failed to push {repo_path}: {inner_e}")
                    continue

            pushed_files.append(repo_path)

    return f"Pushed {len(pushed_files)} file(s) to `{repo}` in `{target_dir or '/'}`"

@mcp.tool("list_repositories")
def list_repositories(github_token: str) -> list:
    """
    Returns a list of all repositories (names) for the authenticated user.
    Includes private, public, and internal repositories.
    """
    g = Github(github_token)
    repos = g.get_user().get_repos()  # auto-paginates
    return [repo.full_name for repo in repos]


if __name__ == "__main__":
    import sys
    print("Github MCP starting...", file=sys.stderr)
    mcp.run(transport="stdio")
