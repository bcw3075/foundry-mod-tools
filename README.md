# foundry-mod-tools

Scripts that keep a Foundry VTT module repo's knowledge next to its code and refuse a release
until the docs, checks and review are in place. Python 3, standard library only. Generic: they
read `.modtools.json`, the feature docs' frontmatter and git, nothing else.

## The idea
- **Feature docs** `docs/features/<name>.md`: one per feature. Frontmatter names the code files it
  owns whole (`files`) or, for big files listed in `functionOwned`, the functions (`functions`,
  as `file.mjs:name` or a bare name when unique). Body: Decisions, How it works, Checks, Traps,
  Open items. Checks are `- (<id>) {tags} text`; tags `live`, `unit`, `player`, `shared:<feature>`.
- **Change records** `docs/changes/<version>.md`: one per release, made from the template by
  `guide start`, filled during the work, read by `gate`. Release note, test record and history in one.
- **Scripts**: what to load is computed from the change, and a release is refused rather than
  discouraged when something is missing.

## Setup in a mod repo (once)
1. Clone this repo beside the mod repo (`../foundry-mod-tools`), or set `MODTOOLS` to its path.
2. Copy `templates/modtools.json` to the mod repo's root as `.modtools.json` and edit it.
3. Copy `githooks/pre-push` to `tools/githooks/pre-push` in the mod repo (executable).
4. Git-ignore `.private-words` and `.modtools-stamp.json`.
5. List names from other systems' code that the docs quote in `docs/external-names.txt` (tracked; one per line) so the name check stays clean.
6. Put the private word list in `.private-words` (one word or phrase per line). It never goes in
   the repo; keep the master copy somewhere private and copy it in at the start of a session.
7. Add the two markers to `docs/DEVELOPING.md` where the feature index should go:
   `<!-- feature-index:start -->` and `<!-- feature-index:end -->`, then `guide --index`.

## Every change
```
python3 ../foundry-mod-tools/guide.py start 0.11.0 "Monsters fleeing" --plan /home/claude/angel-mod-private/plan/<module>-plan.md
                                       # the lock, questions to ask first, page checks, setup checks, hook on, record
python3 ../foundry-mod-tools/guide.py --diff                            # what applies: docs, decisions, checks, traps, shared items
python3 ../foundry-mod-tools/guide.py take-cover scripts/turn.mjs       # the same for named features or files
...build; fill the record as decisions and findings come; bump the version...
python3 ../foundry-mod-tools/gate.py                                    # refuses, or builds the zip and stamps the tree
git commit; git push                                                    # the pre-push hook re-checks the stamp on main
python3 ../foundry-mod-tools/guide.py unverified add "<what isn't proved>" # the running list and the record
python3 ../foundry-mod-tools/guide.py finish --plan <plan> --rechecked "<what was rechecked, and what it fixed>"
                                                                     # what is still unsaved; owed lessons; branches; the recheck; clears the lock
python3 ../foundry-mod-tools/guide.py handoff --plan <plan> --state "<live state>"   # the handoff, fixed layout
```
`guide` alone prints the feature map. `doccheck.py` and `scan.py` run on their own too.

**The general traps (`docs/foundry-traps.md`, here since 2026-11-10).** What every module's code must know about
Foundry v14 and PF2e (module structure, release and install, the local test harness, the traps, canvas lessons) used to be half of the
foundry-module-dev skill, paid for in every chat. It lives in this repo now, word for word, and is read when code is
written: `guide start` and `guide --diff` (once code has changed) print the pointer; `guide traps` lists the sections,
`guide traps <word> ...` prints every bullet naming any of the words, `guide traps --section <n>` prints one whole; the
gate refuses a code change whose record has no `- traps-read done: <what was read>` under Setup. When the gate
passes it prints `guide traps --section 5`: the verified release and install steps, read at every release. A new general trap
is added to that doc in the same step it is found (its one home; the record's Learned line says
`→ filed: foundry-mod-tools docs/foundry-traps.md`). The doc is public: no campaign words (scan it with the word list
before committing).

