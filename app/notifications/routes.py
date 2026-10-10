"""HTTP controllers for the notifications module.

Owner (proposed): Sreekar Bandi
Requirements: LAB-F-015 (DS-Notification)
Design: docs/Team16_Remote_Laboratory_SAD.docx, sections 3.4 and 4.3

Persistent in-app notifications, inserted in the same transaction as the state change they describe.

Endpoints to implement (SAD 4.3):
    GET /api/notifications

Controllers only parse input and call the service layer. Do not put business
rules or SQL here.
"""

from flask import Blueprint

bp = Blueprint("notifications", __name__, url_prefix="/api/notifications")

# TODO: implement endpoints listed above.
