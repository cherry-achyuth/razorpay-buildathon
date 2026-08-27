/**
 * DecisionVault Buildathon Demo Frontend Application
 */

const API_BASE = '/api/v1';

let state = {
  users: [],
  merchants: [],
  policies: [],
  mandates: [],
  activeUserId: null,
  activeMerchantId: null,
  activeDecisionId: null,
  auditLogs: [],
};

// --- Initialization ---
document.addEventListener('DOMContentLoaded', async () => {
  setupTabs();
  initOnboarding();
  await loadInitialData();
  await refreshGatewayStatus();
  await refreshAuditChainStatus();

  const userSel = document.getElementById('decision-user');
  const merchSel = document.getElementById('decision-merchant');
  if (userSel) userSel.addEventListener('change', autoFillAmountFromMemory);
  if (merchSel) merchSel.addEventListener('change', autoFillAmountFromMemory);
});

function initOnboarding() {
  try {
    if (localStorage.getItem('dv_onboarding_dismissed') === '1') {
      const b = document.getElementById('onboarding-banner');
      if (b) b.style.display = 'none';
    }
  } catch (_) {}
}

window.dismissOnboarding = function () {
  const b = document.getElementById('onboarding-banner');
  if (b) b.style.display = 'none';
  try {
    localStorage.setItem('dv_onboarding_dismissed', '1');
  } catch (_) {}
};

window.fillAndRunPrompt = async function (promptText) {
  const input = document.getElementById('agent-prompt');
  if (input) input.value = promptText;
  await handleAgentEvaluate();
};

let technicalDetailsOpen = false;
window.toggleTechnicalDetails = function () {
  const sec = document.getElementById('technical-details-section');
  const icon = document.getElementById('details-toggle-icon');
  const txt = document.getElementById('details-toggle-text');
  if (!sec) return;
  technicalDetailsOpen = !technicalDetailsOpen;
  sec.style.display = technicalDetailsOpen ? 'block' : 'none';
  if (icon) icon.textContent = technicalDetailsOpen ? '🔼' : '🔍';
  if (txt) txt.textContent = technicalDetailsOpen ? 'Hide Safety Rules & History ←' : 'See Safety Rules & Memory History →';
};

function setupTabs() {
  const tabs = document.querySelectorAll('.tab-btn');
  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      tabs.forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
      
      tab.classList.add('active');
      const target = tab.dataset.tab;
      document.getElementById(`tab-${target}`).classList.add('active');

      if (target === 'memory') loadMemoryView();
      if (target === 'audit') loadAuditView();
      if (target === 'evaluation') loadEvaluationView();
    });
  });
}

// --- Data Loading ---
async function loadInitialData() {
  try {
    const [uRes, mRes] = await Promise.all([
      fetch(`${API_BASE}/users`),
      fetch(`${API_BASE}/merchants`),
    ]);

    state.users = (await uRes.json()).users || [];
    state.merchants = (await mRes.json()).merchants || [];

    populateSelect('decision-user', state.users, u => `${u.external_reference} (${u.id.slice(0, 8)})`);
    populateSelect('decision-merchant', state.merchants, m => `${m.name} (${m.id.slice(0, 8)})`);
    populateSelect('memory-user', state.users, u => `${u.external_reference}`);
    populateSelect('eval-user', state.users, u => `${u.external_reference}`);

    const hasData = state.users.length > 0 && state.merchants.length > 0;
    const warningElem = document.getElementById('empty-data-warning');
    if (warningElem) {
      warningElem.style.display = hasData ? 'none' : 'block';
    }
    const btnEval = document.getElementById('btn-evaluate');
    const btnPay = document.getElementById('btn-pay');
    if (btnEval) btnEval.disabled = !hasData;
    if (btnPay) btnPay.disabled = !hasData;

    if (state.users.length > 0) state.activeUserId = state.users[0].id;
    if (state.merchants.length > 0) state.activeMerchantId = state.merchants[0].id;

    await autoFillAmountFromMemory();
  } catch (err) {
    console.error('Failed to load initial data:', err);
  }
}

async function autoFillAmountFromMemory() {
  const userSelect = document.getElementById('decision-user');
  const merchantSelect = document.getElementById('decision-merchant');
  const amountInput = document.getElementById('decision-amount');
  const hintElem = document.getElementById('decision-amount-hint');

  const userId = userSelect?.value || state.activeUserId;
  const merchantId = merchantSelect?.value || state.activeMerchantId;

  if (!userId || !merchantId || !amountInput) return;

  try {
    const res = await fetch(`${API_BASE}/memories?user_id=${userId}&status=ACTIVE`);
    if (!res.ok) return;
    const data = await res.json();
    const memories = data.memories || [];

    const mem = memories.find(
      m => m.structured_data && String(m.structured_data.merchant_id) === String(merchantId)
    );

    if (mem && mem.structured_data && (mem.structured_data.avg_amount || mem.structured_data.amount || mem.structured_data.last_amount)) {
      const baseAmt = mem.structured_data.avg_amount || mem.structured_data.amount || mem.structured_data.last_amount;
      amountInput.value = parseFloat(baseAmt).toFixed(2);
      if (hintElem) {
        hintElem.style.display = 'none';
        hintElem.textContent = '';
      }
    } else {
      amountInput.value = '';
      if (hintElem) {
        hintElem.style.display = 'block';
        hintElem.textContent = 'No spending history found for this merchant. Enter an amount manually.';
      }
    }
  } catch (err) {
    console.error('Error auto-filling amount from memory:', err);
  }
}

