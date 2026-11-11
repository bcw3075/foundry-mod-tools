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
    "externalNames": "docs/external-names.txt",   # names from other systems' code the docs may quote (one per line)
    "unverified": "docs/unverified.md",     # the one running list of unverified items
    "unverifiedLimit": 8,                   # above this many open at a release's start, it must close some
    "closeOutAtLeast": 3,                   # how many a close-out pass closes (or down to the limit)
    "protocol2From": None,                  # records from this version on must say `protocol: 2`
    "planDoc": None,                        # the private project doc holding the lock, Next and the questions
    "pageChecks": [],                       # recurring traps made into scripts run on every page each chat
    "handoff": {"load": "", "where": []},   # fixed lines for `guide handoff`
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
                fs = own.features_for_function(rel, name) or base_function_owners(root, cfg, base, rel, name)
                if fs:
                    touched.update(fs)
                else:
                    unowned.append(f"{rel} `{name}`")
    return files, touched, unowned


def base_function_owners(root, cfg, base, rel, name):
    """The features that owned a function at the base, for one that no longer exists (removed or renamed): its doc
    can't own it any more (doccheck refuses a function that isn't there), yet removing it changes that feature
    (found 2026-11-09, Encounter Builder 0.18.0, when `hostile` became `runnable`). Only for a function gone from
    the working tree; one that still exists must be owned now."""
    try:
        if name in _func_bodies(read(root, rel)):
            return []
    except FileNotFoundError:
        pass
    key, out = function_key(rel, name), []
    try:
        names = git(root, "ls-tree", "--name-only", base, cfg["features"] + "/").split()
    except Fail:
        return []
    for path in names:
        if not path.endswith(".md"):
            continue
        try:
            meta, body = parse_frontmatter(git(root, "show", f"{base}:{path}"))
        except Fail:
            continue
        fns = meta.get("functions") or []
        if key in fns or name in fns:   # a bare name meant the file it was in at the base, and it was in this one
            out.append(meta.get("feature") or os.path.basename(path)[:-3])
    return out


def shared_required(feats, touched):
    """Check items in other features tagged shared:<touched feature>. Each item once, even when it is
    shared with several touched features (0.16.0's gate listed sd-1 to sd-11 twice, 2026-11-09)."""
    req, seen = [], set()
    for f in feats.values():
        if f.name in touched:
            continue
        for cid, tags, text in f.checks:
            if (f.name, cid) in seen:
                continue
            if any(t.startswith("shared:") and t[7:] in touched for t in tags):
                seen.add((f.name, cid))
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


def strip_comments(text):
    """The text without its <!-- --> template hints, which can run over several lines."""
    return re.sub(r"<!--.*?-->", "", text or "", flags=re.S)


def section_filled(text):
    """A section counts as filled when it has a line that is not blank and not a template hint. A hint can run over several lines, so comments
    are removed whole first: a hint's second line once counted as content (and its words "waived by Rhea" as a waiver), found 2026-11-08."""
    if text is None:
        return False
    for line in strip_comments(text).split("\n"):
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


TRAPS_DOC = "docs/foundry-traps.md"     # in this tools repo: the general Foundry and PF2e traps, moved out of the skill
TRAPS_ID = "traps-read"                 # the Setup line the gate wants when code changed


def traps_path():
    return os.path.join(tools_dir(), TRAPS_DOC)


def traps_sections():
    """The traps doc as [(heading, [bullet or paragraph, ...])]; a bullet keeps the lines that follow it
    (a code block) up to the next bullet or blank line."""
    p = traps_path()
    if not os.path.isfile(p):
        raise Fail(f"{TRAPS_DOC} is missing from the tools repo ({tools_dir()}): pull foundry-mod-tools again")
    out, items, cur, fence = [], None, None, False
    with open(p, encoding="utf-8") as f:
        for line in f.read().split("\n"):
            if line.startswith("```"):
                fence = not fence
            if not fence and line.startswith("## "):
                items = []
                out.append((line[3:].strip(), items))
                cur = None
            elif items is None:
                continue
            elif not fence and (line.startswith("- ") or re.match(r"^\d+\. ", line) or (line.strip() and cur is None)):
                cur = [line]
                items.append(cur)
            elif line.strip() or fence:
                if cur is not None:
                    cur.append(line)
            else:
                cur = None
    return [(h, ["\n".join(i) for i in items]) for h, items in out]


