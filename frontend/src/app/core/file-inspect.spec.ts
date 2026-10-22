import { describe, expect, it } from 'vitest';

import { inspectFile } from './file-inspect';

const file = (content: string, name: string) => new File([content], name);

describe('inspectFile', () => {
  it('reads CSV columns and rows, including quoted multi-line values', async () => {
    const result = await inspectFile(
      file('id;verbatim;date\n1;"ligne 1\nligne 2";x\n2;ok;y\n', 'a.csv'),
    );
    expect(result.columns).toEqual(['id', 'verbatim', 'date']);
    expect(result.rows).toBe(2);
    expect(result.textColumn).toBe('verbatim');
    expect(result.error).toBeNull();
  });

  it('accepts a table without verbatim column (detected by the server)', async () => {
    const result = await inspectFile(file('note,ce que vous pensez\n5,bien\n', 'a.csv'));
    expect(result.error).toBeNull();
    expect(result.textColumn).toBeNull();
  });

  it('counts TXT lines and JSON items', async () => {
    expect((await inspectFile(file('a\n\nb\n', 'r.txt'))).rows).toBe(2);
    expect((await inspectFile(file('{"avis": ["a", "b", "c"]}', 'r.json'))).rows).toBe(3);
  });

  it('leaves Excel, Word and PDF to the server', async () => {
    const result = await inspectFile(file('PK...', 'enquete.xlsx'));
    expect(result.error).toBeNull();
    expect(result.rows).toBeNull();
    expect(result.formatLabel).toBe('Excel');
  });

  it('refuses scripts and unknown formats', async () => {
    expect((await inspectFile(file('alert(1)', 'x.js'))).error).toContain('.js');
    expect((await inspectFile(file('x', 'x.docm'))).error).toContain('.docm');
    expect((await inspectFile(file('x', 'x.odt'))).error).toContain('Format non accepté');
  });
});
