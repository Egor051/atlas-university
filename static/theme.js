/* Apply the browser's appearance before the first paint, including the sign-in screen. */
(() => {
  'use strict';
  const storageKey = 'atlas.theme';
  const system = matchMedia('(prefers-color-scheme: dark)');
  const colorScheme = document.querySelector('meta[name="color-scheme"]');
  const themeColor = document.querySelector('meta[name="theme-color"]');
  const normalize = value => value === 'light' || value === 'dark' ? value : 'system';
  let mode = 'system';

  function readMode() {
    try { return normalize(localStorage.getItem(storageKey)); }
    catch { return mode; }
  }

  function apply() {
    const dark = mode === 'dark' || (mode === 'system' && system.matches);
    document.documentElement.dataset.theme = mode;
    colorScheme.content = mode === 'system' ? 'light dark' : mode;
    themeColor.content = dark ? '#151420' : '#f5f6fa';
  }

  function sync(value) {
    mode = normalize(value);
    apply();
    for (const choice of document.querySelectorAll('[data-theme-choice]')) {
      choice.checked = choice.value === mode;
    }
  }

  mode = readMode();
  apply();
  if (system.addEventListener) system.addEventListener('change', apply);
  else system.addListener(apply);
  window.addEventListener('storage', event => {
    if (event.storageArea === localStorage && (event.key === storageKey || event.key === null)) sync(event.newValue);
  });
  window.addEventListener('pageshow', event => {
    if (event.persisted) sync(readMode());
  });
  document.addEventListener('change', event => {
    if (!event.target.matches('[data-theme-choice]')) return;
    mode = normalize(event.target.value);
    apply();
    try { localStorage.setItem(storageKey, mode); }
    catch { /* The choice still applies for the current page. */ }
  });
  window.ATLASTheme = { get mode() { return mode; } };
})();
