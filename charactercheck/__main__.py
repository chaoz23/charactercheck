"""Make `python3 -m charactercheck ...` work.

Handed a GitHub URL, an agent clones the repo rather than pip-installing it —
which is entirely reasonable, and then the natural next move is
`python3 -m charactercheck derive <ref>`. Without this file that fails with
"No module named charactercheck.__main__", which is a dead end that teaches the
caller nothing.

Found by running the actual user story against a real agent: it recovered by
guessing `-m charactercheck.cli`, but it should not have had to guess.
"""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
