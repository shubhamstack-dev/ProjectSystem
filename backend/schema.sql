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
