"""gate: refuses to make a release until the conditions hold, then builds the zip and stamps the tree.

  gate            all checks, then build the zip and write the stamp
  gate --check    all checks, build nothing (a dry run)
  gate --hook     called by tools/githooks/pre-push: a push to main needs a fresh stamp

Conditions (every one is reported; the first failure refuses the release):
  1 the manifest's version has a change record (`guide start <version>`) and is bumped since its base
  2 doccheck is clean (names exist, every function owned once, check ids unique, index generated)
  3 the privacy scan is clean (and fails closed without its word list)
  4 the unit tests pass (config `tests`)
  5 every changed code path is owned by a feature
  6 every touched feature's doc changed in this release, or the record waives it with a reason
  7 every check id of every touched feature, and every shared item they trigger, is recorded
    pass / not run (with a reason); `unit` items are covered by step 4; a `fail` refuses
  8 the Review section is filled when code changed (or `waived by Rhea <date>`)
  9 the record's title is no longer the template's
 Records made since the tightening (frontmatter `protocol: 2`) also need:
 10 every page check recorded under Setup (done, or not run with a reason)
 11 no question in `Asked first` still pending
 12 the running unverified list well formed, each item of the record's Unverified in it, and a
    close-out pass when more than the limit were open at the record's base
 13 every lesson in Learned naming its home (`→ filed:` and the others); from `lessonScopeFrom` each tagged
    `[general]` (then its home is a skill card) or `[module]`
 14 when code changed: `- traps-read done: <what was read>` under Setup (the general traps, `guide traps`)
"""
import datetime, io, json, os, re, subprocess, sys, zipfile
from . import common as c
from . import doccheck, scan


