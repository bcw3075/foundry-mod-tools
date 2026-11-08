"""guide: what applies to this change, and what to do at the start and the end.

  guide                      the feature map: every feature, one line each, with sizes
  guide start <version>      setup checks, switch the pre-push hook on, create the change record
  guide <file|feature ...>   the decisions, checks, traps and shared items for those features
  guide --diff [base]        the same, for everything changed since base (default: the record's base)
  guide --index              regenerate the feature index in DEVELOPING.md (never edit it by hand)
  guide finish [version]     what is still unsaved: git, the record, and the homes outside the repo
  guide new-feature <name>   create a feature doc from the template
"""
import datetime, os, re, subprocess, sys
from . import common as c
from . import doccheck


def setup_problems(root, cfg):
    probs = []
    if not os.path.isfile(os.path.join(root, c.WORDS_NAME)):
        probs.append(f"{c.WORDS_NAME} is missing: copy the private word list from the project doc into the repo root (git-ignored)")
    for chk in cfg.get("setupChecks", []):
        if not os.path.exists(os.path.join(root, chk["path"])):
            probs.append(f"{chk['path']} is missing: {chk.get('hint', '')}".rstrip(": "))
    hooks = os.path.join(root, "tools", "githooks")
    if not os.path.isfile(os.path.join(hooks, "pre-push")):
        probs.append("tools/githooks/pre-push is missing: copy it from foundry-mod-tools/githooks/")
    return probs


def hook_on(root):
    cur = c.git(root, "config", "--get", "core.hooksPath", check=False).strip()
    if cur != "tools/githooks":
        c.git(root, "config", "core.hooksPath", "tools/githooks")
        return True
    return False


def cmd_start(root, cfg, version, title=None):
    if not re.match(r"^\d+\.\d+\.\d+$", version or ""):
        raise c.Fail("usage: guide start <version> (for example 0.11.0)")
    probs = setup_problems(root, cfg)
    for p in probs:
        print("SETUP:", p)
    hooks = os.path.join(root, "tools", "githooks", "pre-push")
    if os.path.isfile(hooks):
        if not os.access(hooks, os.X_OK):
            os.chmod(hooks, 0o755)
        print("hook: pre-push switched on" if hook_on(root) else "hook: pre-push already on")
    rel = c.record_path(root, cfg, version)
    if os.path.isfile(os.path.join(root, rel)):
        print(f"record: {rel} already exists (continuing it)")
    else:
        os.makedirs(os.path.dirname(os.path.join(root, rel)), exist_ok=True)
        base = c.git(root, "rev-parse", "HEAD").strip()
        text = c.template("change.md", version=version, date=datetime.date.today().isoformat(),
                                              base=base, title=title or "<what this release does>")
        with open(os.path.join(root, rel), "w", encoding="utf-8") as f:
            f.write(text)
        print(f"record: created {rel} (base {base[:9]}); fill the title now")
    cur = c.manifest_version(root, cfg)
    if cur == version:
        print(f"WARNING: {cfg['manifest']} already says {version}; the gate needs the version bumped in this release")
    print("\nTask list skeleton:")
    for t in ["fill the record's title and the decisions as they come", "build the change",
              "`guide --diff` and run every check it lists; record each as pass / fail / not run",
              "independent review of the diff and the record; verify and record its findings",
              "`gate` (builds the zip and stamps the tree); commit; push (the hook re-checks the stamp)",
              "install and check as foundry-module-dev section 5 says", "`guide finish`; the handoff"]:
        print(f"  - [ ] {t}")
    if probs:
        print(f"\n{len(probs)} setup problem(s) above: fix them before building.")
        return 1
    return 0


def print_feature(f, feats, touched_names):
    print(f"\n=== {f.name}  ({f.path}, {len(f.body):,} chars) ===")
    owns = ", ".join(f.files) if f.files else f"{len(f.functions)} functions"
    print(f"owns: {owns}" + (f"   depends on: {', '.join(f.dependsOn)}" if f.dependsOn else ""))
    for title in ("Decisions", "Traps", "Open items"):
        sec = f.section(title)
        if sec.strip():
            print(f"\n-- {title} --\n{sec}")
    if f.checks:
        print("\n-- Checks (every id must appear in the record) --")
        for cid, tags, text in f.checks:
            print(f"  ({cid}) {{{','.join(tags)}}} {text}")


