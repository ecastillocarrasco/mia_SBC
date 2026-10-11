/**
 * 2D already renders Markdown tables from the backend's answer field. In 3D,
 * that same answer was treated as a plain caption whenever presentations was
 * empty. Recover only EXPLICIT tables: never invent rows or infer employees.
 */
const splitCells = (line) => String(line).trim().replace(/^\||\|$/g, '').split(/(?<!\\)\|/)
  .map((cell) => cell.replace(/\\\|/g, '|').trim());
const separator = (line) => {
  const cells=splitCells(line);
  return cells.length>=2 && cells.every((c) => /^:?-{2,}:?$/.test(c));
};

export function extractMarkdownTables(answer) {
  const lines = String(answer ?? '').replace(/\r/g, '').split('\n');
  const tables=[];
  let latestTitle='Información disponible';
  for (let i=0;i<lines.length;i++) {
    const heading=/^\s*#{1,4}\s+(.+?)\s*$/.exec(lines[i]);
    if (heading) latestTitle=heading[1].replace(/[\*`]/g,'').trim();
    if (!lines[i]?.includes('|') || !separator(lines[i+1] || '')) continue;
    const columns=splitCells(lines[i]);
    if (columns.length<2) continue;
    i++;
    const rows=[];
    while (i+1<lines.length && lines[i+1]?.includes('|') && lines[i+1]?.trim()) {
      const cells=splitCells(lines[++i]);
      if (cells.length === columns.length) rows.push(cells);
    }
    if (rows.length) tables.push({ type:'table', title:latestTitle, columns, rows });
  }
  return tables;
}

function stableTableSignature(item) {
  if (!item || !Array.isArray(item.rows)) return '';
  return JSON.stringify({columns:item.columns||[],rows:item.rows});
}

export function completePresentations(answer, original) {
  const presentations=Array.isArray(original)?[...original]:[];
  const signatures=new Set(presentations.map(stableTableSignature).filter(Boolean));
  for (const parsed of extractMarkdownTables(answer)) {
    const signature=stableTableSignature(parsed);
    if (!signatures.has(signature)) {
      presentations.push(parsed);
      signatures.add(signature);
    }
  }
  return presentations;
}
