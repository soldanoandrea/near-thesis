# Terminal part of the demo video (docs/DEMO_SCRIPT.md, scene 1), recorded by VHS in a fresh clone of this repository.
# Rendered by `make video` (scripts/video/render.sh), which clones HEAD into a temporary directory, runs this tape
# there (so no local paths show) and plays it at 2x speed in the final video. Everything shown is a real run:
# `make reproduce` rebuilds every table, report, the essay and the dashboard offline, then runs the tests.

Output terminal.mp4

Require make
Require uv
Require git

Set Shell "bash"
Set FontFamily "Menlo"
Set FontSize 15
Set LineHeight 1.15
Set Width 1280
Set Height 720
Set Padding 22
Set Theme "Catppuccin Mocha"
Set TypingSpeed 30ms
Set Framerate 30
Set WaitTimeout 300s

# Setup, not recorded: a plain prompt, and `highlights`, which keeps only the build steps, three headline numbers
# and the test summary from the output of `make reproduce`. (VHS drives a terminal in a headless browser that stalls
# on long bursts of output, and nobody can read the full tables at video speed; they are in reports/.)
Hide
Type "export PS1='$ ' BASH_SILENCE_DEPRECATION_WARNING=1"
Enter
Type `highlights() { grep --line-buffered -E '^(uv run|\[build\]|\[site\])|passed|Organic share of transactions, 2026-Q3 |On-chain swap volume / DefiLlama|rebuilt on-chain / DefiLlama'; }`
Enter
Type "clear"
Enter
Sleep 500ms
Show

Type "# A fresh clone of github.com/soldanoandrea/near-thesis: no keys, no accounts. (Played at 2x.)"
Enter
Sleep 1s
Type "git log --oneline -1 && ls"
Enter
Sleep 2s
Type "make reproduce 2>&1 | highlights   # raw snapshots -> tables, reports, THESIS.md, site/, then the tests"
Enter
Wait+Screen@300s /passed/
Sleep 3s
Type "clear && git status --short | wc -l   # 0 = every output rebuilt byte-identical to the committed one"
Enter
Sleep 3s
Type "shasum -a 256 thesis/predictions.csv && git tag -n3 predictions-2026-10-31"
Enter
Sleep 6s
