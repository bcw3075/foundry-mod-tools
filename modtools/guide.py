"""guide: what applies to this change, and what to do at the start and the end.

  guide                      the feature map: every feature, one line each, with sizes
  guide start <version> "<title>" [--plan <copy>] [--take-over "<Rhea's OK>"]
                             setup checks, the build lock, questions to ask first, page checks,
                             switch the pre-push hook on, create the change record
  guide <file|feature ...>   the decisions, checks, traps and shared items for those features
  guide --diff [base]        the same, for everything changed since base (default: the record's base)
  guide --index              regenerate the feature index in DEVELOPING.md (never edit it by hand)
  guide finish [--plan <copy>]  what is still unsaved: git, the record, owed lessons, branches, the lock
  guide handoff --plan <copy> --state "<text>"   the handoff, in the fixed layout
  guide unverified [add "<text>"]   the open unverified items, or add one (file and record)
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


def lock_token(root):
    tok = c.git(root, "config", "--local", "--get", "modtools.lockToken", check=False).strip()
    if not tok:
        tok = os.urandom(4).hex()
        c.git(root, "config", "--local", "modtools.lockToken", tok)
    return tok


def load_plan(cfg, path):
    if not cfg.get("planDoc"):
        return None
    if not path:
        raise c.Fail(f"--plan <file> is required: project_read `{cfg['planDoc']}` into a scratch folder (outside the repo) and pass that copy")
    if not os.path.isfile(path):
        raise c.Fail(f"--plan {path}: no such file")
    plan = c.Plan(path)
    if plan.problems:
        raise c.Fail("the plan doc can't be read:\n  - " + "\n  - ".join(plan.problems))
    return plan


def carried_lessons(root, cfg, version):
    """Lessons still owed, or cards Rhea hasn't confirmed, in the latest record before this one."""
    prev = [v for v in c.record_versions(root, cfg) if c.vkey(v) < c.vkey(version)]
    if not prev:
        return []
    _, meta, body = c.load_record(root, cfg, prev[-1])
    if not c.is_protocol2(meta):
        return []
    return [f"{line} (carried from {prev[-1]})" for line, kind, _ in c.learned(body) if kind in ("owed", "card proposed")]


