"""scan: no private words in anything that could reach the public repo.

The word list is `.private-words` at the mod repo's root: one word or phrase per line,
`#` comments allowed, matched case-insensitively as whole words. It must be git-ignored and
never tracked. The scan fails closed: no list, or an empty list, is a failure.
Scanned: every tracked and untracked-not-ignored text file (the zip is checked by the gate,
which builds it from the same tree). Exit 0 clean, 1 with hits or a missing list.
"""
import os, re, sys
from . import common as c


def load_words(root):
    p = os.path.join(root, c.WORDS_NAME)
    if not os.path.isfile(p):
        raise c.Fail(f"{c.WORDS_NAME} is missing at the repo root: copy it from the private project doc (the scan fails closed)")
    if not c.is_ignored(root, c.WORDS_NAME):
        raise c.Fail(f"{c.WORDS_NAME} is not git-ignored; add it to .gitignore before anything else")
    if c.WORDS_NAME in c.tracked_files(root):
        raise c.Fail(f"{c.WORDS_NAME} is tracked by git; remove it from the index (git rm --cached)")
    words = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            s = line.split("#", 1)[0].strip()
            if s:
                words.append(s)
    if not words:
        raise c.Fail(f"{c.WORDS_NAME} holds no words (the scan fails closed)")
    return words


def scan(root, words, files=None):
    pats = [(w, re.compile(r"(?<![A-Za-z0-9])" + re.escape(w) + r"(?![A-Za-z0-9])", re.I)) for w in words]
    hits = []
    for rel in (files if files is not None else c.worktree_files(root)):
        if rel == c.WORDS_NAME or rel == c.STAMP_NAME or not c.is_text_file(rel):
            continue
        try:
            text = c.read(root, rel)
        except Exception:
            continue
        for i, line in enumerate(text.split("\n"), 1):
            for w, pat in pats:
                if pat.search(line):
                    hits.append((rel, i, w))
    return hits


def run(root, quiet=False):
    words = load_words(root)
    hits = scan(root, words)
    if not quiet:
        print(f"scan: {len(words)} words, {len(hits)} hits")
        for rel, i, w in hits:
            print(f"  - {rel}:{i}: {w}")
    return hits


def main(argv=None):
    try:
        root = c.find_root()
        hits = run(root)
    except c.Fail as e:
        c.die(str(e), 1)
    sys.exit(1 if hits else 0)
