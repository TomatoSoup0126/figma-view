// Deterministic read of Figma's view-only Properties panel for the current selection. No model involved.
(() => {
  const text = e => (e?.innerText || '').trim().replace(/\s+\n/g, '\n');
  const panels = [...document.querySelectorAll('[data-testid$="-inspection-panel"]')];
  if (!panels.length) return null;
  const sections = [];
  for (const panel of panels) {
    if (panel.dataset.testid === 'export-inspection-panel') continue;
    const title = text(panel.querySelector('[data-testid="inspectPanelTitle"]')).split('\n')[0] || null;
    const kind = panel.dataset.testid.replace('-inspection-panel', '');
    const rows = [...panel.querySelectorAll('[data-testid="inspectionPropertyRow"]')];
    const props = {}, items = [];
    for (const row of rows) {
      const name = text(row.querySelector('[data-testid="inspectionPropertyName"]'));
      const value = text(row.querySelector('[data-testid="inspectionPropertyValue"]'));
      if (name && value) props[name] = value;
      else if (text(row)) items.push(text(row).split('\n').filter(Boolean).join(' '));
    }
    // Sections without name/value pairs (Content, Colors swatches, Borders) keep their visible lines.
    if (!Object.keys(props).length) {
      items.length = 0;
      const lines = text(panel).split('\n').map(s => s.trim()).filter(Boolean);
      items.push(...lines.filter(l => l !== title && !['Color format', 'Hex', 'Copy'].includes(l)));
    }
    sections.push({kind, title, ...(Object.keys(props).length && {props}), ...(items.length && {items})});
  }
  const row = document.querySelector('[data-testid="objects-panel"] [role="row"][aria-selected="true"]');
  const nodeId = (row?.querySelector('[data-testid$="-layers-panel-row"]')?.dataset.testid || '').replace('-layers-panel-row', '');
  // The selection may not be revealed in the Layers panel (e.g. opened by node-id inside a collapsed
  // parent). The Properties header right before the first section also names it, with a type icon.
  const first = panels[0];
  const header = first && [...first.parentElement.children].slice(0, [...first.parentElement.children].indexOf(first))
    .reverse().find(c => c.querySelector('[role="img"][aria-label]') && c.querySelector('button'));
  return {
    node_id: nodeId || new URLSearchParams(location.search).get('node-id')?.replace('-', ':') || null,
    layer: text(row).split('\n')[0] || text(header?.querySelector('button')).split('\n')[0] || null,
    type: row?.querySelector('[role="img"][aria-label]')?.getAttribute('aria-label') ||
      header?.querySelector('[role="img"][aria-label]')?.getAttribute('aria-label') || null,
    sections: sections.filter(s => s.props || s.items || s.title),
  };
})()
