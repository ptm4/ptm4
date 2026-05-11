async function checkHealth() {
  const dot = document.getElementById('healthDot');
  const uptimeEl = document.getElementById('uptimeEl');
  try {
    const res = await fetch('/api/health');
    const data = await res.json();
    dot.classList.add('health-up');
    const s = Math.floor(data.uptime);
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
    uptimeEl.textContent = `uptime ${h}h ${m}m ${sec}s`;
  } catch {
    dot.classList.add('health-down');
    uptimeEl.textContent = 'API unreachable';
  }
}

checkHealth();
