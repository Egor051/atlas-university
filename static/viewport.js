(() => {
  'use strict';

  const root = document.documentElement;
  const viewport = window.visualViewport;
  const mobile = matchMedia('(max-width: 900px) and (pointer: coarse)');
  const editor = '#login-form input, #direct-message';
  let restingHeight = innerHeight, restingWidth = innerWidth;
  let frame = 0, previousHeight, previousInset, previousField;

  function geometry() {
    const useVisual = viewport && Math.abs(viewport.scale - 1) < .02;
    return {height: Math.round(useVisual ? viewport.height : innerHeight),
      top: Math.round(useVisual ? viewport.offsetTop : 0), zoomed: viewport && !useVisual};
  }

  function update() {
    frame = 0;
    const field = document.activeElement?.matches(editor) ? document.activeElement : null;
    const {height, top, zoomed} = geometry();
    if (Math.abs(innerWidth - restingWidth) > 40) {
      restingWidth = innerWidth;
      restingHeight = innerHeight;
    }
    const covered = Math.max(0, innerHeight - height - top);
    const keyboard = mobile.matches && !zoomed &&
      (field !== null || (root.hasAttribute('data-atlas-keyboard') && document.querySelector(editor) !== null)) &&
      Math.max(innerHeight - height, restingHeight - height) > 96;
    if (!keyboard && !field && !zoomed) restingHeight = height;
    const inset = keyboard ? covered : 0;
    const visibleHeight = keyboard ? height : null;
    root.toggleAttribute('data-atlas-keyboard', keyboard);
    if (visibleHeight !== previousHeight || inset !== previousInset) {
      if (keyboard) {
        root.style.setProperty('--atlas-visible-height', `${height}px`);
        root.style.setProperty('--atlas-keyboard-inset', `${inset}px`);
      } else {
        root.style.removeProperty('--atlas-visible-height');
        root.style.removeProperty('--atlas-keyboard-inset');
      }
    }
    if (visibleHeight !== previousHeight || (keyboard && previousField !== field)) {
      document.dispatchEvent(new Event('atlas:viewport'));
    }
    previousHeight = visibleHeight;
    previousInset = inset;
    previousField = field;
  }

  function schedule() {
    if (!frame) frame = requestAnimationFrame(update);
  }

  function reveal(element, priority = element) {
    if (!root.hasAttribute('data-atlas-keyboard') || !element?.isConnected || !priority?.isConnected) return;
    const {height, top} = geometry();
    let rect = element.getBoundingClientRect();
    if (rect.height > height - 16) rect = priority.getBoundingClientRect();
    const lower = rect.bottom - (top + height - 8);
    const upper = rect.top - (top + 8);
    if (lower > 1) window.scrollBy({top: lower, behavior: 'instant'});
    else if (upper < -1) window.scrollBy({top: upper, behavior: 'instant'});
  }

  window.ATLASViewport = {reveal};
  window.addEventListener('resize', schedule);
  viewport?.addEventListener('resize', schedule);
  viewport?.addEventListener('scroll', schedule);
  document.addEventListener('focusin', schedule);
  document.addEventListener('focusout', schedule);
  schedule();
})();
