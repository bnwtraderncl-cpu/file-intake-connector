// AFRD_OPS_REGISTERS.gs
// Shared configuration, constants, and utility functions for the AFRD batch system.
// All other phase scripts depend on this file.

// ── USER CONFIGURATION ────────────────────────────────────────────────────────
// Set this to the ID of your AFRD_OPS_REGISTERS Google Spreadsheet.
const SPREADSHEET_ID = 'YOUR_SPREADSHEET_ID_HERE';

// ── TAB NAMES ─────────────────────────────────────────────────────────────────
const TABS = {
  CONFIG:                      'Config',
  ARTIFACT_INTAKE_LOG:         'Artifact_Intake_Log',
  ARTIFACT_ID_REGISTER:        'Artifact_ID_Register',
  ARTIFACT_ROUTE_LOG:          'Artifact_Route_Log',
  JOURNAL_ID_REGISTER:         'Journal_ID_Register',
  ARTIFACT_JOURNAL_LEDGER:     'Artifact_Journal_Ledger',
  MANUAL_APPLY_QUEUE:          'Manual_Apply_Queue',
  SPECIALIST_QUEUE_REGISTER:   'Specialist_Queue_Register',
  SPECIALIST_ROUTING_DASHBOARD:'Specialist_Routing_Dashboard',
  APPROVAL_GATE_LOG:           'Approval_Gate_Log',
  CORRECTION_LOG:              'Correction_Log',
  FOLDER_ID_MAP:               'Folder_ID_Map',
  BATCH_CONTROL_REGISTER:      'Batch_Control_Register',
  OPERATIONS_RUN_LOG:          'Operations_Run_Log',
  RUN_RECORD_INPUT:            'Run_Record_Input',
  FILE_STATUS_DASHBOARD:       'File_Status_Dashboard',
};

// ── COLUMN HEADERS ────────────────────────────────────────────────────────────
const HEADERS = {
  CONFIG: [
    'Key', 'Value',
  ],
  ARTIFACT_INTAKE_LOG: [
    'Batch_ID', 'Timestamp', 'Artifact_ID', 'Filename', 'Drive_Link',
    'File_ID', 'Route_Path', 'Version', 'Safety_Flag', 'Status', 'Notes',
  ],
  ARTIFACT_ID_REGISTER: [
    'Artifact_ID', 'Filename', 'File_ID', 'Drive_Link',
    'Batch_ID', 'Intake_Timestamp', 'Route_Path', 'Version', 'Safety_Flag',
  ],
  ARTIFACT_ROUTE_LOG: [
    'Artifact_ID', 'Filename', 'Route_Path', 'Source_Folder_ID',
    'Dest_Folder_ID', 'Status', 'Timestamp', 'Batch_ID', 'Notes',
  ],
  JOURNAL_ID_REGISTER: [
    'Journal_ID', 'Artifact_ID', 'Filename', 'Batch_ID', 'Assigned_Timestamp',
  ],
  ARTIFACT_JOURNAL_LEDGER: [
    'Artifact_ID', 'Journal_ID', 'Filename', 'Batch_ID', 'Status', 'Timestamp',
  ],
  MANUAL_APPLY_QUEUE: [
    'Queue_Row_ID', 'Artifact_ID', 'Filename', 'Source_Drive_Link',
    'Source_File_ID', 'Dest_Folder_ID', 'Dest_Path', 'Status',
    'Approved', 'Approved_By', 'Batch_ID', 'Timestamp',
  ],
  SPECIALIST_QUEUE_REGISTER: [
    'Artifact_ID', 'Journal_ID', 'Filename', 'Route_Path',
    'Specialist_Queue', 'Status', 'Batch_ID', 'Timestamp',
  ],
  SPECIALIST_ROUTING_DASHBOARD: [
    'Queue_Name', 'Pending_Count', 'In_Progress_Count', 'Complete_Count', 'Last_Updated',
  ],
  APPROVAL_GATE_LOG: [
    'Timestamp', 'Gate_Name', 'Action', 'Token', 'Batch_ID',
  ],
  CORRECTION_LOG: [
    'Timestamp', 'Artifact_ID', 'Error_Type', 'Description',
    'Resolution_Status', 'Resolved_Timestamp', 'Batch_ID',
  ],
  FOLDER_ID_MAP: [
    'Folder_Name', 'Folder_ID', 'Parent_Folder_ID', 'Notes',
  ],
  BATCH_CONTROL_REGISTER: [
    'Batch_ID', 'Start_Timestamp', 'End_Timestamp', 'Status',
    'Baseline_Intake', 'Baseline_Journal', 'Baseline_Applied', 'Baseline_Routed',
    'Delta_Intake', 'Delta_Journal', 'Delta_Applied', 'Delta_Routed', 'Notes',
  ],
  OPERATIONS_RUN_LOG: [
    'Run_ID', 'Timestamp', 'Script_Name', 'Batch_ID',
    'Status', 'Records_Processed', 'Delta_Notes', 'Operator_Notes',
  ],
  RUN_RECORD_INPUT: [
    'Field', 'Value',
  ],
  FILE_STATUS_DASHBOARD: [
    'Artifact_ID', 'Filename', 'Journal_ID', 'Current_Status',
    'Location', 'Batch_ID', 'Last_Updated',
  ],
};