class Gate:
    def __init__(self, root, cfg):
        self.root, self.cfg = root, cfg
        self.lines = []
        self.refused = False

    def ok(self, msg):
        self.lines.append(f"  ok   {msg}")

    def refuse(self, msg):
        self.lines.append(f"  FAIL {msg}")
        self.refused = True
        raise c.Fail(msg)

    def run_checks(self):
        root, cfg = self.root, self.cfg
        # 1 version and record
        version = c.manifest_version(root, cfg)
        if not version:
            self.refuse(f"{cfg['manifest']} has no readable version")
        rel, meta, body = c.load_record(root, cfg, version)
        base = meta.get("base")
        if not base:
            self.refuse(f"{rel} has no `base` in its frontmatter")
        if c.manifest_version(root, cfg, base) == version:
            self.refuse(f"version {version} is the same as at the record's base {base[:9]}: bump it")
        self.ok(f"record {rel}, version {version} bumped since {base[:9]}")
        # 2 doccheck
        probs = doccheck.run(root, cfg, quiet=True)
        if probs:
            self.lines.append("  FAIL doccheck:\n" + "\n".join(f"         - {p}" for p in probs))
            raise c.Fail(f"doccheck found {len(probs)} problem(s)")
        self.ok("doccheck clean")
        # 3 scan
        try:
            hits = scan.run(root, quiet=True)
        except c.Fail as e:
            self.refuse(f"privacy scan: {e}")
        if hits:
            self.lines.append("  FAIL private words:\n" + "\n".join(f"         - {r}:{i}: {w}" for r, i, w in hits))
            raise c.Fail(f"privacy scan found {len(hits)} hit(s)")
        self.ok("privacy scan clean")
        # 4 unit tests
        if cfg.get("tests"):
            r = subprocess.run(cfg["tests"], shell=True, cwd=root, capture_output=True, text=True)
            if r.returncode != 0:
                tail = (r.stdout + r.stderr).strip().split("\n")[-15:]
                self.lines.append("  FAIL unit tests:\n" + "\n".join(f"         {t}" for t in tail))
                raise c.Fail(f"unit tests failed (`{cfg['tests']}`)")
            self.ok(f"unit tests passed (`{cfg['tests']}`)")
        else:
            self.lines.append("  note no `tests` command configured")
        # 5 mapping
        feats = c.load_features(root, cfg)
        own = c.Ownership(root, cfg, feats)
        files, touched, unowned = c.map_changes_with_functions(root, cfg, own, base)
        if unowned:
            self.lines.append("  FAIL unowned changes:\n" + "\n".join(f"         - {u}" for u in unowned))
            raise c.Fail("changed code that no feature owns")
        extra = self.record_listed_features(body, feats)
        touched |= extra
        self.write_features_touched(rel, body, touched)
        rel, meta, body = c.load_record(root, cfg, version)
        self.ok(f"{len(files)} file(s) changed; features touched: {', '.join(sorted(touched)) or 'none'}")
        # 6 docs changed with the code
        waivers = c.record_waivers(body)
        changed = set(files)
        for n in sorted(touched):
            if feats[n].path in changed:
                continue
            if n in waivers:
                self.lines.append(f"  note {n}: doc unchanged, waived: {waivers[n]}")
                continue
            self.refuse(f"feature `{n}` changed but {feats[n].path} did not (edit it, or waive it in the record with a reason)")
        self.ok("every touched feature's doc changed (or is waived)")
        # 7 checks recorded
        results = c.record_results(body)
        required = [(n, cid, tags, text) for n in sorted(touched) for cid, tags, text in feats[n].checks]
        required += c.shared_required(feats, touched)
        missing, failed, bad_notrun, counts = [], [], [], {"pass": 0, "unit": 0, "not run": 0}
        for fname, cid, tags, text in required:
            if "unit" in tags and cid not in results:
                counts["unit"] += 1
                continue
            if cid not in results:
                missing.append(f"({cid}) [{fname}] {text}")
                continue
            res, note = results[cid]
            if res == "fail":
                failed.append(f"({cid}) {note}")
            elif res == "not run":
                if not note:
                    bad_notrun.append(cid)
                counts["not run"] += 1
            else:
                counts["pass"] += 1
        if missing:
            self.lines.append("  FAIL checks not recorded:\n" + "\n".join(f"         - {m}" for m in missing))
            raise c.Fail(f"{len(missing)} required check(s) have no result in the record")
        if failed:
            self.lines.append("  FAIL failing checks:\n" + "\n".join(f"         - {m}" for m in failed))
            raise c.Fail(f"{len(failed)} check(s) are recorded as fail")
        if bad_notrun:
            self.refuse(f"`not run` needs a reason: {', '.join(bad_notrun)}")
        self.ok(f"checks: {counts['pass']} pass, {counts['unit']} by unit tests, {counts['not run']} not run (with reasons), {len(required)} required")
        self.not_run = list(dict.fromkeys((cid, results[cid][1]) for _, cid, _, _ in required if cid in results and results[cid][0] == "not run"))
        # 8 review
        code_changed = [f for f in files if any(f.startswith(p.rstrip("/") + "/") or f == p for p in cfg["reviewPaths"])]
        review = c.strip_comments(c.record_section(body, "Review"))   # the template's own hint mentions a waiver
        if code_changed:
            if not c.section_filled(review):
                self.refuse("code changed but the Review section is empty (independent review, or `waived by Rhea <date>`)")
            if re.search(r"waived by Rhea", review or "", re.I):
                self.lines.append("  note review waived by Rhea")
            else:
                self.ok("review recorded")
        else:
            self.ok("no code change under reviewPaths; review not required")
        # 9 title
        if "<what this release does>" in body:
            self.refuse(f"{rel}: the title is still the template's")
        self.unverified = c.record_section(body, "Unverified") or ""
        self.version, self.files, self.touched = version, files, touched
        self.code_changed = bool(code_changed)
        if c.is_protocol2(meta):
            self.protocol2(rel, base, body, version, meta)
        elif c.needs_protocol2(cfg, version):
            self.refuse(f"{rel} lacks `protocol: 2` in its frontmatter (required from {cfg['protocol2From']}); the rules can't be switched off by deleting it")
        else:
            self.lines.append("  note protocol 1 record: rules 10 to 13 not applied")
        return version

    def protocol2(self, rel, base, body, version, meta):
        root, cfg = self.root, self.cfg
        # 10 page checks
        setup = {}
        for line in c.bullets(c.record_section(body, "Setup")):
            m = re.match(r"^-\s*([\w.-]+)\s+(done|not run)\b\s*:?\s*(.*)$", line, re.I)
            if m:
                setup[m.group(1)] = (m.group(2).lower(), m.group(3).strip())
        for pc in cfg.get("pageChecks") or []:
            res = setup.get(pc["id"])
            if not res:
                self.refuse(f"page check `{pc['id']}` is not recorded under Setup (`- {pc['id']} done: what was seen`)")
            if res[0] == "not run" and (not res[1] or res[1].lower() == "pending"):
                self.refuse(f"page check `{pc['id']}` is still pending: run it on every page this chat uses ({pc['script']})")
            if res[0] == "done" and not res[1]:
                self.refuse(f"page check `{pc['id']}`: say what was seen")
        self.ok(f"page checks recorded ({len(cfg.get('pageChecks') or [])})")
        # 14 the general traps were read before code changed (they left the skill for docs/foundry-traps.md, 2026-11-10)
        if self.code_changed:
            res = setup.get(c.TRAPS_ID)
            if not res or res[0] != "done" or not res[1]:
                self.refuse(f"code changed but Setup has no `- {c.TRAPS_ID} done: <what was read>`: run `guide traps <words for what the "
                            f"change touches>` ({c.TRAPS_DOC} in the tools repo), read what it prints, then record it")
            self.ok(f"general traps read ({res[1][:60]})")
        else:
            self.ok("no code change under reviewPaths; traps line not required")
        # 11 questions asked first
        asked = {}
        for l in c.bullets(c.record_section(body, "Asked first")):
            m = re.match(r"^-\s*(q-\d+)\s+(pending\s*$|asked\b|answered\b|dropped\b)", l)
            if m:
                asked[m.group(1)] = m.group(2).strip()
        due = meta.get("askFirst") or []
        due = due if isinstance(due, list) else [due]
        for q in due:
            if q not in asked:
                self.refuse(f"{q} was due to be asked first (frontmatter askFirst) but has no line under Asked first")
        pend = [q for q, s in asked.items() if s == "pending"]
        if pend:
            self.refuse("questions to ask Rhea first are still pending: " + ", ".join(pend))
        self.ok(f"questions asked first: {len(due)}")
        # 12 unverified
        items, probs = c.read_unverified(root, cfg)
        if items is None:
            self.refuse(f"{cfg['unverified']} is missing: `guide unverified add \"<text>\"` makes it")
        if probs:
            self.lines.append("  FAIL unverified list:\n" + "\n".join(f"         - {p}" for p in probs))
            raise c.Fail(f"{cfg['unverified']} has {len(probs)} malformed line(s)")
        lines = c.bullets(self.unverified)
        if not lines:
            self.refuse("the record's Unverified section is empty (`guide unverified add`, or `- none`)")
        for l in lines:
            if re.match(r"^-\s*none\b", l, re.I):
                continue
            m = re.match(r"^-\s*\((u-\d+)\)", l)
            if not m:
                self.refuse(f"an Unverified line isn't in the running list (add it with `guide unverified add`): {l[:80]}")
            if m.group(1) not in items:
                self.refuse(f"{m.group(1)} is in the record but not in {cfg['unverified']}")
        open_now = {k for k, i in items.items() if i["status"] == "open"}
        old, _ = c.read_unverified(root, cfg, base)
        gone = sorted(set(old or {}) - set(items))
        if gone:
            self.refuse(f"item(s) removed from {cfg['unverified']}: {', '.join(gone)}; close them in place (verified ... or dropped ... with a reason)")
        open_then = {k for k, i in (old or {}).items() if i["status"] == "open"}
        lim = cfg["unverifiedLimit"]
        closed = {k for k in open_then if items[k]["status"] in ("verified", "dropped")}
        if len(open_then) > lim:
            need = min(cfg["closeOutAtLeast"], len(open_then) - lim)
            if len(closed) < need:
                self.refuse(f"close-out pass needed: {len(open_then)} unverified items were open at this release's start (limit {lim}); "
                            f"close at least {need} in {cfg['unverified']} (closed so far: {len(closed)})")
        self.ok(f"unverified: {len(open_now)} open (limit {lim}); {len(closed)} closed in this release")
        self.open_unverified = len(open_now)
        # 13 lessons
        bad = [line for line, kind, _ in c.learned(body) if kind is None]
        if bad:
            self.refuse("lessons must end with their home (`→ filed: <where>`): " + "; ".join(b[:60] for b in bad))
        if c.needs_lesson_scope(self.cfg, version, meta):
            probs = c.lesson_scope_problems(body)
            if probs:
                self.refuse("lessons: " + " | ".join(probs))
        owed = [line for line, kind, _ in c.learned(body) if kind == "owed"]
        if owed:
            self.lines.append(f"  note {len(owed)} lesson(s) still owed: `guide finish` refuses until they are filed")
        self.ok("every lesson names its home")

    def record_listed_features(self, body, feats):
        out = set()
        for line in (c.record_section(body, "Features touched") or "").split("\n"):
            m = re.match(r"^\s*-\s*([a-z][a-z0-9-]*)\s*(\(|$)", line)
            if m and m.group(1) in feats:
                out.add(m.group(1))
        return out

    def write_features_touched(self, rel, body, touched):
        """Keep the section's own lines (waivers, notes); make sure every touched feature is listed."""
        sec = c.record_section(body, "Features touched")
        if sec is None:
            return
        listed = self.record_listed_features(body, {n: 1 for n in touched})
        add = [f"- {n} (from the diff)" for n in sorted(touched) if n not in listed]
        if not add:
            return
        new_sec = sec.rstrip("\n") + "\n" + "\n".join(add) + "\n\n"
        text = c.read(self.root, rel)
        m = re.search(r"^##\s+Features touched\b[^\n]*$", text, re.M)
        start = m.end()
        text = text[:start] + new_sec + text[start + len(sec):]
        with open(os.path.join(self.root, rel), "w", encoding="utf-8") as f:
            f.write(text)

    def build_zip(self):
        z = self.cfg["zip"]
        if not z.get("path"):
            self.lines.append("  note no zip configured; nothing built")
            return None
        include = z.get("include") or []
        members = []
        for rel in c.worktree_files(self.root):
            if rel in (c.WORDS_NAME, c.STAMP_NAME) or rel == z["path"]:
                continue
            if any(rel == inc or rel.startswith(inc.rstrip("/") + "/") for inc in include):
                members.append(rel)
        if self.cfg["manifest"] not in members:
            raise c.Fail(f"zip include list does not cover {self.cfg['manifest']}")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for rel in sorted(members):
                info = zipfile.ZipInfo(rel, date_time=(2020, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                with open(os.path.join(self.root, rel), "rb") as f:
                    zf.writestr(info, f.read())
        os.makedirs(os.path.dirname(os.path.join(self.root, z["path"])) or ".", exist_ok=True)
        with open(os.path.join(self.root, z["path"]), "wb") as f:
            f.write(buf.getvalue())
        with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as zf:
            v = json.loads(zf.read(self.cfg["manifest"]))["version"]
        if v != self.version:
            raise c.Fail(f"the built zip says version {v}, not {self.version}")
        self.ok(f"built {z['path']} ({len(members)} files, version {v})")
        return z["path"]

    def stamp(self):
        tree = c.tree_hash_worktree(self.root, self.cfg)
        c.write_stamp(self.root, {"version": self.version, "tree": tree, "date": datetime.datetime.now().isoformat(timespec="seconds")})
        if not c.is_ignored(self.root, c.STAMP_NAME):
            self.lines.append(f"  WARN {c.STAMP_NAME} is not git-ignored")
        self.ok(f"stamp written for tree {tree[:12]}")

    def summary(self):
        out = [f"gate: {'REFUSED' if self.refused else 'PASSED'}"] + self.lines
        if getattr(self, "touched", None) is not None:
            out.append("\nReport skeleton for Rhea:")
            out.append(f"  version {self.version}; features touched: {', '.join(sorted(self.touched)) or 'none'}")
            if self.not_run:
                out.append("  not run: " + "; ".join(f"{cid} ({n})" for cid, n in self.not_run))
            if getattr(self, "open_unverified", None) is not None:
                out.append(f"  unverified: {self.open_unverified} open in {self.cfg['unverified']} (this release's in the record)")
            else:
                uv = [l.strip() for l in c.strip_comments(self.unverified).split("\n") if l.strip()]
                out.append("  unverified: " + ("; ".join(uv) if uv else "(record says nothing)"))
        return "\n".join(out)


def run_hook(root, cfg, stdin):
    """pre-push: refuse a push to main whose commit tree isn't the one the gate stamped."""
    main = cfg["mainBranch"]
    stamp = c.read_stamp(root)
    probs = []
    for line in stdin.read().split("\n"):
        parts = line.split()
        if len(parts) != 4:
            continue
        local_ref, local_sha, remote_ref, remote_sha = parts
        if remote_ref != f"refs/heads/{main}" or set(local_sha) == {"0"}:
            continue
        if not stamp:
            probs.append(f"pushing {main} but the gate has never passed here (no {c.STAMP_NAME})")
            continue
        tree = c.tree_hash_commit(root, cfg, local_sha)
        if tree != stamp.get("tree"):
            probs.append(f"pushing {main} at {local_sha[:9]}: its tree is not the one the gate stamped; run `gate` again and commit")
        v = c.manifest_version(root, cfg, local_sha)
        if v != stamp.get("version"):
            probs.append(f"pushing {main}: manifest version {v} is not the stamped {stamp.get('version')}")
        z = cfg["zip"].get("path")
        if z:
            try:
                data = subprocess.run(["git", "show", f"{local_sha}:{z}"], cwd=root, capture_output=True).stdout
                with zipfile.ZipFile(io.BytesIO(data)) as zf:
                    zv = json.loads(zf.read(cfg["manifest"]))["version"]
                if zv != v:
                    probs.append(f"pushing {main}: the committed zip says {zv}, the manifest {v}")
            except Exception as e:
                probs.append(f"pushing {main}: the committed zip can't be read ({e})")
    if probs:
        print("pre-push gate REFUSED:", file=sys.stderr)
        for p in probs:
            print("  -", p, file=sys.stderr)
        return 1
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        root = c.find_root()
        cfg = c.load_config(root)
    except c.Fail as e:
        c.die(str(e), 1)
    if "--hook" in argv:
        sys.exit(run_hook(root, cfg, sys.stdin))
    g = Gate(root, cfg)
    try:
        g.run_checks()
        if "--check" not in argv:
            g.build_zip()
            g.stamp()
    except c.Fail as e:
        g.refused = True
        print(g.summary())
        c.die(str(e))
    print(g.summary())
    sys.exit(0)
