# Integrations — status and requirements

**Status: no integration with any SIS exists. No partnership, no pilot, no data-sharing
agreement, and no API credentials have been obtained from any vendor or district.**

This file exists so that the claim can be checked rather than taken on trust. If anything
elsewhere — a post, a deck, a commit message — implies a PowerSchool integration, a Devin
Bots pairing, or a district data pipeline, **this file is the source of truth and that claim
is wrong.**

| Integration | Status | Evidence |
|---|---|---|
| PowerSchool SIS | Not started | No district authorization, no app registration, no OAuth client |
| OneRoster 1.2 (CSV/REST) | Not started | Standard identified, no district contact |
| Ed-Fi | Not started | Not evaluated |
| Any LLM agent platform pairing | None | No joint work, no shared repo, no agreement |
| Manual CSV roster import | Not built | Would be the first thing to build |

---

## Why roster data is the actual gate

Every design decision in this project assumes the system knows *which section a student is
in* and *which assignment a turn belongs to*. Without that, `session → task` linkage is
manual, and `over_help_rate` cannot be aggregated per class — which is the only level at
which the metric is actionable for a teacher.

So this is not a nice-to-have feature. Without roster data the evaluation in
`DESIGN.md` §5 cannot run at all: there is no way to compute `transfer_delta` by condition
if students cannot be joined to their post-test records.

## The four options, in order of preference

### 1. OneRoster 1.2 CSV (district-mediated)

The district exports `orgs.csv`, `courses.csv`, `classes.csv`, `enrollments.csv`,
`users.csv`, `academicSessions.csv` on a schedule. Lowest trust surface: we never hold API
credentials, the district controls what leaves.

- Cost: a scheduled import job plus reconciliation; rosters go stale between exports.
- Requires: a district data-sharing agreement, a named contact who owns the export.
- Privacy: student names can be dropped at export time — we only need `sourcedId`.

### 2. OneRoster 1.2 REST

Same data model, token-based, near-real-time. Preferred once a pilot is real, because
section changes mid-term are common and stale rosters corrupt per-class metrics.

- Requires: district-issued OAuth client, token rotation, an audit log of every pull.

### 3. Vendor API (PowerSchool and similar)

PowerSchool exposes a district-scoped API, but access is granted to the **district**, which
then authorizes a third-party application. There is no path where an independent developer
obtains credentials directly from the vendor; the district is always in the loop.

Realistic sequence, none of which has happened here:

1. District signs off on the pilot.
2. District registers the application and issues client credentials.
3. Scopes are negotiated — narrow by default.
4. A Data Processing Agreement is signed before the first API call.
5. Security review, then a read-only test against a sandbox section.

### 4. Manual CSV import

A teacher drops a CSV exported from the gradebook. Ugly, slow, and it is what every pilot
actually starts with. Build this first; it validates the schema before any vendor
integration exists.

## Field-level data minimization

What the system would read, and why. Anything not in this table is not requested.

| Field | Needed for | Retention |
|---|---|---|
| `sourcedId` (student) | joining a session to a section | session lifetime |
| `class.sourcedId` | per-class aggregation of `over_help_rate` | 1 term |
| `class.course.sourcedId` | grouping by subject for taxonomy selection | 1 term |
| teacher `sourcedId` | routing the weekly report | 1 term |
| assignment `sourcedId` | linking a turn to a task | session lifetime |
| student name, email, DOB, grade history, IEP/504 status | **not requested** | — |

Names are not requested. Any importer that reads a `givenName`/`familyName` column must
drop it before persistence, not after.

## What an integration does not buy

Approval to read a roster is not approval to store student work, and it is not consent. In
the US, FERPA puts the district in the role of data controller; COPPA adds a separate
consent layer for under-13s. In Japan, 個人情報保護法 and each board of education's own
rules apply, and school-side review is typically slower than the vendor side. None of this
is resolved by having an API key.

Practically: the ethics review described in `DESIGN.md` §5.5 is a **prerequisite to the
first API call**, not a step after it.

## What would change this file

One line, when it is true:

```
| PowerSchool SIS | Pilot — district [name], read-only roster sync | DPA signed [date], app id [id] |
```

Until that line can be written with a district name and a date, no other document in this
repository should claim an integration exists.
