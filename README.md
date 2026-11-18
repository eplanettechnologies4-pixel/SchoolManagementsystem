# 🎓 E-Planet Educational Portal

A modern, enterprise-grade **School Management System (SMS)** web platform built with **Django 6**, **Django REST Framework (DRF)**, **ReportLab**, **Tailwind CSS**, **HTMX**, and **Alpine.js**.

Designed with strict multi-tenancy (`SchoolScopedModel`), role-based access control (RBAC), object-level security, immutable financial ledger tracking, GPS-geofenced staff tracking, student admission workflows, and PWA capabilities.

---

## 🏛️ Architecture & Global Standards

- **Multi-Tenant Foundation**: Every core model inherits from `SchoolScopedModel` with automatic school scoping via `SchoolScopedManager`, soft delete (`is_deleted`), and timestamping.
- **Audit Logging**: Centralized, persistent `AuditLog` records actor, action (`CREATE`, `UPDATE`, `DELETE`, `PAYMENT`, `REVERSAL`, `PROMOTION`), old/new state snapshots, timestamp, and client IP address.
- **Sequential Concurrency Safety**: Number generators (`admission_number`, `roll_number`, `employee_id`, `challan_no`) execute inside `transaction.atomic` with `select_for_update()` to eliminate race conditions.
- **Strict RBAC & Object Ownership**: Granular permission checks at view and API layers ensure parents access only their own wards, teachers access only their assigned classes, and students access only self records.
- **Design System**: Clean, responsive layout using **White and Primary Royal Blue** theme, mobile-first bottom navigation, and PWA offline shell.

---

## 🚀 Key Modules & Capabilities

### Part 1: Virtual Fees & Challan System
- **Fee Configuration**: `FeeCategory` and `FeeStructure` linked to academic years and class levels.
- **Challan Engine**: Sequential challan numbers (`CHL-YYYY-XXXX`), tracking `Unpaid`, `Paid`, `Partial`, and `Cancelled` statuses.
- **Immutable Payment Ledger**: Modifying or deleting a `Payment` raises a validation error; financial adjustments occur strictly through reversal entries (`is_reversal=True`).
- **Pluggable Payment Gateway**: Abstract `PaymentGateway` architecture with an active `VirtualGateway` generating reference numbers (`VIR-YYYYMM-XXXX`) and clear "VIRTUAL / SIMULATED" watermarks.
- **Challan PDF Generator**: High-resolution, multi-copy printable fee challan generated via ReportLab with embedded dynamic QR code.
- **Accountant Dashboard**: Real-time summary of total receivables, collected virtual payments, and defaulter tracking.

### Part 2: Academics, Capacity & Promotion Engine
- **Classes & Sections**: `Section` capacity constraints (e.g. `24/35 filled`) enforced via model validation and displayed dynamically.
- **Academic Year Constraint**: Enforces a single active academic year per school.
- **Student Promotion Tool**: Bulk class-to-class promotion engine with interactive preview, hold-back/skip selection, and complete rollback via audit history snapshots.
- **Faculty Workload**: HTMX-powered subject assignment view with teacher period conflict detection and workload monitoring.
- **Exports & Bulk Import**: Export class directories to PDF (ReportLab) and Excel (`openpyxl`), and bulk import classes/sections via CSV.

### Part 3: Student Admission Wizard & SIS Forms
- **5-Step Admission Wizard**:
  - *Step 1 (Student)*: Legal particulars, Pakistani B-Form validation (`35202-1234567-1`), WebP photo compression (max 2MB).
  - *Step 2 (Guardian)*: CNIC format validation, Pakistani mobile validation (`+92`), and **automatic sibling auto-linking** by Guardian CNIC.
  - *Step 3 (Academic)*: Class & section allocation with live capacity verification.
  - *Step 4 (Documents)*: Secure upload for B-Form, CNIC, and marksheets with file extension and 5MB size limits.
  - *Step 5 (Review)*: Summary review, duplicate detection warnings, and atomic finalization.
- **Draft Saving**: Save incomplete applications as drafts (`AdmissionDraft`) to resume later.
- **Official Certificates**: Generate formal School Leaving Certificates and Admission Confirmation Letters as ReportLab PDFs.
- **Private Document Vault**: Private document storage served via permission-checked endpoints.
- **Bulk Student Import**: CSV/Excel bulk student registration with row-level error reporting.

### Part 4: Staff Management & Geofenced Tracking
- **Staff Profiles**: `Staff` records with auto-generated unique Employee IDs (`EMP-YYYY-XXXX`), employment types, designations, and shifts.
- **GPS Geofenced Check-in**:
  - Staff check-in captures latitude and longitude via HTML5 Geolocation.
  - Computes distance against school coordinates using the **Haversine formula**.
  - Flags out-of-range attempts if distance exceeds `school.radius_meters`.
