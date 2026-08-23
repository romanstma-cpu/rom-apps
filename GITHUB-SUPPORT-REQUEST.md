# Ask GitHub to garbage-collect rom-apps

The CS2 loader files have been removed from `main` and purged from every commit
in the repository's history, and the rewritten history has been force-pushed.
But GitHub keeps unreferenced objects until it garbage-collects, so the old
commits are **still reachable by their full SHA**:

```
https://github.com/romanstma-cpu/rom-apps/commit/5969a7c
https://github.com/romanstma-cpu/rom-apps/commit/f0805d7
https://github.com/romanstma-cpu/rom-apps/commit/f3bcf3b
```

Only GitHub Support can trigger the cleanup. Open a ticket at
<https://support.github.com/request> and send something like the message below.

---

**Subject:** Request garbage collection after history rewrite — romanstma-cpu/rom-apps

Hello,

I removed several files from `romanstma-cpu/rom-apps` using `git filter-repo`
and force-pushed the rewritten history. The files are gone from every branch
and tag, but the old commits are still reachable by their full SHA — for
example `5969a7c`, `f0805d7` and `f3bcf3b`.

Please run garbage collection on the repository so the unreferenced objects are
removed. There are no forks and no open pull requests referencing them.

Thank you.

---

## Also worth doing

The repository has no forks today, but if it is ever forked, unreferenced
objects can survive in the fork network. Check before assuming the cleanup is
complete:

```bash
gh api repos/romanstma-cpu/rom-apps --jq '.forks_count'
```
