"""HTTP controllers for the reporting module.

Owner (proposed): Sreekar Bandi
Requirements: LAB-F-017 (DS-Reporting)
Design: docs/Team16_Remote_Laboratory_SAD.docx, sections 3.4 and 4.3

Period-based actual utilization and unrecorded usage counts.

Endpoints to implement (SAD 4.3):
    GET /api/reports/utilization

Controllers only parse input and call the service layer. Do not put business
rules or SQL here.
"""

from flask import Blueprint

bp = Blueprint("reporting", __name__, url_prefix="/api/reports")

# TODO: implement endpoints listed above.
