import { describe, expect, it } from 'vitest';

import { inspectCsv } from './csv-inspect';

const csv = (content: string, name = 'enquete.csv') =>
  new File([content], name, { type: 'text/csv' });

describe('inspectCsv', () => {
  it('detects columns and counts rows, including quoted multi-line values', async () => {
    const result = await inspectCsv(csv('id;verbatim;date\n1;"ligne 1\nligne 2";x\n2;ok;y\n'));
    expect(result.columns).toEqual(['id', 'verbatim', 'date']);
    expect(result.rows).toBe(2);
    expect(result.error).toBeNull();
  });

  it('reports a missing verbatim column', async () => {
    const result = await inspectCsv(csv('reponse,note\nbien,5\n'));
    expect(result.hasVerbatim).toBe(false);
    expect(result.error).toBe('Colonne « verbatim » introuvable');
  });

  it('rejects other file types', async () => {
    const result = await inspectCsv(csv('verbatim\nx\n', 'enquete.xlsx'));
    expect(result.error).toContain('.csv');
  });
});
