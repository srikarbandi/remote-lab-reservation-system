"""HTTP controllers for the approvals module.

Owner (proposed): Soha Rafiq
Requirements: LAB-F-010 to LAB-F-012 (DS-Approval)
Design: docs/Team16_Remote_Laboratory_SAD.docx, sections 3.4 and 4.3

Pending queue and version-checked approval or rejection.

Endpoints to implement (SAD 4.3):
    POST /api/reservations/{id}/decision

Controllers only parse input and call the service layer. Do not put business
rules or SQL here.
"""

from flask import Blueprint

bp = Blueprint("approvals", __name__, url_prefix="/api/reservations")

# TODO: implement endpoints listed above.
