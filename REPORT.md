# Incident Report — FinTrack Release Night Chaos

**Author:** Kaushik Shettigar
**Assignment:** Kubernetes & Docker Black Box Challenge — Assignment #2

Screenshots for Phases 1–4 live in [`/screenshots`](./screenshots) and are embedded inline below. Save yours under these exact filenames and the embeds will render on GitHub. The bonus round doesn't have screenshots embedded yet.

## Screenshot Index (Phase 1)

| Filename | What it shows |
|---|---|
| `screenshots/phase1-baseline-log.png` | `git log --oneline --graph --all` — messy "before" history (vague messages, direct-to-main) |
| `screenshots/phase1-bisect-run.png` | `git bisect run` output narrowing to the bad commit |
| `screenshots/phase1-diff-bug.png` | `git diff` showing the exact POST→GET regression |
| `screenshots/phase1-reflog.png` | `git reflog` — recovery point captured before the history-rewriting rebase |
| `screenshots/phase1-revert-deletes-k8s.png` | The revert's diffstat unexpectedly deleting `k8s/*.yaml` (the `git add .` lesson) |
| `screenshots/phase1-secret-verified-gone.png` | `git log --all --oneline -- services/account-service/.env` — returns nothing |
| `screenshots/phase1-clean-final-log.png` | Final `git log --oneline --graph --all` — bug fix, secret removal, and k8s recovery all visible |
| `screenshots/phase1-hook-blocks-secret.png` | Pre-push hook blocking a correctly-shaped fake AWS key |
| `screenshots/phase1-pr-checks-failing.png` | PR #1 — gitleaks + python-lint both red (before fixes) |
| `screenshots/phase1-pr-checks-passing.png` | PR #2 — gitleaks + python-lint both green (after fixes) |
| `screenshots/phase1-direct-push-rejected.png` | Branch protection blocking a direct push to `main` |
| `screenshots/phase1-changelog-diff.png` | Final `CHANGELOG.md` PR diff — full auto-generated release history |

## Screenshot Index (Phase 2)

| Filename | What it shows |
|---|---|
| `screenshots/phase2-agent-connected.png` | Jenkins agent `docker-agent` status page — "Agent is connected" |
| `screenshots/phase2-disk-full-df.png` | `df -h` — root volume at 100%, 0 bytes free (real incident, not simulated) |
| `screenshots/phase2-disk-resized-df.png` | `df -h` after EBS volume resize — space no longer critical |
| `screenshots/phase2-agent-exited.png` | `docker ps -a` showing `jenkins-agent` as `Exited (143)` after EC2 stop/start |
| `screenshots/phase2-rollback-bug-console.png` | Pipeline build #6 console — rollback fails on hardcoded nonexistent tag `v1.0.0` |
| `screenshots/phase2-rollback-fixed-console.png` | Pipeline build #7 console — rollback correctly resolves to `v2025.06.1` via `git describe` |
| `screenshots/phase2-timeout-notify-console.png` | Pipeline build #8 console — `Timeout set to expire in 10 min` and `NOTIFY:` line firing on failure |
| `screenshots/phase2-matrix-security.png` | Jenkins matrix-based authorization restricting anonymous/non-admin pipeline triggers |
| `screenshots/phase2-credential-stored.png` | `dockerhub-creds` stored in Jenkins Credentials Manager (masked value) |

## Screenshot Index (Phase 3)

| Filename | What it shows |
|---|---|
| `screenshots/phase3-oomkilled-describe.png` | `kubectl describe pod` — `Reason: OOMKilled`, `Exit Code: 137` before the fix |
| `screenshots/phase3-pvc-pending-describe.png` | `kubectl describe pvc` — Events showing the missing storage class before the fix |
| `screenshots/phase3-pvc-bound.png` | `kubectl get pvc` — `Bound` against `local-path`, real volume attached |
| `screenshots/phase3-cascading-pileup.png` | `kubectl get pods` — hundreds of `Error`/`ContainerStatusUnknown`/`Evicted` pods from a real cascading incident |
| `screenshots/phase3-fintrack-clean.png` | `kubectl get pods -n fintrack` after cleanup — 6 healthy pods, 2/2, zero restarts |
| `screenshots/phase3-istio-clean.png` | `kubectl get pods -n istio-system` after cleanup — 3 healthy core components |
| `screenshots/phase3-canary-labels.png` | `kubectl get pods --show-labels` — `version=v1`/`version=v2` correctly set for Istio subset routing |
| `screenshots/phase3-quota-active.png` | `kubectl describe resourcequota` — active and correctly sized for Istio sidecar overhead |
| `screenshots/phase3-rolling-update.png` | `kubectl get pods -w` — rolling update after applying the corrected manifest, old pods terminating as new ones come up |

