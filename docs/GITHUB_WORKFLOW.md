# GitHub Issue and PR Workflow

This project should keep code changes traceable through GitHub Issues and Pull Requests.

## Rule

Do not push behavioral changes directly to `main` unless it is an emergency demo fix. Normal changes use:

```text
Issue -> branch -> commit -> PR -> review/verification -> merge
```

## Issue Content

Every issue should explain:

1. Symptom or goal.
2. Exact command and key log lines.
3. Suspected cause.
4. Expected behavior.
5. Files likely involved.
6. Hardware requirement.

For completed work that was already pushed, create an archive issue with:

1. Commit SHA.
2. Root cause.
3. Files changed.
4. Verification that was actually run.
5. Remaining follow-up.

## Branch Naming

Use short names that identify the problem:

```text
fix/ble-rdy-handshake
docs/runbook-update
archive/ble-recovery-baseline
calibration/pixel-angle-regression
```

## PR Content

Every PR should include:

1. Linked issue, preferably `Closes #N`.
2. Cause.
3. Change summary by file.
4. Static verification commands.
5. Hardware verification status.
6. Risk section.

If a PR changes Hub behavior, explicitly state whether `hub_pybricks_gesture_server.py` must be uploaded again in Pybricks Code.

## Generated Files

Do not commit runtime/generated files:

```text
gesture_bt/.venv/
gesture_bt/__pycache__/
gesture_bt/models/*.task
gesture_bt/aim_dataset.csv
```

## Current Archive

- Issue #3 archives main commit `db20895`, which hardened BLE recovery, absolute home calibration, one-shot fire logic, fire dataset logging, and README/protocol docs.
- Issue #4 tracks the follow-up BLE reconnect stall where the Hub can remain RUNNING but the Mac has no fresh `rdy` to resume stdin flow.
