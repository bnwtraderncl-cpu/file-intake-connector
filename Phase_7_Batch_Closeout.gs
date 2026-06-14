// Phase_7_Batch_Closeout.gs
// Manages the full batch lifecycle: recording baseline counts, validating
// readiness, calculating deltas, updating the dashboard, and logging the run.

// ── COUNT HELPERS ─────────────────────────────────────────────────────────────
function _countBatchRows(tabName, batchId) {
  return getSheetRows(tabName)
    .filter(r => String(r['Batch_ID']).trim() === batchId)
    .length;
}

function _getCurrentCounts(batchId) {
  return {
    intake:   _countBatchRows(TABS.ARTIFACT_INTAKE_LOG,       batchId),
    journal:  _countBatchRows(TABS.JOURNAL_ID_REGISTER,       batchId),
    applied:  _countBatchRows(TABS.ARTIFACT_ROUTE_LOG,        batchId),
    routed:   _countBatchRows(TABS.SPECIALIST_QUEUE_REGISTER, batchId),
  };
}

// ── GET BATCH CONTROL ROW ─────────────────────────────────────────────────────
// Returns { rowIndex (1-based), data } for the current batch, or null.
function _getBatchControlRow(batchId) {
  const sheet  = getSheet(TABS.BATCH_CONTROL_REGISTER);
  const values = sheet.getDataRange().getValues();
  const headers= values[0];
  const idCol  = headers.indexOf('Batch_ID');
  for (let i = 1; i < values.length; i++) {
    if (String(values[i][idCol]).trim() === batchId) {
      const obj = {};
      headers.forEach((h, j) => { obj[h] = values[i][j]; });
      return { rowIndex: i + 1, data: obj };
    }
  }
  return null;
}

// ── START OPERATIONS BATCH ───────────────────────────────────────────────────
// Records baseline counts and creates a Batch_Control_Register entry.
// Throws if any gate is open (token safety check).
function startOperationsBatch() {
  assertTokenSafety();

  const batchId = getCurrentBatchId();
  const existing = _getBatchControlRow(batchId);
  if (existing && String(existing.data['Status']).trim() === 'Open') {
    throw new Error(
      'AFRD: Batch "' + batchId + '" is already open.\n' +
      'Close the previous batch before starting a new one.'
    );
  }

  const counts = _getCurrentCounts(batchId);
  const sheet  = getSheet(TABS.BATCH_CONTROL_REGISTER);

  sheet.appendRow([
    batchId,
    new Date(),  // Start_Timestamp
    '',          // End_Timestamp
    'Open',
    counts.intake,
    counts.journal,
    counts.applied,
    counts.routed,
    0, 0, 0, 0,  // Deltas (calculated later)
    '',          // Notes
  ]);

  const msg =
    'Batch "' + batchId + '" started.\n\n' +
    'Baseline counts:\n' +
    '  Intake:   ' + counts.intake  + '\n' +
    '  Journal:  ' + counts.journal + '\n' +
    '  Applied:  ' + counts.applied + '\n' +
    '  Routed:   ' + counts.routed;
  Logger.log(msg);
  SpreadsheetApp.getUi().alert(msg);
}

// ── DRY RUN PHASE 7 CHECKLIST ─────────────────────────────────────────────────
// Read-only checklist to verify the system is in a clean state.
function dryRunPhase7BatchChecklist() {
  const batchId = getCurrentBatchId();
  const lines   = [
    'DRY RUN — Phase 7 Batch Checklist',
    'Batch: ' + batchId,
    '',
  ];

  const checks = [
    {
      name:  'Token safety — all gates closed',
      check: () => {
        const issues = [];
        if (getConfigValue('Journal_ID_Assignment_Enabled').toLowerCase() !== 'no')
          issues.push('Journal_ID_Assignment_Enabled is not "no"');
        if (getConfigValue('Apply_Enabled').toLowerCase() !== 'no')
          issues.push('Apply_Enabled is not "no"');
        if (getConfigValue('Journal_ID_Assignment_Approval_Token') !== '')
          issues.push('Journal_ID_Assignment_Approval_Token not empty');
        if (getConfigValue('Apply_Approval_Token') !== '')
          issues.push('Apply_Approval_Token not empty');
        return issues.length === 0 ? null : issues.join(', ');
      },
    },
    {
      name:  'Production_Automation_Enabled is "no"',
      check: () => getConfigValue('Production_Automation_Enabled').toLowerCase() !== 'no'
        ? 'Production_Automation_Enabled must be "no"' : null,
    },
    {
      name:  'INBOX_Folder_ID is set',
      check: () => !getConfigValue('INBOX_Folder_ID') ? 'INBOX_Folder_ID is empty in Config' : null,
    },
    {
      name:  'No ART-pending IDs in Artifact_Intake_Log',
      check: () => {
        const pending = getSheetRows(TABS.ARTIFACT_INTAKE_LOG)
          .filter(r => String(r['Artifact_ID']).trim() === 'ART-pending');
        return pending.length > 0
          ? pending.length + ' row(s) still have ART-pending Artifact_ID'
          : null;
      },
    },
    {
      name:  'No open Correction_Log entries',
      check: () => {
        const open = getSheetRows(TABS.CORRECTION_LOG)
          .filter(r => String(r['Resolution_Status']).trim() === 'Open');
        return open.length > 0 ? open.length + ' unresolved correction(s) logged' : null;
      },
    },
  ];

  checks.forEach(c => {
    const issue = c.check();
    lines.push((issue ? '[FAIL] ' : '[PASS] ') + c.name);
    if (issue) lines.push('       → ' + issue);
  });

  const msg = lines.join('\n');
  Logger.log(msg);
  SpreadsheetApp.getUi().alert(msg);
}

