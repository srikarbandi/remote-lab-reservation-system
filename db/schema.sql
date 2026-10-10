-- DRAFT shared schema for the Remote Laboratory Equipment Reservation System.
--
-- Derived from the SAD (class diagram in 3.3.1, supporting records in 3.3.2,
-- data rules and indexes in 3.6.1). It is a starting point: agree changes as a
-- team (open an issue / PR) because every module depends on it.
--
-- Conventions (SAD 3.6.1): UUID primary keys, timezone-aware timestamps stored
-- in UTC and shown in Asia/Kolkata, intervals are half-open [start, end),
-- equipment is deactivated rather than deleted, version columns increment on
-- every update for stale-request detection.

CREATE TABLE users (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    identifier    text NOT NULL UNIQUE,
    password_hash text NOT NULL,
    active        boolean NOT NULL DEFAULT true,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE labs (
    id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name     text NOT NULL UNIQUE,
    timezone text NOT NULL DEFAULT 'Asia/Kolkata'
);

-- Roles come from the database, never from the browser (SAD 3.3).
CREATE TABLE lab_memberships (
    user_id uuid NOT NULL REFERENCES users (id),
    lab_id  uuid NOT NULL REFERENCES labs (id),
    role    text NOT NULL CHECK (role IN ('Student', 'Technician', 'Administrator')),
    PRIMARY KEY (user_id, lab_id)
);

-- Weekly opening windows (weekday set) and date overrides (override_date set).
CREATE TABLE lab_opening_intervals (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    lab_id        uuid NOT NULL REFERENCES labs (id),
    weekday       smallint CHECK (weekday BETWEEN 0 AND 6),  -- 0 = Monday
    override_date date,
    open_time     time,   -- NULL on an override row means closed all day
    close_time    time,
    CHECK ((weekday IS NULL) <> (override_date IS NULL)),
    CHECK (open_time IS NULL OR close_time IS NULL OR open_time < close_time)
);

CREATE TABLE equipment (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    lab_id      uuid NOT NULL REFERENCES labs (id),
    code        text NOT NULL UNIQUE,
    name        text NOT NULL,
    description text NOT NULL DEFAULT '',
    active      boolean NOT NULL DEFAULT true
);

-- Pending and Approved reservations hold their slot (SRS 2.5).
-- Overlap is prevented by the equipment row lock protocol (SAD 4.1.1).
CREATE TABLE reservations (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id      uuid NOT NULL REFERENCES users (id),
    equipment_id    uuid NOT NULL REFERENCES equipment (id),
    starts_at       timestamptz NOT NULL,
    ends_at         timestamptz NOT NULL,
    status          text NOT NULL DEFAULT 'Pending'
                    CHECK (status IN ('Pending', 'Approved', 'Rejected', 'Cancelled', 'Completed')),
    version         integer NOT NULL DEFAULT 1,
    purpose         text NOT NULL CHECK (char_length(btrim(purpose)) BETWEEN 1 AND 500),
    decision_reason text,
    decided_by      uuid REFERENCES users (id),
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CHECK (starts_at < ends_at)
);

CREATE TABLE maintenance_blocks (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    equipment_id uuid NOT NULL REFERENCES equipment (id),
    created_by   uuid NOT NULL REFERENCES users (id),
    starts_at    timestamptz NOT NULL,
    ends_at      timestamptz NOT NULL,
    reason       text NOT NULL CHECK (char_length(btrim(reason)) BETWEEN 1 AND 500),
    version      integer NOT NULL DEFAULT 1,
    created_at   timestamptz NOT NULL DEFAULT now(),
    CHECK (starts_at < ends_at)
);

-- One usage record per reservation. A no-show has both timestamps NULL and 0 minutes.
CREATE TABLE usage_records (
    reservation_id uuid PRIMARY KEY REFERENCES reservations (id),
    used_start     timestamptz,
    used_end       timestamptz,
    used_minutes   integer NOT NULL CHECK (used_minutes >= 0),
    recorded_by    uuid NOT NULL REFERENCES users (id),
    recorded_at    timestamptz NOT NULL DEFAULT now(),
    CHECK ((used_start IS NULL) = (used_end IS NULL)),
    CHECK (used_start IS NOT NULL OR used_minutes = 0),
    CHECK (used_start IS NULL OR used_start < used_end)
);

CREATE TABLE notifications (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        uuid NOT NULL REFERENCES users (id),
    reservation_id uuid REFERENCES reservations (id),
    event_type     text NOT NULL,
    message        text NOT NULL,
    created_at     timestamptz NOT NULL DEFAULT now(),
    read_at        timestamptz
);

-- Written only by the application. Never store passwords or session secrets.
CREATE TABLE audit_events (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_id    uuid REFERENCES users (id),
    action      text NOT NULL,
    target_type text NOT NULL,
    target_id   uuid,
    outcome     text NOT NULL,
    request_id  uuid,
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- Supporting records (SAD 3.3.2) --------------------------------------------

CREATE TABLE sessions (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    token_hash       text NOT NULL UNIQUE,   -- hash of the opaque token, never the token itself
    user_id          uuid NOT NULL REFERENCES users (id),
    created_at       timestamptz NOT NULL DEFAULT now(),
    last_activity_at timestamptz NOT NULL DEFAULT now(),
    revoked_at       timestamptz
);

-- Five failures in 15 minutes trigger a further 15 minute cooldown (LAB-SR-004).
CREATE TABLE login_attempts (
    identifier      text PRIMARY KEY,
    failure_count   integer NOT NULL DEFAULT 0,
    window_started  timestamptz NOT NULL DEFAULT now(),
    locked_until    timestamptz
);

CREATE TABLE idempotency_records (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       uuid NOT NULL REFERENCES users (id),
    operation     text NOT NULL,
    key           text NOT NULL CHECK (char_length(key) BETWEEN 1 AND 128),
    request_hash  text NOT NULL,
    response_code integer NOT NULL,
    response_body jsonb NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (user_id, operation, key)
);

-- Indexes (SAD 3.6.1) -------------------------------------------------------

CREATE INDEX idx_equipment_lab_active    ON equipment (lab_id, active);
CREATE INDEX idx_reservations_equipment  ON reservations (equipment_id, starts_at);
CREATE INDEX idx_reservations_student    ON reservations (student_id, starts_at DESC);
CREATE INDEX idx_reservations_pending    ON reservations (equipment_id, created_at) WHERE status = 'Pending';
CREATE INDEX idx_maintenance_equipment   ON maintenance_blocks (equipment_id, starts_at);
CREATE INDEX idx_notifications_user      ON notifications (user_id, created_at DESC);
CREATE INDEX idx_audit_target            ON audit_events (target_type, target_id);
CREATE INDEX idx_sessions_user           ON sessions (user_id);
