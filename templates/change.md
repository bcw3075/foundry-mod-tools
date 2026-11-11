---
version: {version}
started: {date}
base: {base}
protocol: 2
lessonScope: 1
askFirst: [{askfirst}]
---
# {version} — {title} (started {date})

## Setup
<!-- One line per page check (`guide start` prints the scripts): run it on every page this chat uses,
     then `- <id> done: what was seen`, or `- <id> not run: why`. The gate refuses `pending`.
     `- traps-read done: <sections or words read>` is needed once code changes (`guide traps <word> ...`). -->
{setup}
## Asked first
<!-- Questions carried through two handoffs, asked before any build work: `- q-N asked <date>: Rhea's answer`
     (or `Rhea: later`). The gate refuses `pending`. Empty when none were overdue. -->
{asked}
## Features touched
<!-- Filled by the gate from the diff; add any the diff can't see (a behaviour change with no code change).
     To release without changing a touched feature's doc, give the reason on its own line:
     - doc-unchanged <feature>: <why the doc already says everything> -->

## Decisions made
<!-- Rhea's answers, each with the question it answered and the date. -->

## Checks
<!-- One line per check id the gate asks for: `- <id> pass: what was seen`, `- <id> fail: what`,
     `- <id> not run: why`. `unit` items are satisfied by the gate's unit-test run. -->

## Review
<!-- The independent reviewer's findings, each marked verified true or false and what was done.
     Required when code changed; otherwise write `waived by Rhea <date>` with her reason. -->

## Unverified
<!-- Add each with `guide unverified add "<text>"` (it goes in the running list and here as `- (u-N) text`),
     close older ones in the running list, or write `- none`. -->

## Learned, and where it was filed
<!-- Each lesson starts `- [general]` (true beyond this module: Foundry, PF2e, the bridge, the tools) or
     `- [module]` (only this module), and ends with its home: `→ filed: <where>`, `→ card proposed: <skill>`
     (Rhea saves it), `→ card saved: <skill>`, or `→ owed: <where>` (finish refuses until it is filed).
     A general lesson goes to its one home outside the repo: a Foundry or PF2e code trap into the tools repo's
     traps doc (`→ filed: foundry-mod-tools docs/foundry-traps.md`), anything else into the project doc that
     claude/docs-index.md names (`→ filed: claude/...`), a skill card only for what every chat needs. -->
{learned}
## Private notes
<!-- A pointer only: `see claude/<doc>` for anything that can't be public. Never the content. -->