// ── VALIDATE PHASE 7 BATCH READINESS ─────────────────────────────────────────
// Full validation of Config and register state before opening a batch.
function validatePhase7BatchReadiness() {
  const batchId = getCurrentBatchId();
  const issues  = [];

  if (!batchId) issues.push('Current_Batch_ID is not set');
  if (!getConfigValue('INBOX_Folder_ID')) issues.push('INBOX_Folder_ID is not set');
  if (!getConfigValue('AFRD_ROOT_Folder_ID')) issues.push('AFRD_ROOT_Folder_ID is not set');
  if (getConfigValue('Mode') !== 'manual_review') issues.push('Mode must be "manual_review"');
  if (getConfigValue('Production_Automation_Enabled').toLowerCase() !== 'no')
    issues.push('Production_Automation_Enabled must be "no"');

  const folderMap = getFolderIdMap();
  if (Object.keys(folderMap).length === 0) issues.push('Folder_ID_Map is empty');

  if (issues.length === 0) {
    const msg = 'Phase 7 Readiness Validation PASSED for batch: ' + batchId;
    Logger.log(msg);
    SpreadsheetApp.getUi().alert(msg);
  } else {
    const msg = 'Phase 7 Readiness Validation FAILED:\n\n' + issues.join('\n');
    Logger.log(msg);
    SpreadsheetApp.getUi().alert(msg);
  }
}

// ── UPDATE OPERATIONS BATCH STATUS ───────────────────────────────────────────
// Calculates deltas between current counts and the baseline snapshot.
function updateOperationsBatchStatus() {
  const batchId = getCurrentBatchId();
  const row     = _getBatchControlRow(batchId);
  if (!row) throw new Error('AFRD: No open batch record for "' + batchId + '". Run startOperationsBatch() first.');

  const baseline = {
    intake:  Number(row.data['Baseline_Intake'])  || 0,
    journal: Number(row.data['Baseline_Journal']) || 0,
    applied: Number(row.data['Baseline_Applied']) || 0,
    routed:  Number(row.data['Baseline_Routed'])  || 0,
  };
  const current = _getCurrentCounts(batchId);

  const deltas = {
    intake:  current.intake  - baseline.intake,
    journal: current.journal - baseline.journal,
    applied: current.applied - baseline.applied,
    routed:  current.routed  - baseline.routed,
  };

  // Update the Batch_Control_Register row
  const sheet   = getSheet(TABS.BATCH_CONTROL_REGISTER);
  const values  = sheet.getDataRange().getValues();
  const headers = values[0];
  const col     = name => headers.indexOf(name) + 1;

  sheet.getRange(row.rowIndex, col('Delta_Intake')).setValue(deltas.intake);
  sheet.getRange(row.rowIndex, col('Delta_Journal')).setValue(deltas.journal);
  sheet.getRange(row.rowIndex, col('Delta_Applied')).setValue(deltas.applied);
  sheet.getRange(row.rowIndex, col('Delta_Routed')).setValue(deltas.routed);

  const msg =
    'Batch "' + batchId + '" status updated.\n\n' +
    'Deltas (current − baseline):\n' +
    '  Intake:   ' + deltas.intake  + '\n' +
    '  Journal:  ' + deltas.journal + '\n' +
    '  Applied:  ' + deltas.applied + '\n' +
    '  Routed:   ' + deltas.routed;
  Logger.log(msg);
  SpreadsheetApp.getUi().alert(msg);
}

