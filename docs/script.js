async function loadData() {
  try {
    const response = await fetch('data.json?_=' + Date.now()); // cache-bust
    if (!response.ok) throw new Error('data.json not found');
    const data = await response.json();
    renderPage(data);
  } catch (err) {
    document.getElementById('date-range').textContent = 'Data unavailable';
    document.getElementById('investor-list').innerHTML =
      '<li class="error">Could not load fund data. Check back soon.</li>';
    console.error(err);
  }
}

function renderPage(data) {
  document.getElementById('date-range').textContent =
    `${data.compared_to} → ${data.date}`;

  const investorList = document.getElementById('investor-list');
  investorList.innerHTML = data.top_investor_increases
    .map(item => `
      <li class="mover-item">
        <span class="mover-name">
          <span class="mover-code">${item.code}</span>
          <span class="mover-title">${item.title}</span>
        </span>
        <span class="mover-numbers">
          <span class="mover-change">+${item.change.toLocaleString()}</span>
          <span class="mover-total">${item.investors_now.toLocaleString()} total</span>
        </span>
      </li>
    `).join('');

  const aumList = document.getElementById('aum-list');
  aumList.innerHTML = data.top_aum_increases
    .map(item => `
      <li class="mover-item">
        <span class="mover-name">
          <span class="mover-code">${item.code}</span>
          <span class="mover-title">${item.title}</span>
        </span>
        <span class="mover-numbers">
          <span class="mover-change">+${item.change_M.toLocaleString()}M ₺</span>
          <span class="mover-total">${item.aum_now_M.toLocaleString()}M ₺ total</span>
        </span>
      </li>
    `).join('');
}

loadData();
