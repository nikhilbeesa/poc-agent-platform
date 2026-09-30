'use strict';
// =====================================================================================
// export.js — client-side file export
//   1. A small ZIP writer (deflate when the browser supports CompressionStream, else store)
//   2. Markdown -> Word (.docx) conversion, so the generated artefacts can be opened, edited
//      and shared in Microsoft Word. Everything runs in the browser: no server round-trip and
//      no extra library. Mermaid diagrams are embedded as images.
// =====================================================================================

// ------------------------------------------------------------------ ZIP writer
const CRC_TABLE = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = (c & 1) ? (0xEDB88320 ^ (c >>> 1)) : (c >>> 1);
    t[n] = c >>> 0;
  }
  return t;
})();

function crc32(bytes) {
  let c = 0xFFFFFFFF;
  for (let i = 0; i < bytes.length; i++) c = CRC_TABLE[(c ^ bytes[i]) & 0xFF] ^ (c >>> 8);
  return (c ^ 0xFFFFFFFF) >>> 0;
}

async function deflateRaw(bytes) {
  if (typeof CompressionStream === 'undefined') return null;
  try {
    const stream = new Blob([bytes]).stream().pipeThrough(new CompressionStream('deflate-raw'));
    return new Uint8Array(await new Response(stream).arrayBuffer());
  } catch (e) { return null; }
}

// files: [{ name, data }] where data is a string (UTF-8) or a Uint8Array. Returns the zip as bytes.
async function zipBytes(files) {
  const enc = new TextEncoder();
  const now = new Date();
  const dosTime = (now.getHours() << 11) | (now.getMinutes() << 5) | (now.getSeconds() >> 1);
  const dosDate = ((now.getFullYear() - 1980) << 9) | ((now.getMonth() + 1) << 5) | now.getDate();
  const chunks = [], central = [];
  let offset = 0;

  for (const f of files) {
    const name = enc.encode(f.name);
    const raw = typeof f.data === 'string' ? enc.encode(f.data) : f.data;
    const crc = crc32(raw);
    let body = raw, method = 0;
    const packed = raw.length > 64 ? await deflateRaw(raw) : null;
    if (packed && packed.length < raw.length) { body = packed; method = 8; }

    const local = new DataView(new ArrayBuffer(30));
    local.setUint32(0, 0x04034b50, true); local.setUint16(4, 20, true); local.setUint16(6, 0x0800, true);
    local.setUint16(8, method, true); local.setUint16(10, dosTime, true); local.setUint16(12, dosDate, true);
    local.setUint32(14, crc, true); local.setUint32(18, body.length, true); local.setUint32(22, raw.length, true);
    local.setUint16(26, name.length, true); local.setUint16(28, 0, true);
    chunks.push(new Uint8Array(local.buffer), name, body);

    const cen = new DataView(new ArrayBuffer(46));
    cen.setUint32(0, 0x02014b50, true); cen.setUint16(4, 20, true); cen.setUint16(6, 20, true); cen.setUint16(8, 0x0800, true);
    cen.setUint16(10, method, true); cen.setUint16(12, dosTime, true); cen.setUint16(14, dosDate, true);
    cen.setUint32(16, crc, true); cen.setUint32(20, body.length, true); cen.setUint32(24, raw.length, true);
    cen.setUint16(28, name.length, true); cen.setUint32(42, offset, true);
    central.push(new Uint8Array(cen.buffer), name);

    offset += 30 + name.length + body.length;
  }

  const centralSize = central.reduce((n, c) => n + c.length, 0);
  const end = new DataView(new ArrayBuffer(22));
  end.setUint32(0, 0x06054b50, true); end.setUint16(8, files.length, true); end.setUint16(10, files.length, true);
  end.setUint32(12, centralSize, true); end.setUint32(16, offset, true);

  const parts = [...chunks, ...central, new Uint8Array(end.buffer)];
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let pos = 0;
  parts.forEach((p) => { out.set(p, pos); pos += p.length; });
  return out;
}

function downloadBlob(filename, blob) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = filename;
  document.body.appendChild(a); a.click(); document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

const DOCX_MIME = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';

