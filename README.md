

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
