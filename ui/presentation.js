// The host owns placement. Request its expanded side-panel view once per mount.
export function createSidePanel(app, changed) {
  let context = {}, pending = false, attempted = false, message = '';
  const state = () => ({mode: context.displayMode || 'inline', pending, message});
  async function update(next = {}) {
    context = {...context, ...next};
    if (context.displayMode === 'fullscreen') {
      attempted = true;message = '';changed(state());return;
    }
    if (!context.availableDisplayModes?.includes('fullscreen')) {
      message = Array.isArray(context.availableDisplayModes) ? 'This app does not offer an expanded panel. The monitor remains available here.' : '';
      changed(state());return;
    }
    if (attempted || pending) return;
    attempted = true;pending = true;message = '';changed(state());
    try {
      const result = await app.requestDisplayMode({mode: 'fullscreen'});
      context = {...context, displayMode: result.mode};
      message = result.mode === 'fullscreen' ? '' : 'The app kept the monitor in its current view.';
    } catch {
      message = 'The app could not open the side panel. The monitor remains available here.';
    } finally {pending = false;changed(state());}
  }
  return {update};
}
