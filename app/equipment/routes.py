"""HTTP controllers for the equipment module.

Owner (proposed): Shristi Shukla
Requirements: LAB-F-003, LAB-F-004, LAB-F-005, LAB-F-013 (DS-Equipment)
Design: docs/Team16_Remote_Laboratory_SAD.docx, sections 3.4 and 4.3

Catalogue, search, available slots and opening hours, safe equipment updates or deactivation.

Endpoints to implement (SAD 4.3):
    GET /api/equipment
    GET /api/equipment/{id}/availability
    POST /api/equipment
    PATCH /api/equipment/{id}

Controllers only parse input and call the service layer. Do not put business
rules or SQL here.
"""

from flask import Blueprint

bp = Blueprint("equipment", __name__, url_prefix="/api/equipment")

# TODO: implement endpoints listed above.