- **Shift & Grace Period Late Detection**: Automatic `LATE` status evaluation based on `ShiftTiming.start_time` and `grace_minutes`.
- **Automated Absence Scheduler**: Management command `python manage.py mark_absent_staff` auto-marks active staff without check-in as Absent (or on Leave).
- **Principal Tracking Dashboard**: Real-time staff attendance metrics, interactive **Leaflet.js** live check-in map, and monthly PDF/Excel export.
- **Teacher Dashboard**: "Aaj ki classes" assigned schedule, monthly attendance statistics, and leave balance tracking.
- **Leave Management**: Staff leave application, approval/rejection workflow, and quota tracking.
- **Payroll Hooks**: Pre-computed monthly attendance summaries (present, late, half-day, leave days) ready for external payroll integration.

### Part 5: Student & Parent Portals
- **Student Portal**:
  - Overview of enrollment, class, section, roll number, and attendance standing.
  - Curriculum subjects with assigned teacher details.
  - Timetable view and read-only fee challans with "Pay at school / Coming soon" notices.
  - School announcements widget with user read receipts (`NoticeRead`).
  - Private document downloads and printable student ID card PDF.
- **Parent Portal**:
  - Multi-ward switcher dropdown allowing parents with multiple children to seamlessly toggle between wards.
  - Child leave request application form routed to class administration.
  - Ward academic progress and fee challan history.
- **First Login Security**: Forced password update (`must_change_password=True`) redirects users to set a secure password upon initial login.
- **Mobile-First & PWA**: Responsive mobile bottom navigation bar, Web App Manifest (`manifest.json`), and Service Worker (`sw.js`) for offline shell caching.
- **Tamper Protection**: Comprehensive object-level permissions preventing student/parent URL and ID tampering.

### Part 6: Security & Hardening
- **Brute-Force Protection**: Integrated `django-axes` tracking failed login attempts and locking out attackers after 5 invalid attempts.
- **JWT Lifetimes**: DRF SimpleJWT configured with a 10-minute access token lifetime, 7-day refresh token rotation, and token blacklisting.
- **API Throttling**: Standardized DRF rate limits (`100/day` anonymous, `1000/day` authenticated).
- **Session Security**: 30-minute session expiration (`SESSION_COOKIE_AGE = 1800`), `SESSION_SAVE_EVERY_REQUEST = True`.
- **Environment Safety**: `seed_data` management command is guarded to execute only when `DEBUG=True`.

---

## 🛠️ Technology Stack

- **Backend**: Python 3.14, Django 6.0, Django REST Framework, SimpleJWT, Django-Axes, Django-Filter
- **PDF Generation**: ReportLab 5.0 (Student ID Cards, Fee Challans, Admission Letters, Leaving Certificates, Attendance Sheets)
- **Spreadsheets & Data**: OpenPyXL, Pillow (PIL WebP processing)
- **Frontend**: Tailwind CSS, HTMX, Alpine.js, Leaflet.js, Lucide Icons, Chart.js
- **Testing**: Pytest, Pytest-Django (31 automated unit, integration, and security tests)

---

## 💻 Setup & Installation

### 1. Clone & Set Up Environment
```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure Environment Variables
Create a `.env` file in the project root:
```env
SECRET_KEY=your-secure-django-secret-key
DEBUG=True
ALLOWED_HOSTS=*
```

### 3. Apply Database Migrations
```powershell
python manage.py migrate
```

### 4. Seed Demonstration Data (DEBUG Mode Only)
```powershell
python manage.py seed_data
```
*Note: Demo users created include `admin`, `principal`, `teacher_math`, `teacher_science`, `accountant`, `parent_smith`, and `student_john`. Users with temporary passwords will be prompted to update their password upon first login.*

### 5. Run Development Server
```powershell
python manage.py runserver 8000
```
Navigate to **`http://127.0.0.1:8000/login/`** in your browser.

---

## 🧪 Running Automated Tests

Run the complete 31-test suite across all 6 parts:
```powershell
pytest
```

Run tests for individual modules:
```powershell
# Part 1: Virtual Fees & Challans
pytest tests/test_part1_fees.py

# Part 2: Academics, Capacity & Promotion
pytest tests/test_part2_academics.py

# Part 3: Student Admission & Forms
pytest tests/test_part3_students.py

# Part 4: Staff Tracking & Geofencing
pytest tests/test_part4_staff.py

# Part 5: Student & Parent Portals
pytest tests/test_part5_portal.py

# Part 6: Security & Hardening
pytest tests/test_part6_security.py
```

---

## 📌 Intentional Placeholders (For Future Integration)

1. **Online Payment Gateways**: Real JazzCash/Easypaisa/Stripe integrations are intentionally left as interfaces; payments currently execute via `VirtualGateway` with clear simulation badges.
2. **SMS / WhatsApp Gateways**: Guardian and staff notifications log contact numbers (`+92 format validated`); integration with external SMS APIs (e.g. Twilio, Zong SMS) is left for Phase 4.
3. **Payroll Monetary Calculation**: Staff attendance summaries (effective present days, late deductions, approved leaves) are aggregated via `payroll_hooks.py`; salary slip calculation is reserved for a future dedicated accounting release.
