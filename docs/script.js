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
    document.getElementById('date-range').textContent = 'Veri şu anda kullanılamıyor';
    document.getElementById('aum-list').innerHTML =
      '<li class="error">Fon verileri yüklenemedi. Lütfen daha sonra tekrar deneyin.</li>';
    console.error(err);
  }
}

function renderPage(data) {
  document.getElementById('date-range').textContent =
    `${data.compared_to} → ${data.date}`;

  // AUM section: sorted by absolute TL change (already sorted server-side),
  // bar length driven by percentage change relative to the max in this list
  const aumItems = data.top_aum_increases;
  const maxPct = Math.max(...aumItems.map(i => Math.abs(i.change_pct || 0)), 1);

  const aumList = document.getElementById('aum-list');
  aumList.innerHTML = aumItems.map(item => {
    const barWidth = Math.min(100, (Math.abs(item.change_pct || 0) / maxPct) * 100);
    return `
      <li class="mover-item">
        <div class="mover-top-row">
          <span class="mover-name">
            <span class="mover-title">${item.code} (${item.title})</span>
          </span>
          <span class="mover-main-number">+${trNumber(item.change_M, 1)}M ₺</span>
        </div>
        <div class="bar-track">
          <div class="bar-fill" style="width: ${barWidth}%"></div>
        </div>
        <div class="mover-detail">
          Toplam: ${trNumber(item.aum_now_M, 1)}M ₺ · Değişim: ${trPercent(item.change_pct || 0)} · Yatırımcı: ${trNumber(item.investors_now || 0)} (${trSignedInt(item.investors_change || 0)})
        </div>
      </li>
    `;
  }).join('');
}

loadData();
