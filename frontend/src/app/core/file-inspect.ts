// Client-side look at an uploaded file before sending it: format, size, rows and columns
// for text formats. The backend (services/file_loader.py) stays the authority: it reads
// Excel, Word and PDF and checks the real content; this only gives early feedback.

export const MAX_UPLOAD_BYTES = 5 * 1024 * 1024;
export const ACCEPTED_FORMATS = 'CSV, TSV, TXT, JSON, Excel (.xlsx), Word (.docx) ou PDF';
export const ACCEPT_ATTRIBUTE = '.csv,.tsv,.txt,.json,.xlsx,.docx,.pdf';

const FORMAT_LABELS: Record<string, string> = {
  csv: 'CSV',
  tsv: 'TSV',
  txt: 'Texte',
  json: 'JSON',
  xlsx: 'Excel',
  docx: 'Word',
  pdf: 'PDF',
};
// Same list as BLOCKED_EXTENSIONS in file_loader.py (scripts, programs, markup, macros).
const BLOCKED = new Set(
  (
    'js mjs cjs ts html htm xhtml svg xml php py rb pl sh bash bat cmd ps1 vbs vbe wsf exe dll ' +
    'msi com scr jar apk app bin iso zip rar 7z gz tar xlsm xltm docm dotm pptm hta lnk reg'
  ).split(' '),
);
// Same preferred column names as TEXT_COLUMNS in file_loader.py.
const TEXT_COLUMNS = [
  'verbatim',
  'verbatims',
  'réponse',
  'reponse',
  'réponses',
  'reponses',
  'commentaire',
  'commentaires',
  'avis',
  'remarque',
  'remarques',
  'texte',
  'text',
  'comment',
  'comments',
  'feedback',
  'answer',
  'response',
];
const DELIMITERS = [',', ';', '\t'] as const;
const BOM = new RegExp('^' + String.fromCharCode(0xfeff));

export interface FileInspection {
  filename: string;
  sizeLabel: string;
  formatLabel: string;
  /** null when the file is only read by the server (Excel, Word, PDF). */
  rows: number | null;
  columns: string[];
  /** The column that will be read, when it can be named before upload. */
  textColumn: string | null;
  error: string | null;
}

function sizeLabel(bytes: number): string {
  return bytes < 1024 * 1024
    ? `${Math.max(1, Math.round(bytes / 1024))} Ko`
    : `${(bytes / (1024 * 1024)).toLocaleString('fr-FR', { maximumFractionDigits: 1 })} Mo`;
}

function extensionOf(filename: string): string {
  const dot = filename.lastIndexOf('.');
  return dot >= 0 ? filename.slice(dot + 1).toLowerCase() : '';
}

function guessDelimiter(headerLine: string): string {
  return DELIMITERS.reduce((best, d) =>
    headerLine.split(d).length > headerLine.split(best).length ? d : best,
  );
}

/** Split the text into records, honouring double quotes (multi-line values). */
function countRecordsAndHeader(
  text: string,
  delimiter: string,
): { header: string[]; rows: number } {
  const header: string[] = [];
  let field = '';
  let inQuotes = false;
  let records = 0;
  let recordHasContent = false;
  let inHeader = true;

  const endField = () => {
    if (inHeader) header.push(field.trim());
    field = '';
  };
  const endRecord = () => {
    endField();
    if (recordHasContent && !inHeader) records += 1;
    inHeader = false;
    recordHasContent = false;
  };

  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (inQuotes) {
      if (c === '"' && text[i + 1] === '"') {
        field += '"';
        i++;
      } else if (c === '"') {
        inQuotes = false;
      } else {
        field += c;
      }
      continue;
    }
    if (c === '"') {
      inQuotes = true;
      recordHasContent = true;
    } else if (c === delimiter) {
      endField();
      recordHasContent = true;
    } else if (c === '\n') {
      endRecord();
    } else if (c !== '\r') {
      field += c;
      recordHasContent = true;
    }
  }
  if (field || recordHasContent) endRecord();
  return { header, rows: records };
}

function knownTextColumn(columns: string[]): string | null {
  const lower = columns.map((c) => c.toLowerCase());
  for (const name of TEXT_COLUMNS) {
    const i = lower.indexOf(name);
    if (i >= 0) return columns[i];
  }
  return null;
}

export async function inspectFile(file: File): Promise<FileInspection> {
  const ext = extensionOf(file.name);
  const result: FileInspection = {
    filename: file.name,
    sizeLabel: sizeLabel(file.size),
    formatLabel: FORMAT_LABELS[ext] ?? ext.toUpperCase(),
    rows: null,
    columns: [],
    textColumn: null,
    error: null,
  };
  if (BLOCKED.has(ext)) {
    return { ...result, error: `Les fichiers .${ext} ne sont pas acceptés.` };
  }
  if (!(ext in FORMAT_LABELS)) {
    return { ...result, error: `Format non accepté. Formats acceptés : ${ACCEPTED_FORMATS}.` };
  }
  if (file.size === 0) return { ...result, error: 'Le fichier est vide.' };
  if (file.size > MAX_UPLOAD_BYTES) {
    return { ...result, error: 'Fichier trop volumineux (5 Mo maximum).' };
  }
  if (ext === 'xlsx' || ext === 'docx' || ext === 'pdf') return result;

  const text = (await file.text()).replace(BOM, '');
  if (!text.trim()) return { ...result, error: 'Le fichier est vide.' };
  if (ext === 'txt') {
    return { ...result, rows: text.split('\n').filter((l) => l.trim()).length };
  }
  if (ext === 'json') {
    try {
      const payload: unknown = JSON.parse(text);
      const list = Array.isArray(payload)
        ? payload
        : Object.values(payload as Record<string, unknown>).find(Array.isArray);
      return list
        ? { ...result, rows: list.length }
        : { ...result, error: 'JSON attendu : une liste de réponses.' };
    } catch {
      return { ...result, error: 'Fichier JSON invalide.' };
    }
  }
  const firstLine = text.split('\n', 1)[0] ?? '';
  const delimiter = ext === 'tsv' ? '\t' : guessDelimiter(firstLine);
  const { header, rows } = countRecordsAndHeader(text, delimiter);
  const columns = header.filter((h) => h.length > 0);
  if (rows === 0) return { ...result, columns, error: 'Le tableau ne contient aucune ligne.' };
  return { ...result, rows, columns, textColumn: knownTextColumn(columns) };
}
