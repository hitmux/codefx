# Official Linux CI and Codefx checks

Codefx validates and publishes Linux x86_64 and ARM64. Windows and macOS
runners and release artifacts are outside the supported matrix.

## Versioned official baseline

`.github/upstream-ci.json` pins the source version, official tag, commit and
CI files. The current baseline is `openai/codex` `rust-v0.166.0`, commit
`6ff1e1ca3b30fc8b914720681fcf5fe62e95f856`.

The required policy job checks out that exact upstream commit and compares its
Linux projection with this repository. It checks commands, step conditions,
action pins, helper scripts and lint target discovery, including test binaries.
Removing a command, skipping a check without credentials or narrowing a selector
fails the comparison. Comments and blank lines may differ.

The only permitted adaptations in `check_upstream_ci.py` are:

- Remove Windows/macOS matrix entries, dedicated jobs and their result fan-in.
- Replace private Linux runner groups with GitHub-hosted Ubuntu runners.
- Increase 30-minute build timeouts and the 20-minute SDK timeout to 180 minutes
  for cold hosted builds, without changing the commands or test graph.
- Add `codefx-linux-runner` to common setup. It frees unused hosted tools,
  limits local CPU/memory consumption and bounds Cargo build parallelism.
- Use the canonical `facebook/install-dotslash` URL with the upstream action SHA.
- Keep the cargo-deny Docker cache on the runner home volume. Its dependency
  graph and manifests are unchanged; resolution or worktree changes must fail.
- Omit the unavailable OpenAI Fence audit hook; retain the blob-size check.

The V8 canary retains native GNU and musl Cargo smoke, target selection and
ignored-test execution from upstream. Its Windows source build is removed.
The retired upstream publishing workflows must remain absent.

BuildBuddy remains optional through the official wrapper's existing fallback.
Absent credentials must never disable tests or lint. Runner capacity failures
remain failures and must be addressed as infrastructure problems.

## Required PR checks

`blocking-ci.yml` tests GitHub's synthetic merge revision and requires:

- Official Bazel GNU/musl tests, Linux Clippy (including test code), and the
  official release-configuration build and bwrap checks.
- Official fast Rust checks, SDK checks, dependency policy, spelling, blob size,
  repository checks and formatting.
- Codefx baseline/coverage policy and its regression tests.
- Codefx installer transaction, failure and rollback tests.
- Codefx packages built from that same source revision for Linux x86_64 and
  ARM64 musl, including native execution and installation/reinstallation.

The current-source package check never checks out a release tag, normalizes a
lockfile, reuses published binaries or publishes anything. Only its HTTP
transport uses installer test fixtures to serve the newly built package;
package contents and installed executables are real. Artifacts record the
source commit, target, version and digest.

Codefx retry and update regressions remain in the complete official Rust test
graph; their dedicated existing regression tests are not filtered out.
`CI required` must depend on every official and Codefx workflow and reject
failed, cancelled or skipped dependencies. Published-release smoke is separate
from current-source validation and remains available manually.

## On every upstream version sync

1. Select the official release tag and resolve it to an immutable commit.
2. Update the source and `.github/upstream-ci.json` together. Update the policy
   job's pinned upstream checkout to the same commit.
3. Copy the official CI files and referenced helpers, retaining all Linux jobs
   and commands. Apply only the documented platform/infrastructure adaptations.
   If upstream changes matrix syntax or job names, review the projection and
   regression tests explicitly; comparison failure is not a reason to bypass it.
4. Open or update the sync PR and run `blocking-ci`. Run the complete Linux
   `rust-ci-full.yml` before release; `postmerge-ci.yml` also runs it on main.
5. Publish only after required CI, full Linux CI and the current release's
   verified native package/install checks pass. Report the exact source commit
   and run links; skipped, pending or unavailable checks are not passes.

All formatting, lint, generation, builds and tests run in GitHub Actions.
The local checkout is for file editing and static Git review only.