## Screenshot Index (Phase 4)

| Filename | What it shows |
|---|---|
| `screenshots/phase4-mtls-canary-describe.png` | `istioctl x describe pod` — `Workload mTLS mode: STRICT`, DestinationRule/VirtualService correctly matched, 90% weight to v1 |
| `screenshots/phase4-canary-distribution.png` | 50-request distribution test — 47 v1 / 3 v2, matching the 90/10 target |
| `screenshots/phase4-circuit-breaker-tripped.png` | 5 real `500`s followed by `503`s once Envoy ejects the pod |
| `screenshots/phase4-circuit-breaker-recovered.png` | `200`s again after `baseEjectionTime`, confirming the ejection is temporary |
| `screenshots/phase4-jaeger-services.png` | Jaeger service dropdown showing `frontend`, `account-service`, `payment-service` as real traced services |
| `screenshots/phase4-unified-trace.png` | Full end-to-end trace — `Services 3`, `Depth 4`, `Total Spans 6` — showing where latency concentrates |

---

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

---

## Phase 1 — Git Hygiene & Release Management Fixes

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

While creating the deliberate "fix" commit, `git add .` was used — which staged not just the intended one-line bug but also four untracked `k8s/*.yaml` manifest files that happened to exist in the working directory at the time. When commit `84cc827` was later reverted, those manifests were deleted from the repo along with the bug, since `revert` undoes the *entire* diff of the target commit:

![Revert unexpectedly deletes k8s manifests](./screenshots/phase1-revert-deletes-k8s.png)

**Fix:** the manifests were recreated and committed in their own dedicated commit (`git add k8s/` — explicit path, not `.`), with a commit message documenting why. Final history shows the full arc — bug, fix, secret removal, and recovery — as one honest, readable trail:

![Final clean git log](./screenshots/phase1-clean-final-log.png)

**Lesson (documented for this exact reason):** `git add .` stages everything in the working directory indiscriminately. A later `revert` on a commit built this way has a much larger blast radius than the developer likely intended. Prefer `git add <specific-paths>` and `git status` before every commit.

### Branch Protection & GitHub Flow

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

`.github/workflows/changelog.yml` triggers on any `v*` tag push, builds a changelog from `git log` since the last tag, and opens a PR with the result (rather than pushing directly, since `main` is protected). Release branch/tag convention followed: `release/2025.06.1`, tag `v2025.06.1`.

![Final changelog PR diff](./screenshots/phase1-changelog-diff.png)

**Debugging chain (worth documenting — four distinct, real root causes found in sequence):**
1. `gitleaks-action` initially failed with a permissions error — it needs `GITHUB_TOKEN` passed explicitly via `env:`, which the first workflow draft omitted.
2. `python-lint` failed on genuine PEP8 violations (E302, E305, E401 — missing blank lines, multiple imports on one line) across all three services — fixed by reformatting each `app.py`.
3. The changelog workflow tried to push its generated `CHANGELOG.md` directly to `main` — blocked by the same branch protection rule that blocks humans, since bots aren't exempt. Fixed by switching to `peter-evans/create-pull-request`, which opens a PR instead.
4. Even after that fix, PR creation failed twice more: first because a tag-triggered checkout leaves Git in detached-HEAD state, so `create-pull-request` needs an explicit `base: main` input; second because the repository-level setting "Allow GitHub Actions to create and approve pull requests" was disabled by default, which is separate from the workflow's own `permissions:` block.

Each of these was diagnosed from the actual GitHub Actions log output rather than guessed, and each fix is its own small, reviewable commit.

---

## Phase 2 — Jenkins CI/CD Diagnosis and Pipeline Recovery

Jenkins (master + one agent, `docker-agent`) was installed via Docker on the control-plane node, connected over a dedicated Docker network. Baseline healthy state:

![Agent connected](./screenshots/phase2-agent-connected.png)

### Real incident (unplanned): EC2 root volume disk-full during Jenkins install