// ------------------------------------------------------------------ Mermaid -> PNG
// Diagrams are rendered a second time off-screen with plain SVG text labels (HTML labels would
// stop the browser rasterising them), passed through the same connector routing as on screen,
// then drawn onto a canvas. Returns null when anything fails — the caller then falls back to
// putting the diagram source in the document, so an export never fails because of a diagram.
async function mermaidToPng(source, index) {
  if (!window.mermaid) return null;
  const host = document.createElement('div');
  host.style.cssText = 'position:fixed;left:-20000px;top:0;width:1600px;visibility:hidden;pointer-events:none;';
  document.body.appendChild(host);
  try {
    const init = '%%{init: {"htmlLabels": false, "flowchart": {"htmlLabels": false}, ' +
                 '"themeVariables": {"fontFamily": "Arial, Helvetica, sans-serif"}}}%%\n';
    const { svg } = await window.mermaid.render(`docx-diagram-${Date.now()}-${index}`, init + source);
    host.innerHTML = svg;
    const el = host.querySelector('svg');
    if (!el) return null;
    if (typeof routeFlowchart === 'function') routeFlowchart(el);

    const vb = el.viewBox && el.viewBox.baseVal;
    let W = vb && vb.width, H = vb && vb.height;
    if (!W || !H) { const bb = el.getBBox(); W = bb.width + 24; H = bb.height + 24; }
    el.setAttribute('width', W); el.setAttribute('height', H);
    el.removeAttribute('style');
    el.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
    const xml = new XMLSerializer().serializeToString(el);

    const scale = Math.max(1, Math.min(2, 4000 / W, 9000 / H));
    const canvas = document.createElement('canvas');
    canvas.width = Math.round(W * scale); canvas.height = Math.round(H * scale);
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#ffffff'; ctx.fillRect(0, 0, canvas.width, canvas.height);
    const img = new Image();
    await new Promise((resolve, reject) => {
      img.onload = resolve; img.onerror = () => reject(new Error('diagram image failed to load'));
      img.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(xml);
    });
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/png'));
    if (!blob) return null;                       // tainted canvas
    return { data: new Uint8Array(await blob.arrayBuffer()), w: W, h: H };
  } catch (e) {
    return null;
  } finally {
    host.remove();
    document.querySelectorAll('[id^="ddocx-diagram-"]').forEach((n) => n.remove());   // mermaid's temp nodes
  }
}

// ------------------------------------------------------------------ Markdown -> DOCX
const W_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" ' +
  'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" ' +
  'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" ' +
  'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" ' +
  'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"';

const PAGE = {
  portrait: { w: 11906, h: 16838, landscape: false },   // A4
  landscape: { w: 16838, h: 11906, landscape: true },
};
const MARGIN = 1134;                                     // 2 cm
const contentWidth = (o) => PAGE[o].w - MARGIN * 2;
const WIDE_TABLE_COLS = 7;                               // tables at least this wide get a landscape page

const xmlEsc = (s) => String(s)
  .replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g, '')
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