// ── VALIDATE PHASE 7 BATCH COMPLETION ────────────────────────────────────────
// Verifies delta consistency: intake == journal == applied == routed.
function validatePhase7BatchCompletion() {
  const batchId = getCurrentBatchId();
  const row     = _getBatchControlRow(batchId);
  if (!row) throw new Error('AFRD: No batch record for "' + batchId + '".');

  const d = {
    intake:  Number(row.data['Delta_Intake'])  || 0,
    journal: Number(row.data['Delta_Journal']) || 0,
    applied: Number(row.data['Delta_Applied']) || 0,
    routed:  Number(row.data['Delta_Routed'])  || 0,
  };

  const issues = [];
  if (d.intake !== d.journal) issues.push('Intake delta (' + d.intake + ') ≠ Journal delta (' + d.journal + ')');
  if (d.intake !== d.applied) issues.push('Intake delta (' + d.intake + ') ≠ Applied delta (' + d.applied + ')');
  if (d.intake !== d.routed)  issues.push('Intake delta (' + d.intake + ') ≠ Routed delta (' + d.routed + ')');
  if (d.intake === 0)         issues.push('Delta is zero — no new files processed in this batch');

  if (issues.length === 0) {
    const msg =
      'Phase 7 Completion Validation PASSED.\n\n' +
      'All deltas are consistent: ' + d.intake + ' file(s) completed full pipeline.';
    Logger.log(msg);
    SpreadsheetApp.getUi().alert(msg);
  } else {
    const msg = 'Phase 7 Completion Validation FAILED:\n\n' + issues.join('\n');
    Logger.log(msg);
    SpreadsheetApp.getUi().alert(msg);
  }
}

// ── UPDATE DASHBOARD PHASE 7 ──────────────────────────────────────────────────
// Rebuilds File_Status_Dashboard with the current status of every artifact
// in the current batch.
function updateDashboardPhase7() {
  const batchId    = getCurrentBatchId();
  const dashSheet  = getSheet(TABS.FILE_STATUS_DASHBOARD);

  // Clear existing rows for this batch
  const existing = dashSheet.getDataRange().getValues();
  const batCol   = existing[0].indexOf('Batch_ID');
  for (let i = existing.length - 1; i >= 1; i--) {
    if (String(existing[i][batCol]).trim() === batchId) {
      dashSheet.deleteRow(i + 1);
    }
  }

  // Build lookup maps
  const journalMap = {};
  getSheetRows(TABS.JOURNAL_ID_REGISTER)
    .filter(r => String(r['Batch_ID']) === batchId)
    .forEach(r => { journalMap[String(r['Artifact_ID']).trim()] = String(r['Journal_ID']).trim(); });

  const routeMap = {};
  getSheetRows(TABS.ARTIFACT_ROUTE_LOG)
    .filter(r => String(r['Batch_ID']) === batchId)
    .forEach(r => { routeMap[String(r['Artifact_ID']).trim()] = r; });

  const intakeRows = getSheetRows(TABS.ARTIFACT_INTAKE_LOG)
                       .filter(r => String(r['Batch_ID']) === batchId);

  const now = new Date();
  intakeRows.forEach(r => {
    const artifactId = String(r['Artifact_ID']).trim();
    const journalId  = journalMap[artifactId] || '';
    const routeRow   = routeMap[artifactId];
    const status     = String(r['Status'] || 'Suggest').trim();
    const location   = routeRow ? String(routeRow['Route_Path'] || '') : '02_INBOX';

    dashSheet.appendRow([
      artifactId,
      String(r['Filename'] || ''),
      journalId,
      status,
      location,
      batchId,
      now,
    ]);
  });

  const msg = 'File Status Dashboard updated: ' + intakeRows.length + ' artifact(s) for batch ' + batchId;
  Logger.log(msg);
  SpreadsheetApp.getUi().alert(msg);
}

// ── RECORD OPERATIONS RUN FROM INPUT ─────────────────────────────────────────
// Reads field/value pairs from Run_Record_Input tab and appends a row to
// Operations_Run_Log. Clear Run_Record_Input after a successful write.
function recordOperationsRunFromInput() {
  const inputRows = getSheetRows(TABS.RUN_RECORD_INPUT);
  const input     = {};
  inputRows.forEach(r => {
    if (r['Field']) input[String(r['Field']).trim()] = String(r['Value'] || '').trim();
  });

  const batchId     = getCurrentBatchId();
  const runLogSheet = getSheet(TABS.OPERATIONS_RUN_LOG);

  // Generate a simple run ID
  const runCount = runLogSheet.getLastRow(); // rows including header
  const runId    = 'RUN-' + String(runCount).padStart(4, '0');

  runLogSheet.appendRow([
    runId,
    new Date(),
    input['Script_Name']       || '(not specified)',
    input['Batch_ID']          || batchId,
    input['Status']            || 'Complete',
    input['Records_Processed'] || '',
    input['Delta_Notes']       || '',
    input['Operator_Notes']    || '',
  ]);

  // Mark the batch as closed if requested
  if (String(input['Close_Batch'] || '').toLowerCase() === 'yes') {
    const row = _getBatchControlRow(batchId);
    if (row) {
      const sheet   = getSheet(TABS.BATCH_CONTROL_REGISTER);
      const values  = sheet.getDataRange().getValues();
      const headers = values[0];
      const col     = name => headers.indexOf(name) + 1;
      sheet.getRange(row.rowIndex, col('End_Timestamp')).setValue(new Date());
      sheet.getRange(row.rowIndex, col('Status')).setValue('Closed');
    }
  }

  const msg = 'Operations run logged as ' + runId + ' for batch ' + batchId;
  Logger.log(msg);
  SpreadsheetApp.getUi().alert(msg);
}
