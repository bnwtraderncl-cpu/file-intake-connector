// Phase_3_File_Intake.gs
// Reads files from INBOX/00_New_Uploads, parses [AFRD EXPORT BLOCK] headers,
// checks for duplicates, and writes rows to Artifact_Intake_Log and
// Artifact_ID_Register without moving any files (suggest-only).

// ── EXPORT BLOCK PARSER ───────────────────────────────────────────────────────
// Parses an [AFRD EXPORT BLOCK] section from a string of file content.
// Returns an object with the parsed fields, or null if no block is found.
function parseExportBlock(text) {
  const startMarker = '[AFRD EXPORT BLOCK]';
  const endMarker   = '[/AFRD EXPORT BLOCK]';
  const start = text.indexOf(startMarker);
  const end   = text.indexOf(endMarker);
  if (start === -1 || end === -1 || end <= start) return null;

  const block = text.substring(start + startMarker.length, end);
  const result = {
    Artifact_ID:  '',
    Route_Path:   '',
    Version:      '',
    Safety_Flag:  '',
    raw:          block.trim(),
  };

  block.split('\n').forEach(line => {
    const sep = line.indexOf(':');
    if (sep === -1) return;
    const key   = line.substring(0, sep).trim();
    const value = line.substring(sep + 1).trim();
    if (key === 'Artifact_ID')  result.Artifact_ID  = value;
    if (key === 'Route_Path')   result.Route_Path   = value;
    if (key === 'Version')      result.Version      = value;
    if (key === 'Safety_Flag')  result.Safety_Flag  = value;
  });

  return result;
}

// ── GDOC-PATCH ────────────────────────────────────────────────────────────────
// Exports a Google Doc as plain text so the export block can be parsed.
// For non-Doc files (markdown, .txt) reads the blob directly.
function getFileTextContent(file) {
  const mimeType = file.getMimeType();

  if (mimeType === MimeType.GOOGLE_DOCS) {
    const exportUrl =
      'https://docs.google.com/feeds/download/documents/export/Export?id=' +
      file.getId() + '&exportFormat=txt';
    const response = UrlFetchApp.fetch(exportUrl, {
      headers: { Authorization: 'Bearer ' + ScriptApp.getOAuthToken() },
      muteHttpExceptions: true,
    });
    if (response.getResponseCode() !== 200) {
      throw new Error('GDOC-PATCH: Failed to export Google Doc "' + file.getName() + '"');
    }
    return response.getContentText();
  }

  // Plain text, markdown, or any other text-based file
  try {
    return file.getBlob().getDataAsString();
  } catch (e) {
    throw new Error('AFRD: Cannot read file "' + file.getName() + '": ' + e.message);
  }
}

// ── RERUN GUARD ───────────────────────────────────────────────────────────────
// Returns true if this file already has a row in Artifact_Intake_Log,
// matching on any of: filename, Drive link, or file ID.
function isRerunDuplicate(existingRows, filename, driveLink, fileId) {
  return existingRows.some(row =>
    (row['Filename']   && String(row['Filename']).trim()   === filename)  ||
    (row['Drive_Link'] && String(row['Drive_Link']).trim() === driveLink) ||
    (row['File_ID']    && String(row['File_ID']).trim()    === fileId)
  );
}

// ── INBOX SCANNER ─────────────────────────────────────────────────────────────
// Returns an array of candidate file records from INBOX/00_New_Uploads.
function scanInbox() {
  const inboxFolderId = getConfigValue('INBOX_Folder_ID');
  if (!inboxFolderId) throw new Error('AFRD: INBOX_Folder_ID is not set in Config.');

  const inboxFolder = DriveApp.getFolderById(inboxFolderId);
  const candidates  = [];
  const files       = inboxFolder.getFiles();

  while (files.hasNext()) {
    const file     = files.next();
    const filename = file.getName();
    const driveLink= file.getUrl();
    const fileId   = file.getId();

    let exportBlock = null;
    let parseError  = '';
    try {
      const content = getFileTextContent(file);
      exportBlock   = parseExportBlock(content);
      if (!exportBlock) parseError = 'No [AFRD EXPORT BLOCK] found';
    } catch (e) {
      parseError = e.message;
    }

    candidates.push({ file, filename, driveLink, fileId, exportBlock, parseError });
  }

  return candidates;
}

