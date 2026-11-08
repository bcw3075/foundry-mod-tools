---
feature: {name}
files: []                 # code files this feature owns whole (repo-relative)
functions: []             # for functionOwned files: file.mjs:name, or a bare name when unique
dependsOn: []             # shared features whose change should re-run this feature's shared items
since: {version}
---
One line saying what this feature is, for the index.

## Decisions
<!-- Rhea's choice, the date, her reasons, and the options she rejected. -->

## How it works
<!-- Technical only. The repo is public. -->

## Checks
<!-- One per line: `- (<id>) {tags} what to do and what a pass looks like`.
     Tags: live (needs the server), unit (the unit tests cover it), player (as the test player),
     shared:<feature> (also required whenever that feature changes). Ids are unique across all docs. -->
- ({prefix}-1) {live} 

## Traps
<!-- Things that went wrong once and why. A trap tied to one line of code belongs at that line
     (a comment or a unit test) and is only summarised here. -->

## Open items
