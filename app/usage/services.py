"""Business rules and transaction boundaries for the usage module.

Owner (proposed): Sreekar Bandi
Requirements: LAB-F-016 (DS-Usage)

Follow the shared booking transaction protocol in SAD 4.1.1: validate, lock the
equipment row (SELECT ... FOR UPDATE), re-check, write the change together with
its notification and audit event, then commit.
"""

# TODO: implement service functions. Use parameterized queries only (LAB-SR-005).