def traps_pointer():
    return (f"TRAPS: before the first code change read the general traps: `guide traps` lists the sections of "
            f"{traps_path()}; `guide traps <word> ...` prints the bullets that name what the change touches; "
            f"`guide traps --section 4` prints one whole. Then record `- {TRAPS_ID} done: <what was read>` under "
            f"Setup (the gate refuses a code change without it). A new general trap goes into that doc in the same step.")


def template(tpl, **fields):
    """A template with its {placeholders} filled; other braces (check tags) are left alone."""
    with open(os.path.join(tools_dir(), "templates", tpl), encoding="utf-8") as f:
        text = f.read()
    for k, v in sorted(fields.items(), key=lambda kv: kv[0] == "title"):   # the title last: its text is Claude's
        text = text.replace("{" + k + "}", str(v))
    return text


def say(*parts):
    print(*parts)


def die(msg, code=2):
    print(f"REFUSED: {msg}" if code == 2 else msg, file=sys.stderr)
    sys.exit(code)


# ---------- protocol 2: versions, lessons, unverified items, the plan doc ----------

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


def vkey(v):
    return tuple(int(x) for x in v.split("."))


def record_versions(root, cfg):
    folder = os.path.join(root, cfg["changes"])
    if not os.path.isdir(folder):
        return []
    vs = [fn[:-3] for fn in os.listdir(folder) if fn.endswith(".md") and VERSION_RE.match(fn[:-3])]
    return sorted(vs, key=vkey)


def is_protocol2(meta):
    return str(meta.get("protocol", "")).strip() == "2"


def needs_protocol2(cfg, version):
    """Records from `protocol2From` on must carry `protocol: 2`: deleting the line can't switch the rules off."""
    start = cfg.get("protocol2From")
    return bool(start and version and VERSION_RE.match(version) and vkey(version) >= vkey(start))


def bullets(text):
    """The `- ` lines of a section, template hints removed."""
    return [l.strip() for l in strip_comments(text or "").split("\n") if l.strip().startswith("- ")]


LEARN_RE = re.compile(r"(?:→|->)\s*(filed|owed|card proposed|card saved)\s*:\s*((?:(?!→|->).)+?)\s*(?=→|->|$)", re.I)


def learned(body):
    """[(line, kind, home)] from the Learned section; kind is None when the line names no home, or when
    the line isn't a `- ` bullet (every non-blank line is a lesson, so a `*` list can't slip past).
    A line naming several homes counts as the strictest: owed, then card proposed."""
    out = []
    for raw in strip_comments(record_section(body, "Learned, and where it was filed") or "").split("\n"):
        line = raw.strip()
        if not line:
            continue
        if not line.startswith("- "):
            out.append((line, None, None))
            continue
        hits = [(m.group(1).lower(), m.group(2)) for m in LEARN_RE.finditer(line)]
        if not hits:
            out.append((line, None, None))
            continue
        order = ["owed", "card proposed", "card saved", "filed"]
        kind, home = min(hits, key=lambda h: order.index(h[0]))
        out.append((line, kind, home))
    return out


SCOPE_RE = re.compile(r"^-\s*\[(general|module)\]", re.I)


def needs_lesson_scope(cfg, version, meta):
    """Records from `lessonScopeFrom` on (or with `lessonScope: 1` in the frontmatter) tag every lesson
    `[general]` or `[module]` (Rhea, 2026-11-09, after general lessons were twice filed only in a module's docs)."""
    if str(meta.get("lessonScope", "")).strip() == "1":
        return True
    start = cfg.get("lessonScopeFrom")
    return bool(start and version and VERSION_RE.match(version) and vkey(version) >= vkey(start))