// Default Config key-value pairs written on first setup.
const DEFAULT_CONFIG = [
  ['Current_Batch_ID',                      ''],
  ['Journal_ID_Assignment_Enabled',         'no'],
  ['Journal_ID_Assignment_Approval_Token',  ''],
  ['Apply_Enabled',                         'no'],
  ['Apply_Approval_Token',                  ''],
  ['Production_Automation_Enabled',         'no'],
  ['Mode',                                  'manual_review'],
  ['INBOX_Folder_ID',                       ''],
  ['AFRD_ROOT_Folder_ID',                   ''],
  ['Applied_Folder_ID',                     ''],
  ['Journals_Folder_ID',                    ''],
];

// ── SPREADSHEET ACCESS ────────────────────────────────────────────────────────
function getSpreadsheet() {
  if (SPREADSHEET_ID === 'YOUR_SPREADSHEET_ID_HERE') {
    throw new Error(
      'AFRD: SPREADSHEET_ID is not configured.\n' +
      'Open AFRD_OPS_REGISTERS.gs and set SPREADSHEET_ID to your spreadsheet ID.'
    );
  }
  return SpreadsheetApp.openById(SPREADSHEET_ID);
}

function getSheet(tabName) {
  const sheet = getSpreadsheet().getSheetByName(tabName);
  if (!sheet) {
    throw new Error(
      'AFRD: Tab "' + tabName + '" not found.\n' +
      'Run setupSpreadsheetTabs() to create all required tabs.'
    );
  }
  return sheet;
}

// Returns all data rows (excluding header) as an array of objects keyed by header name.
function getSheetRows(tabName) {
  const sheet = getSheet(tabName);
  const values = sheet.getDataRange().getValues();
  if (values.length < 2) return [];
  const headers = values[0];
  return values.slice(1).map(row => {
    const obj = {};
    headers.forEach((h, i) => { obj[h] = row[i]; });
    return obj;
  });
}

// ── CONFIG HELPERS ─────────────────────────────────────────────────────────────
function getConfigValue(key) {
  const sheet = getSheet(TABS.CONFIG);
  const data = sheet.getDataRange().getValues();
  for (let i = 1; i < data.length; i++) {
    if (String(data[i][0]).trim() === key) return String(data[i][1]).trim();
  }
  return '';
}

function setConfigValue(key, value) {
  const sheet = getSheet(TABS.CONFIG);
  const data = sheet.getDataRange().getValues();
  for (let i = 1; i < data.length; i++) {
    if (String(data[i][0]).trim() === key) {
      sheet.getRange(i + 1, 2).setValue(value);
      return;
    }
  }
  sheet.appendRow([key, value]);
}

function getCurrentBatchId() {
  const id = getConfigValue('Current_Batch_ID');
  if (!id) throw new Error('AFRD: Current_Batch_ID is not set in the Config tab.');
  return id;
}

// ── FOLDER ID MAP ─────────────────────────────────────────────────────────────
// Returns a map of { folder_name_lowercase: folder_id } from Folder_ID_Map tab.
function getFolderIdMap() {
  const rows = getSheetRows(TABS.FOLDER_ID_MAP);
  const map = {};
  rows.forEach(r => {
    if (r['Folder_Name'] && r['Folder_ID']) {
      map[String(r['Folder_Name']).trim().toLowerCase()] = String(r['Folder_ID']).trim();
    }
  });
  return map;
}

