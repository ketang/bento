# Artifact Verification

When a landing includes binary files, compressed archives, or LFS-tracked
objects, verify committed bytes match what local testing validated.

Local workspaces may contain real content while the committed tree stores an
LFS pointer or stale snapshot. Remote source-build platforms receive the
committed tree, not the workspace.

## Checks

- `git show HEAD:<path> | file -` — if it says "ASCII text" for an expected
  binary, the commit contains an LFS pointer, not the artifact.
- For LFS-tracked files, confirm the deploy platform hydrates LFS in its
  build path. If unverified, prefer a normal blob or build-time fetch.
- For container/image builds from the git snapshot, verify the remote
  builder's source tree matches what local testing used. Common divergence:
  LFS pointers, `.dockerignore` exclusions, platform source filtering.
