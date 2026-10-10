"""HTTP controllers for the auth module.

Owner (proposed): Spoorthy M
Requirements: LAB-F-001, LAB-F-002, LAB-F-018 (DS-Authentication)
Design: docs/Team16_Remote_Laboratory_SAD.docx, sections 3.4 and 4.3

Login, logout, provisioned accounts, lab roles, disabled accounts, sessions and login throttling.

Endpoints to implement (SAD 4.3):
    POST /api/auth/login
    POST /api/auth/logout
    POST /api/users
    PATCH /api/users/{id}

Controllers only parse input and call the service layer. Do not put business
rules or SQL here.
"""

from flask import Blueprint

bp = Blueprint("auth", __name__, url_prefix="/api/auth")

# TODO: implement endpoints listed above.