// Resolves a route path like "03_APPLIED/science" to a Drive folder ID using
// the Folder_ID_Map and, as fallback, the AFRD_ROOT config value.
function resolveFolderIdForRoute(routePath) {
  const map = getFolderIdMap();
  const key = String(routePath).trim().toLowerCase();
  if (map[key]) return map[key];
  // Try just the last segment of the path
  const lastSegment = key.split('/').pop();
  if (map[lastSegment]) return map[lastSegment];
  return null;
}

// ── TOKEN SAFETY ──────────────────────────────────────────────────────────────
function checkTokenSafetyStatus() {
  const keys = [
    'Journal_ID_Assignment_Enabled',
    'Journal_ID_Assignment_Approval_Token',
    'Apply_Enabled',
    'Apply_Approval_Token',
    'Production_Automation_Enabled',
  ];
  const lines = keys.map(k => '  ' + k + ': [' + (getConfigValue(k) || '(empty)') + ']');
  const msg = 'AFRD Token Safety Status:\n' + lines.join('\n');
  Logger.log(msg);
  SpreadsheetApp.getUi().alert(msg);
}

// Throws if any gates are left open — called at batch start.
function assertTokenSafety() {
  const issues = [];
  if (getConfigValue('Journal_ID_Assignment_Enabled').toLowerCase() !== 'no') {
    issues.push('Journal_ID_Assignment_Enabled must be "no"');
  }
  if (getConfigValue('Journal_ID_Assignment_Approval_Token') !== '') {
    issues.push('Journal_ID_Assignment_Approval_Token must be empty');
  }
  if (getConfigValue('Apply_Enabled').toLowerCase() !== 'no') {
    issues.push('Apply_Enabled must be "no"');
  }
  if (getConfigValue('Apply_Approval_Token') !== '') {
    issues.push('Apply_Approval_Token must be empty');
  }
  if (issues.length > 0) {
    throw new Error(
      'AFRD TOKEN SAFETY FAILURE — close all gates before starting a batch:\n' +
      issues.map(i => '  • ' + i).join('\n')
    );
  }
}

// ── CORRECTION LOG ────────────────────────────────────────────────────────────
function logCorrection(artifactId, errorType, description) {
  const sheet = getSheet(TABS.CORRECTION_LOG);
  const batchId = getConfigValue('Current_Batch_ID') || '(none)';
  sheet.appendRow([new Date(), artifactId || '', errorType, description, 'Open', '', batchId]);
  Logger.log('CORRECTION: [' + errorType + '] ' + description);
}

// ── APPROVAL GATE LOG ─────────────────────────────────────────────────────────
function logGateAction(gateName, action, token) {
  const sheet = getSheet(TABS.APPROVAL_GATE_LOG);
  const batchId = getConfigValue('Current_Batch_ID') || '(none)';
  sheet.appendRow([new Date(), gateName, action, token || '', batchId]);
}

// ── SPREADSHEET SETUP ─────────────────────────────────────────────────────────
// Run once to create all required tabs and seed the Config tab with defaults.
function setupSpreadsheetTabs() {
  const ss = getSpreadsheet();
  const ui = SpreadsheetApp.getUi();

  for (const [key, tabName] of Object.entries(TABS)) {
    let sheet = ss.getSheetByName(tabName);
    if (!sheet) {
      sheet = ss.insertSheet(tabName);
      Logger.log('Created tab: ' + tabName);
    }
    const headers = HEADERS[key];
    if (headers && sheet.getLastRow() === 0) {
      sheet.appendRow(headers);
      sheet.getRange(1, 1, 1, headers.length)
           .setFontWeight('bold')
           .setBackground('#d9ead3');
    }
  }

  // Seed Config with defaults if keys don't exist yet
  for (const [key, value] of DEFAULT_CONFIG) {
    if (getConfigValue(key) === '') setConfigValue(key, value);
  }

  ui.alert(
    'AFRD Setup Complete',
    'All tabs created and Config seeded with defaults.\n\n' +
    'Next steps:\n' +
    '1. Open the Config tab\n' +
    '2. Set INBOX_Folder_ID and AFRD_ROOT_Folder_ID\n' +
    '3. Populate Folder_ID_Map with your specialist folder IDs\n' +
    '4. Set Current_Batch_ID before running any phase',
    ui.ButtonSet.OK
  );
}
