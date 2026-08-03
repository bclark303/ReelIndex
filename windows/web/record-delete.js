(() => {
  'use strict';

  const overlay = document.getElementById('overlay-root');
  if (!overlay) return;

  let selectedMovieId = null;

  function showToast(message, type = 'success') {
    const node = document.createElement('div');
    node.className = `toast ${type}`;
    node.textContent = message;
    document.body.appendChild(node);
    setTimeout(() => node.remove(), 3500);
  }

  function rememberSelectedMovie(event) {
    const target = event.target instanceof Element ? event.target.closest('[data-movie]') : null;
    if (target?.dataset.movie) selectedMovieId = target.dataset.movie;
  }

  function inferMovieId(drawer) {
    if (selectedMovieId) return selectedMovieId;
    const poster = drawer.querySelector('img.detail-poster');
    const match = poster?.getAttribute('src')?.match(/\/api\/posters\/([^?]+)/);
    if (!match) return null;
    try {
      return decodeURIComponent(match[1]);
    } catch {
      return match[1];
    }
  }

  async function responseError(response) {
    try {
      const payload = await response.json();
      return payload.detail || payload.message || response.statusText || 'Request failed';
    } catch {
      return response.statusText || 'Request failed';
    }
  }

  async function deleteInventoryRecord(button, drawer) {
    const movieId = inferMovieId(drawer);
    if (!movieId) {
      showToast('Could not determine which inventory record is open', 'error');
      return;
    }

    const title = drawer.querySelector('.detail-heading h1')?.textContent?.trim() || 'this movie';
    const confirmed = window.confirm(
      `Delete the ReelIndex inventory record for “${title}”?\n\n` +
      'Every version currently grouped into this record will be removed from the ReelIndex database and rediscovered by future scans using the current matching rules.\n\n' +
      'Movie files, sidecars, and media-server libraries will not be changed.'
    );
    if (!confirmed) return;

    button.disabled = true;
    button.textContent = 'Deleting inventory record…';
    try {
      const response = await fetch(`/api/movies/${encodeURIComponent(movieId)}`, {
        method: 'DELETE',
        headers: {Accept: 'application/json'},
        cache: 'no-store',
      });
      if (!response.ok) throw new Error(await responseError(response));
      const result = await response.json();
      const sourceCount = Array.isArray(result.source_ids) ? result.source_ids.length : 0;
      showToast(
        `${result.title || title} removed from inventory. ` +
        `Run ${sourceCount === 1 ? 'the associated source scan' : 'the associated source scans'} to rediscover it.`
      );
      overlay.innerHTML = '';
      setTimeout(() => location.reload(), 900);
    } catch (error) {
      showToast(error.message || 'Could not delete the inventory record', 'error');
      button.disabled = false;
      button.textContent = 'Delete inventory record';
    }
  }

  function enhanceDrawer(drawer) {
    if (drawer.dataset.inventoryDeleteReady === 'true') return;
    if (!drawer.querySelector('#manage-poster')) return;
    if (!inferMovieId(drawer)) return;

    drawer.dataset.inventoryDeleteReady = 'true';
    const section = document.createElement('section');
    section.className = 'detail-section inventory-record-actions';
    section.innerHTML = `
      <div class="section-heading">
        <div>
          <span class="eyebrow">Inventory repair</span>
          <h2>Record actions</h2>
        </div>
      </div>
      <p class="overview">Delete this generated ReelIndex record when unrelated movies were grouped together. All grouped versions are removed from the inventory only and can be rebuilt by the next source scans.</p>
      <button class="button danger" id="delete-inventory-record" type="button">Delete inventory record</button>
    `;

    const summary = drawer.querySelector('.detail-summary-grid');
    if (summary) summary.insertAdjacentElement('afterend', section);
    else drawer.appendChild(section);

    section.querySelector('#delete-inventory-record').onclick = event => {
      deleteInventoryRecord(event.currentTarget, drawer);
    };
  }

  document.addEventListener('click', rememberSelectedMovie, true);

  const observer = new MutationObserver(() => {
    overlay.querySelectorAll('.detail-drawer').forEach(enhanceDrawer);
  });
  observer.observe(overlay, {childList: true, subtree: true});
})();
