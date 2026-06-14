# File Intake Connector

A specialized batch operations system for the AFRD (Artifact-First Research and Development) framework. Automates file intake, artifact classification, journal logging, file routing, and batch validation with strict manual-review gates and audit trails.

## Overview

**File Intake Connector** manages the complete lifecycle of artifact ingestion into the AFRD system:

- **Phase 3:** File intake from INBOX with export block parsing and route validation
- **Phase 4:** Journal ID assignment and audit logging
- **Phase 5:** File movement to canonical folders with approval gates
- **Phase 6:** Specialist routing and queue management
- **Phase 7:** Batch closeout with delta validation and completion checks

All operations run in `manual_review` mode — nothing happens automatically. Every action requires explicit operator decision and approval tokens.

## Key Features

- **Export Block Parsing** — Reads metadata headers from markdown files to classify and route artifacts
- **Duplicate Detection** — Rerun guards prevent duplicate register entries using filename, Drive link, and file ID matching
- **Manual Approval Gates** — Phase 4 and Phase 5 require approval tokens and explicit queue row approvals
- **Batch Tracking** — Baseline snapshots and delta calculations verify completeness (intake → journal → apply → routing)
- **Correction Logging** — Centralized error and mismatch tracking with resolution status
- **Audit Trail** — Operations run log records every script execution with deltas and timestamps
- **Google Docs Support** — GDOC-PATCH handles Google Docs by auto-exporting as plain text before parsing

## Project Structure

```
file-intake-connector/
├── AFRD_OPS_REGISTERS.gs                # Main spreadsheet with all register tabs and config
├── Phase_3_File_Intake.gs               # Intake script with dry run and suggest-only modes
├── Phase_4_Journal_IDs.gs               # Journal ID assignment with approval gate
├── Phase_5_Apply_Moves.gs               # File movement with approval queue
├── Phase_6_Routing.gs                   # Specialist routing and queue building
├── Phase_7_Batch_Closeout.gs            # Batch validation and completion
├── AFRD_Batch_Operations_Guide_v0_1.md  # Complete operator guide
└── README.md                            # This file
```

## Getting Started

### Prerequisites

- Google Drive with AFRD_ROOT folder structure
- Google Sheets with AFRD_OPS_REGISTERS spreadsheet (Config, Artifact_Intake_Log, etc.)
- Files with `[AFRD EXPORT BLOCK]` metadata headers in markdown format

### Setup

1. Create the AFRD folder structure in Google Drive:

```
AFRD_ROOT/
├── 01_STANDARDS/
├── 02_INBOX/
│   └── 00_New_Uploads/
├── 03_APPLIED/
├── 04_JOURNALS/
└── [other specialist folders]
```

2. Set up AFRD_OPS_REGISTERS spreadsheet with tabs:
   - Config (with folder IDs, mode settings, gates)
   - Artifact_Intake_Log
   - Artifact_ID_Register
   - Artifact_Route_Log
   - Journal_ID_Register
   - Artifact_Journal_Ledger
   - Manual_Apply_Queue
   - Specialist_Queue_Register
   - Specialist_Routing_Dashboard
   - Approval_Gate_Log
   - Correction_Log
   - Folder_ID_Map
   - Batch_Control_Register
   - Operations_Run_Log
   - Run_Record_Input
   - File_Status_Dashboard

3. Update the Config tab with your folder IDs and settings (see guide for details).

## Basic Workflow

### Opening a Batch

```
startOperationsBatch()                 # Record baseline
dryRunPhase7BatchChecklist()           # Verify clean state
validatePhase7BatchReadiness()         # Validate all settings
```

### Processing Files

```
dryRunFileIntake()                     # Preview intake
runFileIntakeSuggestOnly()             # Write register rows (no moves)
validatePhase3IntakeRows()             # Check quality
```

### Assigning Journal IDs

```
dryRunJournalIdAssignment()            # Preview ID assignment
[CONFIG: Open Phase 4 gate]
runJournalIdAssignmentPilot()          # Assign IDs
[CONFIG: Close Phase 4 gate]
validateJournalIdControl()             # Verify consistency
```

### Moving Files