function populateSelect(elemId, items, labelFn) {
  const sel = document.getElementById(elemId);
  if (!sel) return;
  sel.innerHTML = '';
  if (!items || items.length === 0) {
    const opt = document.createElement('option');
    opt.value = '';
    opt.textContent = 'No records. Click "⚡ Seed Demo Data"';
    sel.appendChild(opt);
    return;
  }
  items.forEach(item => {
    const opt = document.createElement('option');
    opt.value = item.id;
    opt.textContent = labelFn(item);
    sel.appendChild(opt);
  });
}

window.handleSeedDemo = async function () {
  try {
    const res = await fetch(`${API_BASE}/demo/seed`, { method: 'POST' });
    const data = await res.json();
    if (res.ok) {
      alert('✅ Deterministic 30-day demo data seeded successfully! All principals and baseline memories ready.');
      await loadInitialData();
      await refreshGatewayStatus();
      await refreshAuditChainStatus();
    } else {
      alert('⚠️ Demo seed issue: ' + (data.detail || 'Failed to seed'));
    }
  } catch (err) {
    alert('Failed to execute demo seed: ' + err.message);
  }
};

window.handleAgentInterpret = async function () {
  const prompt = document.getElementById('agent-prompt').value.trim();
  const userId = document.getElementById('decision-user').value || state.activeUserId;
  const preview = document.getElementById('agent-intent-preview');

  if (!prompt || !userId) {
    alert('Please enter a purchase prompt and select a user.');
    return;
  }

  preview.style.display = 'block';
  preview.innerHTML = '<span style="color:var(--text-secondary);">🤖 Interpreting natural language intent...</span>';

  try {
    const res = await fetch(`${API_BASE}/agent/interpret`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: userId, prompt: prompt, currency: 'INR' }),
    });
    const intent = await res.json();

    if (intent.is_ambiguous) {
      preview.innerHTML = `
        <div style="color:#f87171;font-weight:600;">⚠️ Ambiguous Intent Detected:</div>
        <div>${intent.ambiguity_reason || 'Could not unambiguously resolve merchant or monetary amount.'}</div>
        <div style="color:var(--text-secondary);margin-top:0.25rem;font-size:0.8rem;">Confidence: ${(intent.confidence * 100).toFixed(0)}%</div>
      `;
    } else {
      preview.innerHTML = `
        <div style="color:#34d399;font-weight:600;">✅ Structured Payment Intent Extracted:</div>
        <div style="margin-top:0.25rem;">
          <strong>Merchant:</strong> ${intent.merchant_name || 'None'} (${intent.merchant_id ? intent.merchant_id.slice(0, 8) + '...' : 'Unresolved'}) | 
          <strong>Amount:</strong> ${intent.amount ? intent.amount + ' ' + intent.currency : 'Unspecified'} | 
          <strong>Type:</strong> ${intent.transaction_type}
        </div>
        ${intent.resolution_notes ? `<div style="color:var(--text-secondary);font-size:0.8rem;margin-top:0.25rem;">Note: ${intent.resolution_notes}</div>` : ''}
      `;
      if (intent.merchant_id) document.getElementById('decision-merchant').value = intent.merchant_id;
      if (intent.amount) document.getElementById('decision-amount').value = parseFloat(intent.amount).toFixed(2);
      if (intent.currency) document.getElementById('decision-currency').value = intent.currency;
    }
  } catch (err) {
    preview.innerHTML = `<span style="color:#f87171;">Intent parsing error: ${err.message}</span>`;
  }
};