def cmd_start(root, cfg, version, title=None, plan_path=None, takeover=None):
    if not re.match(r"^\d+\.\d+\.\d+$", version or ""):
        raise c.Fail("usage: guide start <version> (for example 0.11.0)")
    plan = load_plan(cfg, plan_path)
    mod = c.manifest_id(root, cfg) or os.path.basename(root)
    # the build lock: one build chat per mod at a time
    if plan is not None:
        tok = lock_token(root)
        held = plan.lock_for(mod)
        if held and held[3] != tok:
            if not takeover:
                raise c.Fail(f"another chat is building {mod} ({held[1]}, started {held[2]}). Stop and tell Rhea. "
                             f"Only with her OK, rerun with --take-over \"<her words and the date>\"")
            print(f"lock: taken over from the chat that started {held[1]} at {held[2]} ({takeover})")
        if not held or held[3] != tok or held[1] != version:
            plan.set_lock(mod, version, datetime.datetime.now().isoformat(timespec="minutes"), tok,
                          takeover if held and held[3] != tok else None)
            plan.save()
            print(f"lock: written in {plan_path}. project_write it back to `{cfg['planDoc']}` NOW, before any build work")
        else:
            print("lock: this chat already holds it")
    probs = setup_problems(root, cfg)
    for p in probs:
        print("SETUP:", p)
    hooks = os.path.join(root, "tools", "githooks", "pre-push")
    if os.path.isfile(hooks):
        if not os.access(hooks, os.X_OK):
            os.chmod(hooks, 0o755)
        print("hook: pre-push switched on" if hook_on(root) else "hook: pre-push already on")
    versions = c.record_versions(root, cfg)
    overdue = c.overdue_questions(plan, versions, version) if plan else []
    pages = cfg.get("pageChecks") or []
    rel = c.record_path(root, cfg, version)
    if os.path.isfile(os.path.join(root, rel)):
        print(f"record: {rel} already exists (continuing it)")
    else:
        os.makedirs(os.path.dirname(os.path.join(root, rel)), exist_ok=True)
        base = c.git(root, "rev-parse", "HEAD").strip()
        carried = carried_lessons(root, cfg, version)
        text = c.template("change.md", version=version, date=datetime.date.today().isoformat(),
                          base=base, title=title or "<what this release does>",
                          setup="".join(f"- {p['id']} not run: pending\n" for p in pages),
                          asked="".join(f"- {q['id']} pending\n" for q, _ in overdue),
                          askfirst=", ".join(q["id"] for q, _ in overdue),
                          learned="".join(f"{l}\n" for l in carried))
        with open(os.path.join(root, rel), "w", encoding="utf-8") as f:
            f.write(text)
        print(f"record: created {rel} (base {base[:9]}); fill the title now")
        for l in carried:
            print(f"CARRIED lesson (finish refuses until filed): {l}")
    if overdue:
        print("\nASK RHEA FIRST, one at a time, before any build work (carried through two handoffs or more):")
        for q, n in overdue:
            print(f"  ({q['id']}) since {q['since']}, carried {n}: {q['text']}")
        print("  Record each in the plan doc (asked/answered) and in the record's `Asked first` (`- q-N asked <date>: <answer>`); the gate refuses a `pending` one.")
    if pages:
        print("\nPAGE CHECKS (recurring traps): run each on every page this chat uses; record `- <id> done: what was seen` under Setup")
        for p in pages:
            print(f"  [{p['id']}] {p.get('why', '')}")
            print(f"     on: {p.get('pages', 'every page')}; script: {p['script']}")
            sp = os.path.join(root, p["script"])
            if os.path.isfile(sp):
                print("     " + c.read(root, p["script"]).strip().replace("\n", "\n     "))
            else:
                probs.append(f"page check script {p['script']} is missing")
                print(f"SETUP: page check script {p['script']} is missing")
    items, uprobs = c.read_unverified(root, cfg)
    if items is not None:
        open_n = sum(1 for i in items.values() if i["status"] == "open")
        lim = cfg["unverifiedLimit"]
        print(f"\nunverified: {open_n} open in {cfg['unverified']} (limit {lim})")
        if open_n > lim:
            need = min(cfg["closeOutAtLeast"], open_n - lim)
            print(f"  CLOSE-OUT PASS due: this release must close at least {need} (test the cheapest live, or drop with a reason); the gate checks it")
    if c.manifest_version(root, cfg) == version:
        print(f"WARNING: {cfg['manifest']} already says {version}; the gate needs the version bumped in this release")
    print("\nTask list skeleton:")
    steps = []
    if overdue:
        steps.append("ask Rhea the overdue questions above, one at a time; record her answers")
    if pages:
        steps.append("run the page checks on every page this chat uses; record them under Setup")
    steps += ["fill the record's title and the decisions as they come", "build the change",
              "`guide --diff` and run every check it lists; record each as pass / fail / not run",
              "new unverified items: `guide unverified add \"<text>\"`",
              "independent review of the diff and the record; verify and record its findings",
              "`gate` (builds the zip and stamps the tree); commit; push (the hook re-checks the stamp)",
              "install and check as foundry-module-dev section 5 says",
              "file every lesson (`→ filed:`); `guide finish --plan`; `guide handoff`"]
    for s in steps:
        print(f"  - [ ] {s}")
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


def finish_state(root, cfg, version=None):
    """(issues, yellow): what is unsaved in the repo, and what only Rhea can do."""
    issues, yellow = [], []
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
        if not c.is_protocol2(meta) and c.needs_protocol2(cfg, version):
            issues.append(f"{rel} lacks `protocol: 2` in its frontmatter (required from {cfg['protocol2From']})")
        if c.is_protocol2(meta) and c.needs_lesson_scope(cfg, version, meta):
            issues += c.lesson_scope_problems(body)
        if c.is_protocol2(meta):
            for line, kind, home in c.learned(body):
                if kind is None:
                    issues.append(f"lesson names no home (end it with `→ filed: <where>`): {line[:100]}")
                elif kind == "owed":
                    issues.append(f"lesson owed, file it now and mark it `→ filed:`: {line[:100]}")
                elif kind == "card proposed":
                    yellow.append(f"Save the skill card for {home} (then I mark it `card saved`)")
    else:
        issues.append("no change record found")
    stamp = c.read_stamp(root)
    if not stamp:
        issues.append("no gate stamp: `gate` has not passed in this tree")
    elif stamp.get("tree") != c.tree_hash_worktree(root, cfg):
        issues.append("the tree changed after the last `gate`: run it again")
    branches = c.remote_branches(root)
    if branches is None:
        issues.append("couldn't list the remote branches (offline?): leftover branches can't be checked")
    leftover = [b for b in branches or [] if b != cfg["mainBranch"]]
    if leftover:   # Rhea 2026-11-09: no deletes as they come; one cleanup at the end of the project
        print(f"note: leftover branches kept for the end-of-project cleanup: {', '.join(leftover)}")
    return issues, list(dict.fromkeys(yellow)), version   # one line per card, however many lessons name it