While installing Jenkins plugins, the EC2 control-plane node's 6.7GB root volume hit 100% used / 0 bytes free — an unplanned but genuine hit on exactly the diagnostic question the assignment poses ("Is disk full?"):

![Disk full during Jenkins setup](./screenshots/phase2-disk-full-df.png)

**Diagnosis:** `df -h` confirmed 100% usage; `sudo du -h --max-depth=2 /var` broke it down further, showing `containerd` (2.4G — Kubernetes images/snapshots) and `docker` (765M — Jenkins + service images) as the real, legitimate consumers, not reclaimable garbage. Low-risk cleanup (old snap revisions, apt autoremove) only freed a few hundred MB.

**Fix:** resized the EBS root volume from ~7GB to 20GB via the AWS console, then `growpart` + `resize2fs` to extend the partition and filesystem live, with no data loss or reinstall required:

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

- **Limiting who can trigger the pipeline:** switched Authorization from "Logged-in users can do anything" to matrix-based security, with only the named admin account granted build/trigger permissions and anonymous users left unchecked:

![Matrix security configured](./screenshots/phase2-matrix-security.png)

- **Credential rotation:** stored a real Docker Hub credential in Jenkins Credentials Manager (ID `dockerhub-creds`) rather than any pipeline code referencing a secret directly:

![Credential stored in Jenkins](./screenshots/phase2-credential-stored.png)

  Rotated it by generating a new Docker Hub access token, updating the Jenkins credential with it, and revoking the old token on Docker Hub's side — no pipeline code changes were needed to rotate the underlying secret, which is the entire point of storing it this way rather than hardcoding it (directly addresses the same class of problem as the leaked `.env` secret in Phase 1, but at the CI/CD layer instead of the Git layer).

---

## Phase 3 — Docker/K8s-Based Resilient Deployment

### Root Cause 1: `account-service-v2` OOMKilled

