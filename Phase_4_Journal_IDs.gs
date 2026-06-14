// Phase_4_Journal_IDs.gs
// Assigns sequential Journal IDs (OPSLOG-XXXX) to artifacts that have been
// ingested but not yet journalled. Requires the Phase 4 gate to be open and
// a valid approval token to be present in Config.

// ── JOURNAL ID GENERATOR ──────────────────────────────────────────────────────
// Returns the next OPSLOG-XXXX ID by inspecting the Journal_ID_Register.
function getNextJournalId() {
  const rows = getSheetRows(TABS.JOURNAL_ID_REGISTER);
  let maxSeq = 0;
  rows.forEach(r => {
    const id = String(r['Journal_ID'] || '');
    const match = id.match(/^OPSLOG-(\d+)$/);
    if (match) maxSeq = Math.max(maxSeq, parseInt(match[1], 10));
  });
  const nextSeq = String(maxSeq + 1).padStart(4, '0');
  return 'OPSLOG-' + nextSeq;
}

// ── GATE CHECK ────────────────────────────────────────────────────────────────
// Throws unless Phase 4 gate is open and a non-empty approval token is set.
function assertPhase4Gate() {
  const enabled = getConfigValue('Journal_ID_Assignment_Enabled');
  const token   = getConfigValue('Journal_ID_Assignment_Approval_Token');

  if (enabled.toLowerCase() !== 'yes') {
    throw new Error(
      'AFRD Phase 4 Gate CLOSED.\n' +
      'Set Journal_ID_Assignment_Enabled = "yes" in Config to proceed.'
    );
  }
  if (!token) {
    throw new Error(
      'AFRD Phase 4 Gate: Approval token is empty.\n' +
      'Set Journal_ID_Assignment_Approval_Token in Config to proceed.'
    );
  }
  logGateAction('Phase_4_Journal_ID', 'gate-checked', token);
}

// ── ROWS NEEDING JOURNAL IDs ──────────────────────────────────────────────────
// Returns intake rows for the current batch that have no Journal_ID yet.
function getUnjournalledRows() {
  const batchId     = getCurrentBatchId();
  const intakeRows  = getSheetRows(TABS.ARTIFACT_INTAKE_LOG)
                        .filter(r => String(r['Batch_ID']) === batchId);
  const ledgerRows  = getSheetRows(TABS.ARTIFACT_JOURNAL_LEDGER);
  const journalledIds = new Set(ledgerRows.map(r => String(r['Artifact_ID']).trim()));

  return intakeRows.filter(r => {
    const id = String(r['Artifact_ID']).trim();
    return id && id !== 'ART-pending' && !journalledIds.has(id);
  });
}

// ── DRY RUN ───────────────────────────────────────────────────────────────────
// Read-only preview of which rows would receive Journal IDs.
function dryRunJournalIdAssignment() {
  const batchId = getCurrentBatchId();
  const pending = getUnjournalledRows();

  const lines = [
    'DRY RUN — Phase 4 Journal ID Assignment',
    'Batch: ' + batchId,
    'Pending rows: ' + pending.length,
    '',
  ];

  let seq = getSheetRows(TABS.JOURNAL_ID_REGISTER).reduce((max, r) => {
    const m = String(r['Journal_ID'] || '').match(/^OPSLOG-(\d+)$/);
    return m ? Math.max(max, parseInt(m[1], 10)) : max;
  }, 0);

  pending.forEach(r => {
    seq++;
    const nextId = 'OPSLOG-' + String(seq).padStart(4, '0');
    lines.push('[WOULD ASSIGN] ' + nextId + ' → ' + r['Artifact_ID'] + ' (' + r['Filename'] + ')');
  });

  if (pending.length === 0) lines.push('(nothing to assign — all rows already have Journal IDs)');

  const msg = lines.join('\n');
  Logger.log(msg);
  SpreadsheetApp.getUi().alert(msg);
}

