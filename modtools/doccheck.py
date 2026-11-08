"""doccheck: do the docs still match the code?

1. Names: every `backticked` name in DEVELOPING.md, the feature docs and `extraDocs`
   must appear somewhere in the repo (the old doccheck's rule), or in the tracked
   `externalNames` file (names from other systems' code the docs quote, one per line).
2. Ownership: every code file is owned whole by exactly one feature, or is functionOwned
   with every top-level function owned by exactly one feature. Owned names must exist.
3. Check ids: unique across all feature docs; every check line is well formed.
4. Feature index: the block between the markers in DEVELOPING.md equals what `guide --index`
   would generate (so it is never hand-edited).
Exit 0 when clean, 1 with the problems listed otherwise.
"""
import os, re, sys
from . import common as c

INDEX_START = "<!-- feature-index:start -->"
INDEX_END = "<!-- feature-index:end -->"
KNOWN = {"python3", "node", "npm", "npx", "git", "true", "false", "null"}


def external_names(root, cfg):
    p = os.path.join(root, cfg["externalNames"])
    if not os.path.isfile(p):
        return set()
    out = set()
    with open(p, encoding="utf-8") as f:
        for line in f:
            s = line.split("#", 1)[0].strip()
            if s:
                out.add(s)
    return out


def missing_names(root, cfg, docs):
    code = ""
    for f in c.worktree_files(root):
        code += f + "\n"            # every path counts as a known name
        if f in docs or not c.is_text_file(f):
            continue
        try:
            code += c.read(root, f) + "\n"
        except Exception:
            pass
    # a doc may quote names that live in another doc (feature names, check ids): the corpus
    # for doc d is the code plus every other doc, never d itself
    texts = {d: c.read(root, d) for d in docs if os.path.isfile(os.path.join(root, d))}
    seen, missing = set(KNOWN) | external_names(root, cfg), []
    for d, text in texts.items():
        corpus = code + "\n".join(t for k, t in texts.items() if k != d)
        for raw in re.findall(r"`([^`\n]{2,80})`", re.sub(r"<!--.*?-->", "", text, flags=re.S)):
            for name in re.split(r"[\s,/()=:;<>?\[\]\"']+|\.\.\.", raw):
                name = name.strip(".'\"{}[]<>*")
                if len(name) < 3 or name in seen or not re.search(r"[A-Za-z]", name):
                    continue
                seen.add(name)
                if name not in corpus:
                    missing.append((d, name))
    return len(seen), missing


def check_ids(feats):
    probs, seen = [], {}
    for f in feats.values():
        for line in f.body.split("\n"):
            s = line.strip()
            if re.match(r"^-\s*\(", s) and not c.CHECK_RE.match(line):
                probs.append(f"{f.path}: malformed check line: {s[:80]}")
        for cid, tags, text in f.checks:
            if cid in seen:
                probs.append(f"check id {cid} used in both {seen[cid]} and {f.path}")
            seen[cid] = f.path
            if not text:
                probs.append(f"{f.path}: check {cid} has no text")
            for t in tags:
                if t.startswith("shared:") and t[7:] not in feats:
                    probs.append(f"{f.path}: check {cid} is tagged shared:{t[7:]} but no such feature exists")
        for d in f.dependsOn:
            if d not in feats:
                probs.append(f"{f.path}: dependsOn `{d}` names no feature")
    return probs


def render_index(feats):
    lines = ["| Feature | Doc | Owns | Checks |", "|---|---|---|---|"]
    for name in sorted(feats):
        f = feats[name]
        owns = ", ".join(f.files) if f.files else f"{len(f.functions)} functions"
        lines.append(f"| {name} | `{f.path}` | {owns} | {len(f.checks)} |")
    return "\n".join(lines)


def index_problem(root, cfg, feats):
    dev = cfg["developing"]
    if not os.path.isfile(os.path.join(root, dev)):
        return [f"{dev} is missing"]
    text = c.read(root, dev)
    if INDEX_START not in text or INDEX_END not in text:
        return [f"{dev} has no feature-index markers ({INDEX_START} ... {INDEX_END})"]
    cur = text.split(INDEX_START, 1)[1].split(INDEX_END, 1)[0].strip("\n")
    if cur != render_index(feats):
        return [f"{dev}: the feature index is stale; run `guide --index` (never edit it by hand)"]
    return []


def run(root, cfg, quiet=False):
    feats = c.load_features(root, cfg)
    probs = []
    if not feats:
        probs.append(f"no feature docs in {cfg['features']}/")
    own = c.Ownership(root, cfg, feats)
    probs += own.check()
    probs += check_ids(feats)
    probs += index_problem(root, cfg, feats)
    docs = [cfg["developing"]] + [f.path for f in feats.values()] + list(cfg["extraDocs"])
    n, missing = missing_names(root, cfg, docs)
    for d, name in missing:
        probs.append(f"{d}: `{name}` is not found anywhere in the repo")
    if not quiet:
        print(f"doccheck: {len(feats)} features, {n} names checked, {len(probs)} problems")
        for p in probs:
            print("  -", p)
    return probs


def main(argv=None):
    try:
        root = c.find_root()
        cfg = c.load_config(root)
        probs = run(root, cfg)
    except c.Fail as e:
        c.die(str(e), 1)
    sys.exit(1 if probs else 0)
