## v2025.06.1
f1eee2e Merge pull request #4 from coshik/ci/fix-changelog-base
c68a794 Fix changelog workflow: explicitly set base branch since tag checkout leaves detached HEAD
35a3bd6 Merge pull request #3 from coshik/ci/fix-changelog-permissions
83cbda2 Fix changelog workflow: open a PR instead of pushing directly to protected main
76d031c Merge pull request #2 from coshik/ci/fix-gitleaks-token
f160608 Resolve flake8 lint errors (E302/E305/E401)
5248f5a Fix gitleaks-action: pass GITHUB_TOKEN so it can post PR check results
5d3276b Merge pull request #1 from coshik/ci/add-pr-checks-and-changelog
7df2b31 Merge remote-tracking branch 'origin/main' into ci/add-pr-checks-and-changelog
94f312a Add PR checks workflow, changelog automation, and pre-push secret hook
ba9f10a test hook
705b40e Restore k8s manifests (previously swept into an unrelated commit via git add .)
50029f2 Revert POST->GET regression in frontend->payment call, found via git bisect (introduced in 84cc827)
287e6a1 minor update
8fdce31 update readme
84cc827 fix
609615b Add frontend, account-service, and payment-service with Dockerfiles
f413cbe Initial repo structure for FinTrack infra assignment
c83a23f Initial commit
