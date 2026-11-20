# Equipment API Documentation

## Overview

The Equipment module manages laboratory equipment information and provides availability data for student reservations.

It supports equipment listing, searching, filtering, availability checking, equipment creation, and equipment updates.

The backend uses Flask and PostgreSQL.

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| GET | /api/equipment | List and search active equipment |
| GET | /api/equipment/{equipment_id}/availability | Get equipment availability for a date |
| POST | /api/equipment | Create equipment |
| PATCH | /api/equipment/{equipment_id} | Update equipment |
| GET | /api/equipment/ui | Display the Velvet OS frontend |

## Authentication and Authorization

Equipment API operations use the application's authentication context.

The catalogue and availability endpoints require an authenticated, active user.

Equipment creation and updates require the Administrator role for the relevant laboratory.

Unauthorized requests are rejected.

The frontend page is served separately and must use the application's authenticated API requests for live functionality.

## 1. List Equipment

### Endpoint

GET /api/equipment

### Description

Returns a paginated list of active laboratory equipment.

### Query Parameters

| Parameter | Description |
|---|---|
| name | Optional equipment-name search |
| lab_id | Optional laboratory UUID |
| page | Pagination page |
| page_size | Number of results per page |

The search term must not exceed 500 characters.

Equipment search is case-insensitive.

### Example Request

```http
GET /api/equipment?name=osc
```

### Example Successful Response

```json
{
  "items": [
    {
      "id": "equipment-uuid",
      "code": "OSC101",
      "name": "Oscilloscope",
      "description": "Digital oscilloscope",
      "active": true,
      "lab_id": "lab-uuid",
      "lab_name": "Electronics Lab"
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20
}
```

The UUID strings above are illustrative placeholders.

### Relevant Error Responses

| Status | Description |
|---|---|
| 401 | Authentication required |
| 403 | Active account required |
| 422 | Invalid search or query parameters |

## 2. Check Equipment Availability

### Endpoint

GET /api/equipment/{equipment_id}/availability

### Description

Returns laboratory opening hours, existing reservations, maintenance blocks, and available intervals for an equipment item on a specified date.

Pending and Approved reservations block their corresponding time intervals.

Maintenance periods also make equipment unavailable.

### Query Parameters

| Parameter | Description |
|---|---|
| date | Required date in YYYY-MM-DD format |

### Example Request

```http
GET /api/equipment/{equipment_id}/availability?date=2026-11-23
```

### Response Fields

| Field | Description |
|---|---|
| equipment_id | Equipment UUID |
| equipment_code | Equipment code |
| equipment_name | Equipment name |
| lab_id | Laboratory UUID |
| lab_name | Laboratory name |
| date | Requested date |
| timezone | Laboratory timezone |
| active | Equipment active status |
| opening_hours | Laboratory opening intervals |
| reserved | Intervals held by reservations |
| maintenance | Maintenance-block intervals |
| available | Intervals available for reservation |

Intervals contain start and end timestamps.

The response respects the laboratory's configured timezone.

Inactive equipment returns an empty available list.

### Relevant Error Responses

| Status | Description |
|---|---|
| 401 | Authentication required |
| 403 | Active account required |
| 404 | Equipment not found |
| 422 | Invalid equipment ID or date |

## 3. Create Equipment

### Endpoint

POST /api/equipment

### Description

Allows an authorized laboratory Administrator to create equipment.

### Request Body

```json
{
  "lab_id": "lab-uuid",
  "code": "OSC200",
  "name": "Oscilloscope",
  "description": "Digital measuring equipment"
}
```

### Fields

| Field | Required | Description |
|---|---|---|
| lab_id | Yes | Laboratory UUID |
| code | Yes | Equipment code |
| name | Yes | Equipment name |
| description | No | Equipment description |

The description cannot exceed 500 characters.

### Successful Response

HTTP 201 Created

```json
{
  "id": "equipment-uuid",
  "lab_id": "lab-uuid",
  "code": "OSC200",
  "name": "Oscilloscope",
  "description": "Digital measuring equipment",
  "active": true
}
```

### Relevant Error Responses

| Status | Description |
|---|---|
| 401 | Authentication required |
| 403 | Administrator permission required |
| 404 | Laboratory not found |
| 409 | Duplicate equipment code |
| 422 | Invalid request fields |

Successful creation is recorded in the audit log.

## 4. Update Equipment

### Endpoint

PATCH /api/equipment/{equipment_id}

### Description

Allows an authorized laboratory Administrator to update equipment details.

### Supported Fields

| Field | Description |
|---|---|
| code | Equipment code |
| name | Equipment name |
| description | Equipment description |
| active | Equipment active status |

At least one supported field must be supplied.

### Example Request

```json
{
  "name": "Digital Oscilloscope",
  "description": "Updated laboratory equipment"
}
```

### Successful Response

HTTP 200 OK

The response returns the updated equipment information.

### Deactivation Rules

Equipment may be deactivated when no Pending or Approved reservations block deactivation.

If such reservations exist, the update returns HTTP 409.

### Relevant Error Responses

| Status | Description |
|---|---|
| 401 | Authentication required |
| 403 | Administrator permission required |
| 404 | Equipment not found |
| 409 | Active reservations or duplicate code |
| 422 | Invalid update fields |

Successful updates are recorded in the audit log.

## 5. Velvet OS Frontend

### Endpoint

GET /api/equipment/ui

### Description

Serves the Velvet OS laboratory equipment interface.

The interface includes:

- Equipment catalogue
- Equipment search
- Equipment availability calendar
- Reservation submission form
- Equipment administration controls

The interface communicates with the backend through API requests.

The reservation form submits bookings through the Reservations module.

## Testing

Equipment integration tests are located in:

tests/integration/test_equipment.py

The tests cover catalogue operations, searching, availability, administration, permissions, validation, and frontend rendering checks.

Related STP cases:

- TC-F-003: Equipment catalogue
- TC-F-004: Equipment search
- TC-F-005: Availability
- TC-F-013: Manage equipment

The automated tests support these STP cases. Separate system-level execution evidence is tracked in the STP execution register.

## Coverage

During Sprint 2 testing:

- 24 equipment tests passed.
- Overall equipment module coverage reached 93%.
- Equipment routes coverage reached 100%.
- Equipment services coverage reached 90%.

Some service branches remain uncovered.

Coverage was measured using pytest-cov with branch coverage enabled.