def lesson_scope_problems(body):
    """Each lesson starts `- [general]` (true beyond this module: Foundry, PF2e, the bridge, the tools) or
    `- [module]` (only this module: any home). A general lesson must reach a home every chat can find: a skill
    card (`→ card proposed:` / `→ card saved:`) a project doc (`→ filed: claude/...`) or the general traps doc (`→ filed: foundry-mod-tools docs/foundry-traps.md`), whichever is that
    fact's one home (claude/docs-index.md); a module's own repo docs alone aren't enough. Skills stay lean:
    most general lessons belong in the project doc a skill points to, not the skill itself."""
    out = []
    for line, kind, home in learned(body):
        m = SCOPE_RE.match(line)
        if not m:
            out.append(f"lesson not tagged `[general]` or `[module]`: {line[:90]}")
            continue
        if m.group(1).lower() != "general" or kind in (None, "owed"):
            continue
        homes = [(k.lower(), h.strip()) for k, h in LEARN_RE.findall(line)]
        if not any(k in ("card proposed", "card saved") or (k == "filed" and ("claude/" in h or "foundry-mod-tools" in h)) for k, h in homes):
            out.append(f"general lesson filed only in this module's docs: file it in its one home too (a project doc `→ filed: claude/...`, the general traps `→ filed: foundry-mod-tools docs/foundry-traps.md`, or a skill card `→ card proposed: <skill>`): {line[:90]}")
    return out


UV_LINE = re.compile(r"^-\s*\((u-\d+)\)")
UV_RE = re.compile(r"^-\s*\((u-\d+)\)\s*\[(\d+\.\d+\.\d+)\]\s*(open|verified\s+(\S+)\s+in\s+(\d+\.\d+\.\d+)|dropped\s+(\S+))\s*:\s*(\S.*)$")


def parse_unverified(text):
    """(items, problems): items maps id -> {release, status, text}; status is open, verified or dropped."""
    items, probs = {}, []
    for line in (text or "").split("\n"):
        s = line.strip()
        if not UV_LINE.match(s):
            continue
        m = UV_RE.match(s)
        if not m:
            probs.append(f"unverified line not in the form `- (u-N) [<release>] open|verified <date> in <version>|dropped <date>: <text>`: {s[:90]}")
            continue
        uid = m.group(1)
        if uid in items:
            probs.append(f"unverified id {uid} is used twice")
        items[uid] = {"release": m.group(2), "status": m.group(3).split()[0], "text": m.group(7)}
    return items, probs


def read_unverified(root, cfg, ref=None):
    rel = cfg["unverified"]
    try:
        text = git(root, "show", f"{ref}:{rel}") if ref else read(root, rel)
    except (Fail, FileNotFoundError):
        return None, []
    return parse_unverified(text)


def plan_section(text, title):
    m = re.search(rf"^##\s+{re.escape(title)}\b[^\n]*$(.*?)(?=^##\s|\Z)", text or "", re.M | re.S)
    return m.group(1) if m else None


LOCK_RE = re.compile(r"^-\s*lock\s+(\S+)\s+(\d+\.\d+\.\d+)\s+started\s+(\S+)\s+token\s+(\w+)(?:\s+took over:.*)?\s*$")
Q_LINE = re.compile(r"^-\s*\((q-\d+)\)")
Q_RE = re.compile(r"^-\s*\((q-\d+)\)\s*\[since\s+(\d+\.\d+\.\d+)\]\s*(open|asked\s+(\S+)|answered\s+(\S+)|dropped\s+(\S+))\s*:\s*(\S.*)$")
NEXT_RE = re.compile(r"\*\*Next, in (?:her|Rhea['’]s) order:\*\*[ \t]*([^\n]+)")   # one line, by design


RECHECK_RE = re.compile(r"^-\s+(\S+)\s+(\d{4}-\d{2}-\d{2}):\s+(.+)$", re.M)