window.handleAgentEvaluate = async function () {
  const prompt = document.getElementById('agent-prompt').value.trim();
  const userId = document.getElementById('decision-user').value || state.activeUserId;
  const preview = document.getElementById('agent-intent-preview');

  if (!prompt || !userId) {
    alert('Please enter a purchase prompt and select a user.');
    return;
  }

  preview.style.display = 'block';
  preview.innerHTML = '<span style="color:var(--text-secondary);">🤖 Executing agentic purchase & DecisionVault evaluation...</span>';

  try {
    const res = await fetch(`${API_BASE}/agent/evaluate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: userId, prompt: prompt, currency: 'INR', auto_execute_payment: true }),
    });
    const data = await res.json();

    const intent = data.structured_intent;
    const color = data.decision === 'ALLOW' ? '#34d399' : (data.decision === 'BLOCK' ? '#f87171' : '#fbbf24');
    preview.innerHTML = `
      <div style="font-weight:600;color:${color};">
        ${data.explanation}
      </div>
      <div style="font-size:0.8rem;color:var(--text-secondary);margin-top:0.35rem;">
        Extracted: ${intent.merchant_name || 'N/A'} | ${intent.amount || '0'} ${intent.currency} | Confidence: ${(intent.confidence * 100).toFixed(0)}%
      </div>
    `;

    // Refresh merchants dropdown if a brand-new merchant was auto-created (Fix 3)
    if (intent && intent.merchant_name) {
      const mName = intent.merchant_name.toLowerCase().trim();
      const exists = state.merchants.some(m => m.name.toLowerCase().trim() === mName);
      if (!exists || intent.is_new_merchant) {
        const mRes = await fetch(`${API_BASE}/merchants`);
        if (mRes.ok) {
          state.merchants = (await mRes.json()).merchants || [];
          populateSelect('decision-merchant', state.merchants, m => `${m.name} (${m.id.slice(0, 8)})`);
          if (intent.merchant_id) {
            document.getElementById('decision-merchant').value = intent.merchant_id;
          }
        }
      }
    }

    const context = {
      amount: intent.amount,
      currency: intent.currency,
      merchant_name: intent.merchant_name,
      is_new_merchant: intent.is_new_merchant,
    };

    if (data.comparison_data) {
      displayDecisionResult(data, context);
    } else if (data.decision_details) {
      displayDecisionResult(data.decision_details, context);
    } else {
      displayDecisionResult(data, context);
    }
    if (data.payment_result) {
      displayPaymentResult(data.payment_result, context);
    }
    await refreshAuditChainStatus();
  } catch (err) {
    preview.innerHTML = `<span style="color:#f87171;">Agent execution error: ${err.message}</span>`;
  }
};

async function refreshGatewayStatus() {
  try {
    const res = await fetch(`${API_BASE}/payments/status`);
    const data = await res.json();
    const badge = document.getElementById('rzp-status-badge');
    badge.textContent = `Razorpay: ${data.mode}`;
  } catch (e) {
    console.error('Error fetching gateway status:', e);
  }
}

async function refreshAuditChainStatus() {
  const badge = document.getElementById('audit-status-badge');
  if (!badge) return;
  try {
    const res = await fetch(`${API_BASE}/audit/verify`);
    if (!res.ok) {
      badge.textContent = `Audit Chain: Status (${res.status})`;
      badge.style.color = '#f87171';
      return;
    }
    const data = await res.json();
    if (data && data.valid) {
      badge.textContent = `Audit Chain: VALID (${data.records_checked ?? 0} events)`;
      badge.style.color = '#34d399';
    } else {
      const reason = (data && data.failure_reason) ? data.failure_reason : 'TAMPERED';
      badge.textContent = `Audit Chain: ${reason}!`;
      badge.style.color = '#f87171';
    }
  } catch (e) {
    badge.textContent = `Audit Chain: Offline`;
    badge.style.color = '#94a3b8';
  }
}

// --- Tab 1: Decision & Payment Console ---
window.handleEvaluateDecision = async function () {
  const userId = document.getElementById('decision-user').value;
  const merchantSelect = document.getElementById('decision-merchant');
  const merchantId = merchantSelect.value;

  if (!userId || !merchantId) {
    alert("⚠️ No data found. Click '⚡ Seed Demo Data' first to get started.");
    return;
  }

  const merchantName = merchantSelect.options[merchantSelect.selectedIndex]?.text?.split('(')[0]?.trim() || 'Merchant';
  const amount = document.getElementById('decision-amount').value;
  const currency = document.getElementById('decision-currency').value;

  const btn = document.getElementById('btn-evaluate');
  btn.disabled = true;
  btn.textContent = 'Checking Safety Guardrails...';

  const context = { amount, currency, merchant_name: merchantName };

  try {
    const res = await fetch(`${API_BASE}/decisions/evaluate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_id: userId,
        merchant_id: merchantId,
        amount: parseFloat(amount).toFixed(4),
        currency: currency,
        transaction_type: 'PURCHASE',
      }),
    });
    const data = await res.json();
    displayDecisionResult(data, context);
  } catch (err) {
    alert('Evaluation failed: ' + err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = '⚡ Check Safety';
  }
};

window.handleExecutePayment = async function () {
  const userId = document.getElementById('decision-user').value;
  const merchantSelect = document.getElementById('decision-merchant');
  const merchantId = merchantSelect.value;

  if (!userId || !merchantId) {
    alert("⚠️ No data found. Click '⚡ Seed Demo Data' first to get started.");
    return;
  }

  const merchantName = merchantSelect.options[merchantSelect.selectedIndex]?.text?.split('(')[0]?.trim() || 'Merchant';
  const amount = document.getElementById('decision-amount').value;
  const currency = document.getElementById('decision-currency').value;

  const btn = document.getElementById('btn-pay');
  btn.disabled = true;
  btn.textContent = 'Processing Payment Gate...';

  const context = { amount, currency, merchant_name: merchantName };

  try {
    const res = await fetch(`${API_BASE}/payments/execute`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_id: userId,
        merchant_id: merchantId,
        amount: parseFloat(amount).toFixed(4),
        currency: currency,
        transaction_type: 'PURCHASE',
      }),
    });
    const data = await res.json();
    displayPaymentResult(data, context);
    await refreshAuditChainStatus();
  } catch (err) {
    alert('Payment execution failed: ' + err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = '💳 Execute via Razorpay Test Mode';
  }
};

const LABEL_MAP = {
  ROUTINE_PATTERN: '🔄 Usual Spending Pattern',
  ANOMALY_EVENT: '⚠️ Past Problem Detected',
  REVENUE_GROWTH: '📈 Spending Pattern',
  PREFERENCE: '⭐ User Preference',
  MandateConstraintRule: 'Mandate & Spending Limits',
  PolicyLimitRule: 'Maximum Budget Cap',
  DuplicatePaymentRule: 'Duplicate Charge Prevention',
  IdempotencyRule: 'Exact Idempotency Deduplication',
  PriceDriftRule: 'Statistical Price Spike Detection',
  MerchantChangeRule: 'Merchant Trust & Switch Check',
};