// ── PILOT RUN ─────────────────────────────────────────────────────────────────
// Assigns Journal IDs and writes to Journal_ID_Register and Artifact_Journal_Ledger.
function runJournalIdAssignmentPilot() {
  assertPhase4Gate();

  const batchId      = getCurrentBatchId();
  const token        = getConfigValue('Journal_ID_Assignment_Approval_Token');
  const pending      = getUnjournalledRows();
  const registerSheet= getSheet(TABS.JOURNAL_ID_REGISTER);
  const ledgerSheet  = getSheet(TABS.ARTIFACT_JOURNAL_LEDGER);

  if (pending.length === 0) {
    SpreadsheetApp.getUi().alert('Phase 4: No rows need Journal IDs for batch ' + batchId);
    return;
  }

  let assigned = 0;
  pending.forEach(r => {
    const journalId  = getNextJournalId();
    const artifactId = String(r['Artifact_ID']).trim();
    const filename   = String(r['Filename']).trim();
    const now        = new Date();

    // Journal_ID_Register
    registerSheet.appendRow([journalId, artifactId, filename, batchId, now]);

    // Artifact_Journal_Ledger
    ledgerSheet.appendRow([artifactId, journalId, filename, batchId, 'Assigned', now]);

    Logger.log('[ASSIGNED] ' + journalId + ' → ' + artifactId);
    assigned++;
  });

  // Update intake log status to 'Journalled' for assigned rows
  _updateIntakeLogStatus(batchId, pending.map(r => String(r['Artifact_ID']).trim()), 'Journalled');

  const summary =
    'Phase 4 complete.\n' +
    'Assigned ' + assigned + ' Journal ID(s) for batch ' + batchId + '.\n' +
    'Approval token used: ' + token + '\n\n' +
    'IMPORTANT: Set Journal_ID_Assignment_Enabled = "no" and clear the token in Config now.';
  Logger.log(summary);
  SpreadsheetApp.getUi().alert(summary);
}

// ── VALIDATE JOURNAL ID CONTROL ───────────────────────────────────────────────
// Verifies: every intake row has a Journal ID, no duplicate Journal IDs.
function validateJournalIdControl() {
  const batchId    = getCurrentBatchId();
  const intakeRows = getSheetRows(TABS.ARTIFACT_INTAKE_LOG)
                       .filter(r => String(r['Batch_ID']) === batchId);
  const ledgerRows = getSheetRows(TABS.ARTIFACT_JOURNAL_LEDGER)
                       .filter(r => String(r['Batch_ID']) === batchId);

  const journalledIds = new Set(ledgerRows.map(r => String(r['Artifact_ID']).trim()));
  const journalIds    = ledgerRows.map(r => String(r['Journal_ID']).trim());
  const seenJids      = new Set();

  const issues = [];

  intakeRows.forEach((r, i) => {
    const id = String(r['Artifact_ID']).trim();
    if (id && id !== 'ART-pending' && !journalledIds.has(id)) {
      issues.push('Row ' + (i + 2) + ': ' + id + ' has no Journal ID');
    }
  });

  journalIds.forEach(jid => {
    if (seenJids.has(jid)) {
      issues.push('Duplicate Journal_ID detected: ' + jid);
    }
    seenJids.add(jid);
  });

  if (issues.length === 0) {
    const msg =
      'Phase 4 Validation PASSED.\n' +
      intakeRows.length + ' intake rows, ' + ledgerRows.length + ' journal entries — all consistent.';
    Logger.log(msg);
    SpreadsheetApp.getUi().alert(msg);
  } else {
    const msg = 'Phase 4 Validation FAILED — ' + issues.length + ' issue(s):\n\n' + issues.join('\n');
    Logger.log(msg);
    issues.forEach(iss => logCorrection('', 'JOURNAL_VALIDATION', iss));
    SpreadsheetApp.getUi().alert(msg);
  }
}

// ── HELPERS ───────────────────────────────────────────────────────────────────
// Updates the Status column in Artifact_Intake_Log for a set of Artifact_IDs.
function _updateIntakeLogStatus(batchId, artifactIds, newStatus) {
  const sheet  = getSheet(TABS.ARTIFACT_INTAKE_LOG);
  const values = sheet.getDataRange().getValues();
  const headers= values[0];
  const idCol  = headers.indexOf('Artifact_ID');
  const batCol = headers.indexOf('Batch_ID');
  const stCol  = headers.indexOf('Status');

  if (idCol === -1 || stCol === -1) return;

  const idSet = new Set(artifactIds);
  for (let i = 1; i < values.length; i++) {
    if (batCol !== -1 && String(values[i][batCol]) !== batchId) continue;
    if (idSet.has(String(values[i][idCol]).trim())) {
      sheet.getRange(i + 1, stCol + 1).setValue(newStatus);
    }
  }
}
