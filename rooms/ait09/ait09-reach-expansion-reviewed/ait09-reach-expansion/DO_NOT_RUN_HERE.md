This copy is for review only. Do not run `setup.sh` from this path.

Every parent directory name here (`ait09`, `ait09-reach-expansion-reviewed`,
`ait09-reach-expansion`) is a clean-room leak: it becomes the bind-mount source path,
which the agent container can read back via `/proc/self/mountinfo` (REVIEW.md, item 22).

Run from the neutral copy instead:

    /private/var/tmp/lab/batch-worker-07-room/

No code changed — every path in the harness resolves relative to its own file location, so
the working copy is a plain directory copy of this one. If you re-review or re-patch this
tree, re-sync the working copy afterward; it does not update itself.
