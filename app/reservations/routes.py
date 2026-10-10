"""HTTP controllers for the reservations module.

Owner (proposed): Soha Rafiq
Requirements: LAB-F-006 to LAB-F-009 (DS-Reservation)
Design: docs/Team16_Remote_Laboratory_SAD.docx, sections 3.4 and 4.3

Atomic booking, conflict detection, own history and cancellation.
Follows the booking transaction protocol in SAD 4.1.1.

Endpoints to implement (SAD 4.3):
    POST /api/reservations
    GET /api/reservations?scope=mine|lab
    POST /api/reservations/{id}/cancel

Controllers only parse input and call the service layer. Do not put business
rules or SQL here.
"""

from flask import Blueprint

bp = Blueprint("reservations", __name__, url_prefix="/api/reservations")

# TODO: implement endpoints listed above.
