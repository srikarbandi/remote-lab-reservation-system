# Integration notes: shared helpers

These helpers were added with the maintenance, usage, reporting and notifications modules because those modules cannot work without them. They are small on purpose. Change them by PR if the team wants something different.

## Who is the user? `app/common/auth_context.py`

`current_user_id()` returns `g.user_id` or raises 401. **The auth module must set `g.user_id` (a UUID) once the session cookie is valid** (active account, not revoked, not expired). Roles are never read from the request. The tests use an `X-Test-User` header as a stand-in (see `tests/conftest.py`); that hook exists only in tests.

## Equipment row lock: `app/common/locking.py`

```python
with conn.transaction():
    equipment = lock_equipment(conn, equipment_id)  # SELECT ... FOR UPDATE, 5 s lock timeout
    require_lab_role(conn, actor_id, equipment["lab_id"], {...})
    # re-validate here, after the lock, then write
```

Every booking, approval, cancellation, equipment-status and opening-hour change must take this lock first (SAD 4.1.1). A timeout becomes `503 LOCK_TIMEOUT`. `tests/integration/test_concurrency.py` has a reference booking transaction (`book()`) that shows the expected shape and proves a booking and a maintenance block cannot both win.

## Roles: `app/common/permissions.py`

`require_lab_role(conn, user_id, lab_id, allowed)` loads the role from `lab_memberships`, rejects disabled accounts, and raises 403. Constants: `STUDENT`, `TECHNICIAN`, `ADMINISTRATOR`, `STAFF_ROLES`.

## Notifications: `app/notifications/services.py`

Call from inside your own transaction so the message commits or rolls back with the change:

```python
from app.notifications import services as notifications

message = notifications.build_message(
    notifications.APPROVED, equipment["name"], res["starts_at"], res["ends_at"]
)
notifications.create_notification(conn, res["student_id"], notifications.APPROVED, message, res["id"])
```

Event types: `SUBMITTED`, `APPROVED`, `REJECTED`, `CANCELLED`, `MAINTENANCE_CANCELLED` (use the last one when an administrator cancels a booking to clear a maintenance block, SRS 2.5).

## Audit: `app/audit/services.py`

`record_event(conn, actor_id, action, target_type, target_id, outcome, request_id)` inserts one row in the caller's transaction. The owner of the audit module is still to be agreed; this is the minimum every module needs. Action names used so far: `maintenance.create|update|delete`, `usage.record`.

## Errors and validation: `app/common/errors.py`, `app/common/validation.py`

Raise `ApiError(status, code, message, fields=None, details=None)`. `validation.py` has `json_body`, `check_fields` (rejects unknown fields), `parse_uuid`, `parse_datetime` (requires a UTC offset, returns UTC), `parse_date`, `parse_int`, `clean_text` (trimmed, 1 to 500 characters) and `parse_page`.

## Database: `app/db.py`

`with translate_db_errors(), connect() as conn:` returns dict rows and maps connection failures and lock timeouts to the 503 contract.

## Decisions to confirm with the team

- **Reports cover past dates only**, inclusive of today, and at most 366 days. The SRS says "past date range"; the 366-day cap is added to bound the work per request (SAD STRIDE denial-of-service row).
- **Usage is clipped to the selected date range, not to opening hours** (SAD 4.1.2), so utilization can exceed 100% if staff record usage outside opening hours.
- **Usage minutes are whole minutes, rounded down.**
- **Recording usage returns 409** when the reservation is not Approved or has not ended yet, and 422 when the usage times are invalid.
- **Maintenance conflicts return 409 with the blocking reservation IDs** in `error.details.reservation_ids`, so the UI can list the bookings to resolve.
