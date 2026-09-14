# Incident Report — FinTrack Release Night Chaos

**Author:** Kaushik Shettigar
**Assignment:** Kubernetes \& Docker Black Box Challenge — Assignment #2

Screenshots for Phases 1–2 live in [`/screenshots`](./screenshots) and are embedded inline below. Save yours under these exact filenames and the embeds will render on GitHub. Phases 3–4 and the bonus round don't have screenshots embedded yet — those sections will get the same treatment once completed (Phase 3's root causes are already confirmed and documented below, just without embeds yet).

## Screenshot Index (Phase 1)

|Filename|What it shows|
|-|-|
|`screenshots/phase1-baseline-log.png`|`git log --oneline --graph --all` — messy "before" history (vague messages, direct-to-main)|
|`screenshots/phase1-bisect-run.png`|`git bisect run` output narrowing to the bad commit|
|`screenshots/phase1-diff-bug.png`|`git diff` showing the exact POST→GET regression|
|`screenshots/phase1-reflog.png`|`git reflog` — recovery point captured before the history-rewriting rebase|
|`screenshots/phase1-revert-deletes-k8s.png`|The revert's diffstat unexpectedly deleting `k8s/\*.yaml` (the `git add .` lesson)|
|`screenshots/phase1-secret-verified-gone.png`|`git log --all --oneline -- services/account-service/.env` — returns nothing|
|`screenshots/phase1-clean-final-log.png`|Final `git log --oneline --graph --all` — bug fix, secret removal, and k8s recovery all visible|
|`screenshots/phase1-hook-blocks-secret.png`|Pre-push hook blocking a correctly-shaped fake AWS key|
|`screenshots/phase1-pr-checks-failing.png`|PR #1 — gitleaks + python-lint both red (before fixes)|
|`screenshots/phase1-pr-checks-passing.png`|PR #2 — gitleaks + python-lint both green (after fixes)|
|`screenshots/phase1-direct-push-rejected.png`|Branch protection blocking a direct push to `main`|
|`screenshots/phase1-changelog-diff.png`|Final `CHANGELOG.md` PR diff — full auto-generated release history|

## Screenshot Index (Phase 2)

|Filename|What it shows|
|-|-|
|`screenshots/phase2-agent-connected.png`|Jenkins agent `docker-agent` status page — "Agent is connected"|
|`screenshots/phase2-disk-full-df.png`|`df -h` — root volume at 100%, 0 bytes free (real incident, not simulated)|
|`screenshots/phase2-disk-resized-df.png`|`df -h` after EBS volume resize — space no longer critical|
|`screenshots/phase2-agent-exited.png`|`docker ps -a` showing `jenkins-agent` as `Exited (143)` after EC2 stop/start|
|`screenshots/phase2-rollback-bug-console.png`|Pipeline build #6 console — rollback fails on hardcoded nonexistent tag `v1.0.0`|
|`screenshots/phase2-rollback-fixed-console.png`|Pipeline build #7 console — rollback correctly resolves to `v2025.06.1` via `git describe`|
|`screenshots/phase2-timeout-notify-console.png`|Pipeline build #8 console — `Timeout set to expire in 10 min` and `NOTIFY:` line firing on failure|
|`screenshots/phase2-matrix-security.png`|Jenkins matrix-based authorization restricting anonymous/non-admin pipeline triggers|
|`screenshots/phase2-credential-stored.png`|`dockerhub-creds` stored in Jenkins Credentials Manager (masked value)|

\---

## Architecture: Before vs. After

**Before (as deployed with deliberate bugs):**

```
frontend → account-service (v1 + v2, no memory limit tuning, label mismatch risk)
                                          → payment-service (no circuit breaker)
account-service → MongoDB (StatefulSet, invalid storageClassName → PVC Pending)
No mTLS. No branch protection. Secrets committable. No automated rollback.
```

**After (target end state):**

```
frontend → Istio VirtualService (90% v1 / 10% v2, retries: 2, timeout: 3s)
              → account-service v1/v2 (memory limits tuned, correct version labels)
              → payment-service (DestinationRule circuit breaker: 5 consecutive 5xx → ejected)
account-service → MongoDB (valid storageClassName, PVC Bound)
mTLS STRICT between all services. Jaeger tracing frontend→account→payment.
Branch-protected main, PR-gated CI (gitleaks + lint), pre-push secret hook,
automated changelog on tag, Jenkins rollback tied to real last-good tag.
```

## Environment Baseline

The Kubernetes cluster (kubeadm, 2 AWS EC2 nodes) and Istio service mesh were confirmed healthy before any application deployment — both nodes `Ready`, all `istio-system` pods `Running`.

\---

## Phase 1 — Git Hygiene \& Release Management Fixes

