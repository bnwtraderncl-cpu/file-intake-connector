// Phase_5_Apply_Moves.gs
// Builds a manual approval queue of file moves, then executes approved moves
// in Google Drive. Requires operator approval on each queue row and an open
// Phase 5 gate with a valid approval token.

// ── GATE CHECK ────────────────────────────────────────────────────────────────
function assertPhase5Gate() {
  const enabled = getConfigValue('Apply_Enabled');
  const token   = getConfigValue('Apply_Approval_Token');

  if (enabled.toLowerCase() !== 'yes') {
    throw new Error(
      'AFRD Phase 5 Gate CLOSED.\n' +
      'Set Apply_Enabled = "yes" in Config to proceed.'
    );
  }
  if (!token) {
    throw new Error(
      'AFRD Phase 5 Gate: Approval token is empty.\n' +
      'Set Apply_Approval_Token in Config to proceed.'
    );
  }
  logGateAction('Phase_5_Apply_Moves', 'gate-checked', token);
}

// ── BUILD MANUAL APPLY QUEUE ──────────────────────────────────────────────────
// Creates queue rows for all journalled artifacts that have not yet been moved.
// Each row must be manually approved (Approved = "yes") before moves run.
function buildManualApplyQueue() {
  const batchId    = getCurrentBatchId();
  const queueSheet = getSheet(TABS.MANUAL_APPLY_QUEUE);

  // Find already-queued artifact IDs to avoid duplicates
  const queuedRows = getSheetRows(TABS.MANUAL_APPLY_QUEUE);
  const queuedIds  = new Set(queuedRows.map(r => String(r['Artifact_ID']).trim()));

  // Source: Artifact_Journal_Ledger rows with status "Assigned" for this batch
  const ledgerRows = getSheetRows(TABS.ARTIFACT_JOURNAL_LEDGER)
                       .filter(r =>
                         String(r['Batch_ID']) === batchId &&
                         String(r['Status']).trim() === 'Assigned'
                       );

  // Cross-reference intake log for file IDs and route paths
  const intakeRows = getSheetRows(TABS.ARTIFACT_INTAKE_LOG)
                       .filter(r => String(r['Batch_ID']) === batchId);
  const intakeMap  = {};
  intakeRows.forEach(r => { intakeMap[String(r['Artifact_ID']).trim()] = r; });

  let added   = 0;
  let skipped = 0;
  let rowSeq  = queuedRows.length;

  ledgerRows.forEach(ledger => {
    const artifactId = String(ledger['Artifact_ID']).trim();

    if (queuedIds.has(artifactId)) {
      skipped++;
      return;
    }

    const intake = intakeMap[artifactId];
    if (!intake) {
      logCorrection(artifactId, 'QUEUE_BUILD', 'No intake row found for ' + artifactId);
      skipped++;
      return;
    }

    const routePath   = String(intake['Route_Path'] || '').trim();
    const destFolderId= resolveFolderIdForRoute(routePath) || '(UNMAPPED)';
    rowSeq++;
    const queueRowId  = 'QR-' + String(rowSeq).padStart(4, '0');

    queueSheet.appendRow([
      queueRowId,
      artifactId,
      String(intake['Filename'] || ''),
      String(intake['Drive_Link'] || ''),
      String(intake['File_ID'] || ''),
      destFolderId,
      routePath,
      'Pending',
      '',        // Approved — operator fills in "yes"
      '',        // Approved_By
      batchId,
      new Date(),
    ]);

    added++;
  });

  const msg =
    'Manual Apply Queue built.\n' +
    'Rows added: ' + added + '  Already queued (skipped): ' + skipped + '\n\n' +
    'Next: Open Manual_Apply_Queue tab, review each row, set Approved = "yes" for rows to move.';
  Logger.log(msg);
  SpreadsheetApp.getUi().alert(msg);
}

// ── DRY RUN APPROVED MOVES ───────────────────────────────────────────────────
// Previews which approved queue rows would be moved, without touching Drive.
function dryRunApplyApprovedMoves() {
  const batchId    = getCurrentBatchId();
  const queueRows  = getSheetRows(TABS.MANUAL_APPLY_QUEUE)
                       .filter(r =>
                         String(r['Batch_ID']) === batchId &&
                         String(r['Approved']).trim().toLowerCase() === 'yes' &&
                         String(r['Status']).trim() === 'Pending'
                       );

  const lines = [
    'DRY RUN — Phase 5 Apply Approved Moves',
    'Batch: ' + batchId,
    'Approved-pending rows: ' + queueRows.length,
    '',
  ];

  queueRows.forEach(r => {
    const destId = String(r['Dest_Folder_ID']).trim();
    const warn   = destId === '(UNMAPPED)' ? ' ⚠ UNMAPPED DEST' : '';
    lines.push('[WOULD MOVE] ' + r['Filename']);
    lines.push('  File ID    : ' + r['Source_File_ID']);
    lines.push('  Dest Folder: ' + destId + warn);
    lines.push('  Route Path : ' + r['Dest_Path']);
  });

  if (queueRows.length === 0) lines.push('(no approved-pending rows found for this batch)');

  const msg = lines.join('\n');
  Logger.log(msg);
  SpreadsheetApp.getUi().alert(msg);
}

