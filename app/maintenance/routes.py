"""HTTP controllers for the maintenance module.

Owner (proposed): Sreekar Bandi
Requirements: LAB-F-014 (DS-Maintenance)
Design: docs/Team16_Remote_Laboratory_SAD.docx, sections 3.4 and 4.3

Maintenance intervals validated against held bookings, using the shared equipment row lock.

Endpoints to implement (SAD 4.3):
    POST /api/maintenance
    PATCH /api/maintenance/{id}
    DELETE /api/maintenance/{id}

Controllers only parse input and call the service layer. Do not put business
rules or SQL here.
"""

from flask import Blueprint

bp = Blueprint("maintenance", __name__, url_prefix="/api/maintenance")

# TODO: implement endpoints listed above.
