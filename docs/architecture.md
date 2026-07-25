# HirePilot Architecture

## Overview

HirePilot is composed of two major systems:

1. The HirePilot application
2. T.A.C.O.S. (Talent Acquisition Career Operating System)

The HirePilot application provides the user experience.

T.A.C.O.S. provides the intelligence.

The application should remain as thin as possible, with business logic centralized inside T.A.C.O.S.

---

## High-Level Architecture

```
                    User

                      │

              HirePilot Frontend

                      │

               FastAPI Backend

                      │

      ┌──────────────────────────────┐
      │           T.A.C.O.S.          │
      ├──────────────────────────────┤
      │ Discovery Engine             │
      │ Resume Intelligence Engine   │
      │ Company Intelligence Engine  │
      │ Opportunity Engine           │
      │ Recommendation Engine        │
      │ Learning Engine              │
      │ Notification Engine          │
      └──────────────────────────────┘

                      │

                PostgreSQL Database

                      │

          Background Workers / Scheduler
```

---

## Core Principle

Every major capability should exist as an independent component.

This allows individual engines to evolve without affecting the rest of the platform.

---

## Responsibilities

### HirePilot

Responsible for:

- Authentication
- User profiles
- Dashboard
- User settings
- Notifications
- Displaying recommendations
- Application tracking

HirePilot should not contain business intelligence.

---

### T.A.C.O.S.

Responsible for:

- Discovering jobs
- Understanding resumes
- Researching companies
- Ranking opportunities
- Learning user preferences
- Generating recommendations
- Supporting future AI workflows

---

## Design Principles

- Modular
- Replaceable
- API-first
- AI-assisted
- Observable
- Scalable
- Testable

---

## Future Components

Potential services include:

- Browser Extension
- Public API
- Mobile Application
- Recruiter Portal
- Analytics Dashboard
- Admin Portal

All future products should consume intelligence from T.A.C.O.S. rather than implementing business logic independently.