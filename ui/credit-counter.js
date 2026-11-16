// Share one animation clock so the credit breakdown and total rise together.
export function createCreditCounter(elements, {
  format, duration = 700, reduceMotion = () => false,
  requestFrame = callback => requestAnimationFrame(callback),
  cancelFrame = id => cancelAnimationFrame(id), now = () => performance.now(),
} = {}) {
  const keys = Object.keys(elements);
  let shown = null, target = null, from = null, frame = null, started = 0, prefix = '';
  function paint(values) {
    for (const key of keys) {
      const text = `${prefix}${format(values[key])}`;
      if (elements[key].textContent !== text) elements[key].textContent = text;
    }
  }
  function stop() {
    if (frame !== null) cancelFrame(frame);
    frame = null;
    keys.forEach(key => {delete elements[key].dataset.counting;});
  }
  function finish() {
    stop();
    if (target) {shown = {...target};paint(shown);}
  }
  function tick(time) {
    const progress = reduceMotion() ? 1 : Math.min(1, Math.max(0, (time - started) / duration));
    const eased = 1 - (1 - progress) ** 3;
    shown = Object.fromEntries(keys.map(key => [key, from[key] + (target[key] - from[key]) * eased]));
    paint(shown);
    if (progress < 1) frame = requestFrame(tick);
    else finish();
  }
  function clear({preserveValue = false} = {}) {
    stop();target = null;
    if (!preserveValue) shown = null;
    for (const key of keys) {elements[key].textContent = '—';elements[key].removeAttribute?.('title');}
  }
  function update(values, {partial = false, available = true} = {}) {
    if (!available || keys.some(key => !Number.isFinite(values[key]) || values[key] < 0)) {clear();return;}
    const nextPrefix = partial ? '≥ ' : '';
    if (target && prefix === nextPrefix && keys.every(key => target[key] === values[key])) {
      if (reduceMotion()) finish();
      return;
    }
    stop();prefix = nextPrefix;target = {...values};
    for (const key of keys) elements[key].title = `${prefix}${format(target[key])} credits`;
    from = shown ? {...shown} : Object.fromEntries(keys.map(key => [key, 0]));
    // Corrections and reduced-motion updates settle immediately, never counting
    // upward to a value that is actually lower than the previous reading.
    if (reduceMotion() || duration <= 0 || keys.some(key => target[key] < from[key])
        || keys.every(key => target[key] === from[key])) {finish();return;}
    shown = {...from};paint(shown);started = now();
    keys.forEach(key => {if (target[key] > from[key]) elements[key].dataset.counting = 'true';});
    frame = requestFrame(tick);
  }
  return {update, clear, finish, destroy: stop};
}
