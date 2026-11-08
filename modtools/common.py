"""Shared pieces for guide, gate, doccheck and scan. Standard library only.

A mod repo opts in with a `.modtools.json` at its root (see templates/modtools.json).
Everything here works from the mod repo's root, found by walking up from the cwd.
"""
import hashlib, json, os, re, subprocess, sys

CONFIG_NAME = ".modtools.json"
STAMP_NAME = ".modtools-stamp.json"
WORDS_NAME = ".private-words"


class Fail(Exception):
    """A refusal or a setup problem; the message is for Rhea or the chat."""


# ---------- repo and config ----------

def find_root(start=None):
    d = os.path.abspath(start or os.getcwd())
    while True:
        if os.path.isfile(os.path.join(d, CONFIG_NAME)):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            raise Fail(f"no {CONFIG_NAME} found above {start or os.getcwd()}; run from inside a mod repo that has one")
        d = parent


DEFAULTS = {
    "scripts": ["scripts"],                 # folders holding the module's code
    "functionOwned": [],                    # files whose functions are owned one by one
    "features": "docs/features",
    "changes": "docs/changes",
    "developing": "docs/DEVELOPING.md",
    "manifest": "module.json",
    "zip": {"path": None, "include": []},  # built by the gate from the tree
    "tests": None,                          # shell command that must exit 0
    "mainBranch": "main",
    "reviewPaths": [],                      # a change under these needs the review section
    "extraDocs": [],                        # other docs doccheck reads names from
}


def load_config(root):
    with open(os.path.join(root, CONFIG_NAME), encoding="utf-8") as f:
        cfg = json.load(f)
    out = dict(DEFAULTS)
    out.update(cfg)
    if not out["reviewPaths"]:
        out["reviewPaths"] = list(out["scripts"])
    if not out["zip"].get("include"):
        out["zip"]["include"] = []
    return out


