"""Builds a small mod repo (plus a bare remote) for the tests. Generated, never hand-edited."""
import json, os, shutil, subprocess, textwrap

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ALPHA = "export function alphaOne() { return 1; }\n"
BIG = textwrap.dedent("""\
    export function bigA() { return 'a'; }

    function bigB() { return 'b'; }

    export const bigC = () => 'c';

    export default class BigWindow {}
    """)

FEATURES = {
    "alpha": textwrap.dedent("""\
        ---
        feature: alpha
        files: [scripts/alpha.mjs]
        functions: []
        dependsOn: []
        since: 0.1.0
        ---
        The alpha feature, owning `alphaOne`.

        ## Decisions
        - Rhea 2026-01-01: alpha returns one, because two was rejected.

        ## How it works
        `alphaOne` returns 1.

        ## Checks
        - (al-1) {live} Call alphaOne through the API: it returns 1
        - (al-2) {unit} alphaOne is covered by the unit tests
        - (al-3) {live,shared:beta} alpha still works after a beta change

        ## Traps
        - Never return two.

        ## Open items
        """),
    "beta": textwrap.dedent("""\
        ---
        feature: beta
        files: []
        functions: [bigA, big.mjs:bigB]
        dependsOn: [alpha]
        since: 0.1.0
        ---
        The beta feature, owning `bigA` and `bigB`.

        ## Decisions

        ## How it works

        ## Checks
        - (be-1) {live} bigA returns a
        - (be-2) {live,shared:alpha} beta still works after an alpha change

        ## Traps

        ## Open items
        """),
    "gamma": textwrap.dedent("""\
        ---
        feature: gamma
        files: []
        functions: [bigC, BigWindow]
        dependsOn: []
        since: 0.1.0
        ---
        The gamma feature, owning `bigC` and the `BigWindow` class.

        ## Decisions

        ## How it works

        ## Checks
        - (ga-1) {live,player} the window opens for the test player

        ## Traps

        ## Open items
        """),
}

CONFIG = {
    "scripts": ["scripts"],
    "functionOwned": ["scripts/big.mjs"],
    "features": "docs/features",
    "changes": "docs/changes",
    "developing": "docs/DEVELOPING.md",
    "manifest": "module.json",
    "zip": {"path": "dist/fixmod.zip", "include": ["module.json", "scripts"]},
    "tests": "python3 tools/test/unit.py",
    "mainBranch": "main",
    "reviewPaths": ["scripts"],
    "extraDocs": [],
    "setupChecks": [{"path": "tools/test/data", "hint": "copy the test data"}],
    "finishList": ["the module's project doc"],
}


def git(root, *args, check=True):
    r = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=root, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr}")
    return r.stdout


def write(root, rel, text):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)


def build(base_dir):
    """Returns (repo_dir, bare_remote_dir). The repo is committed, pushed, index generated, words present."""
    repo = os.path.join(base_dir, "fixmod")
    remote = os.path.join(base_dir, "fixmod-remote.git")
    os.makedirs(repo)
    git(repo, "init", "-q", "-b", "main")
    write(repo, "module.json", json.dumps({"id": "fixmod", "title": "Fixture", "version": "0.1.0"}, indent=1) + "\n")
    write(repo, ".modtools.json", json.dumps(CONFIG, indent=1) + "\n")
    write(repo, ".gitignore", ".private-words\n.modtools-stamp.json\n__pycache__/\ntools/test/data/\n")
    write(repo, "scripts/alpha.mjs", ALPHA)
    write(repo, "scripts/big.mjs", BIG)
    for name, text in FEATURES.items():
        write(repo, f"docs/features/{name}.md", text)
    write(repo, "docs/DEVELOPING.md", "# Fixture\n\n## Layout\n`scripts/alpha.mjs` and `scripts/big.mjs`.\n\n## Feature index\n\n<!-- feature-index:start -->\n<!-- feature-index:end -->\n")
    write(repo, "docs/unverified.md", "# Unverified items\n\n- (u-1) [0.1.0] open: the first item\n")
    write(repo, "tools/test/unit.py", "import sys\nsys.exit(0)\n")
    write(repo, "tools/test/data/.keep", "")
    os.makedirs(os.path.join(repo, "tools/githooks"))
    shutil.copy(os.path.join(TOOLS, "githooks", "pre-push"), os.path.join(repo, "tools/githooks/pre-push"))
    os.chmod(os.path.join(repo, "tools/githooks/pre-push"), 0o755)
    write(repo, ".private-words", "# words that must never reach the repo\nStoneclaim\nRedthorn Hollow\n")
    subprocess.run(["python3", os.path.join(TOOLS, "guide.py"), "--index"], cwd=repo, check=True, capture_output=True)
    # a committed zip with the right version, as a real repo has
    subprocess.run(["python3", "-c", "import zipfile,os;os.makedirs('dist',exist_ok=True);z=zipfile.ZipFile('dist/fixmod.zip','w');z.write('module.json');z.close()"], cwd=repo, check=True)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "fixture 0.1.0")
    git(remote, "init", "-q", "--bare", "-b", "main") if os.makedirs(remote) is None else None
    git(repo, "remote", "add", "origin", remote)
    git(repo, "push", "-q", "-u", "origin", "main")
    return repo, remote