def cmd_show(root, cfg, feats, names):
    own = c.Ownership(root, cfg, feats)
    touched, unknown = set(), []
    for n in names:
        if n in feats:
            touched.add(n)
            continue
        rel = os.path.relpath(os.path.abspath(n), root) if os.path.exists(n) else n
        fs = own.features_for_file(rel)
        if not fs and rel in cfg["functionOwned"]:
            fs = sorted({o for k, os_ in own.func_owner.items() if k.startswith(os.path.basename(rel) + ":") for o in os_})
        if fs:
            touched.update(fs)
        else:
            unknown.append(n)
    for u in unknown:
        print(f"UNKNOWN: `{u}` is neither a feature nor an owned code file")
    return report(root, cfg, feats, touched)


def report(root, cfg, feats, touched, unowned=()):
    if unowned:
        print("UNOWNED CHANGES (doccheck will fail until a feature owns them):")
        for u in unowned:
            print("  -", u)
    if not touched:
        print("No feature is touched.")
        return 1 if unowned else 0
    print(f"Features touched: {', '.join(sorted(touched))}")
    print("Read these docs in full, then the general DEVELOPING.md sections they point to.")
    for n in sorted(touched):
        print_feature(feats[n], feats, touched)
    shared = c.shared_required(feats, touched)
    if shared:
        print("\n=== Shared items required because a feature they depend on changed ===")
        for fname, cid, tags, text in shared:
            print(f"  ({cid}) [{fname}] {{{','.join(tags)}}} {text}")
    deps = sorted({d for n in touched for d in feats[n].dependsOn if d not in touched})
    if deps:
        print(f"\nAlso skim (depended on, not changed): {', '.join(deps)}")
    return 0


def cmd_diff(root, cfg, feats, base=None):
    if not base:
        base = latest_record_base(root, cfg) or "HEAD"
    own = c.Ownership(root, cfg, feats)
    files, touched, unowned = c.map_changes_with_functions(root, cfg, own, base)
    print(f"Changed since {base[:9] if len(base) > 20 else base}: {len(files)} file(s)")
    for f in files:
        print("  ", f)
    return report(root, cfg, feats, touched, unowned)


def latest_record_base(root, cfg):
    folder = os.path.join(root, cfg["changes"])
    if not os.path.isdir(folder):
        return None
    best = None
    for fn in os.listdir(folder):
        m = re.match(r"^(\d+)\.(\d+)\.(\d+)\.md$", fn)
        if m:
            key = tuple(int(x) for x in m.groups())
            if best is None or key > best[0]:
                best = (key, fn)
    if not best:
        return None
    meta, _ = c.parse_frontmatter(c.read(root, os.path.join(cfg["changes"], best[1])))
    return meta.get("base")


def latest_record_version(root, cfg):
    base = latest_record_base(root, cfg)
    if base is None:
        return None
    folder = os.path.join(root, cfg["changes"])
    vs = [fn[:-3] for fn in os.listdir(folder) if re.match(r"^\d+\.\d+\.\d+\.md$", fn)]
    return max(vs, key=lambda v: tuple(int(x) for x in v.split(".")))


def cmd_map(root, cfg, feats):
    if not feats:
        print(f"No feature docs in {cfg['features']}/ yet. `guide new-feature <name>` makes one.")
        return 0
    print(f"{len(feats)} features ({sum(len(f.body) for f in feats.values()):,} chars of docs):")
    for n in sorted(feats):
        f = feats[n]
        owns = ", ".join(f.files) if f.files else f"{len(f.functions)} fn"
        print(f"  {n:<16} {len(f.body):>6,}  {len(f.checks):>2} checks  {owns:<40} {f.summary()}")
    v = latest_record_version(root, cfg)
    if v:
        print(f"\nLatest change record: {cfg['changes']}/{v}.md")
    print(f"General: {cfg['developing']} (layout, data, releasing). Start a change with `guide start <version>`.")
    return 0


def cmd_index(root, cfg, feats):
    dev = os.path.join(root, cfg["developing"])
    text = c.read(root, cfg["developing"]) if os.path.isfile(dev) else ""
    block = f"{doccheck.INDEX_START}\n{doccheck.render_index(feats)}\n{doccheck.INDEX_END}"
    if doccheck.INDEX_START in text and doccheck.INDEX_END in text:
        pre, rest = text.split(doccheck.INDEX_START, 1)
        _, post = rest.split(doccheck.INDEX_END, 1)
        new = pre + block + post
    else:
        new = text.rstrip("\n") + "\n\n## Feature index\n\nGenerated by `guide --index`; never edit by hand.\n\n" + block + "\n"
    if new != text:
        with open(dev, "w", encoding="utf-8") as f:
            f.write(new)
        print(f"index: rewrote the feature index in {cfg['developing']}")
    else:
        print("index: already current")
    return 0


