// Read-only helpers over Figma's Layers and Pages panels. (Re)installed as window.__figTree on every call.
window.__figTree = (() => {
  const panel = () => document.querySelector('[data-testid="objects-panel"]');
  const first = e => (e?.innerText || '').trim().split('\n')[0].trim();
  const scroller = () => {
    let e = panel();
    while (e && !(e.scrollHeight > e.clientHeight && /(auto|scroll)/.test(getComputedStyle(e).overflowY)))
      e = e.parentElement;
    return e;
  };
  const rowInfo = row => ({
    id: (row.querySelector('[data-testid$="-layers-panel-row"]')?.dataset.testid || '').replace('-layers-panel-row', ''),
    name: first(row),
    type: row.querySelector('[role="img"][aria-label]')?.getAttribute('aria-label') || 'Layer',
    level: Number(row.getAttribute('aria-level') || 0),
    index: Number(row.getAttribute('aria-rowindex') || 0),
    expanded: row.getAttribute('aria-expanded'),
    selected: row.getAttribute('aria-selected') === 'true',
    parent: !!row.querySelector('[data-testid="layers-panel-expand-caret"]'),
  });
  const rows = () => [...(panel()?.querySelectorAll('[role="row"]') || [])].map(rowInfo).filter(r => r.id);
  const rowEl = id => panel()?.querySelector(`[data-testid="${CSS.escape(id)}-layers-panel-row"]`)?.closest('[role="row"]');
  const center = e => {
    if (!e) return null;
    const r = e.getBoundingClientRect(), x = r.x + Math.min(r.width / 2, 120), y = r.y + r.height / 2;
    if (!r.width || !r.height || x < 0 || y < 0 || x >= innerWidth || y >= innerHeight) return null;
    const hit = document.elementFromPoint(x, y);
    return e.contains(hit) || hit?.contains(e) ? {x, y} : null;
  };
  return {
    ready: () => rows().length > 0,
    rows,
    pages: () => {
      const grid = [...document.querySelectorAll('[role="grid"][data-fpl-grid-root]')]
        .find(g => g.querySelector('button[class*="pageRowButton"]'));
      return [...(grid?.querySelectorAll('button[class*="pageRowButton"]') || [])]
        .map(b => ({name: first(b), current: b.getAttribute('aria-current') === 'page'})).filter(p => p.name);
    },
    pagePoint: name => {
      const grid = [...document.querySelectorAll('[role="grid"][data-fpl-grid-root]')]
        .find(g => g.querySelector('button[class*="pageRowButton"]'));
      const b = [...(grid?.querySelectorAll('button[class*="pageRowButton"]') || [])].find(b => first(b) === name);
      return center(b);
    },
    pageDelta: name => {
      const grid = [...document.querySelectorAll('[role="grid"][data-fpl-grid-root]')]
        .find(g => g.querySelector('button[class*="pageRowButton"]'));
      const b = [...(grid?.querySelectorAll('button[class*="pageRowButton"]') || [])].find(b => first(b) === name);
      let s = b;
      while (s && !(s.scrollHeight > s.clientHeight && /(auto|scroll)/.test(getComputedStyle(s).overflowY))) s = s.parentElement;
      if (!b || !s) return null;
      const p = s.getBoundingClientRect(), r = b.getBoundingClientRect();
      const delta = r.top < p.top ? r.top - p.top : r.bottom > p.bottom ? r.bottom - p.bottom : 0;
      return {delta, x: p.x + p.width / 2, y: p.y + p.height / 2};
    },
    row: id => { const e = rowEl(id); return e ? rowInfo(e) : null; },
    // Click point on a row's name or caret. No scrolling here: the virtual list re-lays out rows a frame
    // after a scroll, so callers scroll first (scroll.into), wait a frame, then ask for the point.
    point: (id, part) => {
      const e = rowEl(id);
      if (!e) return null;
      return center(part === 'caret' ? e.querySelector('[data-testid="layers-panel-expand-caret"]')
        : e.querySelector('[role="gridcell"]'));
    },
    // Canvas search (the Find field above Pages). Read-only: results, their pages and click points.
    search: {
      open: () => !!document.querySelector('[data-testid="canvas-search-input"]'),
      button: () => center(document.querySelector('[data-testid="canvas-search-icon-button"]')),
      input: () => center(document.querySelector('[data-testid="canvas-search-input"]')),
      busy: () => !!document.querySelector('[data-testid="canvas-search-loading-spinner"]'),
      scope: () => (document.querySelector('[data-testid="figma-design-search-scope-dropdown"]')?.innerText || '').trim(),
      scopePoint: () => center(document.querySelector('[data-testid="figma-design-search-scope-dropdown"]')),
      allPagesPoint: () => center([...document.querySelectorAll('[role="option"],[role="menuitem"],[role="menuitemradio"],[role="menuitemcheckbox"]')]
        .find(o => (o.innerText || '').trim() === 'All pages')),
      closePoint: () => center(document.querySelector('[data-testid="canvas-search-input"]')
        ?.closest('div').parentElement.querySelector('button[aria-label="Close"]')),
      // Group headers are "<page>, N result(s)"; collapsed ones render no options until opened.
      collapsedGroup: () => center([...document.querySelectorAll('[role="listbox"][aria-label="Search results"] button[aria-expanded="false"]')][0]),
      results: () => {
        const list = document.querySelector('[role="listbox"][aria-label="Search results"]');
        const out = []; let page = null;
        for (const b of list ? list.querySelectorAll('button') : []) {
          if (b.hasAttribute('aria-expanded')) { page = (b.getAttribute('aria-label') || '').replace(/, \d+ results?$/, ''); continue; }
          if (b.getAttribute('role') !== 'option') continue;
          out.push({key: b.id, page, name: first(b), type: b.querySelector('[role="img"][aria-label]')?.getAttribute('aria-label') || 'Layer'});
        }
        return out;
      },
      resultPoint: key => center(document.getElementById(key)),
    },
    // Scrolling is done with real wheel events by the caller: setting scrollTop from script leaves
    // Figma's own scroll model behind, and later clicks land on the wrong row. These only measure.
    scroll: {
      // Wheel origin inside the panel and the remaining distance in each direction.
      state: () => {
        const s = scroller();
        if (!s) return null;
        const r = s.getBoundingClientRect();
        return {x: r.x + r.width / 2, y: r.y + r.height / 2, page: Math.floor(s.clientHeight * 0.8),
          up: s.scrollTop, down: s.scrollHeight - s.clientHeight - s.scrollTop};
      },
      // Delta that brings a row to the top of the panel ('start'), or to the middle when it is outside
      // the middle 60% ('center'): rows at the panel's edges did not take clicks reliably.
      delta: (id, block) => {
        const s = scroller(), e = rowEl(id);
        if (!s || !e) return null;
        const p = s.getBoundingClientRect(), r = e.getBoundingClientRect();
        if (block === 'start') return r.top - p.top;
        const mid = r.top + r.height / 2, lo = p.top + p.height * 0.2, hi = p.bottom - p.height * 0.2;
        return mid < lo || mid > hi ? mid - (p.top + p.height / 2) : 0;
      },
    },
  };
})(), true