### Baseline: the messy history

Four commits landed directly on `main` with no branch, no PR, no review — vague messages, a silent bug, and a leaked secret buried between innocent-looking commits:

![Baseline messy git history](./screenshots/phase1-baseline-log.png)

### Root Cause 1: Silent regression in `frontend → payment-service` call

A commit with the vague message `"fix"` silently changed a `requests.post()` call to `requests.get()` in `services/frontend/app.py`, which the Flask route on `payment-service` doesn't accept — breaking payments without an obvious crash or log signature.

**Diagnosis:** Used `git bisect` (`git bisect start`, `bad HEAD`, `good <known-good-commit>`, then `git bisect run grep -q 'requests.post(...)' services/frontend/app.py`) to programmatically identify commit `84cc827` as the first bad commit, rather than guessing from commit messages:

![git bisect run output](./screenshots/phase1-bisect-run.png)

Confirmed the exact change with `git diff <good> <bad> -- services/frontend/app.py`:

![git diff showing the exact bug](./screenshots/phase1-diff-bug.png)

**Fix:** `git revert 84cc827 --no-edit`, with the revert's commit message rewritten to explicitly document what it fixed and how it was found (`"Revert POST->GET regression in frontend->payment call, found via git bisect (introduced in 84cc827)"`).

**Why revert, not reset:** the bad commit was already pushed and potentially shared; `revert` preserves an honest audit trail (the mistake and its correction are both visible in history), whereas `reset --hard` would rewrite shared history and destroy that record.

### Root Cause 2: Leaked AWS credentials committed to Git

A commit with the vague message `"wip"` added a `.env` file containing fake-but-realistically-shaped AWS credentials to `services/account-service/`, buried between two innocent-looking commits ("update readme" before, "minor update" after).

Before rewriting history to remove it, a `git reflog` snapshot was captured as a documented recovery point in case the rebase went wrong:

![git reflog safety net](./screenshots/phase1-reflog.png)

**Fix:** `git revert` was *not* sufficient here — reverting only adds a new commit undoing the change, but the secret remains permanently retrievable via `git show 6b31ec7` for anyone with access to the repo. Instead: `git rebase -i 8fdce31`, marking the `wip` commit as `drop`, then `git push origin main --force-with-lease`. Verified removal:

![Secret confirmed gone from history](./screenshots/phase1-secret-verified-gone.png)

**Alternative considered:** leaving the secret in history and only rotating the credential. Rejected because the assignment scenario is specifically about a credential accidentally committed to a *public* repo — rotation alone doesn't address that the value remains permanently visible to anyone who clones the repo's history.

### Mistake and recovery: `git add .` swept unrelated files into an unrelated commit

While creating the deliberate "fix" commit, `git add .` was used — which staged not just the intended one-line bug but also four untracked `k8s/\*.yaml` manifest files that happened to exist in the working directory at the time. When commit `84cc827` was later reverted, those manifests were deleted from the repo along with the bug, since `revert` undoes the *entire* diff of the target commit:

![Revert unexpectedly deletes k8s manifests](./screenshots/phase1-revert-deletes-k8s.png)

**Fix:** the manifests were recreated and committed in their own dedicated commit (`git add k8s/` — explicit path, not `.`), with a commit message documenting why. Final history shows the full arc — bug, fix, secret removal, and recovery — as one honest, readable trail:

![Final clean git log](./screenshots/phase1-clean-final-log.png)

**Lesson (documented for this exact reason):** `git add .` stages everything in the working directory indiscriminately. A later `revert` on a commit built this way has a much larger blast radius than the developer likely intended. Prefer `git add <specific-paths>` and `git status` before every commit.

### Branch Protection \& GitHub Flow

`main` is now protected: PRs required, status checks (`gitleaks`, `python-lint`) required to pass, force-push and branch deletion restricted. Verified by attempting a direct push after enabling protection:

![Direct push to main rejected](./screenshots/phase1-direct-push-rejected.png)

**Limitation (documented honestly):** required approvals is set to **0**, not 1+, because GitHub does not allow a PR author to approve their own PR — confirmed directly (only "Comment" was available, not "Approve", when attempted). On a team, this would be 1+ with an independent reviewer.

### Pre-push Secret Scanning