function generateNarrativeSummary(data, context) {
  const decision = data.decision;
  const reasonCode = data.reason_code;
  const reason = data.reason || '';

  const rawAmt = data.structured_intent?.amount || (data.amount !== undefined ? data.amount : null) || context?.amount || document.getElementById('decision-amount')?.value;
  const amount = (rawAmt !== undefined && rawAmt !== null && !isNaN(parseFloat(rawAmt))) ? parseFloat(rawAmt).toFixed(2) : (rawAmt || '0.00');
  const currency = data.structured_intent?.currency || data.currency || context?.currency || 'INR';
  const merchant = data.structured_intent?.merchant_name || context?.merchant_name || 'the merchant';

  if (data.comparison_data || data.structured_intent?.comparison_data) {
    return data.explanation || `📊 <strong>Cost Comparison:</strong> Compared available options. No funds were debited.`;
  }

  if (decision === 'ALLOW') {
    return `✅ <strong>Approved:</strong> You've made this routine payment before and it stays safely within your approved spending limit. The payment of <strong>${amount} ${currency}</strong> was sent to Razorpay Test Mode.`;
  }
  if (decision === 'ASK_USER') {
    let baselineStr = '';
    const histBase = data.evidence_metadata?.historical_baseline || 
      data.rule_results?.find(r => r.evidence && r.evidence.historical_baseline)?.evidence?.historical_baseline;
    if (histBase && !isNaN(parseFloat(histBase))) {
      baselineStr = ` (usual baseline: ~${parseFloat(histBase).toFixed(2)} ${currency})`;
    }
    return `⚠️ <strong>Needs your confirmation:</strong> This payment of <strong>${amount} ${currency}</strong> to <strong>${merchant}</strong> looks different from your usual spending${baselineStr}. Reason: ${reason}. Click <strong>"Review & Authorize"</strong> to confirm or cancel.`;
  }
  if (decision === 'BLOCK') {
    if (reasonCode === 'DUPLICATE_PAYMENT_DETECTED' || reason.includes('Identical financial action')) {
      return `🚫 <strong>Blocked for your safety:</strong> An identical payment of <strong>${amount} ${currency}</strong> was already made seconds ago. DecisionVault stopped this duplicate request to protect you from being double-charged. Zero funds debited.`;
    }
    if (reasonCode === 'POLICY_LIMIT_EXCEEDED' || reasonCode === 'POLICY_TRANSACTION_LIMIT_EXCEEDED' || reason.includes('exceeds policy')) {
      return `🚫 <strong>Blocked for your safety:</strong> The requested amount of <strong>${amount} ${currency}</strong> exceeds your configured spending safety cap. Zero funds were moved.`;
    }
    return `🚫 <strong>Blocked for your safety:</strong> ${reason} Zero funds were moved.`;
  }
  return data.reason || data.explanation || 'Decision evaluated.';
}

