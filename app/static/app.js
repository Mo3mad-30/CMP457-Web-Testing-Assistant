// Findings page: local-only filtering, selection, and screenshot highlighting.
(() => {
  const page = document.querySelector('.findings');
  if (!page) return;
  const rows = [...document.querySelectorAll('.element-row')];
  const type = document.getElementById('element-type');
  const search = document.getElementById('element-search');
  const hideLinks = document.getElementById('hide-links');
  const uniqueOnly = document.getElementById('unique-only');
  const count = document.getElementById('visible-count');
  const selected = document.getElementById('selected-count');
  const screenshot = document.getElementById('inspection-screenshot');
  const boxes = document.getElementById('screenshot-boxes');
  const stage = document.getElementById('screenshot-stage');
  let activeId = null;

  function updateSelected() {
    const number = rows.filter(row => row.querySelector('input[type=checkbox]').checked).length;
    selected.textContent = `${number} element${number === 1 ? '' : 's'} selected`;
  }

  function applyFilters() {
    let visible = 0;
    for (const row of rows) {
      const matches = (!type.value || row.dataset.tag === type.value) &&
        row.dataset.search.includes(search.value.toLowerCase().trim()) &&
        (!hideLinks.checked || (row.dataset.tag !== 'a' && row.dataset.role !== 'link')) &&
        (!uniqueOnly.checked || row.dataset.unique === 'true');
      row.hidden = !matches;
      const candidate = document.querySelector(`.candidate-row[data-parent="${row.dataset.elementId}"]`);
      if (candidate) candidate.hidden = !matches;
      const box = boxes?.querySelector(`[data-element-id="${row.dataset.elementId}"]`);
      if (box) box.hidden = !matches;
      if (matches) visible++;
    }
    count.textContent = `${visible} of ${rows.length} shown`;
    document.getElementById('no-filter-results').hidden = visible !== 0;
  }

  function focusElement(id, scrollToRow = true) {
    const row = rows.find(item => item.dataset.elementId === id);
    if (!row) return;
    activeId = id;
    rows.forEach(item => item.classList.toggle('highlighted', item === row));
    boxes?.querySelectorAll('.element-box').forEach(box => box.classList.toggle('highlighted', box.dataset.elementId === id));
    if (scrollToRow) {
      // References can point to filtered-out rows; reveal before scrolling.
      if (row.hidden) { type.value = ''; search.value = ''; hideLinks.checked = false; uniqueOnly.checked = false; applyFilters(); }
      row.scrollIntoView({behavior: 'smooth', block: 'center'});
    } else {
      document.getElementById('screenshot-stage')?.scrollIntoView({behavior: 'smooth', block: 'nearest'});
    }
  }

  function buildBoxes() {
    if (!screenshot || !boxes || !stage) return;
    if (!screenshot.naturalWidth || !screenshot.naturalHeight) return;
    stage.style.width = `${screenshot.naturalWidth}px`;
    boxes.replaceChildren();
    for (const row of rows) {
      let rect;
      try { rect = JSON.parse(row.dataset.box); } catch { continue; }
      if (!rect || !Number.isFinite(rect.x) || !Number.isFinite(rect.y) || rect.width <= 0 || rect.height <= 0) continue;
      const box = document.createElement('button');
      box.type = 'button';
      box.className = 'element-box';
      box.dataset.elementId = row.dataset.elementId;
      box.setAttribute('aria-label', `Highlight ${row.dataset.elementId}`);
      box.title = row.dataset.elementId;
      Object.assign(box.style, {left:`${100 * rect.x / screenshot.naturalWidth}%`, top:`${100 * rect.y / screenshot.naturalHeight}%`, width:`${100 * rect.width / screenshot.naturalWidth}%`, height:`${100 * rect.height / screenshot.naturalHeight}%`});
      box.addEventListener('click', () => focusElement(row.dataset.elementId));
      box.hidden = row.hidden;
      boxes.appendChild(box);
    }
    if (activeId) focusElement(activeId, false);
  }

  [type, search, hideLinks, uniqueOnly].forEach(control => control.addEventListener('input', applyFilters));
  rows.forEach(row => {
    row.addEventListener('click', event => {
      if (event.target.closest('input, a, button, details, summary')) return;
      focusElement(row.dataset.elementId, false);
    });
    row.addEventListener('keydown', event => {if (event.key === 'Enter' && event.target === row) focusElement(row.dataset.elementId, false);});
    row.querySelector('input[type=checkbox]').addEventListener('change', updateSelected);
  });
  document.querySelectorAll('[data-target]').forEach(button => button.addEventListener('click', () => focusElement(button.dataset.target)));
  screenshot?.addEventListener('load', buildBoxes);
  screenshot?.addEventListener('error', () => {
    const container = document.querySelector('.screenshot-scroll');
    if (container) { const fallback = document.createElement('p'); fallback.className = 'empty-screenshot'; fallback.textContent = 'Screenshot unavailable. Element details remain accessible below.'; container.replaceChildren(fallback); }
  });
  if (screenshot?.complete && screenshot.naturalWidth) buildBoxes();

  const form = document.getElementById('selection-form');
  form.addEventListener('submit', event => {
    const checked = rows.filter(row => row.querySelector('input[type=checkbox]').checked).length;
    const words = document.getElementById('goal').value.trim().split(/\s+/).filter(Boolean);
    const feedback = document.getElementById('selection-feedback');
    feedback.textContent = checked < 1 ? 'Select at least one element.' : words.length < 3 ? 'Write a testing goal of at least three words.' : '';
    if (feedback.textContent) { event.preventDefault(); feedback.focus(); }
  });
  updateSelected();
  applyFilters();
})();
