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
5. Put the private word list in `.private-words` (one word or phrase per line). It never goes in
   the repo; keep the master copy somewhere private and copy it in at the start of a session.
6. Add the two markers to `docs/DEVELOPING.md` where the feature index should go:
   `<!-- feature-index:start -->` and `<!-- feature-index:end -->`, then `guide --index`.

## Every change
```
python3 ../foundry-mod-tools/guide.py start 0.11.0 "Monsters fleeing"   # setup checks, hook on, record created
python3 ../foundry-mod-tools/guide.py --diff                            # what applies: docs, decisions, checks, traps, shared items
python3 ../foundry-mod-tools/guide.py take-cover scripts/turn.mjs       # the same for named features or files
...build; fill the record as decisions and findings come; bump the version...
python3 ../foundry-mod-tools/gate.py                                    # refuses, or builds the zip and stamps the tree
git commit; git push                                                    # the pre-push hook re-checks the stamp on main
python3 ../foundry-mod-tools/guide.py finish                            # what is still unsaved, in and out of the repo
```
`guide` alone prints the feature map. `doccheck.py` and `scan.py` run on their own too.

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
8. The Review section is filled when code changed (or `waived by Rhea <date>: <reason>`).
9. The record's title is no longer the template's.

Then it builds the zip from the tree (deterministic, includes only the configured folders, never
the word list) and writes `.modtools-stamp.json` with a hash of the tree. The `pre-push` hook
refuses a push to `main` whose commit tree is not the stamped one, whose manifest version differs
from the stamp, or whose committed zip disagrees with the manifest.

## Honest limits
A script can't prove a live test was run or a player view was looked at: the record asks for what
was seen, and a reviewer reads it against the chat. `git push --no-verify` and a hand-built zip
still work; they are deliberate, visible acts, and the skills forbid them.

## Tests
`python3 -m unittest discover -s tests` builds a fixture repo with a bare remote and checks guide's
mapping, each gate refusal and the pass, the orphan check, the scan and the hook.