```
buildManualApplyQueue()                # Create move queue
[SHEET: Approve queue rows in Manual_Apply_Queue]
dryRunApplyApprovedMoves()             # Preview moves
[CONFIG: Open Phase 5 gate]
runApplyApprovedMoves()                # Move files
[CONFIG: Close Phase 5 gate]
```

### Routing to Specialists

```
buildSpecialistQueueRegister()         # Create routing rows
updateSpecialistRoutingDashboard()     # Refresh dashboard
validateSpecialistRoutingDashboard()   # Check routing
```

### Closing the Batch

```
updateOperationsBatchStatus()          # Calculate deltas
validatePhase7BatchCompletion()        # Verify completeness
updateDashboardPhase7()                # Final dashboard update
recordOperationsRunFromInput()         # Log the run
```

See **AFRD_Batch_Operations_Guide_v0_1.md** for complete step-by-step instructions and troubleshooting.

## Config Tab — Key Fields

| Field | Purpose | Set Before |
|-------|---------|-----------|
| `Current_Batch_ID` | Active batch name | Starting a batch |
| `Journal_ID_Assignment_Enabled` | Phase 4 gate | Running Phase 4 |
| `Journal_ID_Assignment_Approval_Token` | Phase 4 approval | Running Phase 4 |
| `Apply_Enabled` | Phase 5 gate | Running Phase 5 |
| `Apply_Approval_Token` | Phase 5 approval | Running Phase 5 |

**Golden Rule:** Open the gate → run the script → close the gate. Never leave gates open between sessions.

## Core Concepts

**Export Block** — Metadata header in markdown files (enclosed in `[AFRD EXPORT BLOCK]` markers) containing Artifact_ID, routing path, version, and safety flags.

**Dry Run** — Read-only preview of what a script would do. Always run before real operations.

**Suggest-Only** — Phase 3 writes register rows but does not move files. Files stay in INBOX.

**Rerun Guard** — Duplicate detection matching on filename, Drive link, and file ID.

**Delta** — Difference between current register counts and baseline. Used to verify batch completeness.

**Journal_ID** — Sequential log identifier (e.g., `OPSLOG-0013`) assigned by Phase 4 for audit trail linkage.

For full glossary and definitions, see the guide.

## Hard Limits

These cannot be overridden:

- **Live trading** — not approved
- **Capital allocation** — not approved
- **Final edge acceptance** — not approved
- **Production automation** — not approved (`Production_Automation_Enabled` must stay `no`)
- **File deletion** — scripts never delete files
- **Permission changes** — scripts never modify sharing or access

## Troubleshooting

### Bad rows from failed runs

If a script run fails partway through, it may leave partial rows in registers. To clean up:

1. Identify bad rows (look for `ART-pending` IDs or today's timestamps)
2. Delete rows from affected tabs (Artifact_Intake_Log, Artifact_Route_Log, Correction_Log)
3. The rerun guard matches on filename and Drive link — clean up to prevent skips

### Google Docs vs markdown files

The GDOC-PATCH handles Google Docs automatically by exporting as plain text before parsing. If you see `%PDF-1.4` in debug output, the patch is not installed.

### Token safety failures

If `startOperationsBatch()` aborts with token safety issues, check Config:

- `Journal_ID_Assignment_Enabled` should be `no`
- `Journal_ID_Assignment_Approval_Token` should be empty
- `Apply_Enabled` should be `no`
- `Apply_Approval_Token` should be empty

Run `checkTokenSafetyStatus()` (read-only) to see full token state.

## Documentation

- **AFRD_Batch_Operations_Guide_v0_1.md** — Complete step-by-step operator guide with every phase, config change, and troubleshooting scenario
- **Config Tab Reference** — All fields, typical values, when to set/reset
- **Script Run Order** — Standard sequence for batch with new files (20 steps, numbered)
- **Gate Quick Reference Card** — Which gates open/close for each phase

## Version

**v0.1** — June 13, 2026  
Initial release with Phases 3–7, manual review mode, and full operator guide.

## License

[Add your license if applicable]

## Support

For issues or questions, see the AFRD_Batch_Operations_Guide_v0_1.md troubleshooting section.
