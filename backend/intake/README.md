# intake

A folder becomes a manifest. Read `CONTRACT.md` first.

The core today is `reconcile.py`: one-to-one assignment of documents to a roster, recording for each
match whether identity was looked up or inferred, and keeping unmatched / missing / non-student /
unreadable apart as the four different facts they are.
