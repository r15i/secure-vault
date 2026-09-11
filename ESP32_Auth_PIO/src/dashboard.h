// The web dashboard, as one raw string literal.
//
// Every energy figure here is labelled with the power model that produced it:
// an unlabelled energy number would be meaningless, since the two models differ
// by the ratio of their power constants (spec energy-reporting: "Dashboard
// presents both models").
#pragma once

inline const char DASHBOARD_HTML[] = R"HTML(<!DOCTYPE html>
<html>
<head>
<meta charset='utf-8'>
<meta name='viewport' content='width=device-width, initial-scale=1'>
<title>IoT Auth Benchmarking</title>
<style>
body { font-family: -apple-system, sans-serif; background: #f4f7f9; color: #333; margin: 0; padding: 20px; display: flex; justify-content: center; }
.card { background: white; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.08); padding: 30px; width: 100%; max-width: 760px; }
h1 { color: #007aff; margin-top: 0; font-size: 24px; border-bottom: 2px solid #f0f0f0; padding-bottom: 10px; }
h3 { margin-top: 26px; font-size: 15px; text-transform: uppercase; letter-spacing: 0.5px; color: #64748b; }
.stat-group { margin: 16px 0; display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; }
.stat-box { background: #f8fafc; padding: 12px; border-radius: 8px; border: 1px solid #e2e8f0; }
.stat-label { font-size: 11px; color: #64748b; text-transform: uppercase; letter-spacing: 0.5px; }
.stat-value { font-size: 16px; font-weight: 600; color: #1e293b; margin-top: 4px; }
table { width: 100%; border-collapse: collapse; font-size: 13px; margin-top: 8px; }
th, td { text-align: right; padding: 7px 8px; border-bottom: 1px solid #eef2f6; }
th:first-child, td:first-child { text-align: left; }
th { color: #64748b; font-weight: 600; font-size: 11px; text-transform: uppercase; letter-spacing: 0.4px; }
td.num { font-variant-numeric: tabular-nums; }
.btn { display: inline-block; text-decoration: none; background: #007aff; color: white; padding: 10px 14px; border-radius: 8px; font-weight: 600; margin: 4px 6px 4px 0; font-size: 14px; }
.btn-sec { background: #64748b; } .btn-ecc { background: #dc2626; }
.note { background: #fffbeb; border: 1px solid #fbbf24; color: #92400e; padding: 12px; border-radius: 8px; margin-top: 16px; font-size: 12px; line-height: 1.5; }
.warn { background: #fef2f2; border-color: #f87171; color: #991b1b; }
.refresh-control { margin-top: 16px; font-size: 13px; color: #64748b; display: flex; align-items: center; gap: 8px; }
input[type=number] { width: 54px; padding: 4px; border-radius: 4px; border: 1px solid #cbd5e1; }
code { background: #f1f5f9; padding: 1px 5px; border-radius: 4px; font-size: 12px; }
.demo-container { margin-top: 10px; background: #f8fafc; padding: 15px; border-radius: 8px; border: 1px solid #e2e8f0; }
.power-row { display: flex; align-items: center; margin-bottom: 8px; }
.power-row:last-child { margin-bottom: 0; }
.power-label { width: 130px; font-size: 13px; font-weight: 600; color: #475569; }
.power-bar-wrapper { flex-grow: 1; background: #e2e8f0; height: 16px; border-radius: 8px; overflow: hidden; margin-right: 12px; }
.bar-fill { height: 100%; border-radius: 8px; transition: width 0.5s ease-in-out; }
.fill-cl { background: #64748b; }
.fill-sv { background: #007aff; }
.fill-ecc { background: #dc2626; }
.power-val { width: 85px; text-align: right; font-size: 12px; font-variant-numeric: tabular-nums; color: #64748b; }
</style>
</head>
<body>
<div class='card'>
  <h1>IoT Auth Benchmarking</h1>

  <div class='stat-group'>
    <div class='stat-box'><div class='stat-label'>WiFi RSSI</div><div id='rssi' class='stat-value'>--</div></div>
    <div class='stat-box'><div class='stat-label'>Uptime</div><div id='uptime' class='stat-value'>--</div></div>
    <div class='stat-box'><div class='stat-label'>Instr. overhead</div><div id='overhead' class='stat-value'>--</div></div>
    <div class='stat-box'><div class='stat-label'>HW accel</div><div id='hwaccel' class='stat-value'>--</div></div>
  </div>

  <h3>Measured latency and energy</h3>
  <table>
    <thead><tr>
      <th>Protocol</th><th>Cycles</th><th>Fail</th>
      <th>Crypto mean</th><th>Median</th><th>Stddev</th>
      <th>Energy / cycle<br>(paper model)</th><th>Energy / cycle<br>(device model)</th>
    </tr></thead>
    <tbody id='rows'><tr><td colspan='8'>Loading...</td></tr></tbody>
  </table>

  <h3>Ratios (invariant to the power constants)</h3>
  <table>
    <thead><tr><th>Comparison</th><th>Measured</th><th>Reference paper</th></tr></thead>
    <tbody id='ratios'><tr><td colspan='3'>Awaiting cycles...</td></tr></tbody>
  </table>

  <h3>Power Consumption Demo (Relative to ECC)</h3>
  <div class='demo-container' id='power-demo'>
    <div style='font-size:13px; color:#64748b;'>Awaiting cycles...</div>
  </div>

  <h3>Run a cycle</h3>
  <a href='/api/auth/sv/init' class='btn'>Secure Vault init</a>
  <a href='/api/auth/classical/init' class='btn btn-sec'>Classical init</a>
  <a href='/api/auth/ecc/init' class='btn btn-ecc'>ECC init</a>
  <a href='/api/benchmark?protocol=sv&k=1000' class='btn'>Batch SV x1000</a>
  <a href='/api/benchmark?protocol=classical&k=1000' class='btn btn-sec'>Batch CL x1000</a>
  <a href='/api/benchmark?protocol=ecc&k=20' class='btn btn-ecc'>Batch ECC x20</a>

  <div class='note' id='model'>Loading power model...</div>
  <div class='note warn' id='violations' style='display:none'></div>

  <div class='refresh-control'><span>Refresh every</span><input type='number' id='refreshTime' value='5' min='1'><span>seconds</span></div>
</div>

<script>
// Reference figures from Gupta & Kumaraguru, TrustCom 2018, Table 1.
const PAPER = { sv: 646.75, classical: 497.5, ecc: 109947.5 };
const LABEL = { sv: 'Secure Vault', classical: 'Classical AES-128', ecc: 'ECC (ECDSA P-256)' };

function fmt(v, digits) { return (v === undefined || v === null) ? '--' : Number(v).toFixed(digits); }

function renderRows(d) {
  const tbody = document.getElementById('rows');
  tbody.innerHTML = '';
  for (const key of ['classical', 'sv', 'ecc']) {
    const p = d.protocols[key];
    const c = p.crypto_us;
    const row = document.createElement('tr');
    row.innerHTML =
      "<td>" + LABEL[key] + "</td>" +
      "<td class='num'>" + p.count + "</td>" +
      "<td class='num'>" + p.failures + "</td>" +
      "<td class='num'>" + fmt(c.mean_us, 2) + " &micro;s</td>" +
      "<td class='num'>" + c.median_us + " &micro;s</td>" +
      "<td class='num'>" + fmt(c.stddev_us, 2) + "</td>" +
      "<td class='num'>" + fmt(p.energy.paper.per_cycle_uj, 3) + " &micro;J</td>" +
      "<td class='num'>" + fmt(p.energy.device.per_cycle_uj, 3) + " &micro;J</td>";
    tbody.appendChild(row);
  }
}

function renderRatios(d) {
  const tbody = document.getElementById('ratios');
  const m = {
    sv: d.protocols.sv.crypto_us.mean_us,
    classical: d.protocols.classical.crypto_us.mean_us,
    ecc: d.protocols.ecc.crypto_us.mean_us
  };
  const rows = [
    ['Secure Vault / Classical', m.sv / m.classical, PAPER.sv / PAPER.classical],
    ['ECC / Secure Vault', m.ecc / m.sv, PAPER.ecc / PAPER.sv],
    ['ECC / Classical', m.ecc / m.classical, PAPER.ecc / PAPER.classical]
  ];
  tbody.innerHTML = '';
  for (const [name, measured, paper] of rows) {
    const tr = document.createElement('tr');
    const shown = isFinite(measured) && measured > 0 ? fmt(measured, 2) + 'x' : '--';
    tr.innerHTML = "<td>" + name + "</td><td class='num'>" + shown +
                   "</td><td class='num'>" + fmt(paper, 2) + "x</td>";
    tbody.appendChild(tr);
  }
}

function renderPowerDemo(d) {
  const container = document.getElementById('power-demo');
  const e = {
    sv: d.protocols.sv.energy.device.per_cycle_uj,
    classical: d.protocols.classical.energy.device.per_cycle_uj,
    ecc: d.protocols.ecc.energy.device.per_cycle_uj
  };
  
  if (!isFinite(e.ecc) || e.ecc <= 0) return;
  
  // Linear scale, minimum 0.5% width so small bars are still barely visible
  const getWidth = (val) => Math.max(0.5, (val / e.ecc) * 100).toFixed(2);
  
  container.innerHTML = `
    <div class='power-row'><div class='power-label'>Classical AES</div><div class='power-bar-wrapper'><div class='bar-fill fill-cl' style='width: ${getWidth(e.classical)}%'></div></div><div class='power-val'>${fmt(e.classical, 1)} &micro;J</div></div>
    <div class='power-row'><div class='power-label'>Secure Vault</div><div class='power-bar-wrapper'><div class='bar-fill fill-sv' style='width: ${getWidth(e.sv)}%'></div></div><div class='power-val'>${fmt(e.sv, 1)} &micro;J</div></div>
    <div class='power-row'><div class='power-label'>ECC P-256</div><div class='power-bar-wrapper'><div class='bar-fill fill-ecc' style='width: ${getWidth(e.ecc)}%'></div></div><div class='power-val'>${fmt(e.ecc, 1)} &micro;J</div></div>
  `;
}

function updateStats() {
  fetch('/api/energy').then(r => r.json()).then(d => {
    document.getElementById('uptime').innerText = d.uptime_s + ' s';
    document.getElementById('rssi').innerText = d.rssi + ' dBm';
    document.getElementById('overhead').innerText = fmt(d.instrumentation.overhead_us.mean_us, 2) + ' µs';
    const hw = d.hw_accel;
    document.getElementById('hwaccel').innerText =
      'AES ' + (hw.aes ? 'HW' : 'SW') + ' / SHA ' + (hw.sha ? 'HW' : 'SW') + ' / ECC ' + (hw.ecc_p256 ? 'HW' : 'SW');

    renderRows(d);
    renderRatios(d);
    renderPowerDemo(d);

    const pm = d.power_model;
    document.getElementById('model').innerHTML =
      '<strong>Energy is derived, not measured.</strong> ' + pm.formula + '<br>' +
      '<strong>Paper model:</strong> ' + pm.paper.power_mw + ' mW (' + pm.paper.current_ma + ' mA @ ' + pm.paper.voltage_v + ' V) &mdash; ' + pm.paper.source + '<br>' +
      '<strong>Device model:</strong> ' + pm.device.power_mw + ' mW (' + pm.device.current_ma + ' mA @ ' + pm.device.voltage_v + ' V) &mdash; ' + pm.device.source + '<br>' +
      pm.note + ' Median is over the most recent ' + d.protocols.sv.crypto_us.median_window + ' samples; mean and stddev are exact over all samples.';

    const v = document.getElementById('violations');
    if (d.invariant_violations > 0) {
      v.style.display = 'block';
      v.innerHTML = '<strong>' + d.invariant_violations + ' invariant violation(s):</strong> measured crypto time exceeded handler time, which should be impossible. Treat these results as suspect.';
    } else {
      v.style.display = 'none';
    }
  });
}

let interval;
function startInterval() {
  if (interval) clearInterval(interval);
  interval = setInterval(updateStats, document.getElementById('refreshTime').value * 1000);
}
document.getElementById('refreshTime').addEventListener('change', startInterval);
startInterval();
updateStats();
</script>
</body>
</html>
)HTML";