function displayDecisionResult(data, context = null) {
  const card = document.getElementById('decision-result-card');
  if (card) card.style.display = 'block';

  state.lastEvaluatedData = { ...data, ...(context || {}) };

  // Handle Comparison UI Display (Item 6)
  const compBox = document.getElementById('comparison-result-box');
  const compData = data.comparison_data || data.structured_intent?.comparison_data;
  if (compBox) {
    if (compData && Array.isArray(compData) && compData.length > 0) {
      compBox.style.display = 'block';

      let minPrice = Infinity;
      let winnerName = '';
      compData.forEach(c => {
        const p = c.estimated_annual_inr || 0;
        if (p < minPrice) {
          minPrice = p;
          winnerName = c.name;
        }
      });

      let tableRows = compData.map(c => {
        const isWinner = c.name === winnerName && compData.length > 1;
        const monthly = c.estimated_monthly_inr || (c.estimated_annual_inr ? Math.round(c.estimated_annual_inr / 12) : 0);
        const annual = c.estimated_annual_inr || 0;
        return `
          <tr style="${isWinner ? 'background:rgba(16,185,129,0.08);' : ''}">
            <td style="padding:0.75rem 1rem;font-weight:600;">
              ${c.name}
              ${isWinner ? '<span class="chip-badge allow" style="margin-left:0.5rem;font-size:0.75rem;">🏆 Best Value</span>' : ''}
            </td>
            <td style="padding:0.75rem 1rem;">₹${monthly.toLocaleString()}/mo</td>
            <td style="padding:0.75rem 1rem;font-weight:700;color:${isWinner ? '#34d399' : 'inherit'};">₹${annual.toLocaleString()}/yr</td>
            <td style="padding:0.75rem 1rem;">${isWinner ? '✅ Cheaper by ₹' + Math.abs((compData[0]?.estimated_annual_inr || 0) - (compData[1]?.estimated_annual_inr || 0)).toLocaleString() : 'Standard'}</td>
            <td style="padding:0.75rem 1rem;text-align:right;">
              <button class="btn btn-secondary" style="font-size:0.78rem;padding:0.35rem 0.65rem;" onclick="fillAndRunPrompt('Pay ₹${annual} to ${c.name} for 1-year subscription')">Choose ${c.name}</button>
            </td>
          </tr>
        `;
      }).join('');

      compBox.innerHTML = `
        <div style="background:linear-gradient(135deg,rgba(59,130,246,0.1),rgba(16,185,129,0.08));border:1px solid rgba(59,130,246,0.3);border-radius:8px;padding:1.25rem;">
          <div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.75rem;">
            <span style="font-size:1.2rem;">📊</span>
            <strong style="font-size:1rem;color:var(--text-primary);">Service Cost Comparison Table</strong>
          </div>
          <div style="overflow-x:auto;margin-bottom:1rem;border-radius:6px;border:1px solid var(--border-color);background:rgba(0,0,0,0.2);">
            <table style="width:100%;border-collapse:collapse;text-align:left;font-size:0.9rem;">
              <thead>
                <tr style="border-bottom:1px solid var(--border-color);color:var(--text-secondary);font-size:0.8rem;text-transform:uppercase;">
                  <th style="padding:0.6rem 1rem;">Merchant / Plan</th>
                  <th style="padding:0.6rem 1rem;">Monthly Cost</th>
                  <th style="padding:0.6rem 1rem;">Annual Cost</th>
                  <th style="padding:0.6rem 1rem;">Assessment</th>
                  <th style="padding:0.6rem 1rem;text-align:right;">Action</th>
                </tr>
              </thead>
              <tbody>
                ${tableRows}
              </tbody>
            </table>
          </div>
          <div style="font-size:0.85rem;color:var(--text-secondary);background:rgba(0,0,0,0.25);padding:0.6rem 0.85rem;border-radius:6px;">
            💬 <strong>Which one would you like to subscribe to?</strong> Click a button above or type your instruction.
          </div>
        </div>
      `;
    } else {
      compBox.style.display = 'none';
      compBox.innerHTML = '';
    }
  }

  // Handle Informational Badge for Auto-Created Merchants (Fix 4)
  const newMBadge = document.getElementById('new-merchant-badge');
  const isNewMerchant = data.structured_intent?.is_new_merchant || context?.is_new_merchant;
  const merchantName = data.structured_intent?.merchant_name || context?.merchant_name || 'New Merchant';

  if (newMBadge) {
    if (isNewMerchant && (!compData || compData.length === 0)) {
      newMBadge.innerHTML = `🆕 <strong>New Merchant</strong> — "${merchantName}" has been added to your merchant registry. This is your first transaction with them — evaluated against policy limits only, no price history available yet.`;
      newMBadge.style.display = 'block';
    } else {
      newMBadge.style.display = 'none';
      newMBadge.innerHTML = '';
    }
  }

  // Outcome Visual Identity (Priority 3)
  const banner = document.getElementById('decision-banner');
  if (banner) {
    if (compData && compData.length > 0) {
      banner.style.display = 'none';
    } else {
      banner.style.display = 'flex';
      banner.className = `decision-banner ${data.decision}`;
      if (data.decision === 'ALLOW') {
        banner.innerHTML = `<span>✅ Approved — Payment will proceed</span><span class="code-pill" style="background:rgba(16,185,129,0.3);color:#34d399;">ALLOW</span>`;
      } else if (data.decision === 'ASK_USER') {
        banner.innerHTML = `<span>⚠️ Needs your OK — Something looks different, please confirm</span><span class="code-pill" style="background:rgba(245,158,11,0.3);color:#fbbf24;">ASK_USER</span>`;
      } else if (data.decision === 'BLOCK') {
        banner.innerHTML = `<span>🚫 Blocked — Stopped for your financial safety</span><span class="code-pill" style="background:rgba(239,68,68,0.3);color:#f87171;">BLOCK</span>`;
      }
    }
  }

  // Narrative Summary Card (Priority 7)
  const narrativeText = document.getElementById('narrative-summary-text');
  if (narrativeText) {
    narrativeText.innerHTML = generateNarrativeSummary(data, context);
  }

  // Render Rules with Friendly Labels (Priority 4)
  const ruleList = document.getElementById('decision-rules-list');
  if (ruleList) {
    ruleList.innerHTML = '';
    (data.rule_results || []).forEach(r => {
      const friendlyName = LABEL_MAP[r.rule_id] || r.rule_id;
      const div = document.createElement('div');
      div.className = 'rule-item';
      div.innerHTML = `
        <div>
          <strong>${friendlyName}</strong>
          <div style="font-size:0.75rem;color:var(--text-secondary);">${r.message}</div>
        </div>
        <span class="rule-badge ${r.status}">${r.status === 'PASS' ? '✅ Passed' : '🚫 Blocked'}</span>
      `;
      ruleList.appendChild(div);
    });
  }

  // Memory Context with Friendly Labels (Priority 4)
  const memList = document.getElementById('decision-memory-list');
  if (memList) {
    memList.innerHTML = '';
    if (!data.memory_context || data.memory_context.length === 0) {
      memList.innerHTML = '<div style="color:var(--text-secondary);font-size:0.85rem;">No historical memory needed for this check.</div>';
    } else {
      data.memory_context.forEach(m => {
        const friendlyType = LABEL_MAP[m.memory_type] || m.memory_type;
        const div = document.createElement('div');
        div.className = 'rule-item';
        div.innerHTML = `
          <div>
            <span class="code-pill">${friendlyType}</span> <span style="font-size:0.75rem;color:#60a5fa;">[${m.relevance}]</span>
            <div style="font-size:0.85rem;margin-top:0.25rem;">${m.summary}</div>
          </div>
        `;
        memList.appendChild(div);
      });
    }
  }

  // Handle ASK_USER confirmation button (only if not in comparison mode)
  const confirmBtn = document.getElementById('btn-confirm-action');
  if (confirmBtn) {
    const decisionId = data.decision_id || data.decision_details?.decision_id || data.structured_intent?.decision_id || data.request_id;
    state.activeDecisionId = decisionId || null;
    if (data.decision === 'ASK_USER' && state.activeDecisionId && (!compData || compData.length === 0)) {
      confirmBtn.style.display = 'inline-flex';
    } else {
      confirmBtn.style.display = 'none';
    }
  }
}

