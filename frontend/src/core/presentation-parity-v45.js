/**
 * mIA SBC V4.5 — 2D/3D presentation parity without changing the backend.
 * In 2D renderExtras() displays table-associated KPIs, charts and stats.
 * In the old 3D controller these parts were dropped for type="table".
 * Preserve all rows, all presentations, and apply the existing 20-row pager.
 */
import { renderPresentation } from './present.js';

const esc = (v) => String(v ?? '').replace(/[&<>"']/g,
  (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const palette = ['#b77a63','#62aaa9','#7183bb','#d3a36c','#8d8cba','#6fa78c'];

function asNumber(value) {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value !== 'string') return 0;
  const parsed = Number(value.replace(/\s/g, '').replace(/\.(?=\d{3}(?:\D|$))/g, '').replace(',', '.'));
  return Number.isFinite(parsed) ? parsed : 0;
}
const fmt = (v) => new Intl.NumberFormat('es-ES', { maximumFractionDigits: 1 }).format(v);

function renderKpis(kpis) {
  const data = Array.isArray(kpis) ? kpis : Object.entries(kpis || {}).map(([label,value])=>({label,value}));
  if (!data.length) return '';
  return `<div class="mia45-kpi-grid">${data.map((item)=>`<div class="mia45-kpi"><span>${esc(item?.label ?? item?.name ?? 'Dato')}</span><strong>${esc(item?.value ?? item?.total ?? '—')}</strong></div>`).join('')}</div>`;
}

function renderBar(spec) {
  const labels = Array.isArray(spec?.labels) ? spec.labels : [];
  const vals = Array.isArray(spec?.series?.[0]?.values) ? spec.series[0].values : [];
  if (!labels.length || !vals.length) return '';
  const values = labels.map((_,i)=>asNumber(vals[i]));
  const max = Math.max(1, ...values.map(Math.abs));
  return `<div class="mia45-chart-rows">${labels.map((label,i)=>{
    const value=values[i];const width=(Math.abs(value)/max*100).toFixed(1);
    return `<div class="mia45-chart-row"><span>${esc(label)}</span><i><b style="width:${width}%"></b></i><strong>${esc(fmt(value))}</strong></div>`;
  }).join('')}</div>`;
}

function renderDonut(spec) {
  const labels = Array.isArray(spec?.labels) ? spec.labels : [];
  const vals = Array.isArray(spec?.series?.[0]?.values) ? spec.series[0].values : [];
  if (!labels.length || !vals.length) return '';
  const values = labels.map((_, i) => Math.max(0, asNumber(vals[i])));
  const sum = values.reduce((a,b)=>a+b,0);
  if (sum <= 0) return renderBar(spec);
  const circumference = 2*Math.PI*54;
  let offset = 0;
  const arcs = values.map((value,i)=>{
    const length = value/sum*circumference;
    const circle = `<circle r="54" cx="70" cy="70" fill="none" stroke-width="15" stroke="${palette[i%palette.length]}" transform="rotate(-90 70 70)" stroke-dasharray="${Math.max(0,length-1)} ${circumference}" stroke-dashoffset="${-offset.toFixed(2)}"/>`;
    offset+=length;return circle;
  }).join('');
  return `<div class="mia45-donut"><svg viewBox="0 0 140 140" aria-label="Gráfico de proporciones" role="img"><circle r="54" cx="70" cy="70" fill="none" stroke="#e9eff0" stroke-width="15"/>${arcs}<text x="70" y="76" text-anchor="middle" fill="#213848" font-size="17">${esc(fmt(sum))}</text></svg><div class="mia45-donut-legend">${labels.map((x,i)=>`<div><i style="background:${palette[i%palette.length]}"></i><span>${esc(x)}</span><strong>${esc(fmt(values[i]))}</strong></div>`).join('')}</div></div>`;
}

function renderLine(spec) {
  const labels=Array.isArray(spec?.labels)?spec.labels:[];
  const vals=Array.isArray(spec?.series?.[0]?.values)?spec.series[0].values:[];
  if (!labels.length || !vals.length) return '';
  const values=labels.map((_,i)=>asNumber(vals[i]));
  const min=Math.min(0,...values),max=Math.max(1,...values),range=Math.max(1,max-min);
  const span=values.length-1;
  const points=values.map((v,i)=>[24+(span?i*502/span:251),155-(v-min)/range*125]);
  const path=points.map(([x,y],i)=>`${i?'L':'M'}${x.toFixed(1)} ${y.toFixed(1)}`).join(' ');
  return `<div class="mia45-line-wrap"><svg viewBox="0 0 550 180" role="img" aria-label="Evolución estadística"><path d="${path}" fill="none" stroke="#56a6a4" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>${points.map(([x,y])=>`<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="3.5" fill="#b87a60"/>`).join('')}</svg><div class="mia45-line-labels">${labels.map((lab)=>`<span>${esc(lab)}</span>`).join('')}</div></div>`;
}

function renderCharts(charts) {
  if (!Array.isArray(charts)) return '';
  return charts.map((chart)=>{
    let content;
    if(chart?.type==='donut') content=renderDonut(chart);
    else if(chart?.type==='line')content=renderLine(chart);
    else content=renderBar(chart);
    if(!content)return '';
    return `<section class="mia45-chart"><h3>${esc(chart?.title || 'Visualización de datos')}</h3>${content}</section>`;
  }).join('');
}

export function render2DTableExtras(presentation) {
  if (!presentation || typeof presentation !== 'object' || presentation.type !== 'table') return '';
  return renderKpis(presentation.kpis) + renderCharts(presentation.charts) +
    (presentation.stats ? renderPresentation(presentation.stats) : '');
}

export function summarizeCoverage(presentations) {
  let totalRows=0, tables=0, dataPresentations=0;
  for (const item of presentations || []) {
    if (!item || typeof item!=='object') continue;
    dataPresentations++;
    if (Array.isArray(item.rows)) { totalRows+=item.rows.length; tables++; }
    for (const table of item.tables || []) {
      if (Array.isArray(table?.rows)) { totalRows+=table.rows.length; tables++; }
    }
  }
  return { totalRows, tables, presentations:dataPresentations };
}

export function presentationCoverageLabel(summary) {
  if (summary.totalRows>0) return `${fmt(summary.totalRows)} registros recibidos · ${summary.tables} tablas`;
  return `${summary.presentations} presentaciones recibidas`;
}
