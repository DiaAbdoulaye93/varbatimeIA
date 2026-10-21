// Client-side look at a CSV before upload: columns, row count, presence of `verbatim`.
// The backend (csv_loader.py) stays the authority; this only gives early feedback.

export const MAX_UPLOAD_BYTES = 5 * 1024 * 1024;
const DELIMITERS = [',', ';', '\t'] as const;
const BOM = new RegExp('^' + String.fromCharCode(0xfeff));

export interface CsvInspection {
  filename: string;
  sizeLabel: string;
  columns: string[];
  rows: number;
  hasVerbatim: boolean;
  error: string | null;
}

function sizeLabel(bytes: number): string {
  return bytes < 1024 * 1024
    ? `${Math.max(1, Math.round(bytes / 1024))} Ko`
    : `${(bytes / (1024 * 1024)).toLocaleString('fr-FR', { maximumFractionDigits: 1 })} Mo`;
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

export async function inspectCsv(file: File): Promise<CsvInspection> {
  const base = { filename: file.name, sizeLabel: sizeLabel(file.size) };
  if (!file.name.toLowerCase().endsWith('.csv')) {
    return {
      ...base,
      columns: [],
      rows: 0,
      hasVerbatim: false,
      error: 'Le fichier doit être au format .csv.',
    };
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    return {
      ...base,
      columns: [],
      rows: 0,
      hasVerbatim: false,
      error: 'Fichier trop volumineux (5 Mo maximum).',
    };
  }
  const text = (await file.text()).replace(BOM, '');
  const firstLine = text.split('\n', 1)[0] ?? '';
  const { header, rows } = countRecordsAndHeader(text, guessDelimiter(firstLine));
  const columns = header.filter((h) => h.length > 0);
  const hasVerbatim = columns.some((c) => c.toLowerCase() === 'verbatim');
  let error: string | null = null;
  if (!text.trim()) error = 'Le fichier CSV est vide.';
  else if (!hasVerbatim) error = 'Colonne « verbatim » introuvable';
  else if (rows === 0) error = 'Le fichier ne contient aucune ligne de données.';
  return { ...base, columns, rows, hasVerbatim, error };
}