function decodeEntities(s) {
  s = String(s == null ? '' : s);
  if (!/&(#\d+|#x[\da-f]+|[a-z]+);/i.test(s)) return s;
  const t = document.createElement('textarea');
  t.innerHTML = s;
  return t.value;
}

// ---- runs
function rPr(f) {
  let x = '';
  if (f.code) x += '<w:rFonts w:ascii="Consolas" w:hAnsi="Consolas" w:cs="Consolas"/>';
  if (f.b) x += '<w:b/><w:bCs/>';
  if (f.i) x += '<w:i/><w:iCs/>';
  if (f.strike) x += '<w:strike/>';
  if (f.link) x += '<w:color w:val="1F4E9C"/>';
  else if (f.color) x += `<w:color w:val="${f.color}"/>`;
  const sz = f.code ? (f.sz ? Math.max(14, f.sz - 1) : 19) : f.sz;
  if (sz) x += `<w:sz w:val="${sz}"/><w:szCs w:val="${sz}"/>`;
  if (f.link) x += '<w:u w:val="single"/>';
  if (f.code) x += '<w:shd w:val="clear" w:color="auto" w:fill="EEF2F6"/>';
  return x ? `<w:rPr>${x}</w:rPr>` : '';
}

function runXml(text, f) {
  if (!text) return '';
  const props = rPr(f || {});
  const lines = String(text).split('\n');
  let out = '';
  lines.forEach((line, i) => {
    if (i) out += `<w:r>${props}<w:br/></w:r>`;
    if (line) out += `<w:r>${props}<w:t xml:space="preserve">${xmlEsc(line)}</w:t></w:r>`;
  });
  return out;
}

// Inline markdown tokens -> runs. Works with the token shapes of marked 5 - 18.
function inlineXml(tokens, f) {
  let x = '';
  for (const t of tokens || []) {
    switch (t.type) {
      case 'strong': x += inlineXml(t.tokens, { ...f, b: true }); break;
      case 'em': x += inlineXml(t.tokens, { ...f, i: true }); break;
      case 'del': x += inlineXml(t.tokens, { ...f, strike: true }); break;
      case 'codespan': x += runXml(decodeEntities(t.text), { ...f, code: true }); break;
      case 'br': x += '<w:r><w:br/></w:r>'; break;
      case 'link': x += inlineXml(t.tokens && t.tokens.length ? t.tokens : [{ type: 'text', text: t.text }], { ...f, link: true }); break;
      case 'image': x += runXml(decodeEntities(t.text || ''), f); break;
      case 'html': if (/^<br\s*\/?>$/i.test((t.text || t.raw || '').trim())) x += '<w:r><w:br/></w:r>'; break;
      case 'checkbox': x += runXml(t.checked ? '\u2611 ' : '\u2610 ', f); break;
      default:
        if (t.tokens && t.tokens.length) x += inlineXml(t.tokens, f);
        else x += runXml(decodeEntities(t.text != null ? t.text : t.raw), f);
    }
  }
  return x;
}

// ---- paragraphs
function pXml(inner, o = {}) {
  let pr = '';
  if (o.style) pr += `<w:pStyle w:val="${o.style}"/>`;
  if (o.keepNext) pr += '<w:keepNext/>';
  if (o.keepLines) pr += '<w:keepLines/>';
  if (o.numId) pr += `<w:numPr><w:ilvl w:val="${o.ilvl || 0}"/><w:numId w:val="${o.numId}"/></w:numPr>`;
  if (o.border) pr += o.border;
  if (o.spacing) pr += o.spacing;
  if (o.ind) pr += o.ind;
  if (o.jc) pr += `<w:jc w:val="${o.jc}"/>`;
  return `<w:p>${pr ? `<w:pPr>${pr}</w:pPr>` : ''}${inner}</w:p>`;
}

// ---- tables
function plainText(cell) {
  if (cell == null) return '';
  if (typeof cell === 'string') return cell;
  return decodeEntities(cell.text != null ? cell.text : '').replace(/[*_`~]/g, '');
}

// Column widths (in twips) that sum to `total`: proportional to content, but never narrower than
// the longest short word in the column, so headings and IDs don't break mid-word.
function columnWidths(rows, ncols, total) {
  const avg = new Array(ncols).fill(0), minw = new Array(ncols).fill(0);
  rows.forEach((row) => {
    for (let j = 0; j < ncols; j++) {
      const txt = plainText(row[j]);
      avg[j] += Math.min(txt.length, 80);
      const longest = txt.split(/\s+/).reduce((m, w) => Math.max(m, w.length), 0);
      minw[j] = Math.max(minw[j], Math.min(longest, 14));
    }
  });
  const n = Math.max(1, rows.length);
  const weight = avg.map((a) => Math.max(6, a / n));
  const floor = minw.map((m) => m * 92 + 200);
  const floorSum = floor.reduce((a, b) => a + b, 0);
  const scaleFloor = floorSum > total ? total / floorSum : 1;
  let widths = weight.map((w) => (w / weight.reduce((a, b) => a + b, 0)) * total);
  // raise anything under its floor, taking the space from the wider columns
  for (let pass = 0; pass < 4; pass++) {
    let deficit = 0, spare = 0;
    widths.forEach((w, j) => { const fl = floor[j] * scaleFloor; if (w < fl) deficit += fl - w; else spare += w - fl; });
    if (deficit < 1 || spare < 1) break;
    const take = Math.min(1, deficit / spare);
    widths = widths.map((w, j) => { const fl = floor[j] * scaleFloor; return w < fl ? fl : w - (w - fl) * take; });
  }
  widths = widths.map((w) => Math.floor(w));
  widths[widths.length - 1] += total - widths.reduce((a, b) => a + b, 0);
  return widths;
}

function cellInline(cell, f) {
  if (cell == null) return '';
  if (typeof cell === 'string') return runXml(decodeEntities(cell), f);
  if (cell.tokens && cell.tokens.length) return inlineXml(cell.tokens, f);
  return runXml(decodeEntities(cell.text), f);
}

function tableXml(tok, totalWidth) {
  const header = tok.header || [], rows = tok.rows || [];
  const ncols = header.length || (rows[0] || []).length;
  if (!ncols) return '';
  const widths = columnWidths([header, ...rows], ncols, totalWidth);
  const align = tok.align || [];
  const border = (n) => `<w:${n} w:val="single" w:sz="4" w:space="0" w:color="BFC7D1"/>`;
  const fs = 17;                                                   // 8.5 pt table text

  const cellXml = (cell, j, isHead) => {
    const jc = align[j] && align[j] !== 'left' ? ` <w:jc w:val="${align[j]}"/>` : '';
    const inner = cellInline(cell, { sz: fs, b: isHead });
    const shade = isHead ? '<w:shd w:val="clear" w:color="auto" w:fill="DCE6F2"/>' : '';
    return `<w:tc><w:tcPr><w:tcW w:w="${widths[j]}" w:type="dxa"/>${shade}</w:tcPr>` +
      `<w:p><w:pPr><w:pStyle w:val="TableText"/>${jc.trim()}</w:pPr>${inner}</w:p></w:tc>`;
  };
  const rowXml = (cells, isHead) => {
    let tcs = '';
    for (let j = 0; j < ncols; j++) tcs += cellXml(cells[j], j, isHead);
    return `<w:tr><w:trPr><w:cantSplit/>${isHead ? '<w:tblHeader/>' : ''}</w:trPr>${tcs}</w:tr>`;
  };

  return '<w:tbl><w:tblPr>' +
    `<w:tblW w:w="${totalWidth}" w:type="dxa"/>` +
    `<w:tblBorders>${['top', 'left', 'bottom', 'right', 'insideH', 'insideV'].map(border).join('')}</w:tblBorders>` +
    '<w:tblLayout w:type="fixed"/>' +
    '<w:tblCellMar><w:top w:w="40" w:type="dxa"/><w:left w:w="80" w:type="dxa"/><w:bottom w:w="40" w:type="dxa"/><w:right w:w="80" w:type="dxa"/></w:tblCellMar>' +
    '</w:tblPr>' +
    `<w:tblGrid>${widths.map((w) => `<w:gridCol w:w="${w}"/>`).join('')}</w:tblGrid>` +
    rowXml(header, true) + rows.map((r) => rowXml(r, false)).join('') +
    '</w:tbl>' + pXml('', { spacing: '<w:spacing w:before="0" w:after="120"/>' });   // gap after the table
}

// ---- the converter
async function markdownToDocx(markdown, opts = {}) {
  const title = opts.title || 'Document';
  const onProgress = opts.onProgress || (() => {});
  const tokens = (window.marked && marked.lexer)
    ? marked.lexer(String(markdown || ''), { gfm: true, breaks: true })
    : [{ type: 'paragraph', text: String(markdown || ''), tokens: [{ type: 'text', text: String(markdown || '') }] }];

  const body = [];
  const media = [];              // { name, data }
  const nums = [];               // extra <w:num> entries for ordered lists
  let nextNumId = 2;             // 1 = shared bullet list
  let docPrId = 1;
  let orient = 'portrait';
  let hasContent = false;

  const sectPr = (o) => {
    const p = PAGE[o];
    return '<w:sectPr><w:footerReference w:type="default" r:id="rIdFooter"/>' +
      `<w:pgSz w:w="${p.w}" w:h="${p.h}"${p.landscape ? ' w:orient="landscape"' : ''}/>` +
      `<w:pgMar w:top="${MARGIN}" w:right="${MARGIN}" w:bottom="${MARGIN}" w:left="${MARGIN}" w:header="567" w:footer="567" w:gutter="0"/></w:sectPr>`;
  };
  const switchTo = (o) => {
    if (o === orient) return;
    if (hasContent) body.push(`<w:p><w:pPr>${sectPr(orient)}</w:pPr></w:p>`);   // closes the section before
    orient = o;
  };

  // Which top-level blocks should sit on a landscape page? Wide tables, plus the heading /
  // intro lines directly above them, so a heading is never stranded on the previous page.
  const wide = tokens.map((t) => t.type === 'table' && (t.header || []).length >= WIDE_TABLE_COLS);
  const land = wide.slice();
  wide.forEach((isWide, i) => {
    if (!isWide) return;
    let k = i - 1, paras = 0;
    while (k >= 0) {
      const ty = tokens[k].type;
      if (ty === 'space') { k--; continue; }
      if (ty === 'paragraph' && paras < 2) { land[k] = true; paras++; k--; continue; }
      if (ty === 'heading') { land[k] = true; }
      break;
    }
  });
  for (let i = 1; i < tokens.length - 1; i++) {                       // don't flip-flop over a tiny gap
    if (!land[i]) {
      let j = i; while (j < tokens.length && !land[j] && j - i <= 2) j++;
      let p = i - 1; while (p >= 0 && !land[p] && i - p <= 2) p--;
      if (j < tokens.length && land[j] && p >= 0 && land[p] && tokens.slice(i, j).every((t) => t.type === 'space' || t.type === 'paragraph')) {
        for (let q = i; q < j; q++) land[q] = true;
      }
    }
  }

  const imageXml = (rId, cx, cy, alt) => {
    const id = docPrId++;
    return '<w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0">' +
      `<wp:extent cx="${cx}" cy="${cy}"/><wp:docPr id="${id}" name="Diagram ${id}" descr="${xmlEsc(alt)}"/>` +
      '<wp:cNvGraphicFramePr><a:graphicFrameLocks noChangeAspect="1"/></wp:cNvGraphicFramePr>' +
      '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic>' +
      `<pic:nvPicPr><pic:cNvPr id="${id}" name="diagram${id}.png"/><pic:cNvPicPr/></pic:nvPicPr>` +
      `<pic:blipFill><a:blip r:embed="${rId}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>` +
      `<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="${cx}" cy="${cy}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>` +
      '</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r>';
  };

  const codeParagraph = (text) => pXml(runXml(text.replace(/\t/g, '    '), {}), { style: 'Code' });

  let diagramIndex = 0;
  async function diagramBlock(source) {
    diagramIndex++;
    onProgress(`Drawing diagram ${diagramIndex}…`);
    const png = await mermaidToPng(source, diagramIndex);
    if (!png) {                                                    // fall back to the source text
      return pXml(runXml('Process flow diagram (source)', { b: true }), { keepNext: true }) + codeParagraph(source);
    }
    const name = `image${media.length + 1}.png`;
    media.push({ name, data: png.data });
    const rId = `rIdImg${media.length}`;
    let cx = Math.round(png.w * 9525), cy = Math.round(png.h * 9525);         // 96 dpi pixels -> EMU
    const maxW = contentWidth(orient) * 635, maxH = 7900000;                    // page width / ~22 cm
    const k = Math.min(1, maxW / cx, maxH / cy);
    cx = Math.round(cx * k); cy = Math.round(cy * k);
    return pXml(imageXml(rId, cx, cy, 'Process flow diagram'), { jc: 'center', keepLines: true, spacing: '<w:spacing w:before="120" w:after="200"/>' });
  }

  // ---- lists
  function newOrderedNum(start) {
    const id = nextNumId++;
    nums.push(`<w:num w:numId="${id}"><w:abstractNumId w:val="1"/><w:lvlOverride w:ilvl="0"><w:startOverride w:val="${start}"/></w:lvlOverride></w:num>`);
    return id;
  }

  async function listXml(list, level) {
    const numId = list.ordered ? newOrderedNum(parseInt(list.start, 10) || 1) : 1;
    let out = '';
    for (const item of list.items || []) {
      let first = true;
      const lead = item.task ? (item.checked ? '\u2611 ' : '\u2610 ') : '';
      let hasCheckboxToken = (item.tokens || []).some((t) => t.type === 'checkbox');
      for (const t of item.tokens || []) {
        if (t.type === 'text' || t.type === 'paragraph') {
          const inner = (first && lead && !hasCheckboxToken ? runXml(lead, {}) : '') + inlineXml(t.tokens || [{ type: 'text', text: t.text }], {});
          out += first
            ? pXml(inner, { style: 'ListParagraph', numId, ilvl: Math.min(level, 8), keepLines: true })
            : pXml(inner, { style: 'ListParagraph', ind: `<w:ind w:left="${720 + level * 360}"/>` });
          first = false;
        } else if (t.type === 'list') {
          out += await listXml(t, level + 1);
        } else if (t.type === 'checkbox') {
          // newer marked versions emit the checkbox as its own token; the text token that follows carries the label
          continue;
        } else if (t.type !== 'space') {
          out += await blockXml(t);
        }
      }
    }
    return out;
  }

  // ---- blocks
  async function blockXml(t) {
    switch (t.type) {
      case 'space': return '';
      case 'heading': {
        const lvl = Math.min(Math.max(t.depth || 1, 1), 4);
        return pXml(inlineXml(t.tokens || [{ type: 'text', text: t.text }], {}), { style: `Heading${lvl}`, keepNext: true });
      }
      case 'paragraph':
        return pXml(inlineXml(t.tokens || [{ type: 'text', text: t.text }], {}));
      case 'text':
        return pXml(inlineXml(t.tokens || [{ type: 'text', text: t.text }], {}));
      case 'hr':
        return pXml('', { border: '<w:pBdr><w:bottom w:val="single" w:sz="6" w:space="1" w:color="B8C2CC"/></w:pBdr>', spacing: '<w:spacing w:before="60" w:after="120"/>' });
      case 'code': {
        if ((t.lang || '').trim().toLowerCase() === 'mermaid') return diagramBlock(t.text);
        return String(t.text || '').split('\n').map(codeParagraph).join('');
      }
      case 'blockquote': {
        let out = '';
        for (const c of t.tokens || []) {
          if (c.type === 'paragraph' || c.type === 'text') out += pXml(inlineXml(c.tokens || [{ type: 'text', text: c.text }], { i: true }), { style: 'Quote' });
          else out += await blockXml(c);
        }
        return out;
      }
      case 'list': return listXml(t, 0);
      case 'table': return tableXml(t, contentWidth(orient));
      case 'html': {
        const txt = decodeEntities(String(t.text || t.raw || '').replace(/<br\s*\/?>/gi, '\n').replace(/<[^>]+>/g, '')).trim();
        return txt ? pXml(runXml(txt, {})) : '';
      }
      default:
        return t.text ? pXml(runXml(decodeEntities(t.text), {})) : '';
    }
  }

  for (let i = 0; i < tokens.length; i++) {
    const t = tokens[i];
    if (t.type === 'space') continue;
    switchTo(land[i] ? 'landscape' : 'portrait');
    const x = await blockXml(t);
    if (x) { body.push(x); hasContent = true; }
  }
  if (!hasContent) body.push(pXml(''));

  // ---------- package parts
  const documentXml = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document ${W_NS}><w:body>${body.join('')}${sectPr(orient)}</w:body></w:document>`;

  const stylesXml = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:eastAsia="Calibri" w:cs="Calibri"/><w:sz w:val="21"/><w:szCs w:val="21"/><w:lang w:val="en-US"/></w:rPr></w:rPrDefault>
<w:pPrDefault><w:pPr><w:spacing w:after="120" w:line="264" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:keepLines/><w:pBdr><w:bottom w:val="single" w:sz="8" w:space="2" w:color="1F3864"/></w:pBdr><w:spacing w:before="360" w:after="160"/><w:outlineLvl w:val="0"/></w:pPr><w:rPr><w:b/><w:bCs/><w:color w:val="1F3864"/><w:sz w:val="36"/><w:szCs w:val="36"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:keepLines/><w:spacing w:before="300" w:after="120"/><w:outlineLvl w:val="1"/></w:pPr><w:rPr><w:b/><w:bCs/><w:color w:val="1F3864"/><w:sz w:val="28"/><w:szCs w:val="28"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading3"><w:name w:val="heading 3"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:keepLines/><w:spacing w:before="240" w:after="100"/><w:outlineLvl w:val="2"/></w:pPr><w:rPr><w:b/><w:bCs/><w:color w:val="2E5597"/><w:sz w:val="24"/><w:szCs w:val="24"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading4"><w:name w:val="heading 4"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:keepLines/><w:spacing w:before="200" w:after="80"/><w:outlineLvl w:val="3"/></w:pPr><w:rPr><w:b/><w:bCs/><w:color w:val="404040"/><w:sz w:val="22"/><w:szCs w:val="22"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="ListParagraph"><w:name w:val="List Paragraph"/><w:basedOn w:val="Normal"/><w:qFormat/><w:pPr><w:spacing w:after="60"/></w:pPr></w:style>
<w:style w:type="paragraph" w:styleId="TableText"><w:name w:val="Table Text"/><w:basedOn w:val="Normal"/><w:qFormat/><w:pPr><w:spacing w:before="0" w:after="0" w:line="240" w:lineRule="auto"/></w:pPr><w:rPr><w:sz w:val="17"/><w:szCs w:val="17"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Code"><w:name w:val="Code"/><w:basedOn w:val="Normal"/><w:qFormat/><w:pPr><w:pBdr><w:top w:val="nil"/><w:left w:val="single" w:sz="18" w:space="6" w:color="9AA7B5"/><w:bottom w:val="nil"/></w:pBdr><w:shd w:val="clear" w:color="auto" w:fill="F3F5F8"/><w:spacing w:before="0" w:after="0" w:line="240" w:lineRule="auto"/><w:ind w:left="160"/></w:pPr><w:rPr><w:rFonts w:ascii="Consolas" w:hAnsi="Consolas" w:cs="Consolas"/><w:sz w:val="18"/><w:szCs w:val="18"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Quote"><w:name w:val="Quote"/><w:basedOn w:val="Normal"/><w:qFormat/><w:pPr><w:pBdr><w:left w:val="single" w:sz="18" w:space="8" w:color="9AA7B5"/></w:pBdr><w:spacing w:before="60" w:after="120"/><w:ind w:left="360"/></w:pPr><w:rPr><w:i/><w:iCs/><w:color w:val="4A5563"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Footer"><w:name w:val="footer"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="0"/></w:pPr><w:rPr><w:color w:val="6B7785"/><w:sz w:val="17"/><w:szCs w:val="17"/></w:rPr></w:style>
</w:styles>`;

  const lvl = (i, fmt, text, font) => {
    const left = 720 + i * 360;
    return `<w:lvl w:ilvl="${i}"><w:start w:val="1"/><w:numFmt w:val="${fmt}"/><w:lvlText w:val="${text}"/><w:lvlJc w:val="left"/>` +
      `<w:pPr><w:ind w:left="${left}" w:hanging="360"/></w:pPr>${font ? `<w:rPr><w:rFonts w:ascii="${font}" w:hAnsi="${font}" w:hint="default"/></w:rPr>` : ''}</w:lvl>`;
  };
  const bulletChars = ['\u2022', '\u2013', '\u25AA'];
  const numFmts = ['decimal', 'lowerLetter', 'lowerRoman'];
  let bullets = '', decimals = '';
  for (let i = 0; i < 9; i++) {
    bullets += lvl(i, 'bullet', bulletChars[i % 3], 'Calibri');
    decimals += lvl(i, numFmts[i % 3], `%${i + 1}.`, null);
  }
  const numberingXml = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:numbering xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">` +
    `<w:abstractNum w:abstractNumId="0"><w:multiLevelType w:val="hybridMultilevel"/>${bullets}</w:abstractNum>` +
    `<w:abstractNum w:abstractNumId="1"><w:multiLevelType w:val="hybridMultilevel"/>${decimals}</w:abstractNum>` +
    `<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>${nums.join('')}</w:numbering>`;

  const fld = (code) => `<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText xml:space="preserve"> ${code} </w:instrText></w:r><w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>1</w:t></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r>`;
  const footerXml = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:ftr ${W_NS}><w:p><w:pPr><w:pStyle w:val="Footer"/><w:jc w:val="center"/></w:pPr>` +
    `<w:r><w:t xml:space="preserve">Page </w:t></w:r>${fld('PAGE')}<w:r><w:t xml:space="preserve"> of </w:t></w:r>${fld('NUMPAGES')}</w:p></w:ftr>`;

  const settingsXml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:settings xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:defaultTabStop w:val="720"/><w:compat><w:compatSetting w:name="compatibilityMode" w:uri="http://schemas.microsoft.com/office/word" w:val="15"/></w:compat></w:settings>';

  const nowIso = new Date().toISOString().replace(/\.\d+Z$/, 'Z');
  const coreXml = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">` +
    `<dc:title>${xmlEsc(title)}</dc:title><dc:creator>AI Product Specification Platform</dc:creator>` +
    `<dcterms:created xsi:type="dcterms:W3CDTF">${nowIso}</dcterms:created><dcterms:modified xsi:type="dcterms:W3CDTF">${nowIso}</dcterms:modified></cp:coreProperties>`;
  const appXml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"><Application>AI Product Specification Platform</Application></Properties>';

  const contentTypes = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">' +
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/>' +
    '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>' +
    '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>' +
    '<Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>' +
    '<Override PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/>' +
    '<Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>' +
    '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>' +
    '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/></Types>';

  const rootRels = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>' +
    '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>' +
    '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/></Relationships>';

  const R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships';
  const docRels = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
    `<Relationship Id="rIdStyles" Type="${R}/styles" Target="styles.xml"/>` +
    `<Relationship Id="rIdNumbering" Type="${R}/numbering" Target="numbering.xml"/>` +
    `<Relationship Id="rIdSettings" Type="${R}/settings" Target="settings.xml"/>` +
    `<Relationship Id="rIdFooter" Type="${R}/footer" Target="footer1.xml"/>` +
    media.map((m, i) => `<Relationship Id="rIdImg${i + 1}" Type="${R}/image" Target="media/${m.name}"/>`).join('') +
    '</Relationships>';

  onProgress('Packaging…');
  return zipBytes([
    { name: '[Content_Types].xml', data: contentTypes },
    { name: '_rels/.rels', data: rootRels },
    { name: 'word/document.xml', data: documentXml },
    { name: 'word/_rels/document.xml.rels', data: docRels },
    { name: 'word/styles.xml', data: stylesXml },
    { name: 'word/numbering.xml', data: numberingXml },
    { name: 'word/settings.xml', data: settingsXml },
    { name: 'word/footer1.xml', data: footerXml },
    { name: 'docProps/core.xml', data: coreXml },
    { name: 'docProps/app.xml', data: appXml },
    ...media.map((m) => ({ name: `word/media/${m.name}`, data: m.data })),
  ]);
}

// ------------------------------------------------------------------ public API
const MD_MIME = 'text/markdown;charset=utf-8';

// "PRD — Product Requirements" style titles -> safe file names
function safeFileName(name, fallback) {
  const s = String(name || '').replace(/[\\/:*?"<>|\u0000-\u001F]+/g, ' ').replace(/\s+/g, ' ').trim();
  return (s || fallback || 'document').slice(0, 120);
}

async function markdownToDocxBlob(markdown, opts) {
  const bytes = await markdownToDocx(markdown, opts);
  return new Blob([bytes], { type: DOCX_MIME });
}

// One artefact -> one .docx download.
async function downloadDocx(filename, markdown, opts) {
  const blob = await markdownToDocxBlob(markdown, opts);
  downloadBlob(filename, blob);
}

// All artefacts -> ONE .zip holding one .docx per artefact.
// artefacts: [{ type, title, content_markdown }]
async function downloadAllDocxZip(artefacts, zipName, onProgress) {
  const progress = onProgress || (() => {});
  const files = [];
  for (let i = 0; i < artefacts.length; i++) {
    const a = artefacts[i];
    progress(`Document ${i + 1} of ${artefacts.length}…`);
    const bytes = await markdownToDocx(a.content_markdown, {
      title: a.title || a.type,
      onProgress: (m) => progress(`Document ${i + 1} of ${artefacts.length} — ${m}`),
    });
    files.push({ name: `${safeFileName(a.type, 'document-' + (i + 1))}.docx`, data: bytes });
  }
  const zip = await zipBytes(files);
  downloadBlob(zipName, new Blob([zip], { type: 'application/zip' }));
}

// All artefacts -> ONE .zip holding the original Markdown files.
async function downloadAllMarkdownZip(artefacts, zipName) {
  const files = artefacts.map((a, i) => ({
    name: `${safeFileName(a.type, 'document-' + (i + 1))}.md`,
    data: a.content_markdown || '',
  }));
  const zip = await zipBytes(files);
  downloadBlob(zipName, new Blob([zip], { type: 'application/zip' }));
}

function downloadMarkdown(filename, content) {
  downloadBlob(filename, new Blob([content], { type: MD_MIME }));
}