function displayPaymentResult(data, context = null) {
  displayDecisionResult(data, context);

  if (data.decision_id) {
    state.activeDecisionId = data.decision_id;
  }

  const payInfo = document.getElementById('payment-info-box');
  if (!payInfo) return;
  payInfo.style.display = 'block';

  if (data.status === 'SUCCESS') {
    payInfo.innerHTML = `
      <div style="color:#34d399;font-weight:bold;margin-bottom:0.4rem;">✅ Payment Successful (Razorpay Test Mode)</div>
      <div><strong>Order ID:</strong> <span class="code-pill">${data.gateway_order_id || 'N/A'}</span></div>
      <div><strong>Payment ID:</strong> <span class="code-pill">${data.gateway_payment_id || data.payment_id || 'N/A'}</span></div>
      <div><strong>Transaction ID:</strong> <span class="code-pill">${data.transaction_id || 'N/A'}</span></div>
      <div><strong>Mode:</strong> ${data.gateway_mode || 'SANDBOX_SIMULATION'}</div>
    `;
  } else if (data.status === 'BLOCKED') {
    payInfo.innerHTML = `
      <div style="color:#f87171;font-weight:bold;margin-bottom:0.4rem;">🛑 Payment Blocked by Safety Guardrails</div>
      <div><strong>Reason:</strong> ${data.reason}</div>
      <div style="font-size:0.8rem;color:var(--text-secondary);margin-top:0.4rem;">Zero funds debited. No payment gateway call executed.</div>
    `;
  } else if (data.status === 'REQUIRES_USER_CONFIRMATION') {
    payInfo.innerHTML = `
      <div style="color:#fbbf24;font-weight:bold;margin-bottom:0.4rem;">⚠️ Pending Your Confirmation</div>
      <div><strong>Reason:</strong> ${data.reason}</div>
      <div style="font-size:0.8rem;color:var(--text-secondary);margin-top:0.4rem;">Payment is paused until you click "Review & Authorize".</div>
    `;
  } else if (data.status === 'REJECTED_BY_USER') {
    payInfo.innerHTML = `
      <div style="color:#f87171;font-weight:bold;margin-bottom:0.4rem;">🛑 Payment Rejected by User</div>
      <div><strong>Status:</strong> REJECTED_BY_USER</div>
      <div style="font-size:0.8rem;color:var(--text-secondary);margin-top:0.4rem;">Zero funds debited. No money movement occurred.</div>
    `;
  }
}

window.openConfirmModal = function () {
  const modal = document.getElementById('confirm-modal');
  const desc = document.getElementById('confirm-modal-description');
  if (desc) {
    const d = state.lastEvaluatedData || {};
    const rawAmt = d.structured_intent?.amount || (d.amount !== undefined ? d.amount : null) || document.getElementById('decision-amount')?.value;
    const amount = (rawAmt !== undefined && rawAmt !== null && !isNaN(parseFloat(rawAmt))) ? parseFloat(rawAmt).toFixed(2) : (rawAmt || '0.00');
    const currency = d.structured_intent?.currency || d.currency || 'INR';
    const merchant = d.structured_intent?.merchant_name || d.merchant_name || 'the merchant';
    const reason = d.reason || d.explanation || '';
    const reasonCode = d.reason_code || '';

    if (reasonCode === 'SIGNIFICANT_PRICE_DRIFT' || reason.includes('higher than historical') || reason.includes('price spike')) {
      const match = reason.match(/baseline of\s+([0-9.]+)\s+INR/i);
      const baseline = match ? match[1] : (d.evidence_metadata?.historical_baseline || '649.00');
      const ratio = (parseFloat(amount) / (parseFloat(baseline) || 1)).toFixed(1);
      desc.innerHTML = `Your historical baseline for <strong>${merchant}</strong> is ~<strong>${parseFloat(baseline).toFixed(2)} ${currency}</strong>. This request is for <strong>${parseFloat(amount).toFixed(2)} ${currency}</strong> (${ratio}× more than normal). Do you want to authorize this payment to proceed to Razorpay Test Mode?`;
    } else if (reasonCode === 'UNEXPECTED_MERCHANT_CHANGE' || reason.includes('unrecognized') || reason.includes('first time')) {
      desc.innerHTML = `This is your first time paying <strong>${merchant}</strong> (<strong>${parseFloat(amount).toFixed(2)} ${currency}</strong>) autonomously. Do you want to authorize this payment to proceed to Razorpay Test Mode?`;
    } else {
      desc.innerHTML = `DecisionVault paused this payment of <strong>${parseFloat(amount).toFixed(2)} ${currency}</strong> to <strong>${merchant}</strong> for confirmation: <em>${reason || 'Safety review required'}</em>. Do you want to authorize this payment?`;
    }
  }
  if (modal) modal.classList.add('open');
};

window.closeConfirmModal = function () {
  const modal = document.getElementById('confirm-modal');
  if (modal) modal.classList.remove('open');
};

window.submitConfirmation = async function (confirmed) {
  if (!state.activeDecisionId) {
    alert('No active pending decision found.');
    return;
  }
  const acceptBaseline = document.getElementById('accept-baseline-checkbox')?.checked || false;
  try {
    const res = await fetch(`${API_BASE}/payments/decisions/${state.activeDecisionId}/confirm`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        confirmed: confirmed,
        execute_payment_now: confirmed,
        accept_as_new_baseline: confirmed ? acceptBaseline : false,
        user_notes: confirmed ? 'Authorized via Decision Console UI' : 'Rejected via Decision Console UI',
      }),
    });
    const data = await res.json();
    closeConfirmModal();

    if (!res.ok) {
      alert('Confirmation failed: ' + (data.detail || data.message || 'Unknown error'));
      return;
    }

    if (confirmed && data.payment_result) {
      displayPaymentResult(data.payment_result, state.lastEvaluatedData);
      alert(data.message || 'Payment successfully authorized & executed!');
    } else {
      // Rejection or non-payment confirmation
      const banner = document.getElementById('decision-banner');
      if (banner) {
        banner.className = 'decision-banner BLOCK';
        banner.innerHTML = '<span>🚫 Payment Rejected by User</span><span class="code-pill" style="background:rgba(239,68,68,0.3);color:#f87171;">CANCELLED</span>';
      }
      const narrativeText = document.getElementById('narrative-summary-text');
      if (narrativeText) {
        narrativeText.innerHTML = `🛑 <strong>Payment Cancelled:</strong> You chose to reject this payment. Zero funds were moved and no Razorpay charge was made.`;
      }

      const payInfo = document.getElementById('payment-info-box');
      if (payInfo) {
        payInfo.style.display = 'block';
        payInfo.innerHTML = `
          <div style="color:#f87171;font-weight:bold;margin-bottom:0.4rem;">🛑 Payment Cancelled by User</div>
          <div><strong>Status:</strong> REJECTED_BY_USER</div>
          <div style="font-size:0.8rem;color:var(--text-secondary);margin-top:0.4rem;">Zero funds debited. No payment gateway execution occurred.</div>
        `;
      }
      const confirmBtn = document.getElementById('btn-confirm-action');
      if (confirmBtn) confirmBtn.style.display = 'none';
      alert(data.message || 'Payment rejected by user. Zero funds debited.');
    }
    await refreshAuditChainStatus();
  } catch (err) {
    alert('Confirmation error: ' + err.message);
  }
};

