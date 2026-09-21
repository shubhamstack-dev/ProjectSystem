
## v1.5 — customer users, screenshots and video, and one gate in front of the API

### Customer users, straight onto the customer

*Customers → pick one → Add a person.* A name, a work email, optionally a role
and a password. Leave the password empty and one is generated in a form that
reads over the phone (`vfrF-wd6d-GATH`), shown **once**, and never stored in
clear — only its hash.

Either way the person must choose their own on first sign-in. A password
somebody else has typed or read is not a secret, so until it is replaced the
API refuses everything except replacing it — not just the screen, the API.

What a customer user can do: raise tickets on their customer's projects,
attach screenshots, video and documents, follow the team's replies, reply back
with files of their own. What they cannot: edit a ticket's priority, status or
allocation, delete one, or reach any planning or team screen. Their menu shows
Tickets and nothing else.

Each person on the customer shows a status — awaiting first sign-in, ready,
active, deactivated — with *Reset password* and *Deactivate* beside them.
Deactivating cuts the account off on its next request, not when its session
happens to expire.

### Screenshots, screen recordings and documents

The ticket form and every reply take files by drag-and-drop or picker, with
previews before anything is sent and a progress bar while it goes (a 200 MB
video with no progress bar looks like a hang).

| Kind | Types | Limit |
|---|---|---|
| Images | JPG, PNG, GIF, WebP, HEIC | 25 MB |
| Video | MP4, MOV, WebM, AVI | 250 MB |
| Documents | PDF, Word, Excel, PowerPoint, ZIP, text, CSV, log | 25 MB |

Ten files at a time. All limits are `.env` settings.

On the ticket, pictures show as pictures (click to enlarge), video plays in
place with seeking, and documents download.

**The file's contents decide its type, not its name.** An `.exe` renamed to
`.png`, or a web page renamed to `.txt` or `.pdf`, is refused — checked against
the file's first bytes, in the browser first and again on the server.

**Files live on disk, not in MySQL.** The old column stopped at 16 MB, read
every upload into memory whole, and would have swelled every database backup
with video. Uploads now stream to disk in 1 MB pieces with the limit enforced
as they arrive. Files attached before v1.5 still open exactly as before.

**Uploads are all or nothing.** If one of five files is refused, the other
four are removed too, so a ticket never carries half of what was meant.

### The API was not locked down. It is now.

When sign-in arrived in v1.3 the check went onto the routes being worked on at
the time. **An audit for this release found 40 routes answering with nobody
signed in** — deleting tickets, editing projects, reading the audit trail and
team directory, approving another customer's dates — and the attachment
download was open to anyone who could count.

That is fixed in one place, `app/services/gate.py`, which runs before every
route. Nothing under `/api` answers without a valid session on an active
account, except a short named list (sign-in itself, health). Customer accounts
are held to the routes a customer needs. A test walks **every** route in the
API unauthenticated and fails if any answers, so a route added later cannot
quietly be open.

Two related fixes: the audit trail now takes the name from the signed session
rather than the `X-Acting-As` header, which the caller could set to anyone; and
the customer approval screens (`/api/customer/…`) are scoped to the customer's
own projects — before, they listed everyone's.

**Attachment links are signed.** An `<img>` or `<video>` tag cannot send a
session token, so the API hands out a link carrying an HMAC signature, valid
for an hour, and only inside a ticket the reader may already see. A tampered or
expired link, or another customer's file, answers 404 — not 403, which would
confirm the file exists.

### Deploying — read before updating the server

1. **Set `SECRET_KEY` in `.env`.** Production never had one, so every restart
   has been signing everybody out. It now also signs attachment links. The
   API prints a warning at startup when it is missing. `SERVER-STEPS.md` has
   the one-line command.
2. The compose file gains an **`attachments` volume**. Back it up alongside the
   database: the database holds the list of files, the volume holds the files.
3. Database changes apply themselves on startup.

### Tests

    cd backend && pytest -q        # 95 tests


## v1.4 — the customer master

### A customer is a code and a name

Nothing else belongs on the row. Which projects are theirs, which roles their
people hold and which accounts belong to them are all **assignments** that
change on their own schedule, not fields copied onto a master record.

**The code is generated, never typed.** A code somebody types is a code somebody
mistypes, and two rows for one customer cannot be untangled once projects point
at both.

The counter behind it is persisted and only ever goes up. It is not derived from
the highest code in use, and it is not the row id: SQLite reuses the highest
rowid after a delete, so either of those hands `CUST-0003` to a second customer
the moment the first one is removed — by which time it is printed on somebody's
correspondence. A test pins this.

### Three assignments

**Projects.** A project belongs to one customer, so assigning it takes it off
whoever had it before. That is said in the reply rather than done quietly.

**Customer roles.** Only roles already marked as customer roles can be given to
a customer. A team role handed over would give their people the team's screens,
so it is refused with that reason.

**Their people.** Guest accounts from the directory. An Aequm India account is
refused: a member already sees every project, and filing them under a customer
would say something untrue about who they work for without changing anything
they can reach.

### What a customer user sees

Their own customer, their own projects, their own tickets. They can raise
tickets, follow the status, read the team's replies and reply back.

Three boundaries worth knowing:

* **An account with no customer yet sees nothing at all**, not everything. That
  is the safe way round, and both the API and the sidebar say so plainly rather
  than leaving somebody staring at an empty screen wondering if it is broken.
  The Customers page lists unfiled guests for exactly this reason.
* **Another customer's ticket is 404, not 403.** A 403 confirms the ticket
  exists, which is itself the leak.