**A release in two gates (the live checks need the code installed):** record each live check
`not run: pending live test (test build)` and start the independent review at once, with a Review
line `- pending (test build): …`; gate, push and install the test build; test; then write the real
results and replace the pending line with the review's findings, each verified against the code;
gate and push again. A second test build under the same version is fine: poll raw GitHub for the
new zip, not the version, on the plain URL Foundry's install fetches (2026-11-09: a cache-busted `?t=`
URL served the new zip while the plain one still served the old, and the first install got the old
build); then confirm the install by a changed file's text under `/modules/<id>/`, reinstall if it is
old, and reload the Bridge's page with its cache cleared before testing. If a gate line ever claims something nobody did, stop and fix the tool,
with a test that fails on the old code.

## The tightening (protocol 2, agreed with Rhea 2026-11-08)
Records made from the template since then carry `protocol: 2` and get these rules. Set `protocol2From`
in `.modtools.json` to the first version under them: the gate then refuses a record without the line,
so deleting it can't switch the rules off.
1. **Owed lessons can't wait.** Every line under Learned ends with its home: `→ filed: <where>`,
   `→ card proposed: <skill>` (Rhea saves it; `finish` prints a 🟡 line until it reads `→ card saved:`),
   or `→ owed: <where>`. Every non-blank line counts (a `*` list can't slip past); a line naming two homes
   counts as the strictest. The gate refuses a line with no home; `finish` refuses while one is owed;
   `start` carries owed and unconfirmed lines from the previous record into the new one.
   **Lesson scope (Rhea, 2026-11-09):** records with `lessonScope: 1` (the template adds it; set
   `lessonScopeFrom` in `.modtools.json` so deleting it can't switch it off) tag every lesson `- [general]`
   (true beyond this module: Foundry, PF2e, the bridge, the tools) or `- [module]`. A general lesson must
   reach its one home outside the repo: usually the project doc a skill points to (`→ filed: claude/...`),
   a skill card (`→ card proposed:`) only for what every chat needs, since skills stay lean. The gate and
   `finish` both refuse a general lesson filed only in the module's own docs. Added after general lessons
   were twice filed only in a module's docs.
2. **One running list of unverified items**, `docs/unverified.md` (config `unverified`):
   `- (u-N) [<release>] open: <text>`, closed in place as `verified <date> in <version>: ...` or
   `dropped <date>: ...`. `guide unverified add` writes the item there and `- (u-N) text` in the record;
   the gate refuses a record item missing from the list, a malformed line, an item deleted instead of
   closed in place, and, when more than
   `unverifiedLimit` (8) were open at the record's base, a release that closes fewer than
   `closeOutAtLeast` (3, or down to the limit).
3. **Recurring traps become page checks** (config `pageChecks`: `id`, `why`, `script`, `pages`). `start`
   prints each script and writes `- <id> not run: pending` under Setup; the gate refuses until it says
   `done: <what was seen>` (or `not run: <real reason>`). Rule: a trap seen twice becomes one.
4. **Handoffs written by the script.** `handoff` refuses until `finish` is clean, needs `--state`
   (the live state no script can see), and prints the fixed layout: what was released, read and load,
   Next in Rhea's order (the plan's `**Next, in Rhea's order:**` line), open questions, the unverified
   count, state, where things are (config `handoff.where`), the archive reminder; 🟡 lines after it.
   **Load by phase (2026-11-10):** with `handoff.loadByPhase` in the config (`design`, `build`, `live` in the
   template), `handoff` needs `--next <phase>` and its load line names only what that kind of chat needs: a design
   chat once loaded five skills where it needed one.
5. **Questions for Rhea don't sit.** They live in the plan doc's `## Open questions` as
   `- (q-N) [since <version>] open|asked <date>|answered <date>|dropped <date>: <text>`. One carried
   through two handoffs (two change records at or after `since`) is printed by `start` under ASK RHEA
   FIRST, listed in the record's frontmatter `askFirst`, and written `- q-N pending` under Asked first;
   the gate refuses while one is pending or has no line. `asked` (Rhea: later) still counts toward overdue.
6. **One build chat at a time.** With `planDoc` set, `start` and `finish` need `--plan <path>`:
   the plan file in the clone of Rhea's private repo (since 2026-11-10; the chat workspace can no longer copy
   a project doc to disk, so the plan's one home is that repo and `planDoc` names its short project-doc
   signpost for voice chats). The private doc never goes in the mod repo. `start` writes
   `- lock <mod> <version> started <time> token <t>` under `## Build lock` (the token lives in the
   clone's git config) and refuses when another chat's token is there, unless Rhea agreed
   (`--take-over "<her OK>"`, kept on the lock line); `finish` clears it when nothing is left, and
   `handoff` refuses while it's held. After each, the chat commits and pushes the plan: the scripts print
   the words, `finish` reminds the chat to write the signpost again, and `handoff` refuses a plan in a git
   clone that isn't committed and pushed. (A plan passed as a loose file is still accepted; then the chat
   writes it back with project_write.)
