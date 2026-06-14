// Phase_6_Routing.gs
// Builds the specialist queue register, refreshes the routing dashboard,
// and validates that all routes are mapped and counts are consistent.

// ── BUILD SPECIALIST QUEUE REGISTER ──────────────────────────────────────────
// Creates one row per artifact in Specialist_Queue_Register for artifacts
// that have been moved (status "Applied") and not yet queued for specialists.
function buildSpecialistQueueRegister() {
  const batchId    = getCurrentBatchId();
  const sqrSheet   = getSheet(TABS.SPECIALIST_QUEUE_REGISTER);

  // Existing queue entries — avoid duplication
  const existingRows = getSheetRows(TABS.SPECIALIST_QUEUE_REGISTER);
  const queuedIds    = new Set(existingRows.map(r => String(r['Artifact_ID']).trim()));

  // Source: Applied rows in Artifact_Route_Log for this batch
  const routeRows  = getSheetRows(TABS.ARTIFACT_ROUTE_LOG)
                       .filter(r =>
                         String(r['Batch_ID']) === batchId &&
                         String(r['Status']).trim() === 'Moved'
                       );

  // Cross-reference Journal_ID_Register
  const journalRows = getSheetRows(TABS.JOURNAL_ID_REGISTER)
                        .filter(r => String(r['Batch_ID']) === batchId);
  const journalMap  = {};
  journalRows.forEach(r => { journalMap[String(r['Artifact_ID']).trim()] = String(r['Journal_ID']).trim(); });

  let added   = 0;
  let skipped = 0;

  routeRows.forEach(r => {
    const artifactId = String(r['Artifact_ID']).trim();

    if (queuedIds.has(artifactId)) {
      skipped++;
      return;
    }

    const routePath     = String(r['Route_Path'] || '').trim();
    const specialistQueue = _deriveSpecialistQueue(routePath);
    const journalId     = journalMap[artifactId] || '(none)';

    sqrSheet.appendRow([
      artifactId,
      journalId,
      String(r['Filename'] || ''),
      routePath,
      specialistQueue,
      'Pending',
      batchId,
      new Date(),
    ]);

    added++;
  });

  const msg =
    'Specialist Queue Register built.\n' +
    'Rows added: ' + added + '  Already queued (skipped): ' + skipped + '\n\n' +
    'Run updateSpecialistRoutingDashboard() to refresh counts.';
  Logger.log(msg);
  SpreadsheetApp.getUi().alert(msg);
}

// ── UPDATE SPECIALIST ROUTING DASHBOARD ───────────────────────────────────────
// Recounts items per specialist queue and refreshes the dashboard tab.
function updateSpecialistRoutingDashboard() {
  const sqrRows    = getSheetRows(TABS.SPECIALIST_QUEUE_REGISTER);
  const dashSheet  = getSheet(TABS.SPECIALIST_ROUTING_DASHBOARD);

  // Aggregate counts per queue
  const counts = {}; // queueName -> { pending, inProgress, complete }
  sqrRows.forEach(r => {
    const queue  = String(r['Specialist_Queue'] || '(unassigned)').trim();
    const status = String(r['Status'] || '').trim().toLowerCase();
    if (!counts[queue]) counts[queue] = { pending: 0, inProgress: 0, complete: 0 };
    if (status === 'pending')      counts[queue].pending++;
    else if (status === 'in_progress') counts[queue].inProgress++;
    else if (status === 'complete')    counts[queue].complete++;
  });

  // Clear existing data rows (keep header)
  const lastRow = dashSheet.getLastRow();
  if (lastRow > 1) dashSheet.getRange(2, 1, lastRow - 1, 5).clearContent();

  // Write updated rows
  const now = new Date();
  Object.entries(counts).forEach(([queue, c]) => {
    dashSheet.appendRow([queue, c.pending, c.inProgress, c.complete, now]);
  });

  Logger.log('Specialist Routing Dashboard updated: ' + Object.keys(counts).length + ' queue(s).');
  SpreadsheetApp.getUi().alert(
    'Specialist Routing Dashboard refreshed.\n' +
    Object.keys(counts).length + ' queue(s) updated.'
  );
}

// ── VALIDATE SPECIALIST ROUTING DASHBOARD ─────────────────────────────────────
// Checks: all route paths are in Folder_ID_Map, dashboard totals match SQR.
function validateSpecialistRoutingDashboard() {
  const batchId  = getCurrentBatchId();
  const sqrRows  = getSheetRows(TABS.SPECIALIST_QUEUE_REGISTER)
                     .filter(r => String(r['Batch_ID']) === batchId);
  const dashRows = getSheetRows(TABS.SPECIALIST_ROUTING_DASHBOARD);
  const folderMap= getFolderIdMap();
  const issues   = [];

  // Check all route paths are mapped
  sqrRows.forEach(r => {
    const route = String(r['Route_Path'] || '').trim().toLowerCase();
    const key   = route.split('/').pop();
    if (route && !folderMap[route] && !folderMap[key]) {
      issues.push('Unmapped Route_Path: ' + route + ' (Artifact: ' + r['Artifact_ID'] + ')');
    }
    if (!r['Specialist_Queue'] || String(r['Specialist_Queue']).trim() === '') {
      issues.push('Missing Specialist_Queue for: ' + r['Artifact_ID']);
    }
  });

  // Check dashboard totals match SQR total for this batch
  const sqrTotal   = sqrRows.length;
  const dashTotal  = dashRows.reduce((sum, r) =>
    sum + (Number(r['Pending_Count']) || 0) +
    (Number(r['In_Progress_Count']) || 0) +
    (Number(r['Complete_Count']) || 0), 0
  );

  // Dashboard may include rows from other batches; only warn if it undercounts
  if (dashTotal < sqrTotal) {
    issues.push(
      'Dashboard total (' + dashTotal + ') is less than SQR rows (' + sqrTotal + '). ' +
      'Run updateSpecialistRoutingDashboard() first.'
    );
  }

  if (issues.length === 0) {
    const msg =
      'Phase 6 Validation PASSED.\n' +
      sqrRows.length + ' specialist queue row(s) validated for batch ' + batchId + '.';
    Logger.log(msg);
    SpreadsheetApp.getUi().alert(msg);
  } else {
    const msg = 'Phase 6 Validation FAILED — ' + issues.length + ' issue(s):\n\n' + issues.join('\n');
    Logger.log(msg);
    issues.forEach(iss => logCorrection('', 'ROUTING_VALIDATION', iss));
    SpreadsheetApp.getUi().alert(msg);
  }
}

// ── HELPERS ───────────────────────────────────────────────────────────────────
// Derives a specialist queue name from a route path.
// Mapping can be extended here as specialist folders are added.
function _deriveSpecialistQueue(routePath) {
  if (!routePath) return 'UNROUTED';
  const lower = routePath.toLowerCase();

  if (lower.includes('standards') || lower.includes('01_standards')) return 'STANDARDS';
  if (lower.includes('applied')   || lower.includes('03_applied'))   return 'APPLIED';
  if (lower.includes('journal')   || lower.includes('04_journal'))   return 'JOURNALS';

  // Use the first path segment as the queue name if no known match
  const firstSegment = routePath.split('/')[0].toUpperCase().replace(/\s+/g, '_');
  return firstSegment || 'GENERAL';
}