* **The project list is scoped as well as the ticket list.** The ticket API
  refuses a foreign project anyway, but offering it in the dropdown produces a
  form that fails on save, and that reads as a broken product rather than a
  boundary.

### Everything else is unchanged

Sign-in, the directory import, processes and process steps all work as they did
in v1.3. Only the customer assignment is new.

### Tests

    cd backend && pytest -q        # 68 tests

All three suites now share one harness. They each used to build their own engine
and override `get_db` on the single FastAPI app, so whichever module imported
last won and the others silently ran against a database with none of their rows
in it.


## v1.3 — Microsoft Entra ID sign-in, and processes beneath a module

### The product had no authentication before this

`X-Acting-As` was a name typed into a box in the sidebar. It is an audit label,
not a login: anyone could call any endpoint and claim to be anyone. That is fine
for a plan nobody outside the room can reach, and not fine once customers raise
tickets on it. So sign-in had to be built, not extended.

The typed-in box is gone. Whoever is signed in is who the audit trail records.

### Two ways in

**Microsoft Entra ID** (what used to be Azure AD), for Aequm India and for
customers invited into the tenant. The browser authenticates against Microsoft
directly using the authorisation code flow with PKCE; this API never sees a
password.

**Local accounts**, so the product still starts and still has an administrator
on a machine with no Azure application registered. Without that fallback, a
misconfigured tenant locks the owner out of their own system. On first run, if
there is no account at all, one administrator is created and its password
printed to the API log once — never written to a file.

The sign-in screen only offers the Microsoft button when a tenant is actually
configured, and says why when it is not.

### Importing users from the directory

*Directory* (administrators only) reads the tenant through Microsoft Graph and
creates the people here. Fetch and import are two separate buttons: reading
changes nothing, so you can see who is there, and who is already in the system,
before creating a single account.

**Matching is on the Entra object id, never on the address.** People marry,
change surname and keep the same account. Matching on mail would import them a
second time and orphan every ticket assigned to the first row. A test pins this.

**Members and guests land on different sides.** Graph reports `userType`. Aequm
India staff are Members; a customer invited into the tenant as B2B is a Guest.
That one field decides which organisation and role the imported person is filed
under, so both sides are created the same way and still end up on the right side
of the wall. The four `ENTRA_*_ORG` / `ENTRA_*_ROLE` settings control where.

**A guest cannot let themselves in.** Members may sign in and be provisioned on
the spot; guests must be imported by an administrator first. A customer who can
create their own account is a customer who can reach another customer's tickets.
`ENTRA_AUTO_PROVISION_GUESTS` exists if you disagree, and defaults to off.

Every import writes a row to `directory_sync` — who ran it, when, and the counts
— shown at the bottom of the Directory page.

### App registration

    Redirect URI (SPA)   http://localhost:5173/auth/callback
    API permission       User.Read.All (Application) + admin consent

Sign-in needs only the tenant id and client id. It is the *directory read* that
needs the client secret and the consent; the Directory page says so plainly when
they are missing.

### Processes and process steps

A **process** is master data with **ordered steps**, and `module_process`
assigns it to modules many-to-many.

Many-to-many on purpose: period-end close is one process that finance,
controlling and treasury all run. Nesting it under a single module would force a
copy per module, and the copies drift apart the first time somebody edits one.

Tickets gained `ProcessId` and `ProcessStepId`, so work is located inside the
process rather than only against the module. The chain is validated: **the step
must belong to the process, and the process must be assigned to the ticket's
module.** Otherwise a ticket can claim a step the module never runs, and every
report grouped by module and process stops reconciling to the ticket list.

Two refusals worth knowing:

* A process named on a ticket cannot be deleted, and cannot be taken off that
  module. Mark it inactive instead, so the ticket keeps saying what it was
  raised against.
* Moving a ticket to a module that does not run its process **clears the
  process and says so**; *naming* such a process is **refused**. A move is a
  decision, a mismatched name is a mistake, and the two deserve different
  answers.

### Migration

Nothing by hand. On startup the backend creates the new tables and adds the two
ticket columns to an existing database; `schema.sql` carries the same DDL for
fresh installs.

### Tests

    cd backend && pytest -q        # 43 tests

Graph and the Microsoft token endpoint are stubbed — the point is the behaviour
on this side of the wire, not whether Microsoft answers.



## v1.1 — Customer roles, line-item date approvals, and phases

**Roles menu.** The sidebar now has a *Roles* section with two items:
*Team Roles* (the existing organisations / roles / people page) and
*Customer Roles*.

**Customer Roles.** Define the customer-side roles (name, responsibilities,
colour; access is fixed to the customer portal). The page's workspace lets a
customer pick a project, see its status (state, % complete, planned end,
forecast finish and variance), and **approve or reject the actual dates line
item by line item**: whenever an organisation employee enters or changes an
actual start/finish on the Plan, that line automatically goes *Pending* for
the customer; rejecting requires a comment so the team knows what to fix, and
editing the dates again re-submits the line. Every decision is written to the
audit trail. Tables: `date_approval` (one row per line item), `role.IsCustomer`.

**Phases.** The new *Phases* page splits a project into ordered phases
(name, dates, colour) and holds the project's **roles & responsibilities
table**: per phase, assign each role — with the responsibilities defined on
the role — to a team member, with an optional note for that phase.
Tables: `phase`, `phase_assignment`.

**Migration.** Nothing to do by hand: on startup the backend creates the
three new tables and adds `role.IsCustomer` to an existing database
(`schema.sql` carries the same DDL for fresh installs).