class Plan:
    """The module's private plan doc (the file in the private repo's clone, or a loose copy): the build lock,
    the open questions for Rhea, and Next in her order."""

    def __init__(self, path):
        self.path = path
        with open(path, encoding="utf-8") as f:
            self.text = f.read()
        self.problems = []
        if plan_section(self.text, "Build lock") is None:
            self.problems.append("the plan doc has no `## Build lock` section")
        if plan_section(self.text, "Open questions") is None:
            self.problems.append("the plan doc has no `## Open questions` section")
        self.locks = [LOCK_RE.match(l.strip()).groups() for l in (plan_section(self.text, "Build lock") or "").split("\n") if LOCK_RE.match(l.strip())]
        self.questions = []
        for l in strip_comments(plan_section(self.text, "Open questions") or "").split("\n"):
            s = l.strip()
            if not Q_LINE.match(s):
                continue
            m = Q_RE.match(s)
            if not m:
                self.problems.append(f"question not in the form `- (q-N) [since <version>] open|asked <date>|answered <date>|dropped <date>: <text>`: {s[:90]}")
                continue
            self.questions.append({"id": m.group(1), "since": m.group(2), "status": m.group(3).split()[0], "text": m.group(7)})
        m = NEXT_RE.search(self.text)
        self.next = m.group(1).strip() if m else None
        # Rhea's rule (2026-11-09): recheck everything before saying finished; `guide finish --rechecked` writes it here
        m = RECHECK_RE.search(plan_section(self.text, "Last recheck") or "")
        self.recheck = {"version": m.group(1), "date": m.group(2), "text": m.group(3).strip()} if m else None

    def set_recheck(self, version, date, text):
        line = f"- {version} {date}: {' '.join(text.split())}"
        if plan_section(self.text, "Last recheck") is None:
            self.text = self.text.rstrip("\n") + "\n\n## Last recheck\n" + line + "\n"
        else:
            self._replace_section("Last recheck", line)
        self.recheck = {"version": version, "date": date, "text": " ".join(text.split())}

    def lock_for(self, mod):
        return next((l for l in self.locks if l[0] == mod), None)

    def set_lock(self, mod, version, started, token, note=None):
        sec = plan_section(self.text, "Build lock")
        keep = [l for l in sec.split("\n") if not (LOCK_RE.match(l.strip()) and LOCK_RE.match(l.strip()).group(1) == mod)]
        body = "\n".join(keep).rstrip("\n")
        if version:
            body += f"\n- lock {mod} {version} started {started} token {token}" + (f" took over: {note}" if note else "")
        self._replace_section("Build lock", body.strip("\n"))

    def _replace_section(self, title, body):
        m = re.search(rf"^(##\s+{re.escape(title)}\b[^\n]*\n)(.*?)(?=^##\s|\Z)", self.text, re.M | re.S)
        self.text = self.text[:m.start()] + m.group(1) + body + "\n\n" + self.text[m.end():]

    def save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(self.text)


def overdue_questions(plan, versions, new_version=None):
    """Open questions carried through two handoffs or more: two change records (one per handoff)
    at or after the version they were first carried in, not counting the one being started."""
    out = []
    for q in plan.questions:
        if q["status"] not in ("open", "asked"):   # "asked, Rhea: later" doesn't stop the clock
            continue
        carried = [v for v in versions if vkey(v) >= vkey(q["since"]) and v != new_version]
        if len(carried) >= 2:
            out.append((q, len(carried)))
    return out


def manifest_id(root, cfg):
    try:
        return json.loads(read(root, cfg["manifest"])).get("id")
    except Exception:
        return None


def remote_branches(root):
    """Remote branch names, or None when the remote can't be listed (said, not hidden)."""
    r = subprocess.run(["git", "ls-remote", "--heads", "origin"], cwd=root, capture_output=True, text=True)
    if r.returncode != 0:
        return None
    out = r.stdout
    return sorted(l.split("refs/heads/", 1)[1] for l in out.split("\n") if "refs/heads/" in l)