// ── DRY RUN ───────────────────────────────────────────────────────────────────
// Read-only preview: shows what would be ingested without writing anything.
function dryRunFileIntake() {
  const batchId      = getCurrentBatchId();
  const existingRows = getSheetRows(TABS.ARTIFACT_INTAKE_LOG);
  const candidates   = scanInbox();

  const lines = ['DRY RUN — Phase 3 File Intake', 'Batch: ' + batchId, ''];
  let wouldIngest = 0;
  let wouldSkip   = 0;

  candidates.forEach(c => {
    const isDupe = isRerunDuplicate(existingRows, c.filename, c.driveLink, c.fileId);

    if (isDupe) {
      lines.push('[SKIP-DUPE] ' + c.filename);
      wouldSkip++;
      return;
    }
    if (c.parseError) {
      lines.push('[SKIP-ERROR] ' + c.filename + ' — ' + c.parseError);
      wouldSkip++;
      return;
    }
    lines.push('[INGEST] ' + c.filename);
    lines.push('  Artifact_ID : ' + (c.exportBlock.Artifact_ID  || '(missing)'));
    lines.push('  Route_Path  : ' + (c.exportBlock.Route_Path   || '(missing)'));
    lines.push('  Version     : ' + (c.exportBlock.Version      || '(missing)'));
    lines.push('  Safety_Flag : ' + (c.exportBlock.Safety_Flag  || '(none)'));
    wouldIngest++;
  });

  lines.push('');
  lines.push('Summary: ' + wouldIngest + ' would be ingested, ' + wouldSkip + ' would be skipped.');
  const msg = lines.join('\n');
  Logger.log(msg);
  SpreadsheetApp.getUi().alert(msg);
}

// ── SUGGEST-ONLY RUN ──────────────────────────────────────────────────────────
// Writes register rows without moving any files.
function runFileIntakeSuggestOnly() {
  const batchId       = getCurrentBatchId();
  const existingRows  = getSheetRows(TABS.ARTIFACT_INTAKE_LOG);
  const intakeSheet   = getSheet(TABS.ARTIFACT_INTAKE_LOG);
  const registerSheet = getSheet(TABS.ARTIFACT_ID_REGISTER);
  const candidates    = scanInbox();

  let ingested = 0;
  let skipped  = 0;
  const errors = [];

  candidates.forEach(c => {
    const isDupe = isRerunDuplicate(existingRows, c.filename, c.driveLink, c.fileId);

    if (isDupe) {
      Logger.log('[SKIP-DUPE] ' + c.filename);
      skipped++;
      return;
    }
    if (c.parseError) {
      Logger.log('[SKIP-ERROR] ' + c.filename + ': ' + c.parseError);
      logCorrection('', 'PARSE_ERROR', c.filename + ': ' + c.parseError);
      errors.push(c.filename + ': ' + c.parseError);
      skipped++;
      return;
    }

    const eb        = c.exportBlock;
    const now       = new Date();
    const artifactId= eb.Artifact_ID || 'ART-pending';
    const routePath = eb.Route_Path  || '';
    const version   = eb.Version     || '';
    const safetyFlag= eb.Safety_Flag || '';

    // Artifact_Intake_Log
    intakeSheet.appendRow([
      batchId, now, artifactId, c.filename, c.driveLink,
      c.fileId, routePath, version, safetyFlag, 'Suggest', '',
    ]);

    // Artifact_ID_Register
    registerSheet.appendRow([
      artifactId, c.filename, c.fileId, c.driveLink,
      batchId, now, routePath, version, safetyFlag,
    ]);

    Logger.log('[INGESTED] ' + c.filename + ' → ' + artifactId);
    ingested++;
  });

  const summary =
    'Phase 3 Suggest-Only complete.\n' +
    'Ingested: ' + ingested + '  Skipped: ' + skipped +
    (errors.length ? '\n\nErrors:\n' + errors.join('\n') : '');
  Logger.log(summary);
  SpreadsheetApp.getUi().alert(summary);
}

// ── VALIDATE PHASE 3 ROWS ─────────────────────────────────────────────────────
// Quality check on intake rows written in this batch.
function validatePhase3IntakeRows() {
  const batchId = getCurrentBatchId();
  const rows    = getSheetRows(TABS.ARTIFACT_INTAKE_LOG)
                    .filter(r => String(r['Batch_ID']) === batchId);

  const issues   = [];
  const seen_ids = {};

  rows.forEach((r, i) => {
    const rowNum = i + 2; // 1-indexed + header
    const id     = String(r['Artifact_ID']).trim();
    const route  = String(r['Route_Path']).trim();
    const link   = String(r['Drive_Link']).trim();

    if (!id || id === 'ART-pending') {
      issues.push('Row ' + rowNum + ': Missing Artifact_ID (' + r['Filename'] + ')');
    } else if (seen_ids[id]) {
      issues.push('Row ' + rowNum + ': Duplicate Artifact_ID ' + id);
    } else {
      seen_ids[id] = true;
    }

    if (!route) {
      issues.push('Row ' + rowNum + ': Missing Route_Path (' + r['Filename'] + ')');
    }
    if (!link) {
      issues.push('Row ' + rowNum + ': Missing Drive_Link (' + r['Filename'] + ')');
    }
  });

  if (issues.length === 0) {
    const msg = 'Phase 3 Validation PASSED — ' + rows.length + ' rows OK for batch ' + batchId;
    Logger.log(msg);
    SpreadsheetApp.getUi().alert(msg);
  } else {
    const msg =
      'Phase 3 Validation FAILED — ' + issues.length + ' issue(s):\n\n' +
      issues.join('\n');
    Logger.log(msg);
    issues.forEach(iss => logCorrection('', 'VALIDATION_FAIL', iss));
    SpreadsheetApp.getUi().alert(msg);
  }
}