// ── RUN APPROVED MOVES ────────────────────────────────────────────────────────
// Moves files in Drive for all approved queue rows. Updates queue and route log.
function runApplyApprovedMoves() {
  assertPhase5Gate();

  const batchId    = getCurrentBatchId();
  const token      = getConfigValue('Apply_Approval_Token');
  const queueSheet = getSheet(TABS.MANUAL_APPLY_QUEUE);
  const queueData  = queueSheet.getDataRange().getValues();
  const qHeaders   = queueData[0];

  const col = name => qHeaders.indexOf(name);
  const COL = {
    ARTIFACT_ID:   col('Artifact_ID'),
    FILENAME:      col('Filename'),
    SOURCE_LINK:   col('Source_Drive_Link'),
    SOURCE_ID:     col('Source_File_ID'),
    DEST_FOLDER:   col('Dest_Folder_ID'),
    DEST_PATH:     col('Dest_Path'),
    STATUS:        col('Status'),
    APPROVED:      col('Approved'),
    BATCH_ID:      col('Batch_ID'),
  };

  const routeSheet = getSheet(TABS.ARTIFACT_ROUTE_LOG);
  let moved  = 0;
  let failed = 0;

  for (let i = 1; i < queueData.length; i++) {
    const row      = queueData[i];
    const rowBatch = String(row[COL.BATCH_ID]).trim();
    const approved = String(row[COL.APPROVED]).trim().toLowerCase();
    const status   = String(row[COL.STATUS]).trim();

    if (rowBatch !== batchId || approved !== 'yes' || status !== 'Pending') continue;

    const artifactId  = String(row[COL.ARTIFACT_ID]).trim();
    const filename    = String(row[COL.FILENAME]).trim();
    const sourceFileId= String(row[COL.SOURCE_ID]).trim();
    const destFolderId= String(row[COL.DEST_FOLDER]).trim();
    const routePath   = String(row[COL.DEST_PATH]).trim();

    if (!sourceFileId || destFolderId === '(UNMAPPED)') {
      const err = destFolderId === '(UNMAPPED)'
        ? 'Destination folder unmapped for route: ' + routePath
        : 'Missing Source_File_ID';
      queueSheet.getRange(i + 1, COL.STATUS + 1).setValue('Error: ' + err);
      logCorrection(artifactId, 'MOVE_ERROR', err);
      failed++;
      continue;
    }

    try {
      const file       = DriveApp.getFileById(sourceFileId);
      const sourceFolders = file.getParents();
      const destFolder = DriveApp.getFolderById(destFolderId);
      const sourceFolderId = sourceFolders.hasNext() ? sourceFolders.next().getId() : '';

      file.moveTo(destFolder);

      // Update queue row status
      queueSheet.getRange(i + 1, COL.STATUS + 1).setValue('Moved');

      // Artifact_Route_Log
      routeSheet.appendRow([
        artifactId, filename, routePath,
        sourceFolderId, destFolderId,
        'Moved', new Date(), batchId, 'token:' + token,
      ]);

      Logger.log('[MOVED] ' + filename + ' → ' + destFolderId);
      moved++;
    } catch (e) {
      const err = 'Drive error: ' + e.message;
      queueSheet.getRange(i + 1, COL.STATUS + 1).setValue('Error: ' + err);
      logCorrection(artifactId, 'MOVE_ERROR', err);
      Logger.log('[FAIL] ' + filename + ': ' + err);
      failed++;
    }
  }

  // Update Artifact_Intake_Log status for moved artifacts
  const movedIds = [];
  for (let i = 1; i < queueData.length; i++) {
    if (String(queueData[i][COL.STATUS]).trim() === 'Moved' &&
        String(queueData[i][COL.BATCH_ID]).trim() === batchId) {
      movedIds.push(String(queueData[i][COL.ARTIFACT_ID]).trim());
    }
  }
  if (movedIds.length > 0) _updateIntakeLogStatus(batchId, movedIds, 'Applied');

  const summary =
    'Phase 5 complete.\n' +
    'Moved: ' + moved + '  Failed: ' + failed + '\n' +
    'Approval token used: ' + token + '\n\n' +
    'IMPORTANT: Set Apply_Enabled = "no" and clear Apply_Approval_Token in Config now.';
  Logger.log(summary);
  SpreadsheetApp.getUi().alert(summary);
}