// --- Tab 2: Memory View ---
window.loadMemoryView = async function () {
  const userId = document.getElementById('memory-user').value || state.activeUserId;
  if (!userId) return;

  try {
    const [txRes, memRes] = await Promise.all([
      fetch(`${API_BASE}/transactions?user_id=${userId}&limit=20`),
      fetch(`${API_BASE}/memories?user_id=${userId}&limit=20`),
    ]);

    const txData = await txRes.json();
    const memData = await memRes.json();
    const txs = Array.isArray(txData) ? txData : txData.transactions || [];
    const mems = Array.isArray(memData) ? memData : memData.memories || [];

    // Render Raw Transactions
    const txBody = document.getElementById('raw-tx-tbody');
    txBody.innerHTML = '';
    txs.forEach(t => {
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td><span class="code-pill">${t.id.slice(0, 8)}</span></td>
        <td>${t.amount} ${t.currency}</td>
        <td>${t.status}</td>
        <td>${new Date(t.occurred_at).toLocaleString()}</td>
      `;
      txBody.appendChild(tr);
    });

    // Render Decision Memories
    const memBody = document.getElementById('memories-list-box');
    memBody.innerHTML = '';
    mems.forEach(m => {
      const friendlyType = LABEL_MAP[m.memory_type] || m.memory_type;
      const card = document.createElement('div');
      card.className = 'card';
      card.innerHTML = `
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.5rem;">
          <div><span class="code-pill">${friendlyType}</span> <strong style="color:#60a5fa;">[${m.relevance}]</strong></div>
          <span style="font-size:0.75rem;color:var(--text-secondary);">${m.status}</span>
        </div>
        <div style="font-size:0.9rem;margin-bottom:0.5rem;">${m.summary}</div>
        <div style="font-size:0.75rem;color:var(--text-secondary);">Sources Linked: ${(m.sources || []).length} transactions</div>
      `;
      memBody.appendChild(card);
    });
  } catch (err) {
    console.error('Error loading memory view:', err);
  }
};

window.handleTriggerCompression = async function () {
  const userId = document.getElementById('memory-user').value || state.activeUserId;
  if (!userId) return;

  const btn = document.getElementById('btn-compress');
  btn.disabled = true;
  btn.textContent = 'Compressing...';

  try {
    const res = await fetch(`${API_BASE}/memories/compress`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: userId, lookback_days: 90 }),
    });
    const data = await res.json();
    alert(`Compression Completed: ${data.memories_created} memories created, ${data.compression_ratio}x ratio (${data.compression_percentage}% reduction).`);
    await loadMemoryView();
    await refreshAuditChainStatus();
  } catch (e) {
    alert('Compression failed: ' + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = '🔄 Trigger Memory Compression';
  }
};

// --- Tab 3: Audit View ---
window.loadAuditView = async function () {
  const banner = document.getElementById('audit-verify-banner');
  try {
    const [auditRes, verifyRes] = await Promise.all([
      fetch(`${API_BASE}/audit?limit=50`),
      fetch(`${API_BASE}/audit/verify`),
    ]);

    if (!verifyRes.ok) {
      if (banner) {
        banner.style.backgroundColor = 'rgba(239, 68, 68, 0.2)';
        banner.style.borderColor = '#ef4444';
        banner.style.color = '#f87171';
        banner.textContent = `❌ AUDIT VERIFICATION FAILED: HTTP ${verifyRes.status}`;
      }
      return;
    }

    const verify = await verifyRes.json();
    const auditData = auditRes.ok ? await auditRes.json() : { records: [] };
    const logs = Array.isArray(auditData) ? auditData : (auditData.records || []);

    if (banner) {
      if (verify && verify.valid) {
        banner.style.backgroundColor = 'rgba(16, 185, 129, 0.2)';
        banner.style.borderColor = '#10b981';
        banner.style.color = '#34d399';
        banner.textContent = `✅ CRYPTOGRAPHIC HASH CHAIN INTEGRITY: VALID (${verify.records_checked ?? 0} events verified)`;
      } else {
        banner.style.backgroundColor = 'rgba(239, 68, 68, 0.2)';
        banner.style.borderColor = '#ef4444';
        banner.style.color = '#f87171';
        const reason = (verify && verify.failure_reason) ? verify.failure_reason : 'RECORD_HASH_MISMATCH';
        const seq = (verify && verify.first_invalid_sequence !== undefined && verify.first_invalid_sequence !== null)
          ? `at sequence #${verify.first_invalid_sequence}`
          : '';
        banner.textContent = `❌ AUDIT CHAIN INVALID: ${reason} ${seq}`.trim();
      }
    }

    const tbody = document.getElementById('audit-tbody');
    if (tbody) {
      tbody.innerHTML = '';
      if (logs.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-secondary);padding:1.5rem;">No audit events recorded yet.</td></tr>';
        return;
      }
      logs.forEach(l => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td><strong>#${l.sequence_number}</strong></td>
          <td><span class="code-pill">${l.event_type}</span></td>
          <td>${l.entity_type}</td>
          <td><span class="code-pill" title="${l.record_hash}">${l.record_hash ? l.record_hash.slice(0, 10) + '...' : ''}</span></td>
          <td><span class="code-pill" title="${l.previous_hash}">${l.previous_hash ? l.previous_hash.slice(0, 10) + '...' : 'GENESIS'}</span></td>
          <td>${l.occurred_at ? new Date(l.occurred_at).toLocaleTimeString() : '-'}</td>
        `;
        tbody.appendChild(tr);
      });
    }
  } catch (err) {
    console.error('Error loading audit logs:', err);
    if (banner) {
      banner.style.backgroundColor = 'rgba(239, 68, 68, 0.2)';
      banner.style.borderColor = '#ef4444';
      banner.style.color = '#f87171';
      banner.textContent = `⚠️ AUDIT VERIFICATION ERROR: ${err.message || 'Database unavailable'}`;
    }
  }
};

// --- Tab 4: Evaluation Benchmarks ---
window.handleRunEvaluation = async function (suiteName) {
  const userId = document.getElementById('eval-user').value || state.activeUserId;
  if (!userId) return;

  const btn = document.getElementById(`btn-eval-${suiteName.toLowerCase()}`);
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Running Evaluation...';
  }

  try {
    const res = await fetch(`${API_BASE}/evaluations/decision-preservation`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: userId, scenario_suite: suiteName }),
    });
    const data = await res.json();
    displayEvaluationResults(data);
    await refreshAuditChainStatus();
  } catch (err) {
    alert('Evaluation error: ' + err.message);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = `Run ${suiteName} Suite`;
    }
  }
};

function displayEvaluationResults(data) {
  document.getElementById('eval-results-container').style.display = 'block';

  document.getElementById('metric-preservation-rate').textContent = `${(data.decision_preservation_rate * 100).toFixed(1)}%`;
  document.getElementById('metric-safety-rate').textContent = `${(data.safety_critical_preservation_rate * 100).toFixed(1)}%`;
  document.getElementById('metric-critical-recall').textContent = `${(data.critical_memory_recall * 100).toFixed(1)}%`;
  document.getElementById('metric-comp-ratio').textContent = `${data.compression_ratio}x`;

  const tbody = document.getElementById('eval-trace-tbody');
  tbody.innerHTML = '';
  (data.scenarios || []).forEach(sc => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><strong>${sc.scenario_id}</strong></td>
      <td><span class="code-pill">${sc.category}</span></td>
      <td>${sc.full_history_decision}</td>
      <td>${sc.compressed_memory_decision}</td>
      <td><span class="rule-badge ${sc.decision_match ? 'PASS' : 'FAIL'}">${sc.mismatch_type}</span></td>
    `;
    tbody.appendChild(tr);
  });
}