7. **Leftover branches listed.** `finish` notes every remote branch other than main. Rhea (2026-11-09):
   no deletes as they come; they go in one cleanup at the end of the project, so this is a note, not a 🟡 line.
8. **Recheck before finished (Rhea, 2026-11-09).** Her rule: when a task is complete, go back through and recheck
   everything to make sure everything is updated correctly before saying it's finished. `finish` refuses (and keeps the
   lock) until it is run with `--rechecked "<what was rechecked, and what it fixed>"`, and prints its RECHECK list: every
   doc the chat touched reread, every project doc naming the module or its version (plan, history, baseline, roadmap,
   docs index), memory notes, every lesson filed (small traps too), and the live server left clean. It writes the
   answer to the plan doc's `## Last recheck` (made if missing); `handoff` refuses until that line is for the current
   release, and points to it (one home since 2026-11-10: the text is in the plan only, not copied into the handoff or the record). A script can't do the recheck; it makes skipping it a visible act. Added after 0.18.0's
   finish missed a stale roadmap line and two unsaved traps, found only when Rhea asked "No updates needed?".
Also: a shared check is listed once even when it's shared with several touched features.

## What the gate requires
1. A change record for the manifest's version, and the version bumped since the record's base.
2. `doccheck` clean: every backticked name in the docs exists in the repo; every code file is owned
   by exactly one feature, or is function-owned with every top-level function owned by exactly one
   feature; check ids unique; the feature index in DEVELOPING.md is the generated one.
3. The privacy scan clean. It fails closed without `.private-words`.
4. The unit tests pass (`tests` in the config).
5. Every changed code path is owned.
6. Every touched feature's doc changed in the release, or the record says
   `- doc-unchanged <feature>: <reason>` under Features touched.
7. Every check id of every touched feature, plus every `shared:<touched>` item in other features,
   is recorded `pass` or `not run: <reason>`; `unit` items are covered by step 4; a `fail` refuses.
8. The Review section is filled when code changed (or `waived by Rhea <date>: <reason>`). Template
   hints (`<!-- -->`, even over several lines) never count as content or as a waiver.
9. The record's title is no longer the template's.
10. to 13. The tightening's rules (above) for `protocol: 2` records.
14. When code changed (`protocol: 2` records): `- traps-read done: <what was read>` under Setup.

Then it builds the zip from the tree (deterministic, includes only the configured folders, never
the word list) and writes `.modtools-stamp.json` with a hash of the tree. The `pre-push` hook
refuses a push to `main` whose commit tree is not the stamped one, whose manifest version differs
from the stamp, or whose committed zip disagrees with the manifest.

## Honest limits
A script can't prove a live test was run or a player view was looked at: the record asks for what
was seen, and a reviewer reads it against the chat. `git push --no-verify` and a hand-built zip
still work; they are deliberate, visible acts, and the skills forbid them. The build lock's token lives in
the clone's git config: two chats sharing one clone would share it (each chat has its own workspace, so
this doesn't happen today). The lock and the questions live in a private doc the scripts only see as the
file passed with `--plan`; committing and pushing it is the chat's step, checked by `handoff`.

## Traps of the tools themselves
- A script that asks git about one file must pass the full path, or run from the top of the clone: a path
  relative to the top, used from a subfolder, matches nothing and git answers "clean". It made `handoff` accept an
  unsaved plan until a test caught it (2026-11-10).

## Tests
`python3 -m unittest discover -s tests` builds a fixture repo with a bare remote and checks guide's
mapping, each gate refusal and the pass, the orphan check, the scan, the hook, and the seven
protocol-2 rules (TestTightening).