def cmd_finish(root, cfg, plan_path=None, version=None):
    issues, yellow, version = finish_state(root, cfg, version)
    plan = None
    if cfg.get("planDoc"):
        try:
            plan = load_plan(cfg, plan_path)
        except c.Fail as e:
            issues.append(str(e))
    if plan is not None:
        mod = c.manifest_id(root, cfg) or os.path.basename(root)
        held = plan.lock_for(mod)
        tok = c.git(root, "config", "--local", "--get", "modtools.lockToken", check=False).strip()
        if held and held[3] != tok:
            issues.append(f"the plan's lock for {mod} belongs to another chat ({held[1]}, {held[2]}): tell Rhea")
        elif held and not issues:
            plan.set_lock(mod, None, None, None)
            plan.save()
            print(f"lock: cleared in {plan_path}; project_write it back to `{cfg['planDoc']}`")
        elif held:
            print("lock: kept (the build isn't finished: see below)")
    print("In the repo:")
    print("  nothing left" if not issues else "")
    for i in issues:
        print("  -", i)
    items, _ = c.read_unverified(root, cfg)
    if items is not None:
        print(f"\nunverified: {sum(1 for i in items.values() if i['status'] == 'open')} open in {cfg['unverified']}")
    print("\nOutside the repo, confirm each (the scripts can't see these):")
    for item in cfg.get("finishList", []):
        print("  - [ ]", item)
    print("  - [ ] this change record's `Learned` lines really went where they say")
    print("  - [ ] `guide handoff`, in a code block")
    if yellow:
        print("\nFor Rhea (🟡 lines in the reply):")
        for y in yellow:
            print("  🟡", y)
    return 1 if issues else 0


def cmd_handoff(root, cfg, plan_path=None, state=None):
    if not state:
        raise c.Fail('--state "<world, scene, pause, sessions, chat cards, browser pane>" is required: the script can\'t see the server')
    plan = load_plan(cfg, plan_path)
    issues, yellow, version = finish_state(root, cfg)
    mod = c.manifest_id(root, cfg) or os.path.basename(root)
    if plan is not None and plan.lock_for(mod):
        issues.append(f"the plan copy still holds the build lock for {mod}: `guide finish --plan` clears it (then project_write the copy back)")
    if issues:
        raise c.Fail("finish isn't clean; fix these first:\n  - " + "\n  - ".join(issues))
    rel, meta, body = c.load_record(root, cfg, version)
    m = re.search(r"^#\s+\S+\s+—\s+(.*?)\s*\(started", body, re.M)
    title = m.group(1) if m else ""
    ho = cfg.get("handoff") or {}
    lines = [f"{mod} {version} ({title}): gate passed, committed and pushed. What was installed and tested: {rel}.", "",
             "Read memory preferences.md first.", ho.get("load") or "Load the module's skills.", ""]
    if plan is not None:
        if not plan.next:
            raise c.Fail("the plan doc has no `**Next, in Rhea's order:** ...` line")
        lines += [f"Next, in Rhea's order: {plan.next}", ""]
        open_q = [q for q in plan.questions if q["status"] in ("open", "asked")]
        overdue = {q["id"] for q, _ in c.overdue_questions(plan, c.record_versions(root, cfg))}
        if open_q:
            lines.append(f"Open questions for Rhea, one at a time ({cfg['planDoc']}, Open questions):")
            for q in open_q:
                tag = " ASK FIRST" if q["id"] in overdue else (" (asked, waiting)" if q["status"] == "asked" else "")
                lines.append(f"- ({q['id']}){tag} {q['text']}")
        else:
            lines.append("Open questions for Rhea: none.")
        lines.append("")
    items, _ = c.read_unverified(root, cfg)
    if items is not None:
        n = sum(1 for i in items.values() if i["status"] == "open")
        lim = cfg["unverifiedLimit"]
        note = f"; over {lim}, so the next release starts with a close-out pass" if n > lim else ""
        lines += [f"Unverified: {n} open in {cfg['unverified']}{note}.", ""]
    lines += [f"State: {state}", "", "Where things are:"]
    lines += [f"- {w}" for w in ho.get("where", [])]
    lines += [f"- {rel} (this release)", f"- {cfg['unverified']} (unverified items)"]
    if cfg.get("planDoc"):
        lines.append(f"- {cfg['planDoc']} (status, Next, open questions, the build lock)")
    lines += ["", "Reminder: archive the old chat (⋮ > Archive)."]
    print("```\n" + "\n".join(lines) + "\n```")
    for y in yellow:
        print("🟡", y)
    return 0


