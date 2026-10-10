# Contributing

## Workflow

1. Pick or create an issue for the task. Say in the issue that you are taking it.
2. Branch from an up-to-date `main`:
   ```bash
   git checkout main && git pull
   git checkout -b feature/<module>-<short-description>   # e.g. feature/maintenance-overlap-check
   ```
3. Commit small and often. Use clear messages in the imperative: `Add maintenance overlap check`.
4. Before opening a PR run `pytest` and `ruff check .`.
5. Open a pull request into `main` and fill in the template. Request one teammate as reviewer.
6. Merge only after CI is green and one teammate has approved. Do not push directly to `main`.

Branch prefixes: `feature/`, `fix/`, `docs/`, `test/`.

## Where code goes

- Stay inside your module unless the change is agreed. Cross-module changes get their own PR and a heads-up in the group chat.
- Controllers (`routes.py`) parse input and call services. Rules, transactions and SQL belong in `services.py`.
- Use `app/common/intervals.py` for overlap checks and `ApiError` for errors.
- Any change to booking, maintenance, approval, cancellation or equipment-status code must follow the equipment row-lock protocol (SAD 4.1.1) and rerun the regression cases listed in STP 5.4.
- Changes to `db/schema.sql` need a PR that everyone reviews, because every module depends on it.

## Tests

- Name tests after the STP case where there is one (`test_tc_f_014_...`) so the execution register and the RTM stay traceable.
- Use synthetic data only. Never use real student credentials or records.
- Concurrency tests must use separate database connections, not serialized calls.

## Documents (SRS, SAD, STP)

These are `.docx` files, and Git cannot merge them. Tell the group before you edit one so only one person has it open at a time. Do small edits in a dedicated `docs/` branch and merge it quickly.

Record test results in the CSV first (`docs/test-execution/execution-register.csv`). One person updates the STP from the CSV at the end.

If a booking policy or requirement changes, update the SRS, SAD and STP together and note the change in each revision history.

## Never commit

- `.env` files, passwords, tokens or keys
- Real student data or database dumps
- Anything under `docs/test-execution/evidence/` that contains personal data (this folder is git-ignored; share evidence another way and link it in the register)

## Commits

Commit with your own name and the email linked to your GitHub account so contributions are credited correctly:

```bash
git config user.name "Your Name"
git config user.email "you@example.com"
```
