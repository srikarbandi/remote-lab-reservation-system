# Requirement ownership

Source: IDs and priorities from the SRS traceability matrix (SRS section 8). Owners follow the responsibility split agreed in the team chat. The split does not cover audit logging, so that one is open. Change this file by PR if the team agrees a different split.

Status values follow the SRS RTM: **N** not executed, **P** partial, **A** accepted. Update the status only when there is test evidence in the execution register.

## Functional requirements

| ID | Requirement | Priority | Module | Owner | Test case | Status |
|---|---|---|---|---|---|---|
| LAB-F-001 | Login | High | auth | Spoorthy | TC-F-001 | N |
| LAB-F-002 | Logout | High | auth | Spoorthy | TC-F-002 | N |
| LAB-F-003 | Equipment catalogue | High | equipment | Shristi | TC-F-003 | N |
| LAB-F-004 | Equipment search | Medium | equipment | Shristi | TC-F-004 | N |
| LAB-F-005 | Availability | High | equipment (SAD lists it under Reservation) | Shristi, with Soha | TC-F-005 | N |
| LAB-F-006 | Submit request | High | reservations | Soha | TC-F-006 | N |
| LAB-F-007 | Conflict prevention | High | reservations | Soha | TC-F-007 | N |
| LAB-F-008 | Own history | High | reservations | Soha | TC-F-008 | N |
| LAB-F-009 | Cancel request | High | reservations | Soha | TC-F-009 | N |
| LAB-F-010 | Review requests | High | approvals | Soha | TC-F-010 | N |
| LAB-F-011 | Approve request | High | approvals | Soha | TC-F-011 | N |
| LAB-F-012 | Reject request | High | approvals | Soha | TC-F-012 | N |
| LAB-F-013 | Manage equipment | High | equipment | Shristi | TC-F-013 | N |
| LAB-F-014 | Maintenance blocks | High | maintenance | Sreekar | TC-F-014 | N |
| LAB-F-015 | Notifications | High | notifications | Sreekar | TC-F-015 | N |
| LAB-F-016 | Usage recording | High | usage | Sreekar | TC-F-016 | N |
| LAB-F-017 | Utilization report | Medium | reporting | Sreekar | TC-F-017 | N |
| LAB-F-018 | Manage accounts | High | auth | Spoorthy | TC-F-018 | N |
| LAB-F-019 | Audit events | High | audit | **To be agreed** | TC-F-019 | N |

## Non-functional and security requirements

Implementation is shared. The "test owner" column follows STP section 9.

| ID | Requirement | Test owner | Test case | Status |
|---|---|---|---|---|
| LAB-NF-001 | Read response time (p95 under 2 s, 50 users) | Sreekar | TC-NF-001 | N |
| LAB-NF-002 | Restart integrity and concurrent holds | Sreekar | TC-NF-002 | N |
| LAB-NF-003 | First-time booking task (4 of 5 testers in 3 min) | Shristi | TC-NF-003 | N |
| LAB-NF-004 | Keyboard navigation and labelled forms | Shristi | TC-NF-004 | N |
| LAB-NF-005 | Backup and restore (RPO 24 h, RTO 60 min) | Sreekar | TC-NF-005 | N |
| LAB-SR-001 | Role, lab and ownership checks on every operation | Soha | TC-SR-001 | N |
| LAB-SR-002 | Salted adaptive password hashes, secret-free logs | Soha | TC-SR-002 | N |
| LAB-SR-003 | HTTPS, secure cookies, CSRF | Soha | TC-SR-003 | N |
| LAB-SR-004 | Login throttling and 30-minute session expiry | Soha | TC-SR-004 | N |
| LAB-SR-005 | Server-side validation, parameterized queries | Soha | TC-SR-005 | N |

## Cross-module dependencies to settle early

- **Notifications and audit events are written by every module**, in the same transaction as the change. Sreekar's notification service and the audit `record_event()` helper need a signature the others can call from day one.
- **Maintenance and reservations share the equipment row lock.** The maintenance overlap check needs the `reservations` table and the lock helper from Soha's module.
- **Everything needs** `users`, `equipment` and `lab_memberships` from the shared schema, plus the login and session layer.