def cmd_new_feature(root, cfg, name):
    if not re.match(r"^[a-z][a-z0-9-]*$", name or ""):
        raise c.Fail("usage: guide new-feature <lower-case-name>")
    rel = os.path.join(cfg["features"], f"{name}.md")
    if os.path.isfile(os.path.join(root, rel)):
        raise c.Fail(f"{rel} already exists")
    os.makedirs(os.path.dirname(os.path.join(root, rel)), exist_ok=True)
    prefix = "".join(p[0] for p in name.split("-"))
    with open(os.path.join(root, rel), "w", encoding="utf-8") as f:
        f.write(c.template("feature.md", name=name, version=c.manifest_version(root, cfg) or "0.0.0", prefix=prefix))
    print(f"created {rel}; fill it, then `guide --index`")
    return 0


def cmd_finish(root, cfg, version=None):
    issues = []
    status = c.git(root, "status", "--porcelain").strip()
    if status:
        issues.append(f"uncommitted changes:\n{status}")
    branch = c.git(root, "rev-parse", "--abbrev-ref", "HEAD").strip()
    c.git(root, "fetch", "--quiet", "origin", check=False)
    for b in {branch, cfg["mainBranch"]}:
        ahead = c.git(root, "rev-list", "--count", f"origin/{b}..{b}", check=False).strip()
        if ahead and ahead != "0":
            issues.append(f"{b} is {ahead} commit(s) ahead of origin/{b}: push it")
        if b != cfg["mainBranch"]:
            diff = c.git(root, "rev-list", "--count", f"{cfg['mainBranch']}..{b}", check=False).strip()
            if diff and diff != "0":
                issues.append(f"{cfg['mainBranch']} is behind {b}: the manifest points at {cfg['mainBranch']}")
    version = version or latest_record_version(root, cfg)
    if version:
        rel, meta, body = c.load_record(root, cfg, version)
        for title in ("Features touched", "Checks", "Review", "Unverified", "Learned, and where it was filed"):
            if not c.section_filled(c.record_section(body, title)):
                issues.append(f"{rel}: section `{title}` is empty")
        if "<what this release does>" in body:
            issues.append(f"{rel}: the title is still the template's")
    else:
        issues.append("no change record found")
    stamp = c.read_stamp(root)
    if not stamp:
        issues.append("no gate stamp: `gate` has not passed in this tree")
    elif stamp.get("tree") != c.tree_hash_worktree(root, cfg):
        issues.append("the tree changed after the last `gate`: run it again")
    print("In the repo:")
    print("  nothing left" if not issues else "")
    for i in issues:
        print("  -", i)
    print("\nOutside the repo, confirm each (the scripts can't see these):")
    for item in cfg.get("finishList", []):
        print("  - [ ]", item)
    print("  - [ ] this change record's `Learned` lines really went where they say")
    print("  - [ ] handoff text for the next chat, in a code block")
    return 1 if issues else 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        root = c.find_root()
        cfg = c.load_config(root)
        feats = c.load_features(root, cfg)
        if not argv:
            code = cmd_map(root, cfg, feats)
        elif argv[0] == "start":
            code = cmd_start(root, cfg, argv[1] if len(argv) > 1 else None, " ".join(argv[2:]) or None)
        elif argv[0] == "finish":
            code = cmd_finish(root, cfg, argv[1] if len(argv) > 1 else None)
        elif argv[0] == "--diff":
            code = cmd_diff(root, cfg, feats, argv[1] if len(argv) > 1 else None)
        elif argv[0] == "--index":
            code = cmd_index(root, cfg, feats)
        elif argv[0] == "new-feature":
            code = cmd_new_feature(root, cfg, argv[1] if len(argv) > 1 else None)
        elif argv[0] in ("-h", "--help"):
            print(__doc__)
            code = 0
        else:
            code = cmd_show(root, cfg, feats, argv)
    except c.Fail as e:
        c.die(str(e), 1)
    sys.exit(code)
