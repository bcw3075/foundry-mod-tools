"""Tests for guide, gate, doccheck, scan and the pre-push hook, against a generated fixture repo.
Run: python3 -m unittest discover -s tests   (from the foundry-mod-tools root)"""
import json, os, re, shutil, subprocess, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fixture
from fixture import git, write, TOOLS


def run(repo, script, *args, stdin=None):
    env = dict(os.environ, MODTOOLS=TOOLS)
    r = subprocess.run(["python3", os.path.join(TOOLS, script + ".py"), *args], cwd=repo, capture_output=True, text=True, input=stdin, env=env)
    return r.returncode, r.stdout + r.stderr


def read(repo, rel):
    with open(os.path.join(repo, rel), encoding="utf-8") as f:
        return f.read()


def append(repo, rel, text):
    write(repo, rel, read(repo, rel) + text)


def set_version(repo, v):
    m = json.loads(read(repo, "module.json"))
    m["version"] = v
    write(repo, "module.json", json.dumps(m, indent=1) + "\n")


def fill_record(repo, version, checks, review="- reviewer: no findings (verified: read the diff)\n", title="Alpha returns one again", unverified="- none\n", learned="- [module] nothing new → filed: nowhere needed\n"):
    rel = f"docs/changes/{version}.md"
    text = read(repo, rel).replace("<what this release does>", title)
    def put(sec, body):
        nonlocal text   # replace the whole section body, keeping its heading
        text = re.sub(rf"(^## {re.escape(sec)}[^\n]*\n)(.*?)(?=^## |\Z)", lambda m: m.group(1) + body + "\n", text, count=1, flags=re.M | re.S)
    put("Checks", checks)
    put("Review", review)
    put("Unverified", unverified)
    put("Learned, and where it was filed", learned)
    write(repo, rel, text)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="modtools-")
        self.repo, self.remote = fixture.build(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def happy_change(self, version="0.2.0"):
        """Start a release, change alpha and its doc, bump, record everything the gate wants."""
        code, out = run(self.repo, "guide", "start", version)
        self.assertEqual(code, 0, out)
        write(self.repo, "scripts/alpha.mjs", "export function alphaOne() { return 1; } // v2\n")
        append(self.repo, "docs/features/alpha.md", "- 0.2.0: a comment was added\n")
        set_version(self.repo, version)
        fill_record(self.repo, version, "- al-1 pass: returned 1 through the API\n- al-3 pass: alpha fine after beta\n- be-2 not run: beta untouched, nothing to re-run\n")


class TestGuide(Base):
    def test_map_lists_features(self):
        code, out = run(self.repo, "guide")
        self.assertEqual(code, 0, out)
        for n in ("alpha", "beta", "gamma"):
            self.assertIn(n, out)
        self.assertIn("3 features", out)

    def test_file_maps_to_its_feature(self):
        code, out = run(self.repo, "guide", "scripts/alpha.mjs")
        self.assertEqual(code, 0, out)
        self.assertIn("Features touched: alpha", out)
        self.assertIn("(al-1)", out)
        self.assertIn("Never return two", out)                 # traps printed
        self.assertIn("(be-2) [beta]", out)                    # shared item from beta
        self.assertNotIn("(ga-1)", out)

    def test_function_owned_file_maps_to_all_its_features(self):
        code, out = run(self.repo, "guide", "scripts/big.mjs")
        self.assertEqual(code, 0, out)
        self.assertIn("Features touched: beta, gamma", out)

    def test_diff_maps_changed_function_only(self):
        run(self.repo, "guide", "start", "0.2.0")
        write(self.repo, "scripts/big.mjs", fixture.BIG.replace("=> 'c'", "=> 'C'"))
        code, out = run(self.repo, "guide", "--diff")
        self.assertEqual(code, 0, out)
        self.assertIn("Features touched: gamma", out)
        self.assertNotIn("beta", out.split("Features touched")[1].split("\n")[0])

    def test_diff_reports_unowned_function(self):
        run(self.repo, "guide", "start", "0.2.0")
        append(self.repo, "scripts/big.mjs", "export function stray() {}\n")
        code, out = run(self.repo, "guide", "--diff")
        self.assertNotEqual(code, 0)
        self.assertIn("UNOWNED", out)
        self.assertIn("stray", out)

    def test_unknown_name_is_said(self):
        code, out = run(self.repo, "guide", "nope")
        self.assertIn("UNKNOWN", out)

    def test_start_creates_record_and_hook(self):
        code, out = run(self.repo, "guide", "start", "0.2.0", "Alpha", "v2")
        self.assertEqual(code, 0, out)
        self.assertTrue(os.path.isfile(os.path.join(self.repo, "docs/changes/0.2.0.md")))
        self.assertIn("Alpha v2", read(self.repo, "docs/changes/0.2.0.md"))
        self.assertEqual(git(self.repo, "config", "--get", "core.hooksPath").strip(), "tools/githooks")
        self.assertIn("base:", read(self.repo, "docs/changes/0.2.0.md"))

    def test_start_reports_missing_setup(self):
        os.remove(os.path.join(self.repo, ".private-words"))
        shutil.rmtree(os.path.join(self.repo, "tools/test/data"))
        code, out = run(self.repo, "guide", "start", "0.2.0")
        self.assertNotEqual(code, 0)
        self.assertIn(".private-words is missing", out)
        self.assertIn("tools/test/data is missing", out)

    def test_start_rejects_bad_version(self):
        code, out = run(self.repo, "guide", "start", "two")
        self.assertNotEqual(code, 0)

    def test_index_regenerates_and_doccheck_catches_hand_edit(self):
        dev = read(self.repo, "docs/DEVELOPING.md")
        write(self.repo, "docs/DEVELOPING.md", dev.replace("| alpha |", "| alpha (edited) |"))
        code, out = run(self.repo, "doccheck")
        self.assertNotEqual(code, 0)
        self.assertIn("feature index is stale", out)
        code, out = run(self.repo, "guide", "--index")
        self.assertEqual(code, 0, out)
        code, out = run(self.repo, "doccheck")
        self.assertEqual(code, 0, out)

    def test_new_feature_from_template(self):
        code, out = run(self.repo, "guide", "new-feature", "delta-ray")
        self.assertEqual(code, 0, out)
        text = read(self.repo, "docs/features/delta-ray.md")
        self.assertIn("feature: delta-ray", text)
        self.assertIn("(dr-1)", text)

    def test_finish_lists_what_is_unsaved(self):
        self.happy_change()
        code, out = run(self.repo, "guide", "finish")
        self.assertNotEqual(code, 0)
        self.assertIn("uncommitted changes", out)
        self.assertIn("no gate stamp", out)
        self.assertIn("the module's project doc", out)


class TestDoccheckAndScan(Base):
    def test_clean_fixture_passes(self):
        code, out = run(self.repo, "doccheck")
        self.assertEqual(code, 0, out)
        code, out = run(self.repo, "scan")
        self.assertEqual(code, 0, out)

    def test_orphan_function_is_caught(self):
        append(self.repo, "scripts/big.mjs", "export function orphanFn() {}\n")
        code, out = run(self.repo, "doccheck")
        self.assertNotEqual(code, 0)
        self.assertIn("orphan: scripts/big.mjs `orphanFn`", out)

    def test_orphan_file_is_caught(self):
        write(self.repo, "scripts/zeta.mjs", "export function zeta() {}\n")
        git(self.repo, "add", "scripts/zeta.mjs")
        code, out = run(self.repo, "doccheck")
        self.assertNotEqual(code, 0)
        self.assertIn("orphan: scripts/zeta.mjs", out)

    def test_double_owner_and_vanished_function(self):
        append(self.repo, "docs/features/gamma.md", "")
        write(self.repo, "docs/features/gamma.md", read(self.repo, "docs/features/gamma.md").replace("functions: [bigC, BigWindow]", "functions: [bigC, BigWindow, bigA, ghost]"))
        code, out = run(self.repo, "doccheck")
        self.assertNotEqual(code, 0)
        self.assertIn("owned by more than one feature: beta, gamma", out)
        self.assertIn("`ghost`", out)

    def test_duplicate_check_id_and_missing_name(self):
        append(self.repo, "docs/features/gamma.md", "- (al-1) {live} duplicate id\n")
        append(self.repo, "docs/DEVELOPING.md", "\nSee `noSuchFunction`.\n")
        code, out = run(self.repo, "doccheck")
        self.assertNotEqual(code, 0)
        self.assertIn("check id al-1 used in both", out)
        self.assertIn("`noSuchFunction` is not found", out)

    def test_external_names_file_and_untracked_doc_count_as_known(self):
        append(self.repo, "docs/DEVELOPING.md", "\nPF2e's `measureDistanceCuboid` and the new `docs/features/delta.md`.\n")
        code, out = run(self.repo, "doccheck")
        self.assertIn("`measureDistanceCuboid` is not found", out)
        self.assertIn("`delta.md` is not found", out)
        write(self.repo, "docs/external-names.txt", "# other systems' code\nmeasureDistanceCuboid\n")
        run(self.repo, "guide", "new-feature", "delta")      # untracked, not yet committed
        write(self.repo, "docs/features/delta.md", read(self.repo, "docs/features/delta.md").replace("- (d-1) {live} ", "- (d-1) {live} delta still works"))
        run(self.repo, "guide", "--index")
        code, out = run(self.repo, "doccheck")
        self.assertEqual(code, 0, out)

    def test_bad_shared_tag(self):
        append(self.repo, "docs/features/gamma.md", "- (ga-9) {shared:omega} nope\n")
        code, out = run(self.repo, "doccheck")
        self.assertIn("shared:omega but no such feature", out)

    def test_scan_catches_planted_word_in_tracked_and_untracked_files(self):
        append(self.repo, "docs/features/alpha.md", "Tested on the Stoneclaim map.\n")
        write(self.repo, "docs/notes.md", "near redthorn hollow\n")   # untracked, different case
        code, out = run(self.repo, "scan")
        self.assertNotEqual(code, 0)
        self.assertIn("docs/features/alpha.md", out)
        self.assertIn("docs/notes.md", out)
        self.assertNotIn("Stoneclaimed", out)

    def test_scan_whole_words_only(self):
        append(self.repo, "docs/features/alpha.md", "Stoneclaimed is not the word.\n")
        code, out = run(self.repo, "scan")
        self.assertEqual(code, 0, out)

    def test_scan_fails_closed(self):
        os.remove(os.path.join(self.repo, ".private-words"))
        code, out = run(self.repo, "scan")
        self.assertNotEqual(code, 0)
        self.assertIn("missing", out)
        write(self.repo, ".private-words", "# nothing\n")
        code, out = run(self.repo, "scan")
        self.assertNotEqual(code, 0)
        self.assertIn("no words", out)

    def test_scan_refuses_tracked_word_list(self):
        write(self.repo, ".gitignore", ".modtools-stamp.json\n")
        git(self.repo, "add", "-f", ".private-words")
        code, out = run(self.repo, "scan")
        self.assertNotEqual(code, 0)
        self.assertIn("git-ignored", out)


class TestGate(Base):
    def test_passes_when_all_hold_and_builds_zip_and_stamp(self):
        self.happy_change()
        code, out = run(self.repo, "gate")
        self.assertEqual(code, 0, out)
        self.assertIn("PASSED", out)
        self.assertIn("Report skeleton", out)
        self.assertIn("be-2 (beta untouched", out)
        self.assertIn("1 open in docs/unverified.md", out)
        import zipfile
        with zipfile.ZipFile(os.path.join(self.repo, "dist/fixmod.zip")) as zf:
            names = zf.namelist()
            self.assertIn("scripts/alpha.mjs", names)
            self.assertIn("module.json", names)
            self.assertNotIn(".private-words", names)
            self.assertNotIn("docs/features/alpha.md", names)
            self.assertEqual(json.loads(zf.read("module.json"))["version"], "0.2.0")
        self.assertTrue(os.path.isfile(os.path.join(self.repo, ".modtools-stamp.json")))
        rec = read(self.repo, "docs/changes/0.2.0.md")
        self.assertIn("- alpha (from the diff)", rec)
        # running again is idempotent
        code, out = run(self.repo, "gate")
        self.assertEqual(code, 0, out)
        self.assertEqual(rec, read(self.repo, "docs/changes/0.2.0.md"))

    def test_check_mode_builds_nothing(self):
        self.happy_change()
        code, out = run(self.repo, "gate", "--check")
        self.assertEqual(code, 0, out)
        self.assertFalse(os.path.isfile(os.path.join(self.repo, ".modtools-stamp.json")))

    def refuse(self, expect):
        code, out = run(self.repo, "gate")
        self.assertEqual(code, 2, out)
        self.assertIn("REFUSED", out)
        self.assertIn(expect, out)
        self.assertFalse(os.path.isfile(os.path.join(self.repo, ".modtools-stamp.json")), "a refusal must leave no stamp")
        return out

    def test_refuses_without_record(self):
        set_version(self.repo, "0.2.0")
        self.refuse("no change record")

    def test_refuses_unbumped_version(self):
        self.happy_change()
        set_version(self.repo, "0.1.0")
        self.refuse("no change record at docs/changes/0.1.0.md")
        # and with a record for the current version but no bump since its base
        run(self.repo, "guide", "start", "0.1.0")
        self.refuse("bump it")

    def test_refuses_orphan(self):
        self.happy_change()
        append(self.repo, "scripts/big.mjs", "export function orphanFn() {}\n")
        self.refuse("orphanFn")

    def test_refuses_private_word(self):
        self.happy_change()
        append(self.repo, "docs/changes/0.2.0.md", "\nTested at Stoneclaim.\n")
        self.refuse("private words")

    def test_refuses_without_word_list(self):
        self.happy_change()
        os.remove(os.path.join(self.repo, ".private-words"))
        self.refuse("privacy scan")

    def test_refuses_failing_unit_tests(self):
        self.happy_change()
        write(self.repo, "tools/test/unit.py", "import sys\nprint('alpha broke')\nsys.exit(1)\n")
        out = self.refuse("unit tests failed")
        self.assertIn("alpha broke", out)

    def test_refuses_doc_unchanged_unless_waived(self):
        self.happy_change()
        git(self.repo, "checkout", "--", "docs/features/alpha.md")
        self.refuse("docs/features/alpha.md did not")
        rec = read(self.repo, "docs/changes/0.2.0.md")
        write(self.repo, "docs/changes/0.2.0.md", rec.replace("## Features touched\n", "## Features touched\n- doc-unchanged alpha: a comment only, the doc already says it\n"))
        code, out = run(self.repo, "gate")
        self.assertEqual(code, 0, out)
        self.assertIn("waived: a comment only", out)

    def test_refuses_missing_check_and_shared_item(self):
        self.happy_change()
        fill_record(self.repo, "0.2.0", "- al-1 pass: ok\n")   # al-3 and shared be-2 missing
        out = self.refuse("no result in the record")
        self.assertIn("(al-3)", out)
        self.assertIn("(be-2) [beta]", out)
        self.assertNotIn("(al-2)", out)   # unit item is covered by the test run

    def test_refuses_fail_and_notrun_without_reason(self):
        self.happy_change()
        fill_record(self.repo, "0.2.0", "- al-1 fail: returned 2\n- al-3 pass: ok\n- be-2 pass: ok\n")
        self.refuse("recorded as fail")
        fill_record(self.repo, "0.2.0", "- al-1 pass: ok\n- al-3 pass: ok\n- be-2 not run\n")
        self.refuse("`not run` needs a reason")

    def test_refuses_empty_review_when_code_changed_and_accepts_waiver(self):
        self.happy_change()
        fill_record(self.repo, "0.2.0", "- al-1 pass: ok\n- al-3 pass: ok\n- be-2 pass: ok\n", review="")
        self.refuse("Review section is empty")
        fill_record(self.repo, "0.2.0", "- al-1 pass: ok\n- al-3 pass: ok\n- be-2 pass: ok\n", review="waived by Rhea 2026-11-08: one-line comment\n")
        code, out = run(self.repo, "gate")
        self.assertEqual(code, 0, out)
        self.assertIn("review waived", out)

    def test_template_hint_is_not_a_review_or_a_waiver(self):
        # the record template's Review hint runs over two lines and names a waiver; left as it is, the section is empty (found 2026-11-08)
        self.happy_change()
        hint = "<!-- The independent reviewer's findings, each marked verified true or false and what was done.\n     Required when code changed; otherwise write `waived by Rhea <date>` with her reason. -->\n"
        fill_record(self.repo, "0.2.0", "- al-1 pass: ok\n- al-3 pass: ok\n- be-2 pass: ok\n", review=hint)
        out = self.refuse("Review section is empty")
        self.assertNotIn("review waived", out or "")

    def test_review_not_required_for_doc_only_release(self):
        run(self.repo, "guide", "start", "0.2.0")
        set_version(self.repo, "0.2.0")
        append(self.repo, "docs/features/alpha.md", "- clarified\n")
        fill_record(self.repo, "0.2.0", "- none needed\n", review="")
        code, out = run(self.repo, "gate")
        self.assertEqual(code, 0, out)
        self.assertIn("review not required", out)

    def test_refuses_template_title(self):
        self.happy_change()
        rec = read(self.repo, "docs/changes/0.2.0.md").replace("Alpha returns one again", "<what this release does>")
        write(self.repo, "docs/changes/0.2.0.md", rec)
        self.refuse("title is still the template")

    def test_refuses_stale_index(self):
        self.happy_change()
        run(self.repo, "guide", "new-feature", "delta")
        self.refuse("feature index is stale")

    def test_record_can_add_a_feature_the_diff_cannot_see(self):
        run(self.repo, "guide", "start", "0.2.0")
        set_version(self.repo, "0.2.0")
        append(self.repo, "docs/features/gamma.md", "- behaviour note\n")
        rec = read(self.repo, "docs/changes/0.2.0.md").replace("## Features touched\n", "## Features touched\n- gamma\n")
        write(self.repo, "docs/changes/0.2.0.md", rec)
        fill_record(self.repo, "0.2.0", "- x pass: y\n", review="")
        out = self.refuse("no result in the record")
        self.assertIn("(ga-1)", out)


class TestHook(Base):
    def commit(self, msg):
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", msg)

    def push(self, ref="main"):
        r = subprocess.run(["git", "push", "origin", ref], cwd=self.repo, capture_output=True, text=True, env=dict(os.environ, MODTOOLS=TOOLS))
        return r.returncode, r.stdout + r.stderr

    def test_push_to_main_refused_without_gate_and_allowed_after(self):
        self.happy_change()
        self.commit("0.2.0 without gate")
        code, out = self.push()
        self.assertNotEqual(code, 0, out)
        self.assertIn("gate has never passed", out)
        code, out = run(self.repo, "gate")
        self.assertEqual(code, 0, out)
        self.commit("0.2.0 gated")
        code, out = self.push()
        self.assertEqual(code, 0, out)
        self.assertIn("0.2.0 gated", git(self.repo, "log", "origin/main", "-1", "--format=%s"))

    def test_change_after_gate_is_refused(self):
        self.happy_change()
        code, out = run(self.repo, "gate")
        self.assertEqual(code, 0, out)
        append(self.repo, "scripts/alpha.mjs", "// sneaked in after the gate\n")
        self.commit("after gate")
        code, out = self.push()
        self.assertNotEqual(code, 0, out)
        self.assertIn("not the one the gate stamped", out)

    def test_other_branches_are_not_gated(self):
        self.happy_change()
        self.commit("work")
        code, out = self.push("main:work")
        self.assertEqual(code, 0, out)

    def test_hook_refuses_zip_version_mismatch(self):
        self.happy_change()
        code, out = run(self.repo, "gate")
        self.assertEqual(code, 0, out)
        # replace the zip with one that says the old version; the tree hash ignores the zip, so only this check catches it
        subprocess.run(["python3", "-c", "import zipfile,json;z=zipfile.ZipFile('dist/fixmod.zip','w');z.writestr('module.json',json.dumps({'version':'0.1.0'}));z.close()"], cwd=self.repo, check=True)
        self.commit("bad zip")
        code, out = self.push()
        self.assertNotEqual(code, 0, out)
        self.assertIn("committed zip says 0.1.0", out)

    def test_no_verify_is_the_only_way_round(self):
        self.happy_change()
        self.commit("ungated")
        r = subprocess.run(["git", "push", "--no-verify", "origin", "main"], cwd=self.repo, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)   # documented limit: the skill forbids this flag


PLAN = """# Fixture plan

**Status:** fine.

## Next
**Next, in Rhea's order:** the Change button, player reactions.

## Build lock
<!-- written by guide start, cleared by guide finish -->

## Open questions
- (q-1) [since 0.0.8] open: Should escaped tokens stay hidden?
- (q-2) [since 0.1.0] open: A newer question?
- (q-3) [since 0.0.8] answered 2026-11-09: Old one.
"""


class TestTightening(Base):
    """The seven changes agreed 2026-11-08 (claude/process-tightening.md), plus the duplicate fix."""

    def use_plan(self, plan=PLAN, records=("0.0.8", "0.0.9")):
        cfg = json.loads(read(self.repo, ".modtools.json"))
        cfg["planDoc"] = "claude/fixture-plan.md"
        cfg["pageChecks"] = [{"id": "cal-off", "why": "the calendar window comes back", "script": "tools/setup/cal.js", "pages": "every page"}]
        cfg["handoff"] = {"load": "Load the fixture skills.", "where": ["claude/fixture.md (history)"]}
        write(self.repo, ".modtools.json", json.dumps(cfg, indent=1) + "\n")
        write(self.repo, "tools/setup/cal.js", "return 'calendar off';\n")
        for v in records:   # two old handoffs, so q-1 has been carried through two
            write(self.repo, f"docs/changes/{v}.md", f"---\nversion: {v}\nbase: x\n---\n# {v} — old (started 2026-01-01)\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "plan config")
        self.plan = os.path.join(self.tmp, "plan.md")
        write(self.tmp, "plan.md", plan)

    def start(self, version="0.2.0", *extra):
        return run(self.repo, "guide", "start", version, "Fixture change", "--plan", self.plan, *extra)

    def finish_change(self, version="0.2.0", asked="- q-1 asked 2026-11-09: stay hidden\n", setup="- cal-off done: setting off, window closed on both pages\n"):
        write(self.repo, "scripts/alpha.mjs", "export function alphaOne() { return 1; } // v2\n")
        append(self.repo, "docs/features/alpha.md", "- a comment was added\n")
        set_version(self.repo, version)
        fill_record(self.repo, version, "- al-1 pass: 1\n- al-3 pass: fine\n- be-2 not run: beta untouched\n")
        rel = f"docs/changes/{version}.md"
        text = read(self.repo, rel)
        text = re.sub(r"(^## Setup[^\n]*\n)(.*?)(?=^## )", lambda m: m.group(1) + setup + "\n", text, flags=re.M | re.S)
        text = re.sub(r"(^## Asked first[^\n]*\n)(.*?)(?=^## )", lambda m: m.group(1) + asked + "\n", text, flags=re.M | re.S)
        write(self.repo, rel, text)

    # change 6: one build chat at a time
    def test_start_needs_the_plan_and_writes_the_lock(self):
        self.use_plan()
        code, out = run(self.repo, "guide", "start", "0.2.0")
        self.assertNotEqual(code, 0)
        self.assertIn("--plan <file> is required", out)
        self.assertFalse(os.path.exists(os.path.join(self.repo, "docs/changes/0.2.0.md")))
        code, out = self.start()
        self.assertEqual(code, 0, out)
        self.assertIn("project_write it back", out)
        self.assertRegex(read(self.tmp, "plan.md"), r"- lock fixmod 0\.2\.0 started \S+ token \w+")
        code, out = self.start()           # the same chat again: fine
        self.assertEqual(code, 0, out)
        self.assertIn("already holds it", out)

    def test_second_chat_is_stopped_and_take_over_needs_rhea(self):
        self.use_plan()
        self.start()
        git(self.repo, "config", "--local", "modtools.lockToken", "other1")   # as a fresh clone in another chat
        code, out = self.start()
        self.assertNotEqual(code, 0)
        self.assertIn("another chat is building fixmod", out)
        code, out = self.start("0.2.0", "--take-over", "Rhea OK 2026-11-09: the old chat is archived")
        self.assertEqual(code, 0, out)
        self.assertIn("taken over", out)
        self.assertIn("token other1", read(self.tmp, "plan.md"))

    # change 5: questions don't sit
    def test_overdue_question_goes_first_and_gate_refuses_pending(self):
        self.use_plan()
        code, out = self.start()
        self.assertIn("ASK RHEA FIRST", out)
        self.assertIn("(q-1) since 0.0.8, carried 2", out)
        self.assertNotIn("(q-2)", out.split("ASK RHEA FIRST")[1].split("PAGE CHECKS")[0])   # carried once only
        self.assertNotIn("(q-3)", out)                                                     # answered
        self.assertIn("- q-1 pending", read(self.repo, "docs/changes/0.2.0.md"))
        self.finish_change(asked="- q-1 pending\n")
        code, out = run(self.repo, "gate", "--check")
        self.assertNotEqual(code, 0)
        self.assertIn("still pending", out)
        self.finish_change()
        code, out = run(self.repo, "gate", "--check")
        self.assertEqual(code, 0, out)

    # change 3: recurring traps are setup checks
    def test_page_checks_printed_and_required(self):
        self.use_plan()
        code, out = self.start()
        self.assertIn("[cal-off]", out)
        self.assertIn("return 'calendar off';", out)            # the script itself, ready to run
        self.assertIn("- cal-off not run: pending", read(self.repo, "docs/changes/0.2.0.md"))
        self.finish_change(setup="- cal-off not run: pending\n")
        code, out = run(self.repo, "gate", "--check")
        self.assertNotEqual(code, 0)
        self.assertIn("page check `cal-off` is still pending", out)

    def test_missing_page_check_script_is_a_setup_problem(self):
        self.use_plan()
        os.remove(os.path.join(self.repo, "tools/setup/cal.js"))
        code, out = self.start()
        self.assertNotEqual(code, 0)
        self.assertIn("page check script tools/setup/cal.js is missing", out)

    # change 2: one running list of unverified items
    def test_unverified_add_writes_list_and_record(self):
        self.use_plan()
        self.start()
        set_version(self.repo, "0.2.0")
        code, out = run(self.repo, "guide", "unverified", "add", "the player view")
        self.assertEqual(code, 0, out)
        self.assertIn("- (u-2) [0.2.0] open: the player view", read(self.repo, "docs/unverified.md"))
        self.assertIn("- (u-2) the player view", read(self.repo, "docs/changes/0.2.0.md"))
        code, out = run(self.repo, "guide", "unverified")
        self.assertIn("2 open", out)

    def test_gate_refuses_record_item_missing_from_list_and_bad_lines(self):
        self.use_plan()
        self.start()
        self.finish_change()
        fill_record(self.repo, "0.2.0", "- al-1 pass: 1\n- al-3 pass: fine\n- be-2 not run: beta untouched\n", unverified="- the player view\n")
        code, out = run(self.repo, "gate", "--check")
        self.assertIn("isn't in the running list", out)
        fill_record(self.repo, "0.2.0", "- al-1 pass: 1\n- al-3 pass: fine\n- be-2 not run: beta untouched\n", unverified="- (u-9) ghost\n")
        code, out = run(self.repo, "gate", "--check")
        self.assertIn("u-9 is in the record but not in", out)
        append(self.repo, "docs/unverified.md", "- (u-5) open the bad one\n")
        code, out = run(self.repo, "gate", "--check")
        self.assertIn("malformed", out)

    def test_close_out_pass_required_above_the_limit(self):
        write(self.repo, "docs/unverified.md", "# U\n\n" + "".join(f"- (u-{i}) [0.1.0] open: item {i}\n" for i in range(1, 12)))
        git(self.repo, "add", "-A"); git(self.repo, "commit", "-q", "-m", "eleven open")
        self.use_plan(records=())
        code, out = self.start()
        self.assertIn("CLOSE-OUT PASS due: this release must close at least 3", out)
        self.finish_change(asked="")
        code, out = run(self.repo, "gate", "--check")
        self.assertNotEqual(code, 0)
        self.assertIn("close-out pass needed", out)
        text = read(self.repo, "docs/unverified.md")
        text = text.replace("- (u-1) [0.1.0] open: item 1", "- (u-1) [0.1.0] verified 2026-11-09 in 0.2.0: item 1. Seen: it worked")
        text = text.replace("- (u-2) [0.1.0] open: item 2", "- (u-2) [0.1.0] dropped 2026-11-09: item 2. Why: built differently")
        write(self.repo, "docs/unverified.md", text)
        code, out = run(self.repo, "gate", "--check")
        self.assertIn("closed so far: 2", out)
        write(self.repo, "docs/unverified.md", text.replace("- (u-3) [0.1.0] open: item 3", "- (u-3) [0.1.0] verified 2026-11-09 in 0.2.0: item 3. Seen: ok"))
        code, out = run(self.repo, "gate", "--check")
        self.assertEqual(code, 0, out)
        self.assertIn("8 open (limit 8); 3 closed", out)

    # change 1: owed lessons can't wait
    def test_lesson_without_home_refused_and_owed_blocks_finish(self):
        self.use_plan()
        self.start()
        self.finish_change()
        fill_record(self.repo, "0.2.0", "- al-1 pass: 1\n- al-3 pass: fine\n- be-2 not run: beta untouched\n", learned="- a trap\n")
        code, out = run(self.repo, "gate", "--check")
        self.assertIn("lessons must end with their home", out)
        fill_record(self.repo, "0.2.0", "- al-1 pass: 1\n- al-3 pass: fine\n- be-2 not run: beta untouched\n",
                    learned="- [general] a trap → owed: the dev skill section 8\n- [general] a rule → card proposed: foundry-module-dev\n- [general] another → card proposed: foundry-module-dev\n")
        code, out = run(self.repo, "gate")
        self.assertEqual(code, 0, out)
        self.assertIn("1 lesson(s) still owed", out)
        git(self.repo, "add", "-A"); git(self.repo, "commit", "-q", "-m", "0.2.0")
        subprocess.run(["git", "push", "-q", "origin", "main"], cwd=self.repo, check=True, env=dict(os.environ, MODTOOLS=TOOLS))
        code, out = run(self.repo, "guide", "finish", "--plan", self.plan)
        self.assertNotEqual(code, 0)
        self.assertIn("lesson owed, file it now", out)
        self.assertEqual(out.count("🟡 Save the skill card for foundry-module-dev"), 1)
        self.assertIn("lock: kept", out)

    def test_owed_lesson_is_carried_into_the_next_record(self):
        self.use_plan()
        self.start()
        self.finish_change()
        fill_record(self.repo, "0.2.0", "- al-1 pass: 1\n- al-3 pass: fine\n- be-2 not run: beta untouched\n", learned="- a trap → owed: section 8\n")
        run(self.repo, "gate")
        git(self.repo, "add", "-A"); git(self.repo, "commit", "-q", "-m", "0.2.0")
        code, out = self.start("0.3.0")
        self.assertIn("CARRIED lesson", out)
        self.assertIn("- a trap → owed: section 8 (carried from 0.2.0)", read(self.repo, "docs/changes/0.3.0.md"))

    # change 7: leftover branches flagged; change 6: finish clears the lock
    def test_finish_flags_branches_and_clears_lock(self):
        self.use_plan()
        self.start()
        self.finish_change()
        code, out = run(self.repo, "gate")
        self.assertEqual(code, 0, out)
        git(self.repo, "add", "-A"); git(self.repo, "commit", "-q", "-m", "0.2.0")
        r = subprocess.run(["git", "push", "-q", "origin", "main"], cwd=self.repo, capture_output=True, text=True, env=dict(os.environ, MODTOOLS=TOOLS))
        self.assertEqual(r.returncode, 0, r.stderr)
        subprocess.run(["git", "push", "-q", "origin", "main:old-branch"], cwd=self.repo, check=True, env=dict(os.environ, MODTOOLS=TOOLS))
        code, out = run(self.repo, "guide", "finish", "--plan", self.plan)
        self.assertEqual(code, 0, out)
        self.assertIn("leftover branches kept for the end-of-project cleanup: old-branch", out)
        self.assertNotIn("🟡", out)          # Rhea 2026-11-09: listed for the end of the project, not asked each time
        self.assertIn("lock: cleared", out)
        self.assertNotIn("- lock fixmod", read(self.tmp, "plan.md"))

    # change 4: handoffs written by the script
    def test_handoff_layout(self):
        self.use_plan()
        self.start()
        self.finish_change()
        run(self.repo, "gate")
        git(self.repo, "add", "-A"); git(self.repo, "commit", "-q", "-m", "0.2.0")
        subprocess.run(["git", "push", "-q", "origin", "main"], cwd=self.repo, env=dict(os.environ, MODTOOLS=TOOLS))
        code, out = run(self.repo, "guide", "handoff", "--plan", self.plan)
        self.assertNotEqual(code, 0)
        self.assertIn("--state", out)
        code, out = run(self.repo, "guide", "handoff", "--plan", self.plan, "--state", "x")
        self.assertIn("still holds the build lock", out)          # review finding 5
        code, out = run(self.repo, "guide", "finish", "--plan", self.plan)
        self.assertEqual(code, 0, out)
        code, out = run(self.repo, "guide", "handoff", "--plan", self.plan, "--state", "PF2 Test running, paused")
        self.assertEqual(code, 0, out)
        for want in ("```", "fixmod 0.2.0 (Fixture change): gate passed, committed and pushed", "Read memory preferences.md first.", "Load the fixture skills.",
                     "Next, in Rhea's order: the Change button, player reactions.", "(q-1) ASK FIRST Should escaped",
                     "(q-2) A newer question", "Unverified: 1 open in docs/unverified.md", "State: PF2 Test running, paused",
                     "claude/fixture.md (history)", "claude/fixture-plan.md", "archive the old chat"):
            self.assertIn(want, out)
        self.assertNotIn("Old one", out)
        write(self.repo, "scripts/alpha.mjs", "// dirty\n")
        code, out = run(self.repo, "guide", "handoff", "--plan", self.plan, "--state", "x")
        self.assertNotEqual(code, 0)
        self.assertIn("finish isn't clean", out)

    # the 0.16.0 finding: a check shared with two touched features was listed twice
    def test_shared_item_listed_once(self):
        sys.path.insert(0, TOOLS)
        from modtools import common as cm
        root = self.repo
        write(root, "docs/features/delta.md", "---\nfeature: delta\nfiles: []\nfunctions: []\n---\nDelta.\n\n## Checks\n- (de-1) {live,shared:alpha,shared:beta} still fine\n")
        cfg = cm.load_config(root)
        feats = cm.load_features(root, cfg)
        req = cm.shared_required(feats, {"alpha", "beta"})
        self.assertEqual([r[1] for r in req].count("de-1"), 1)


    # the review's findings (2026-11-09), each failing on the code before its fix
    def test_review_deleted_unverified_line_is_not_a_close(self):
        write(self.repo, "docs/unverified.md", "# U\n\n" + "".join(f"- (u-{i}) [0.1.0] open: item {i}\n" for i in range(1, 12)))
        git(self.repo, "add", "-A"); git(self.repo, "commit", "-q", "-m", "eleven open")
        self.use_plan(records=())
        self.start()
        self.finish_change(asked="")
        text = read(self.repo, "docs/unverified.md")
        write(self.repo, "docs/unverified.md", "\n".join(l for l in text.split("\n") if not re.match(r"- \(u-[123]\)", l)) + "\n")
        code, out = run(self.repo, "gate", "--check")
        self.assertNotEqual(code, 0)
        self.assertIn("removed from docs/unverified.md: u-1, u-2, u-3", out)

    def test_review_non_bullet_lesson_and_strictest_home(self):
        self.use_plan()
        self.start()
        self.finish_change()
        fill_record(self.repo, "0.2.0", "- al-1 pass: 1\n- al-3 pass: fine\n- be-2 not run: beta untouched\n", learned="* a trap → owed: section 8\n")
        code, out = run(self.repo, "gate", "--check")
        self.assertIn("lessons must end with their home", out)
        sys.path.insert(0, TOOLS)
        from modtools import common as cm
        body = "## Learned, and where it was filed\n- x → filed: a → owed: b\n"
        self.assertEqual(cm.learned(body)[0][1], "owed")

    def test_lesson_scope_general_needs_a_card(self):
        """Rhea, 2026-11-09: general lessons twice landed only in a module's docs. Tagged records refuse that."""
        self.use_plan()
        self.start()
        self.finish_change()
        checks = "- al-1 pass: 1\n- al-3 pass: fine\n- be-2 not run: beta untouched\n"
        rel = "docs/changes/0.2.0.md"
        self.assertIn("lessonScope: 1", read(self.repo, rel))       # the template switches it on
        fill_record(self.repo, "0.2.0", checks, learned="- a Foundry trap → filed: docs/features/alpha.md\n")
        code, out = run(self.repo, "gate", "--check")
        self.assertNotEqual(code, 0)
        self.assertIn("not tagged `[general]` or `[module]`", out)
        fill_record(self.repo, "0.2.0", checks, learned="- [general] a Foundry trap → filed: docs/features/alpha.md\n")
        code, out = run(self.repo, "gate", "--check")
        self.assertNotEqual(code, 0)
        self.assertIn("general lesson filed only in this module's docs", out)
        fill_record(self.repo, "0.2.0", checks, learned="- [general] a Foundry trap → filed: docs/features/alpha.md, claude/foundry-op-recipes.md\n")
        code, out = run(self.repo, "gate", "--check")
        self.assertNotIn("lessons:", out)
        fill_record(self.repo, "0.2.0", checks, learned="- [general] a Foundry trap → filed: docs/features/alpha.md → card proposed: foundry-module-dev\n- [module] a module trap → filed: docs/features/alpha.md\n")
        code, out = run(self.repo, "gate", "--check")
        self.assertNotIn("lessons:", out)
        sys.path.insert(0, TOOLS)
        from modtools import common as cm
        self.assertEqual(cm.lesson_scope_problems("## Learned, and where it was filed\n- [General] x → card saved: s\n- [module] y → owed: z\n"), [])

    def test_lesson_scope_cannot_be_switched_off_by_deleting_the_line(self):
        self.use_plan()
        cfg = json.loads(read(self.repo, ".modtools.json")); cfg["lessonScopeFrom"] = "0.2.0"
        write(self.repo, ".modtools.json", json.dumps(cfg, indent=1) + "\n")
        git(self.repo, "add", "-A"); git(self.repo, "commit", "-q", "-m", "cutoff")
        self.start()
        self.finish_change()
        rel = "docs/changes/0.2.0.md"
        write(self.repo, rel, read(self.repo, rel).replace("lessonScope: 1\n", ""))
        fill_record(self.repo, "0.2.0", "- al-1 pass: 1\n- al-3 pass: fine\n- be-2 not run: beta untouched\n", learned="- untagged → filed: x\n")
        code, out = run(self.repo, "gate", "--check")
        self.assertIn("not tagged", out)

    def test_review_protocol_line_cannot_be_deleted(self):
        self.use_plan()
        cfg = json.loads(read(self.repo, ".modtools.json")); cfg["protocol2From"] = "0.2.0"
        write(self.repo, ".modtools.json", json.dumps(cfg, indent=1) + "\n")
        git(self.repo, "add", "-A"); git(self.repo, "commit", "-q", "-m", "cutoff")
        self.start()
        self.finish_change()
        rel = "docs/changes/0.2.0.md"
        write(self.repo, rel, read(self.repo, rel).replace("protocol: 2\n", ""))
        code, out = run(self.repo, "gate", "--check")
        self.assertNotEqual(code, 0)
        self.assertIn("lacks `protocol: 2`", out)

    def test_review_unverified_add_before_bump_goes_to_the_new_record(self):
        self.use_plan()
        self.start()                                   # manifest still 0.1.0
        code, out = run(self.repo, "guide", "unverified", "add", "early item")
        self.assertIn("[0.2.0]", out)
        self.assertIn("- (u-2) early item", read(self.repo, "docs/changes/0.2.0.md"))
        self.assertIn("- (u-2) [0.2.0] open: early item", read(self.repo, "docs/unverified.md"))

    def test_review_asked_first_line_cannot_be_deleted_and_pending_word_ok(self):
        self.use_plan()
        self.start()
        self.assertIn("askFirst: [q-1]", read(self.repo, "docs/changes/0.2.0.md"))
        self.finish_change(asked="")
        code, out = run(self.repo, "gate", "--check")
        self.assertIn("q-1 was due to be asked first", out)
        self.finish_change(asked="- q-1 answered 2026-11-09: the pending fix is fine\n")
        code, out = run(self.repo, "gate", "--check")
        self.assertEqual(code, 0, out)

    def test_review_curly_apostrophe_and_asked_still_goes_overdue(self):
        self.use_plan(plan=PLAN.replace("Rhea's order", "Rhea’s order").replace("(q-1) [since 0.0.8] open", "(q-1) [since 0.0.8] asked 2026-11-01"))
        sys.path.insert(0, TOOLS)
        from modtools import common as cm
        p = cm.Plan(self.plan)
        self.assertTrue(p.next.startswith("the Change button"))
        self.assertEqual([q["id"] for q, _ in cm.overdue_questions(p, ["0.0.8", "0.0.9"])], ["q-1"])

    def test_review_take_over_note_kept_in_the_lock(self):
        self.use_plan()
        self.start()
        git(self.repo, "config", "--local", "modtools.lockToken", "other1")
        self.start("0.2.0", "--take-over", "Rhea OK 2026-11-09")
        self.assertIn("took over: Rhea OK 2026-11-09", read(self.tmp, "plan.md"))
        sys.path.insert(0, TOOLS)
        from modtools import common as cm
        self.assertEqual(cm.Plan(self.plan).lock_for("fixmod")[3], "other1")


if __name__ == "__main__":
    unittest.main()
