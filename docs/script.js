// Turkish number formatting: period for thousands, comma for decimals
function trNumber(n, decimals = 0) {
  return n.toLocaleString('tr-TR', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals
  });
}

function trPercent(n) {
  const sign = n >= 0 ? '+' : '';
  return `${sign}%${trNumber(n, 1)}`;
}

function trSignedInt(n) {
  const sign = n >= 0 ? '+' : '';
  return `${sign}${trNumber(n)}`;
}

async function loadData() {
  try {
    const response = await fetch('data.json?_=' + Date.now()); // cache-bust
    if (!response.ok) throw new Error('data.json bulunamadı');
    const data = await response.json();
    renderPage(data);
  } catch (err) {
    document.getElementById('aum-list').innerHTML =
      '<li class="error">Fon verileri yüklenemedi. Lütfen daha sonra tekrar deneyin.</li>';
    console.error(err);
  }
}

function renderMoverList(elementId, items, isNegative) {
  const numberClass = isNegative ? 'mover-main-number negative' : 'mover-main-number';
  const barClass = isNegative ? 'bar-fill negative' : 'bar-fill';

  document.getElementById(elementId).innerHTML = items.map(item => {
    // Bar width = the fund's own percentage change directly (capped at 100%
    // so extreme outliers don't overflow the bar) — NOT scaled relative to
    // other funds in the list. A 40% change always draws a 40%-wide bar,
    // consistent and comparable across different days.
    const barWidth = Math.min(100, Math.abs(item.change_pct || 0));
    const changeText = isNegative
      ? `${trNumber(item.change_M, 1)}M ₺`
      : `+${trNumber(item.change_M, 1)}M ₺`;
    return `
      <li class="mover-item">
        <div class="mover-top-row">
          <span class="mover-name">
            <span class="mover-title">${item.code} (${item.title})</span>
          </span>
          <span class="${numberClass}">${changeText}</span>
        </div>
        <div class="bar-track">
          <div class="${barClass}" style="width: ${barWidth}%"></div>
        </div>
        <div class="mover-detail">
          Toplam: ${trNumber(item.aum_now_M, 1)}M ₺ · Değişim: ${trPercent(item.change_pct || 0)} · Yatırımcı: ${trNumber(item.investors_now || 0)} (${trSignedInt(item.investors_change || 0)})
        </div>
      </li>
    `;
  }).join('');
}

function renderPage(data) {
  renderMoverList('aum-list', data.top_aum_increases, false);
  renderMoverList('aum-decrease-list', data.top_aum_decreases, true);
}

loadData();