`account-service:v2` was deliberately built with an in-memory leak (appends ~1MB per request to a list that's never cleared) and deployed with a memory limit of `50Mi`.

**Diagnosis:** confirmed via `kubectl describe pod` after sending a burst of requests directly to the pod (via `kubectl port-forward`, bypassing the Service's load balancing to guarantee hitting v2):

![OOMKilled confirmed](./screenshots/phase3-oomkilled-describe.png)

`Reason: OOMKilled`, `Exit Code: 137`, `Restart Count: 1`.

**Fix:** raised the memory limit to a more realistic `256Mi` (requests `64Mi`/`50m` CPU) and added a liveness probe (`/healthz`, `failureThreshold: 3`) so Kubernetes automatically cycles the pod if it does get into trouble — this is the "retry strategy" the task asks for. The underlying leak itself is a real application-level bug that raising the limit does not fix, only delays; documented here rather than hidden, since a genuine fix would require patching the leak in `account-service`'s code, not just infrastructure.

**Alternative considered:** fixing the leak in application code directly. Not done, since the leak is a deliberately-injected part of the assignment scenario meant to be diagnosed at the infrastructure layer — noted as the "real" fix a production team would also pursue in parallel.

### Root Cause 2: MongoDB PVC stuck `Pending`

The StatefulSet's `volumeClaimTemplate` specified `storageClassName: "fast-ssd-doesnotexist"`, which did not exist on the cluster — confirmed via `kubectl describe pvc`, Events explicitly showing the storage class could not be found.

**Diagnosis:** `kubectl get storageclass` returned zero results — kubeadm clusters, unlike managed Kubernetes offerings, ship with no default storage provisioner at all.

**Fix:** installed `local-path-provisioner` (Rancher's lightweight standard choice for bare-metal/kubeadm clusters), set it as the default StorageClass, and pointed the StatefulSet at `local-path`. Since `volumeClaimTemplates` are immutable after creation, the StatefulSet and its stuck PVC had to be deleted and recreated rather than patched in place:

![PVC bound](./screenshots/phase3-pvc-bound.png)

### Real incident (unplanned): cascading pod pileup across both nodes

While verifying the above fixes, `kubectl get pods` returned **hundreds** of pods in `Error`, `ContainerStatusUnknown`, and `Evicted` states across both the `fintrack` and `istio-system` namespaces:

![Cascading pod pileup](./screenshots/phase3-cascading-pileup.png)

**Diagnosis, traced back through several layers:**
1. `kubectl get nodes` showed both nodes `Ready` — not a current outage.
2. `kubectl get events --sort-by='.lastTimestamp'` on the worker node showed repeated `Evicted` events with reason `The node was low on resource: ephemeral-storage`, plus `FailedScheduling` errors citing an `untolerated taint {node.kubernetes.io/disk-pressure: }`.
3. `df -h` on the worker confirmed its own 6.7GB root volume was also nearly full — the same class of problem already diagnosed and fixed on the control-plane node in Phase 2, just not yet applied to the worker.
4. Root chain: repeated EC2 stop/starts (during earlier troubleshooting) → `containerd` image/snapshot data accumulating on an undersized disk → disk-pressure taint → pod evictions → each eviction triggering the owning ReplicaSet to spawn a replacement → replacements repeatedly failing the same way while the API server was intermittently reachable → hundreds of orphaned pod objects never garbage collected.

**Fix:** resized the worker's EBS volume the same way as the control-plane (20GB, `growpart` + `resize2fs`), which cleared the disk-pressure taint automatically within a couple of minutes (kubelet self-monitors this, no manual intervention needed). Bulk-removed the dead pod objects rather than one at a time:
```bash
kubectl delete pods --field-selector=status.phase!=Running -n fintrack
kubectl delete pods --field-selector=status.phase!=Running -n istio-system
```

![fintrack namespace clean](./screenshots/phase3-fintrack-clean.png)

![istio-system namespace clean](./screenshots/phase3-istio-clean.png)

**Note for context:** this organically reproduced the assignment's own described symptom — *"kubectl get pods shows a mix of CrashLoopBackOff, ImagePullBackOff, and Pending"* — caused by real infrastructure instability rather than a manually injected fault, which is arguably more representative of the "production SRE" mindset the assignment asks for than the deliberately-seeded bugs.

### Canary Labels

`account-service-v1` and `account-service-v2` Deployments carry `version: v1`/`version: v2` labels on both `metadata.labels` and the pod template, matching what an Istio `DestinationRule` needs to define subsets for traffic splitting (built into the manifests from the start; verified still correct after all the above incidents):

![Canary labels verified](./screenshots/phase3-canary-labels.png)

**Deferred:** actual traffic-split enforcement (90/10 weighting) requires the Istio `VirtualService`/`DestinationRule` objects that are Phase 4's responsibility — the labels are the Phase 3 prerequisite, confirmed correct and ready.

### ResourceQuota

Applied a per-namespace `ResourceQuota` — but the first version (`limits.cpu: "4"`, `limits.memory: "4Gi"`) was immediately exceeded on creation (`Used: 12 / Hard: 4` for CPU), because it didn't account for **Istio's automatic sidecar injection**, which sets a default CPU/memory limit on every `istio-proxy` container added to each pod. With 5+ pods each carrying a sidecar, that overhead alone exceeded the quota before any application container was counted.

**Fix:** raised the quota to `limits.cpu: "16"`, `limits.memory: "8Gi"` — sized to actually fit sidecar + application overhead across the namespace's real pod count, rather than an arbitrary round number:

![ResourceQuota active and correctly sized](./screenshots/phase3-quota-active.png)

**Compounding issue discovered:** this undersized quota silently blocked the Deployment manifest fix from actually applying — `kubectl apply` had been run against the manifest file, but the *live* Deployment's pod template still had no `resources:` block from before the Phase 3 fix, because the corrected file had only been merged to Git, not re-applied to the cluster. The ReplicaSet's `FailedCreate` events explicitly named the missing `resources` fields as the rejection reason. Re-running `kubectl apply -f k8s/account-service-deployment.yaml` triggered a proper rolling update:

![Rolling update in progress](./screenshots/phase3-rolling-update.png)

**Lesson:** merging a fix to Git and applying it to a live cluster are two separate steps — a manifest change sitting only in version control has zero effect on running infrastructure until `kubectl apply` is actually re-run.

### Fault Injection and Recovery Verification

Deleted a running `account-service-v1` pod directly (`kubectl delete pod`) and confirmed Kubernetes' built-in self-healing replaced it automatically via the Deployment's ReplicaSet, without any manual intervention — the same self-healing mechanism the liveness probe (Root Cause 1) also relies on.

---

## Phase 4 — Istio Traffic Control, Security, and Observability

### mTLS

Applied a namespace-wide `PeerAuthentication` with `mtls.mode: STRICT`. Verified directly rather than assuming it took effect:

```bash
istioctl x describe pod $(kubectl get pod -l app=account-service,version=v1 -n fintrack -o jsonpath='{.items[0].metadata.name}') -n fintrack
```

![mTLS and canary routing confirmed together](./screenshots/phase4-mtls-canary-describe.png)

Output showed `Workload mTLS mode: STRICT` under "Effective PeerAuthentication" — confirming enforcement, not just that the resource was created.

**Real consequence discovered:** STRICT mode also rejects any *non-mesh* client connecting directly to a pod — including a raw `curl` hitting the `frontend` NodePort from outside the cluster (`Connection was reset`). This isn't a bug; it's the intended behavior of STRICT mTLS. It meant the "hit the service from outside" testing approach used earlier in the project no longer worked once mTLS was enabled, and traffic generation for later tests (canary, circuit breaker, tracing) had to originate from *inside* the mesh (pod-to-pod) instead.

### Canary Routing (90/10 split)

Created a `DestinationRule` defining `v1`/`v2` subsets (matching the `version` labels already set on the Deployments back in Phase 3) and a `VirtualService` routing 90% of traffic to `v1`, 10% to `v2`, with `retries: {attempts: 2, perTryTimeout: 1s}` and `timeout: 3s`.

**Verification:** sent 50 requests to `account-service` from inside the mesh and counted which version answered:
```python
c = collections.Counter()
for _ in range(50):
    c[requests.get('http://account-service:5000/').json()['version']] += 1
```

![Canary distribution: 47 v1 / 3 v2](./screenshots/phase4-canary-distribution.png)

`47 v1 / 3 v2` — matching the 90/10 target within expected statistical variance for 50 samples.

**Port-naming fix along the way:** `istioctl analyze` flagged all three Services with `IST0118` — unnamed ports don't follow Istio's naming convention, which can lead to unreliable protocol auto-detection (relevant later for tracing accuracy). Fixed by adding `name: http` to every Service's port definition; `istioctl analyze` came back clean afterward.

### Circuit Breaker (payment-service)

Configured a `DestinationRule` with `outlierDetection: {consecutive5xxErrors: 5, interval: 1m, baseEjectionTime: 1m}`.

**First test showed no ejection at all** despite `FAIL_RATE=1.0` producing real `500`s on every request. Root cause: Envoy's outlier detection has a default `maxEjectionPercent` of 10% — with only 1 replica of `payment-service`, ejecting it would remove 100% of the pool, which exceeds that 10% cap, so Envoy refuses to eject the sole host rather than take the entire service down. Fixed by explicitly setting `maxEjectionPercent: 100`, appropriate for a single-replica service.

![Circuit breaker tripped: 500s then 503s](./screenshots/phase4-circuit-breaker-tripped.png)

Retested: 5 real `500`s (matching `consecutive5xxErrors: 5`), then Envoy stopped forwarding to the pod entirely and returned `503` locally for every subsequent request.

**Recovery confirmed temporary**, not permanent, per `baseEjectionTime`:

![Circuit breaker recovered after baseEjectionTime](./screenshots/phase4-circuit-breaker-recovered.png)

### Distributed Tracing

Jaeger was found not actually running in the cluster (lost at some point during earlier EC2 restarts/cleanups) — reinstalled via the standard Istio addon manifest.

**First tracing attempt showed zero real traces** — only Jaeger's own self-monitoring spans (`jaeger-all-in-one`). Diagnosed and fixed through several distinct causes in sequence:
1. Istio 1.22 does not auto-wire tracing from the `demo` profile alone; the `zipkin` extension provider and `enableTracing` had to be configured explicitly via an `IstioOperator` overlay, plus a `Telemetry` resource setting `randomSamplingPercentage: 100`.
2. Even after that, requests showed as two *separate* 2-span traces (`frontend→account-service`, `frontend→payment-service`) instead of one unified trace. Root cause: the Flask app never forwarded incoming trace headers (`x-b3-*`) onto its own outbound requests, so each downstream call started a fresh trace rather than continuing the parent one. Fixed by extracting and forwarding the B3 headers in `frontend/app.py`.
3. That fix appeared to have no effect on retest — because the updated image had been pushed to Docker Hub under the same `:v1` tag, but the node's `imagePullPolicy` (default `IfNotPresent`) meant `kubectl rollout restart` kept reusing the stale cached image rather than pulling the new one. Fixed by setting `imagePullPolicy: Always`.
4. Even with the fix genuinely running, traces still split — because the traffic used to test it (`kubectl exec ... requests.get('http://localhost:5000/')`) hit the app directly on its loopback address, bypassing its own Envoy sidecar entirely; with no sidecar involved, no trace headers were ever generated for the app to forward in the first place. Fixed by sending test traffic from a *different* pod to `frontend`'s Service name, so the request genuinely passed through Envoy on both ends.
5. A related dead end: attempting to test via the external NodePort instead failed with `Connection was reset` — because STRICT mTLS (see above) correctly rejects non-mesh clients, so external NodePort testing isn't viable once mTLS is enabled; testing had to move to mesh-internal pod-to-pod calls instead.

![Jaeger showing all three real services](./screenshots/phase4-jaeger-services.png)

![Unified end-to-end trace](./screenshots/phase4-unified-trace.png)

**Result:** a genuine unified trace — `Services 3`, `Depth 4`, `Total Spans 6` — showing `frontend → account-service` and `frontend → payment-service` as siblings under one parent.

**Where is latency introduced?** In the trace waterfall, `frontend` itself accounts for ~27ms of the ~30ms total trace duration, while `account-service` and `payment-service` each contribute only ~2.5ms (their own server-side processing under 2ms each). The bottleneck is not either downstream service — it's `frontend`'s own handling time. Given the app code calls `account-service` and `payment-service` **sequentially** (one `requests.get`/`requests.post` after the other) despite neither call depending on the other's result, the most direct optimization would be making these two calls concurrently (e.g., a thread pool or async HTTP client) rather than back-to-back, which should reduce `frontend`'s own contribution to roughly the duration of the slower of the two calls instead of their sum.

## Bonus — Final Chaos Injection

*Status: not yet started.*

---

## Summary of Alternatives Considered

| Decision | Chosen | Alternative | Why |
|---|---|---|---|
| Fix the frontend/payment bug | `git revert` | `git reset --hard` | Preserves audit trail on shared/pushed history |
| Remove leaked secret | `git rebase -i` (drop commit) + force-push | `git revert` only | Revert doesn't remove the secret from retrievable history |
| Changelog delivery to `main` | Open a PR via `create-pull-request` | Direct push from the workflow | Branch protection blocks all direct pushes, bots included — this is the correct pattern, not a workaround |
| Branch protection approvals | 0 required | 1+ required | GitHub blocks self-approval; documented as a solo-project limitation rather than disabled protection entirely |
| Local dev cluster | AWS EC2 + `kubeadm` | `kind`/`minikube` | Chosen deliberately for closer-to-production cluster administration experience, at the cost of ~$30/month and more manual setup |
| MongoDB storage | Install `local-path-provisioner` | Manually create PVs | Standard, minimal-effort choice for kubeadm/bare-metal clusters with no cloud storage API to hook into |
| account-service-v2 memory | Raise limit + liveness probe | Fix the leak in code | Infrastructure-layer mitigation matches the assignment's Phase 3 scope; the code-level leak is intentionally part of the scenario and noted as the real underlying fix a team would also pursue |
| ResourceQuota sizing | 16 CPU / 8Gi, based on measured sidecar overhead | Leave at an arbitrary round number | First attempt (4 CPU / 4Gi) was immediately exceeded by Istio sidecar overhead alone; sizing from real `kubectl describe resourcequota` usage avoids repeating that mistake |
| Circuit breaker ejection cap | `maxEjectionPercent: 100` | Leave the 10% default | Default silently prevents ejection entirely when a service has only 1 replica; explicit override needed for the breaker to function as specified |
| Tracing test traffic | Pod-to-pod calls using Service DNS names | `kubectl exec` to `localhost`, or external `curl` via NodePort | Both alternatives bypass the mesh (skip the sidecar or get rejected by STRICT mTLS respectively); only genuine in-mesh, service-to-service calls produce real, connected traces |
| Frontend's sequential downstream calls | Documented as the identified latency bottleneck, not yet changed | Immediately rewrite to run concurrently | Root cause and recommendation captured for the report; implementing was left explicit as future work rather than silently expanding Phase 4's scope |