def cmd_unverified(root, cfg, args):
    path = os.path.join(root, cfg["unverified"])
    items, probs = c.read_unverified(root, cfg)
    if args and args[0] == "add":
        text = " ".join(args[1:]).strip()
        if not text:
            raise c.Fail('usage: guide unverified add "<what this release does not prove>"')
        if items is None:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(UNVERIFIED_HEAD)
            items = {}
        v = c.manifest_version(root, cfg)
        recs = c.record_versions(root, cfg)
        if recs and (not v or c.vkey(recs[-1]) > c.vkey(v)):
            v = recs[-1]   # the release being built: its record exists before the manifest is bumped
        with open(path, encoding="utf-8") as f:
            used = [int(x) for x in re.findall(r"\(u-(\d+)\)", f.read())]   # malformed lines' ids too
        n = max(used + [0]) + 1
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"- (u-{n}) [{v}] open: {text}\n")
        rec = c.record_path(root, cfg, v)
        if os.path.isfile(os.path.join(root, rec)):
            body = c.read(root, rec)
            m = re.search(r"^##\s+Unverified\b[^\n]*\n(.*?)(?=^##\s|\Z)", body, re.M | re.S)
            wrote = False
            if m:
                sec = m.group(1).rstrip("\n") + f"\n- (u-{n}) {text}\n\n"
                body = body[:m.start(1)] + sec + body[m.end(1):]
                with open(os.path.join(root, rec), "w", encoding="utf-8") as f:
                    f.write(body)
                wrote = True
        else:
            wrote = False
        print(f"added u-{n} [{v}] to {cfg['unverified']}" + (f" and {rec}" if wrote else f"; NOT in a record ({rec} has no Unverified section or doesn't exist): add `- (u-{n}) {text}` by hand"))
        return 0
    if items is None:
        print(f"no {cfg['unverified']} yet; `guide unverified add \"<text>\"` makes it")
        return 0
    for p in probs:
        print("PROBLEM:", p)
    op = [(k, i) for k, i in items.items() if i["status"] == "open"]
    print(f"{len(op)} open (limit {cfg['unverifiedLimit']}):")
    for k, i in sorted(op, key=lambda x: int(x[0][2:])):
        print(f"  ({k}) [{i['release']}] {i['text']}")
    return 1 if probs else 0


UNVERIFIED_HEAD = """# Unverified items (one running list)

What a release did not prove, until it is checked live or dropped. Change records add to it with
`guide unverified add "<text>"`; close an item by editing its status in place:
`verified <date> in <version>: <text>. Seen: <what was seen>` or `dropped <date>: <text>. Why: <reason>`.
The gate counts the open ones; above the limit in `.modtools.json` a release must close some.

"""


def opt(argv, name):
    if name in argv:
        i = argv.index(name)
        val = argv[i + 1] if i + 1 < len(argv) else None
        del argv[i:i + 2]
        return val
    return None


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        root = c.find_root()
        cfg = c.load_config(root)
        feats = c.load_features(root, cfg)
        plan_path = opt(argv, "--plan")
        takeover = opt(argv, "--take-over")
        state = opt(argv, "--state")
        if not argv:
            code = cmd_map(root, cfg, feats)
        elif argv[0] == "start":
            code = cmd_start(root, cfg, argv[1] if len(argv) > 1 else None, " ".join(argv[2:]) or None, plan_path, takeover)
        elif argv[0] == "finish":
            code = cmd_finish(root, cfg, plan_path, argv[1] if len(argv) > 1 else None)
        elif argv[0] == "handoff":
            code = cmd_handoff(root, cfg, plan_path, state)
        elif argv[0] == "unverified":
            code = cmd_unverified(root, cfg, argv[1:])
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