// --- Tab 5: 1-Click Scenario Launcher ---
window.runDemoScenario = async function (scenarioIndex) {
  const userId = state.activeUserId;
  const merchantId = state.activeMerchantId;
  if (!userId || !merchantId) {
    alert('Please wait for users and merchants to load.');
    return;
  }

  // Switch to Decision Console tab
  document.querySelectorAll('.tab-btn')[0].click();

  if (scenarioIndex === 1) {
    // Normal Purchase -> ALLOW -> Razorpay Test Mode
    document.getElementById('decision-amount').value = '649.00';
    document.getElementById('decision-currency').value = 'INR';
    await handleExecutePayment();
  } else if (scenarioIndex === 2) {
    // Duplicate Request -> BLOCK
    document.getElementById('decision-amount').value = '649.00';
    document.getElementById('decision-currency').value = 'INR';
    await handleExecutePayment();
    // Replay immediately
    setTimeout(() => handleExecutePayment(), 200);
  } else if (scenarioIndex === 3) {
    // Policy Limit Breach -> BLOCK (₹3500 > ₹3000 hard limit)
    document.getElementById('decision-amount').value = '3500.00';
    document.getElementById('decision-currency').value = 'INR';
    await handleExecutePayment();
  } else if (scenarioIndex === 4) {
    // Price Drift -> ASK_USER (1500.00 INR vs 649.00 INR baseline)
    document.getElementById('decision-amount').value = '1500.00';
    document.getElementById('decision-currency').value = 'INR';
    await handleExecutePayment();
  } else if (scenarioIndex === 5) {
    // Switch to Memory View
    document.querySelectorAll('.tab-btn')[1].click();
    await handleTriggerCompression();
  } else if (scenarioIndex === 6) {
    // Switch to Audit View
    document.querySelectorAll('.tab-btn')[2].click();
    await refreshAuditChainStatus();
  } else if (scenarioIndex === 7) {
    // Switch to Evaluation
    document.querySelectorAll('.tab-btn')[3].click();
    await handleRunEvaluation('ADVERSARIAL');
  } else if (scenarioIndex === 8) {
    // AI Buying Agent Natural Language Purchase
    document.querySelectorAll('.tab-btn')[0].click();
    document.getElementById('agent-prompt').value = 'Pay my usual Netflix subscription';
    await handleAgentEvaluate();
  }
};
