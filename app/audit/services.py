"""Audit events (LAB-F-019, DS-Audit).

Owner: to be agreed by the team. Every module writes audit events, so agree
the record_event() signature early.

Each event stores actor, timestamp, action, target, outcome and request ID, and
is inserted in the same transaction as the state change. Never record
passwords, tokens or session secrets.
"""

# TODO: implement record_event(conn, actor_id, action, target_type, target_id, outcome, request_id).
