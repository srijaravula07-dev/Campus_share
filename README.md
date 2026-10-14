# Campus Share

A college academic resource-sharing and peer-collaboration web platform built with Flask, SQLite, SQLAlchemy, and Jinja2.

---

## Table of Contents

- [Overview](#overview)
- [Key Features](#key-features)
  - [Resource Sharing & Discovery](#resource-sharing--discovery)
  - [Doubt Box (Academic Q&A)](#doubt-box-academic-qa)
  - [Senior Connect (Peer Mentorship)](#senior-connect-peer-mentorship)
  - [Resource Requests & Notifications](#resource-requests--notifications)
  - [User Settings & Account Management](#user-settings--account-management)
  - [Admin Moderation](#admin-moderation)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Prerequisites](#prerequisites)
- [Installation and Setup](#installation-and-setup)
- [Environment Variables](#environment-variables)
- [Running the Application](#running-the-application)
- [Running Tests](#running-tests)
- [Usage Guide](#usage-guide)
- [Security Considerations](#security-considerations)
- [Current Limitations and Future Improvements](#current-limitations-and-future-improvements)
- [Contributing](#contributing)
- [License](#license)
- [Author](#author)

---

## Overview

College students frequently struggle to find high-quality, course-specific study materials such as lecture notes, previous-year question papers, lab manuals, and textbook summaries. Existing solutions are often fragmented across messaging channels, cloud folders, or social media groups where files are easily lost, duplicated, or disorganized.

**Campus Share** addresses this problem by providing a structured, centralized campus portal where students can:
- Upload and organize academic files categorized by academic year, branch, and subject.
- Prevent duplicate file uploads via content-hash detection.
- Preview and read auto-generated summaries of PDF notes directly in the browser.
- Ask and resolve course-related doubts through an accepted-answer Q&A workflow.
- Connect with upper-year students (3rd and 4th years) for peer mentorship.
- Request missing materials and receive automated notifications when matching materials are uploaded.

---

## Key Features

### Resource Sharing & Discovery
- **Multi-Format Uploads**: Supports uploads up to 25 MB in allowed formats: PDF, PPT, PPTX, DOC, DOCX, XLS, XLSX, TXT, ZIP, JPG, JPEG, and PNG.
- **SHA-256 Duplicate Detection**: Hashes file contents upon upload. If the same file was already uploaded under another name, the user is warned and given an explicit choice to cancel or proceed.
- **PDF Text Summaries**: Automatically extracts key sentences from uploaded PDFs using `pypdf` and displays a quick summary directly on the resource detail page.
- **Inline Preview & Direct Downloads**: Dedicated inline viewer endpoint (`/view-file/<id>`) for supported documents, alongside direct download (`/download/<id>`) with separate download vs. page-view counters.
- **Multi-Parameter Search & Filtering**: Filter resources by Academic Year (`1st Year` to `4th Year`), Branch (`CSE`, `ECE`, `EEE`, `MECH`, `CIVIL`, `IT`, `OTHER`), Subject, or File Extension. Supports partial-match keyword searches across titles, descriptions, and filenames.
- **Sorting**: Sort listings by Latest Upload, Most Downloaded, or Highest Rated.
- **Ratings & Low-Quality Flagging**: 1 to 5 star ratings with average score computation. Submitting a new rating updates the existing user score. When a resource receives at least 3 ratings with an average below 2.5, it is automatically flagged as `needs_review` for administrator attention.
- **Comments**: Discussion section on resource pages with author editing and uploader/admin deletion rights. Uploaders can disable comments per resource.
- **Bookmarks & History**: Save resources to a personal Bookmarks list and view a chronological history of recently viewed resources.
- **Reporting**: Report resources with standard reason categories (e.g., Wrong Information, Broken File, Inappropriate Content) for admin review.

### Doubt Box (Academic Q&A)
- **Question Threads**: Students can post academic questions with subject tags, titles, and descriptions.
- **Community Answers**: Other students can post answers, and answer authors can edit their responses.
- **Accepted Answers**: Question authors can mark an answer as "Accepted", setting the doubt status to `resolved`.
- **Automatic State Reversion**: If an accepted answer is deleted, the doubt status automatically reverts to `open` if no other accepted answers remain.
- **Filtering**: Filter doubts by subject keyword, search terms, or status (`all`, `unanswered`, `answered`).

### Senior Connect (Peer Mentorship)
- **Peer Mentor Directory**: Upper-year students (3rd and 4th year) can register as mentors listing their available subjects and bio.
- **Server-Enforced Eligibility**: 1st and 2nd-year students are restricted on the server from creating mentor profiles. If a student changes their year to 1st or 2nd in Settings, their mentor profile is automatically deactivated.
- **Search Mentors**: Search mentors by subject keyword, branch, or year.
- **Availability Toggle**: Mentors can switch their availability on or off from their profile.

### Resource Requests & Notifications
- **Request Board**: Students can post requests for missing study material by subject, year, and branch.
- **Fulfillment**: Users can fulfill an open request by linking an existing resource.
- **Automated Matching Notifications**: When a user uploads a new resource, the system checks for open requests matching that subject, year, and branch, and automatically notifies the requester.
- **In-App Notification Center**: Unread notification counter badge in the sidebar with an automatic mark-as-read mechanism when visiting `/notifications`.

### User Settings & Account Management
- **Profile Updates**: Update full name, email, year, and branch.
- **Password Changes**: Secure password update requiring current password validation and minimum length check.
- **Appearance**: Toggle between Light and Dark themes (persisted to database).
- **Notification Preferences**: Granular notification toggles for comments, requests, ratings, and moderation events.
- **Zero-Orphan Account Deletion**: Users can permanently delete their account by typing `DELETE`. The transactional deletion routine removes physical uploaded files from disk and cleans up related records across all 11 dependent database tables without leaving orphan rows.

### Admin Moderation
- **Moderation Queue**: Accessible at `/admin` for users with `role='admin'`.
- **Report Review**: Dismiss reports, mark them as resolved, or remove offending resources.
- **Quality Queue**: View and review resources flagged by the automated low-quality rating threshold.
- **Open Requests Overview**: Monitor student resource requests.

---

## Tech Stack

### Backend
- **Framework**: [Flask](https://flask.palletsprojects.com/) (3.0.3)
- **Authentication**: [Flask-Login](https://flask-login.readthedocs.io/) (0.6.3)
- **Password Hashing**: [Werkzeug](https://werkzeug.palletsprojects.com/) (3.0.4) using `generate_password_hash` / `check_password_hash` (`scrypt` / `pbkdf2`)
- **Forms & CSRF**: [Flask-WTF](https://flask-wtf.readthedocs.io/) (1.2.1)
- **PDF Processing**: [pypdf](https://pypdf.readthedocs.io/) (4.3.1)
- **Production WSGI Server**: [Gunicorn](https://gunicorn.org/) (22.0.0)

### Database & ORM
- **Database**: [SQLite](https://www.sqlite.org/) (default local file `campus_share.db`), compatible with PostgreSQL via `DATABASE_URL`
- **ORM**: [Flask-SQLAlchemy](https://flask-sqlalchemy.palletsprojects.com/) (3.1.1)

### Frontend
- **Templating**: [Jinja2](https://jinja.palletsprojects.com/) (server-rendered templates)
- **Styling**: Custom responsive CSS (`static/css/style.css`) with CSS custom properties (variables) supporting Light and Dark modes
- **Scripting**: Vanilla JavaScript for mobile sidebar drawer toggling
- **Layout**: Desktop persistent sidebar and mobile slide-out drawer (< 900px viewport width)

### Testing
- **Test Framework**: [pytest](https://docs.pytest.org/) (>= 8.0.0)

---

## Project Structure

```text
campus_share/
├── app.py                   # Main Flask application (routes, models, auth, helpers)
├── campus_share.db          # Local SQLite database (auto-created; git-ignored)
├── requirements.txt         # Production Python dependencies
├── requirements-dev.txt     # Development and testing dependencies
├── .env.example             # Template for local environment variables
├── .gitignore               # Ignored files (databases, uploads, environment, caches)
├── static/
│   ├── css/
│   │   └── style.css        # Responsive styling and theme tokens
│   └── uploads/             # User uploaded files (contents git-ignored)
│       └── .gitkeep         # Directory placeholder
├── templates/               # Jinja2 application templates
│   ├── 403.html             # Forbidden error page
│   ├── 404.html             # Not found error page
│   ├── admin.html           # Admin moderation dashboard
│   ├── base.html            # Application shell, sidebar, CSRF token, flashes
│   ├── bookmarks.html       # Saved resources page
│   ├── doubt_detail.html    # Doubt discussion and answers page
│   ├── doubts.html          # Doubt Box question listing
│   ├── duplicate_warning.html # Duplicate file warning confirmation page
│   ├── edit_resource.html   # Resource metadata editing page
│   ├── index.html           # Browse resources with search & filter controls
│   ├── login.html           # User login form
│   ├── mentor_profile.html  # Mentor registration and edit form
│   ├── mentors.html         # Senior Connect mentor directory
│   ├── my_uploads.html      # User's uploaded resources list
│   ├── new_doubt.html       # Post question form
│   ├── new_request.html     # Post resource request form
│   ├── notifications.html   # User notifications page
│   ├── recently_viewed.html # Browsing history page
│   ├── register.html        # User registration form
│   ├── request_detail.html  # Resource request detail & fulfillment page
│   ├── requests.html        # Resource requests list
│   ├── resource.html        # Resource detail, summary, comments, ratings
│   ├── settings.html        # User profile, theme, and account deletion
│   └── upload.html          # Resource upload form
└── tests/                   # Automated pytest suite
    ├── conftest.py          # Fixtures, test database setup, auth helpers
    ├── test_account_deletion.py # Multi-table zero-orphan deletion verification
    ├── test_auth.py         # Registration, login, open redirect, CSRF tests
    ├── test_resources.py    # Upload, duplicate hashing, filters, rating tests
    └── test_social.py       # Comments, doubts, mentor sync, request tests