A `gitleaks`-based pre-push hook (`hooks/pre-push`) was added and wired in via `git config core.hooksPath hooks`. Verified by attempting to push a correctly-formatted fake AWS key (AWS's own published example key, `AKIAIOSFODNN7EXAMPLE`) — the push was blocked before reaching GitHub:

![Pre-push hook blocks the secret](./screenshots/phase1-hook-blocks-secret.png)

**Note:** an earlier test using an incorrectly-shaped fake key (`AKIAABCDEFTEST`, too short) was *not* blocked — this was a true negative, not a broken hook: the string didn't match gitleaks' AWS key pattern (`AKIA` + 16 chars). Retesting with a correctly-shaped key confirmed the hook works as intended.

### CI-Gated PRs and Release Automation

`.github/workflows/pr-checks.yml` runs `gitleaks` and `flake8` on every PR against `main`. First attempt failed both checks:

![PR checks failing](./screenshots/phase1-pr-checks-failing.png)

After fixing the `gitleaks-action` token permission and the real flake8 violations (E302/E305/E401 across all three services), a subsequent PR passed cleanly:

![PR checks passing](./screenshots/phase1-pr-checks-passing.png)

`.github/workflows/changelog.yml` triggers on any `v\*` tag push, builds a changelog from `git log` since the last tag, and opens a PR with the result (rather than pushing directly, since `main` is protected). Release branch/tag convention followed: `release/2025.06.1`, tag `v2025.06.1`.

![Final changelog PR diff](./screenshots/phase1-changelog-diff.png)

**Debugging chain (worth documenting — four distinct, real root causes found in sequence):**

1. `gitleaks-action` initially failed with a permissions error — it needs `GITHUB\_TOKEN` passed explicitly via `env:`, which the first workflow draft omitted.
2. `python-lint` failed on genuine PEP8 violations (E302, E305, E401 — missing blank lines, multiple imports on one line) across all three services — fixed by reformatting each `app.py`.
3. The changelog workflow tried to push its generated `CHANGELOG.md` directly to `main` — blocked by the same branch protection rule that blocks humans, since bots aren't exempt. Fixed by switching to `peter-evans/create-pull-request`, which opens a PR instead.
4. Even after that fix, PR creation failed twice more: first because a tag-triggered checkout leaves Git in detached-HEAD state, so `create-pull-request` needs an explicit `base: main` input; second because the repository-level setting "Allow GitHub Actions to create and approve pull requests" was disabled by default, which is separate from the workflow's own `permissions:` block.

Each of these was diagnosed from the actual GitHub Actions log output rather than guessed, and each fix is its own small, reviewable commit.

\---

## Phase 2 — Jenkins CI/CD Diagnosis and Pipeline Recovery

Jenkins (master + one agent, `docker-agent`) was installed via Docker on the control-plane node, connected over a dedicated Docker network. Baseline healthy state:

![Agent connected](./screenshots/phase2-agent-connected.png)

### Real incident (unplanned): EC2 root volume disk-full during Jenkins install

While installing Jenkins plugins, the EC2 control-plane node's 6.7GB root volume hit 100% used / 0 bytes free — an unplanned but genuine hit on exactly the diagnostic question the assignment poses ("Is disk full?"):

![Disk full during Jenkins setup](./screenshots/phase2-disk-full-df.png)

**Diagnosis:** `df -h` confirmed 100% usage; `sudo du -h --max-depth=2 /var` broke it down further, showing `containerd` (2.4G — Kubernetes images/snapshots) and `docker` (765M — Jenkins + service images) as the real, legitimate consumers, not reclaimable garbage. Low-risk cleanup (old snap revisions, apt autoremove) only freed a few hundred MB.

**Fix:** resized the EBS root volume from \~7GB to 20GB via the AWS console, then `growpart` + `resize2fs` to extend the partition and filesystem live, with no data loss or reinstall required:

![Disk resized](./screenshots/phase2-disk-resized-df.png)

**Side effect of the corrupted install:** the disk-full condition caused the Jenkins setup wizard's admin-user-creation step to fail silently mid-write, leaving Jenkins in a state where the Setup Wizard kept re-triggering on every load with no valid user underneath it. Recovered by editing `config.xml` directly (`useSecurity` false) to regain access, marking the install/upgrade wizard state files as complete to bypass the broken wizard flow, then reconfiguring a real security realm and resetting the (as it turned out, already-created) `admin` account's password through the UI.

### Root Cause: Offline agent after EC2 stop/start

Task 1 asks whether agents are disconnected — confirmed directly, from a real restart rather than a simulated one:

![Agent shown as Exited](./screenshots/phase2-agent-exited.png)

**Diagnosis:** `docker ps -a` showed `jenkins-agent` as `Exited (143)` after the EC2 instances were stopped and restarted, while the `jenkins` master container came back up (it had been manually started). Root cause: neither container had a restart policy set, so only the one manually restarted came back.

**Fix:** `docker start jenkins-agent` to bring it back immediately, then `docker update --restart unless-stopped jenkins jenkins-agent` on both containers so this doesn't recur on the next stop/start.

**Note:** the assignment also asks whether Docker builds are causing agent overload — that was checked for but was not the actual root cause found here; the disconnect was purely restart-policy-related, not resource contention on the agent itself.

### Root Cause: Rollback pipeline fails on tag mismatch

The pipeline's `post { failure { ... } }` block hardcoded a rollback target of `v1.0.0` — a tag that never existed in this repository.

**Diagnosis:** triggering a deliberate pipeline failure (Health Check stage exits 1 on purpose) surfaced the rollback itself failing:

![Rollback bug reproduced](./screenshots/phase2-rollback-bug-console.png)

**Fix:** replaced the hardcoded tag with a dynamic lookup, `git describe --tags --abbrev=0`, which resolves to the actual last successful release tag at rollback time:

![Rollback fixed](./screenshots/phase2-rollback-fixed-console.png)

**Deferred:** the assignment also asks for a *conditional* rollback triggered by Istio-reported 5xx rates rather than a hardcoded pipeline stage failure. This depends on Istio traffic policies and metrics that don't exist yet (Phase 4) — noted here as a sequencing dependency, not a skipped requirement, and will be added once Phase 4 is complete.

### Timeout and Failure Notifications

Added `options { timeout(time: 10, unit: 'MINUTES') }` and a notification step in the failure block. Confirmed both fire correctly on a real failing build:

![Timeout and notify confirmed](./screenshots/phase2-timeout-notify-console.png)

**Note:** the notification step is currently a placeholder `echo` rather than a real Slack/email integration, since that would require a configured webhook/SMTP credential — documented here rather than faked.

### Securing Jenkins

* **Limiting who can trigger the pipeline:** switched Authorization from "Logged-in users can do anything" to matrix-based security, with only the named admin account granted build/trigger permissions and anonymous users left unchecked:

![Matrix security configured](./screenshots/phase2-matrix-security.png)

* **Credential rotation:** stored a real Docker Hub credential in Jenkins Credentials Manager (ID `dockerhub-creds`) rather than any pipeline code referencing a secret directly:

![Credential stored in Jenkins](./screenshots/phase2-credential-stored.png)

Rotated it by generating a new Docker Hub access token, updating the Jenkins credential with it, and revoking the old token on Docker Hub's side — no pipeline code changes were needed to rotate the underlying secret, which is the entire point of storing it this way rather than hardcoding it (directly addresses the same class of problem as the leaked `.env` secret in Phase 1, but at the CI/CD layer instead of the Git layer).

## Phase 3 — Docker/K8s-Based Resilient Deployment

**Root Cause 1 (confirmed): `account-service-v2` OOMKilled**

* `account-service:v2` was deliberately built with an in-memory leak (appends \~1MB per request to a list that's never cleared) and deployed with a memory limit of `50Mi`.
* Confirmed via `kubectl describe pod` after sending a burst of requests directly to the pod: `Reason: OOMKilled`, `Exit Code: 137`, `Restart Count: 1`.
* *Fix not yet applied — pending: raise/tune the memory limit and address the underlying leak, or both, and document the trade-off.*

**Root Cause 2 (confirmed): MongoDB PVC stuck `Pending`**

* The StatefulSet's `volumeClaimTemplate` specifies `storageClassName: "fast-ssd-doesnotexist"`, which does not exist on the cluster.
* Confirmed via `kubectl describe pvc` — Events explicitly show the storage class cannot be found.
* *Fix not yet applied — pending: point at a valid storage class (e.g., the cluster's default) and re-verify the StatefulSet becomes `Running`.*

*Remaining for this phase: canary label/routing fix, ResourceQuota enforcement, fault-injection verification. Screenshots for this phase will be added once fixes are complete.*

## Phase 4 — Istio Traffic Control, Security, and Observability

*Status: not yet started.*

## Bonus — Final Chaos Injection

*Status: not yet started.*

\---

## Summary of Alternatives Considered

|Decision|Chosen|Alternative|Why|
|-|-|-|-|
|Fix the frontend/payment bug|`git revert`|`git reset --hard`|Preserves audit trail on shared/pushed history|
|Remove leaked secret|`git rebase -i` (drop commit) + force-push|`git revert` only|Revert doesn't remove the secret from retrievable history|
|Changelog delivery to `main`|Open a PR via `create-pull-request`|Direct push from the workflow|Branch protection blocks all direct pushes, bots included — this is the correct pattern, not a workaround|
|Branch protection approvals|0 required|1+ required|GitHub blocks self-approval; documented as a solo-project limitation rather than disabled protection entirely|
|Local dev cluster|AWS EC2 + `kubeadm`|`kind`/`minikube`|Chosen deliberately for closer-to-production cluster administration experience, at the cost of \~$30/month and more manual setup|



