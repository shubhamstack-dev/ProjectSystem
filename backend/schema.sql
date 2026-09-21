-- ---------------------------------------------------------------------------
-- ProjectSystem - MySQL 8 schema
-- Run this if you prefer not to use `dotnet ef database update`.
-- ---------------------------------------------------------------------------
CREATE DATABASE IF NOT EXISTS projectsystem
  CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
USE projectsystem;

CREATE TABLE IF NOT EXISTS organisation (
  Id           INT AUTO_INCREMENT PRIMARY KEY,
  Name         VARCHAR(120) NOT NULL,
  Description  VARCHAR(600) NULL,
  UNIQUE KEY ux_org_name (Name)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS role (
  Id               INT AUTO_INCREMENT PRIMARY KEY,
  Name             VARCHAR(120) NOT NULL,
  Responsibilities VARCHAR(1000) NULL,
  Colour           VARCHAR(9) NOT NULL DEFAULT '#2F6F9E',
  ViewAccess       VARCHAR(200) NOT NULL DEFAULT 'portfolio,plan,assign,miles',
  OrganisationId   INT NULL,
  CONSTRAINT fk_role_org FOREIGN KEY (OrganisationId)
    REFERENCES organisation(Id) ON DELETE SET NULL
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS person (
  Id     INT AUTO_INCREMENT PRIMARY KEY,
  Name   VARCHAR(120) NOT NULL,
  Email  VARCHAR(200) NULL,
  RoleId INT NULL,
  CONSTRAINT fk_person_role FOREIGN KEY (RoleId) REFERENCES role(Id) ON DELETE SET NULL
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS project (
  Id             INT AUTO_INCREMENT PRIMARY KEY,
  Code           VARCHAR(30) NOT NULL,
  Name           VARCHAR(200) NOT NULL,
  PlannedStart   DATE NOT NULL,
  PlannedEnd     DATE NULL,
  Status         INT NOT NULL DEFAULT 0,
  Notes          TEXT NULL,
  OrganisationId INT NULL,
  OwnerId        INT NULL,
  UNIQUE KEY ux_project_code (Code),
  CONSTRAINT fk_project_org   FOREIGN KEY (OrganisationId) REFERENCES organisation(Id) ON DELETE SET NULL,
  CONSTRAINT fk_project_owner FOREIGN KEY (OwnerId)        REFERENCES person(Id)       ON DELETE SET NULL
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS project_team (
  ProjectId INT NOT NULL,
  PersonId  INT NOT NULL,
  PRIMARY KEY (ProjectId, PersonId),
  CONSTRAINT fk_pt_project FOREIGN KEY (ProjectId) REFERENCES project(Id) ON DELETE CASCADE,
  CONSTRAINT fk_pt_person  FOREIGN KEY (PersonId)  REFERENCES person(Id)  ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS holiday (
  Id        INT AUTO_INCREMENT PRIMARY KEY,
  ProjectId INT NOT NULL,
  Date      DATE NOT NULL,
  UNIQUE KEY ux_holiday (ProjectId, Date),
  CONSTRAINT fk_hol_project FOREIGN KEY (ProjectId) REFERENCES project(Id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS activity (
  Id              INT AUTO_INCREMENT PRIMARY KEY,
  ProjectId       INT NOT NULL,
  Sequence        INT NOT NULL,
  Level           INT NOT NULL DEFAULT 0,
  Name            VARCHAR(200) NOT NULL,
  Notes           TEXT NULL,
  Mode            INT NOT NULL DEFAULT 0,
  Duration        INT NOT NULL DEFAULT 0,
  PlannedStart    DATE NULL,
  PlannedFinish   DATE NULL,
  TargetDate      DATE NULL,
  ActualStart     DATE NULL,
  ActualFinish    DATE NULL,
  PercentComplete INT NOT NULL DEFAULT 0,
  RoleId          INT NULL,
  BaselineStart   INT NULL,
  BaselineFinish  INT NULL,
  KEY ix_activity_seq (ProjectId, Sequence),
  CONSTRAINT fk_act_project FOREIGN KEY (ProjectId) REFERENCES project(Id) ON DELETE CASCADE,
  CONSTRAINT fk_act_role    FOREIGN KEY (RoleId)    REFERENCES role(Id)    ON DELETE SET NULL
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS activity_dependency (
  Id            INT AUTO_INCREMENT PRIMARY KEY,
  ActivityId    INT NOT NULL,
  PredecessorId INT NOT NULL,
  Type          INT NOT NULL DEFAULT 0,   -- 0 FS, 1 SS, 2 FF, 3 SF
  `Lag`           INT NOT NULL DEFAULT 0,   -- working days, may be negative
  UNIQUE KEY ux_dep (ActivityId, PredecessorId),
  CONSTRAINT fk_dep_activity FOREIGN KEY (ActivityId)    REFERENCES activity(Id) ON DELETE CASCADE,
  -- RESTRICT on purpose: a predecessor cannot be deleted out from under a link
  CONSTRAINT fk_dep_pred     FOREIGN KEY (PredecessorId) REFERENCES activity(Id) ON DELETE RESTRICT
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS activity_assignee (
  ActivityId INT NOT NULL,
  PersonId   INT NOT NULL,
  PRIMARY KEY (ActivityId, PersonId),
  CONSTRAINT fk_aa_activity FOREIGN KEY (ActivityId) REFERENCES activity(Id) ON DELETE CASCADE,
  CONSTRAINT fk_aa_person   FOREIGN KEY (PersonId)   REFERENCES person(Id)   ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS audit_entry (
  Id           BIGINT AUTO_INCREMENT PRIMARY KEY,
  TimestampUtc DATETIME(3) NOT NULL,
  Who          VARCHAR(120) NOT NULL,
  Action       VARCHAR(40)  NOT NULL,
  EntityKind   VARCHAR(40)  NOT NULL,
  EntityName   VARCHAR(200) NOT NULL,
  ProjectCode  VARCHAR(30)  NULL,
  ProjectId    INT NULL,
  ActivityId   INT NULL,
  Detail       TEXT NULL,
  KEY ix_audit_time (TimestampUtc),
  KEY ix_audit_project (ProjectId)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------------
-- v1.1: customer roles, project phases, and line-item date approvals
-- (The backend also applies these automatically at startup.)
-- ---------------------------------------------------------------------------
ALTER TABLE role ADD COLUMN IsCustomer TINYINT NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS phase (
  Id        INT AUTO_INCREMENT PRIMARY KEY,
  ProjectId INT NOT NULL,
  Sequence  INT NOT NULL DEFAULT 0,
  Name      VARCHAR(120) NOT NULL,
  StartDate DATE NULL,
  EndDate   DATE NULL,
  Colour    VARCHAR(9) NOT NULL DEFAULT '#2F6F9E',
  KEY ix_phase_project (ProjectId, Sequence),
  CONSTRAINT fk_phase_project FOREIGN KEY (ProjectId) REFERENCES project(Id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS phase_assignment (
  Id       INT AUTO_INCREMENT PRIMARY KEY,
  PhaseId  INT NOT NULL,
  RoleId   INT NOT NULL,
  PersonId INT NOT NULL,
  Notes    VARCHAR(500) NULL,
  UNIQUE KEY ux_phase_assign (PhaseId, RoleId, PersonId),
  CONSTRAINT fk_pa_phase  FOREIGN KEY (PhaseId)  REFERENCES phase(Id)  ON DELETE CASCADE,
  CONSTRAINT fk_pa_role   FOREIGN KEY (RoleId)   REFERENCES role(Id)   ON DELETE CASCADE,
  CONSTRAINT fk_pa_person FOREIGN KEY (PersonId) REFERENCES person(Id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS date_approval (
  Id             INT AUTO_INCREMENT PRIMARY KEY,
  ActivityId     INT NOT NULL,
  ActualStart    DATE NULL,
  ActualFinish   DATE NULL,
  Status         VARCHAR(10) NOT NULL DEFAULT 'Pending',
  Comment        VARCHAR(500) NULL,
  SubmittedBy    VARCHAR(120) NOT NULL DEFAULT '',
  SubmittedAtUtc DATETIME NULL,
  DecidedBy      VARCHAR(120) NULL,
  DecidedAtUtc   DATETIME NULL,
  UNIQUE KEY ux_approval_activity (ActivityId),
  CONSTRAINT fk_da_activity FOREIGN KEY (ActivityId) REFERENCES activity(Id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ---- v1.2: tickets ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS ticket_module (
  Id INT AUTO_INCREMENT PRIMARY KEY,
  Name VARCHAR(120) NOT NULL UNIQUE,
  ModuleType VARCHAR(10) NOT NULL DEFAULT 'SAP',      -- SAP | NonSAP
  Description VARCHAR(600) NULL,
  Active TINYINT NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS ticket (
  Id INT AUTO_INCREMENT PRIMARY KEY,
  ProjectId INT NOT NULL,
  PhaseId INT NULL,
  ModuleId INT NULL,
  Title VARCHAR(200) NOT NULL,
  Description TEXT NULL,
  Priority VARCHAR(10) NOT NULL DEFAULT 'Medium',     -- High | Medium | Low
  Status VARCHAR(12) NOT NULL DEFAULT 'Open',         -- Open | InProgress | Resolved | Closed
  AssigneeId INT NULL,
  CreatedBy VARCHAR(120) NOT NULL DEFAULT '',
  CreatedAtUtc DATETIME NOT NULL,
  UpdatedAtUtc DATETIME NOT NULL,
  CONSTRAINT fk_ticket_project FOREIGN KEY (ProjectId) REFERENCES project(Id) ON DELETE CASCADE,
  CONSTRAINT fk_ticket_phase FOREIGN KEY (PhaseId) REFERENCES phase(Id) ON DELETE SET NULL,
  CONSTRAINT fk_ticket_module FOREIGN KEY (ModuleId) REFERENCES ticket_module(Id) ON DELETE SET NULL,
  CONSTRAINT fk_ticket_assignee FOREIGN KEY (AssigneeId) REFERENCES person(Id) ON DELETE SET NULL,
  INDEX ix_ticket_project (ProjectId),
  INDEX ix_ticket_assignee (AssigneeId)
);

CREATE TABLE IF NOT EXISTS ticket_response (
  Id INT AUTO_INCREMENT PRIMARY KEY,
  TicketId INT NOT NULL,
  Author VARCHAR(120) NOT NULL,
  Body TEXT NOT NULL,
  CreatedAtUtc DATETIME NOT NULL,
  CONSTRAINT fk_tresp_ticket FOREIGN KEY (TicketId) REFERENCES ticket(Id) ON DELETE CASCADE,
  INDEX ix_ticket_response (TicketId)
);

CREATE TABLE IF NOT EXISTS ticket_attachment (
  Id INT AUTO_INCREMENT PRIMARY KEY,
  TicketId INT NOT NULL,
  ResponseId INT NULL,
  FileName VARCHAR(255) NOT NULL,
  ContentType VARCHAR(120) NOT NULL DEFAULT 'application/octet-stream',
  SizeBytes INT NOT NULL DEFAULT 0,
  Data MEDIUMBLOB NOT NULL,
  UploadedBy VARCHAR(120) NOT NULL DEFAULT '',
  UploadedAtUtc DATETIME NOT NULL,
  CONSTRAINT fk_tatt_ticket FOREIGN KEY (TicketId) REFERENCES ticket(Id) ON DELETE CASCADE,
  CONSTRAINT fk_tatt_response FOREIGN KEY (ResponseId) REFERENCES ticket_response(Id) ON DELETE CASCADE,
  INDEX ix_ticket_attachment (TicketId)
);

-- ============================================================ v1.3
CREATE TABLE IF NOT EXISTS app_user (
  Id INT AUTO_INCREMENT PRIMARY KEY,
  PersonId INT NULL,
  Email VARCHAR(200) NOT NULL UNIQUE,
  DisplayName VARCHAR(200) NOT NULL,
  Source VARCHAR(10) NOT NULL DEFAULT 'local',
  EntraOid VARCHAR(64) NULL UNIQUE,
  EntraTenantId VARCHAR(64) NULL,
  UserType VARCHAR(10) NOT NULL DEFAULT 'Member',
  PasswordHash VARCHAR(255) NULL,
  IsAdmin TINYINT NOT NULL DEFAULT 0,
  Active TINYINT NOT NULL DEFAULT 1,
  LastLoginUtc DATETIME NULL,
  CreatedAtUtc DATETIME NOT NULL,
  CONSTRAINT fk_appuser_person FOREIGN KEY (PersonId) REFERENCES person(Id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS directory_sync (
  Id INT AUTO_INCREMENT PRIMARY KEY,
  RunBy VARCHAR(120) NOT NULL DEFAULT '',
  RunAtUtc DATETIME NOT NULL,
  Fetched INT NOT NULL DEFAULT 0,
  Created INT NOT NULL DEFAULT 0,
  Updated INT NOT NULL DEFAULT 0,
  Skipped INT NOT NULL DEFAULT 0,
  Detail TEXT NULL
);

CREATE TABLE IF NOT EXISTS process (
  Id INT AUTO_INCREMENT PRIMARY KEY,
  Name VARCHAR(160) NOT NULL UNIQUE,
  Code VARCHAR(40) NULL,
  Description VARCHAR(1000) NULL,
  Active TINYINT NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS process_step (
  Id INT AUTO_INCREMENT PRIMARY KEY,
  ProcessId INT NOT NULL,
  Name VARCHAR(160) NOT NULL,
  Description VARCHAR(1000) NULL,
  SortOrder INT NOT NULL DEFAULT 0,
  OwnerRoleId INT NULL,
  Active TINYINT NOT NULL DEFAULT 1,
  CONSTRAINT fk_step_process FOREIGN KEY (ProcessId) REFERENCES process(Id) ON DELETE CASCADE,
  CONSTRAINT fk_step_role FOREIGN KEY (OwnerRoleId) REFERENCES role(Id) ON DELETE SET NULL,
  CONSTRAINT uq_step_name UNIQUE (ProcessId, Name),
  INDEX ix_step_process (ProcessId)
);

-- Many to many on purpose: one process is run by several modules.
CREATE TABLE IF NOT EXISTS module_process (
  Id INT AUTO_INCREMENT PRIMARY KEY,
  ModuleId INT NOT NULL,
  ProcessId INT NOT NULL,
  SortOrder INT NOT NULL DEFAULT 0,
  CONSTRAINT fk_mp_module FOREIGN KEY (ModuleId) REFERENCES ticket_module(Id) ON DELETE CASCADE,
  CONSTRAINT fk_mp_process FOREIGN KEY (ProcessId) REFERENCES process(Id) ON DELETE CASCADE,
  CONSTRAINT uq_module_process UNIQUE (ModuleId, ProcessId)
);

ALTER TABLE ticket ADD COLUMN ProcessId INT NULL;
ALTER TABLE ticket ADD COLUMN ProcessStepId INT NULL;

-- ============================================================ v1.4
CREATE TABLE IF NOT EXISTS counter (
  Name VARCHAR(40) PRIMARY KEY,
  Value INT NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS customer (
  Id INT AUTO_INCREMENT PRIMARY KEY,
  Code VARCHAR(20) NOT NULL UNIQUE,
  Name VARCHAR(200) NOT NULL UNIQUE,
  Active TINYINT NOT NULL DEFAULT 1
);

ALTER TABLE project  ADD COLUMN CustomerId INT NULL;
ALTER TABLE role     ADD COLUMN CustomerId INT NULL;
ALTER TABLE app_user ADD COLUMN CustomerId INT NULL;
ALTER TABLE project  ADD CONSTRAINT fk_project_customer
  FOREIGN KEY (CustomerId) REFERENCES customer(Id) ON DELETE SET NULL;
ALTER TABLE role     ADD CONSTRAINT fk_role_customer
  FOREIGN KEY (CustomerId) REFERENCES customer(Id) ON DELETE SET NULL;
ALTER TABLE app_user ADD CONSTRAINT fk_appuser_customer
  FOREIGN KEY (CustomerId) REFERENCES customer(Id) ON DELETE SET NULL;

-- ============================================================ v1.5
-- Attachments move to disk; the row keeps the metadata. Data stays for files
-- stored before v1.5 and is empty for everything after.
ALTER TABLE ticket_attachment MODIFY Data MEDIUMBLOB NULL;
ALTER TABLE ticket_attachment ADD COLUMN StorageKey VARCHAR(200) NULL;
ALTER TABLE ticket_attachment ADD COLUMN Sha256 CHAR(64) NULL;
ALTER TABLE ticket_attachment ADD COLUMN Kind VARCHAR(12) NOT NULL DEFAULT 'document';

-- Set when an administrator issues a password; cleared when the holder
-- chooses their own. Until then the account can only change its password.
ALTER TABLE app_user ADD COLUMN MustChangePassword TINYINT NOT NULL DEFAULT 0;
