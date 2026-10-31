# Fresh-clone check (2026-10-31)

A clean clone, following only the commands in the README, run by the agent on 2026-10-31 at 03:14 UTC.

**Setup.** macOS (Darwin 25.6.0, arm64), `make`, uv 0.11.14 (Python 3.12 managed by uv), Google Chrome 156 for the
browser check. The GitHub repository is private and the agents push nothing, so the clone was taken from the local
repository at commit `ad3bc81`, with `--no-tags` (what a clone from GitHub sees until the predictions tag is pushed),
into an empty directory. A fresh, empty uv cache (`UV_CACHE_DIR` in a temporary directory) made `uv sync --frozen`
fetch every locked package from PyPI, as on a judge's machine.

| Step (README) | Command | Result |
|---|---|---|
| 1 | `git clone --no-tags <repository> near-thesis && cd near-thesis` | clone at `ad3bc81`, 0 tags |
| 2 | `make reproduce` | exit 0 in 60 s wall time: 17 packages prepared from PyPI in 4.8 s; `[build] as-of 2026-10-29; wrote 61 files to data/processed/ and reports/`; `[site] wrote 12 files (168 kB in site/)`; pytest `108 passed, 1 skipped` (the skip is the tag check: no tag in this clone) |
| 3 | `git status --porcelain` | 0 lines: every rebuilt output is byte-identical to the committed one |
| 4 | `make verify` | `[verify] OK` |
| 5 | `shasum -a 256 thesis/predictions.csv` | `a926c6a50937ad55d4e5b9e00cf66aa33d86fda8a9c906b1c37fdf2a30b60c94`, the hash quoted in `thesis/THESIS.md` and the README |
| 6 | open `site/dashboard.html` and `site/index.html` from disk (headless Chrome, `file://`) | Plotly.js 2.35.3 loaded from cdnjs with its integrity hash; all 8 charts drawn; the essay renders with its title and table of contents |
| 7 | `scripts/fresh_clone_check.sh` (clones with tags) | `109 passed`; "fresh clone: make reproduce OK, committed outputs unchanged" |
| 8 | relative links in README.md, thesis/*.md and docs/*.md | none broken (this file was the only missing target and is written after the run) |

**Fixed because of the check.** The README quoted a stale line count for the site build (`[site] wrote 9 files`); it
now quotes the line without the count, and says the tag test is skipped in clones without the tag. Earlier in the same
session, while recording the demo, the build log printed absolute local paths; it now prints repository-relative paths.

**Not covered.** A clone from GitHub itself (private, nothing pushed), Linux (only macOS was run here; nothing in the
build is macOS-specific), the GitHub Pages deployment (the workflow was written, not run), and `make refresh` (online,
several hours). `make video` was run in the main working copy, not in this clone; it needs VHS, ffmpeg, Chrome and the
network for Plotly.js.