def git(root, *args, check=True, input=None):
    r = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, input=input)
    if check and r.returncode != 0:
        raise Fail(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout


def tracked_files(root):
    return [f for f in git(root, "ls-files").split("\n") if f]


def worktree_files(root):
    """Tracked plus untracked-but-not-ignored files, as they are on disk."""
    out = git(root, "ls-files", "--cached", "--others", "--exclude-standard")
    files = []
    for f in out.split("\n"):
        if f and os.path.isfile(os.path.join(root, f)):
            files.append(f)
    return sorted(set(files))


def read(root, rel):
    with open(os.path.join(root, rel), encoding="utf-8", errors="replace") as f:
        return f.read()


def is_text_file(path):
    return not path.lower().endswith((".zip", ".png", ".webp", ".jpg", ".jpeg", ".gif", ".pyc", ".woff", ".woff2", ".ttf", ".mp3", ".ogg", ".pdf"))


# ---------- frontmatter ----------

def parse_frontmatter(text):
    """Minimal YAML: `key: value`, `key: [a, b]`, and block lists `- item`. Returns (dict, body)."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    head = text[3:end].strip("\n")
    body = text[end + 4:].lstrip("\n")
    data, key = {}, None
    for line in head.split("\n"):
        if not line.strip() or line.strip().startswith("#"):
            continue
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):\s*(.*)$", line)
        if m:
            key, val = m.group(1), m.group(2).strip()
            val = re.sub(r"\s+#.*$", "", val)
            if val.startswith("[") and val.endswith("]"):
                inner = val[1:-1].strip()
                data[key] = [v.strip().strip("'\"") for v in inner.split(",") if v.strip()] if inner else []
            elif val == "":
                data[key] = []
            else:
                data[key] = val.strip("'\"")
        elif line.strip().startswith("- ") and key is not None:
            if not isinstance(data.get(key), list):
                data[key] = []
            data[key].append(line.strip()[2:].strip().strip("'\""))
    return data, body


# ---------- JS top-level functions ----------

FUNC_RE = re.compile(
    r"^(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)\s*\(|"
    r"^(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)\s*=>|[A-Za-z_$][\w$]*\s*=>|function\b)|"
    r"^(?:export\s+)?(?:default\s+)?class\s+([A-Za-z_$][\w$]*)",
    re.M,
)


def top_level_functions(text):
    """Names of top-level functions and classes (column 0 only, so nested ones are skipped)."""
    names = []
    for m in FUNC_RE.finditer(text):
        names.append(next(g for g in m.groups() if g))
    return names


def code_files(root, cfg):
    files = []
    for f in tracked_files(root):
        for folder in cfg["scripts"]:
            if f.startswith(folder.rstrip("/") + "/") and f.endswith((".mjs", ".js")):
                files.append(f)
    return sorted(set(files))


# ---------- features ----------

CHECK_RE = re.compile(r"^\s*-\s*\(([A-Za-z0-9][\w.-]*)\)\s*(?:\{([^}]*)\})?\s*(.*)$")


class Feature:
    def __init__(self, name, path, meta, body):
        self.name = name
        self.path = path
        self.meta = meta
        self.body = body
        self.files = list(meta.get("files", []) or [])
        self.functions = list(meta.get("functions", []) or [])
        self.dependsOn = list(meta.get("dependsOn", []) or [])
        self.checks = []  # (id, tags, text)
        for line in body.split("\n"):
            m = CHECK_RE.match(line)
            if m:
                tags = [t.strip() for t in (m.group(2) or "").split(",") if t.strip()]
                self.checks.append((m.group(1), tags, m.group(3).strip()))

    def section(self, title):
        m = re.search(rf"^##\s+{re.escape(title)}\s*$(.*?)(?=^##\s|\Z)", self.body, re.M | re.S)
        return m.group(1).strip("\n") if m else ""

    def summary(self):
        for line in self.body.split("\n"):
            s = line.strip()
            if s and not s.startswith("#"):
                return s[:120]
        return ""


def load_features(root, cfg):
    folder = os.path.join(root, cfg["features"])
    feats = {}
    if not os.path.isdir(folder):
        return feats
    for fn in sorted(os.listdir(folder)):
        if not fn.endswith(".md"):
            continue
        rel = os.path.join(cfg["features"], fn)
        meta, body = parse_frontmatter(read(root, rel))
        name = meta.get("feature") or fn[:-3]
        feats[name] = Feature(name, rel, meta, body)
    return feats


def function_key(file, name):
    return f"{os.path.basename(file)}:{name}"


class Ownership:
    """Who owns each code file and each function in the function-owned files."""

    def __init__(self, root, cfg, feats):
        self.root, self.cfg, self.feats = root, cfg, feats
        self.file_owner = {}       # rel path -> [feature]
        self.func_owner = {}       # "file.mjs:name" -> [feature]
        self.problems = []
        self._cache = {}
        fo_basenames = {os.path.basename(f): f for f in cfg["functionOwned"]}
        for f in feats.values():
            for path in f.files:
                self.file_owner.setdefault(path, []).append(f.name)
            for fn in f.functions:
                if ":" in fn:
                    base, name = fn.split(":", 1)
                    if base not in fo_basenames:
                        self.problems.append(f"{f.path}: function `{fn}` names a file that is not in functionOwned")
                    key = fn
                else:
                    # bare name: must be unique across the function-owned files
                    hits = [b for b in fo_basenames if fn in self._funcs_of(fo_basenames[b])]
                    if len(hits) == 1:
                        key = function_key(hits[0], fn)
                    elif len(hits) > 1:
                        self.problems.append(f"{f.path}: function `{fn}` exists in {', '.join(sorted(hits))}; write it as file:name")
                        continue
                    else:
                        key = f"?:{fn}"
                self.func_owner.setdefault(key, []).append(f.name)

    def _funcs_of(self, rel):
        if rel not in self._cache:
            try:
                self._cache[rel] = top_level_functions(read(self.root, rel))
            except FileNotFoundError:
                self._cache[rel] = []
        return self._cache[rel]

    def features_for_file(self, rel):
        return list(self.file_owner.get(rel, []))

    def features_for_function(self, rel, name):
        return list(self.func_owner.get(function_key(rel, name), []))

    def check(self):
        """Every code file owned whole by exactly one feature, or function-owned with every
        top-level function owned by exactly one feature. Returns a list of problems."""
        probs = list(self.problems)
        fo = set(self.cfg["functionOwned"])
        for rel in code_files(self.root, self.cfg):
            owners = self.file_owner.get(rel, [])
            if rel in fo:
                if owners:
                    probs.append(f"{rel} is functionOwned but also listed in `files` of {', '.join(owners)}")
                for name in self._funcs_of(rel):
                    o = self.func_owner.get(function_key(rel, name), [])
                    if not o:
                        probs.append(f"orphan: {rel} `{name}` belongs to no feature")
                    elif len(o) > 1:
                        probs.append(f"{rel} `{name}` is owned by more than one feature: {', '.join(o)}")
            else:
                if not owners:
                    probs.append(f"orphan: {rel} belongs to no feature (list it in a feature's `files` or in functionOwned)")
                elif len(owners) > 1:
                    probs.append(f"{rel} is owned by more than one feature: {', '.join(owners)}")
        for key, o in self.func_owner.items():
            base, name = key.split(":", 1)
            if base == "?":
                probs.append(f"function `{name}` (owned by {', '.join(o)}) exists in no functionOwned file")
                continue
            rel = next((f for f in self.cfg["functionOwned"] if os.path.basename(f) == base), None)
            if rel and name not in self._funcs_of(rel):
                probs.append(f"function `{key}` (owned by {', '.join(o)}) no longer exists")
        for path, owners in self.file_owner.items():
            if not os.path.isfile(os.path.join(self.root, path)):
                probs.append(f"file `{path}` (owned by {', '.join(owners)}) does not exist")
        return probs


# ---------- diffs and mapping ----------

def changed_files(root, base):
    """Paths changed between `base` and the working tree (staged, unstaged and untracked)."""
    out = set()
    for f in git(root, "diff", "--name-only", base).split("\n"):
        if f:
            out.add(f)
    for f in git(root, "ls-files", "--others", "--exclude-standard").split("\n"):
        if f:
            out.add(f)
    return sorted(out)


def changed_functions(root, base, rel):
    """Function names whose text differs between base and the working tree, for one file."""
    try:
        old = git(root, "show", f"{base}:{rel}")
    except Fail:
        old = ""
    try:
        new = read(root, rel)
    except FileNotFoundError:
        new = ""
    a, b = _func_bodies(old), _func_bodies(new)
    return {n for n in set(a) | set(b) if a.get(n) != b.get(n)}


def _func_bodies(text):
    """Map name -> body text, splitting the file at each top-level declaration."""
    bodies, starts = {}, []
    for m in FUNC_RE.finditer(text):
        starts.append((m.start(), next(g for g in m.groups() if g)))
    for i, (pos, name) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(text)
        bodies[name] = text[pos:end].strip()
    return bodies


def map_changes(root, cfg, own, files):
    """Which features a set of changed paths touch. Returns (features, unowned_code_paths)."""
    touched, unowned = set(), []
    fo = set(cfg["functionOwned"])
    base_sha = None
    for rel in files:
        if rel in fo:
            touched.update(own.features_for_file(rel))
            continue
        if any(rel.startswith(s.rstrip("/") + "/") for s in cfg["scripts"]) and rel.endswith((".mjs", ".js")):
            fs = own.features_for_file(rel)
            if fs:
                touched.update(fs)
            else:
                unowned.append(rel)
    return touched, unowned


def map_changes_with_functions(root, cfg, own, base):
    files = changed_files(root, base)
    touched, unowned = map_changes(root, cfg, own, [f for f in files if f not in set(cfg["functionOwned"])])
    for rel in files:
        if rel in set(cfg["functionOwned"]):
            for name in changed_functions(root, base, rel):
                fs = own.features_for_function(rel, name)
                if fs:
                    touched.update(fs)
                else:
                    unowned.append(f"{rel} `{name}`")
    return files, touched, unowned


def shared_required(feats, touched):
    """Check items in other features tagged shared:<touched feature>."""
    req = []
    for f in feats.values():
        for cid, tags, text in f.checks:
            for t in tags:
                if t.startswith("shared:") and t[7:] in touched and f.name not in touched:
                    req.append((f.name, cid, tags, text))
    return req


# ---------- change records ----------

def record_path(root, cfg, version):
    return os.path.join(cfg["changes"], f"{version}.md")


def load_record(root, cfg, version):
    rel = record_path(root, cfg, version)
    if not os.path.isfile(os.path.join(root, rel)):
        raise Fail(f"no change record at {rel}; run `guide start {version}` first")
    meta, body = parse_frontmatter(read(root, rel))
    return rel, meta, body


def record_section(body, title):
    m = re.search(rf"^##\s+{re.escape(title)}\b[^\n]*$(.*?)(?=^##\s|\Z)", body, re.M | re.S)
    return m.group(1) if m else None


def section_filled(text):
    """A section counts as filled when it has a line that is not blank and not a template hint."""
    if text is None:
        return False
    for line in text.split("\n"):
        s = line.strip()
        if s and not s.startswith("<!--") and not s.startswith("_") and s != "-":
            return True
    return False


RESULT_RE = re.compile(r"^\s*-\s*([A-Za-z0-9][\w.-]*)\s+(pass|fail|not run)\b\s*:?\s*(.*)$", re.I)
WAIVE_RE = re.compile(r"^\s*-\s*doc-unchanged\s+([\w-]+)\s*:\s*(.+)$", re.I)


def record_results(body):
    """id -> (result, note) from the Checks section."""
    out = {}
    sec = record_section(body, "Checks") or ""
    for line in sec.split("\n"):
        m = RESULT_RE.match(line)
        if m:
            out[m.group(1)] = (m.group(2).lower(), m.group(3).strip())
    return out


def record_waivers(body):
    out = {}
    sec = record_section(body, "Features touched") or ""
    for line in sec.split("\n"):
        m = WAIVE_RE.match(line)
        if m:
            out[m.group(1)] = m.group(2).strip()
    return out


# ---------- manifest, tree hash, stamp ----------

def manifest_version(root, cfg, ref=None):
    try:
        text = git(root, "show", f"{ref}:{cfg['manifest']}") if ref else read(root, cfg["manifest"])
    except (Fail, FileNotFoundError):
        return None
    try:
        return json.loads(text).get("version")
    except json.JSONDecodeError:
        return None


def _zip_paths(cfg):
    z = cfg["zip"].get("path")
    return {z} if z else set()


def tree_hash_worktree(root, cfg):
    """A hash of every tracked and untracked-not-ignored file as on disk, except the zip."""
    skip = _zip_paths(cfg) | {STAMP_NAME, WORDS_NAME}
    h = hashlib.sha256()
    for rel in worktree_files(root):
        if rel in skip:
            continue
        blob = git(root, "hash-object", "--", rel).strip()
        h.update(f"{rel}\0{blob}\n".encode())
    return h.hexdigest()


def tree_hash_commit(root, cfg, sha):
    skip = _zip_paths(cfg) | {STAMP_NAME, WORDS_NAME}
    h = hashlib.sha256()
    for line in git(root, "ls-tree", "-r", sha).split("\n"):
        if not line:
            continue
        meta, rel = line.split("\t", 1)
        blob = meta.split()[2]
        if rel in skip:
            continue
        h.update(f"{rel}\0{blob}\n".encode())
    return h.hexdigest()


def write_stamp(root, data):
    with open(os.path.join(root, STAMP_NAME), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)


def read_stamp(root):
    p = os.path.join(root, STAMP_NAME)
    if not os.path.isfile(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def is_ignored(root, rel):
    r = subprocess.run(["git", "check-ignore", "-q", rel], cwd=root, capture_output=True)
    return r.returncode == 0


def tools_dir():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def template(tpl, **fields):
    """A template with its {placeholders} filled; other braces (check tags) are left alone."""
    with open(os.path.join(tools_dir(), "templates", tpl), encoding="utf-8") as f:
        text = f.read()
    for k, v in fields.items():
        text = text.replace("{" + k + "}", str(v))
    return text


def say(*parts):
    print(*parts)


def die(msg, code=2):
    print(f"REFUSED: {msg}" if code == 2 else msg, file=sys.stderr)
    sys.exit(code)
