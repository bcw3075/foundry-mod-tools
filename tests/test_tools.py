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


def fill_record(repo, version, checks, review="- reviewer: no findings (verified: read the diff)\n", title="Alpha returns one again", unverified="- the player view was not looked at\n", learned="- nothing new\n"):
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
        self.assertIn("player view was not looked at", out)
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


if __name__ == "__main__":
    unittest.main()
