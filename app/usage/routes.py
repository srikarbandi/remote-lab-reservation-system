"""HTTP controllers for the usage module.

Owner (proposed): Sreekar Bandi
Requirements: LAB-F-016 (DS-Usage)
Design: docs/Team16_Remote_Laboratory_SAD.docx, sections 3.4 and 4.3

Actual usage, no-shows and completion after the reservation ends.

Endpoints to implement (SAD 4.3):
    POST /api/reservations/{id}/usage

Controllers only parse input and call the service layer. Do not put business
rules or SQL here.
"""

from flask import Blueprint

bp = Blueprint("usage", __name__, url_prefix="/api/reservations")

# TODO: implement endpoints listed above.
