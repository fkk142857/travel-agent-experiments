/* ===== 小坤 · 旅游 Agent 实验台 ===== */
(() => {
  'use strict';
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

  const navEl = $('#nav'), stageEl = $('#stage'), statusEl = $('#status');
  const topTitle = $('#topTitle'), topSub = $('#topSub'), toastEl = $('#toast');
  const sidebar = $('#sidebar'), btnMenu = $('#btnMenu'), modelNameEl = $('#modelName');

  let META = { experiments: [], groups: [] };
  let current = 'chat';
  let busy = false;
  // 每个实验各自的会话状态（聊天类实验需要）
  /* =========================================================
     面板状态存储
     ---------------------------------------------------------
     目标：切换视图、甚至刷新浏览器，对话/轮次/草稿都不丢。

     为什么存"数据"而不是存 innerHTML：
     存 HTML 切回来虽然长得一样，但里面的按钮（折叠、审批）监听全没了，
     点不动。这里存每轮的接口返回 JSON + 问题原文，切回来时用**同一个
     渲染函数重放** —— 长得一样，而且监听都是活的。

     存 sessionStorage：与登录态同寿命（关标签页即清），刷新不丢。
     ========================================================= */
  const PANEL_STORE_KEY = 'xiaokun.panels.v2';
  const MAX_TURNS = 20;
  const MAX_BUBBLES = 40;

  function loadPanelStore() {
    try {
      const raw = sessionStorage.getItem(PANEL_STORE_KEY);
      return raw ? (JSON.parse(raw) || {}) : {};
    } catch { return {}; }
  }

  const panelStore = loadPanelStore();

  function psave() {
    try { sessionStorage.setItem(PANEL_STORE_KEY, JSON.stringify(panelStore)); }
    catch { /* 隐私模式 / 超配额：静默降级，本页内仍可用 */ }
  }

  function panelOf(key) {
    if (!panelStore[key] || typeof panelStore[key] !== 'object') panelStore[key] = {};
    return panelStore[key];
  }

  /* 对话类面板（自由问答 / 实验2 / 实验6）：气泡 + 模型上下文一起存。
     只存气泡不存上下文的话，刷新后界面有历史、模型却失忆，行为不一致。 */
  function panelChat(key) {
    const p = panelOf(key);
    if (!p.chat) p.chat = {};
    if (!Array.isArray(p.chat.history)) p.chat.history = [];
    if (!Array.isArray(p.chat.bubbles)) p.chat.bubbles = [];
    return p.chat;
  }

  function clearPanelStore() {
    try { sessionStorage.removeItem(PANEL_STORE_KEY); } catch {}
    for (const k of Object.keys(panelStore)) delete panelStore[k];
  }

  /* 清空某个面板的「对话」——只删对话本身，不动别的：
     轮次列表、聊天气泡+模型上下文、实验12 未完成的审批进度。
     刻意保留：exp15 的阶段勾选（那是操作偏好，不是对话）。
     DOM 交给随后的 render() 重建，不手工拆节点。 */
  function purgePanel(panel) {
    const p = panelStore[panel];
    if (!p) return;
    delete p.turns;
    delete p.chat;
    delete p.gate;
    if (p.inputs) {
      for (const k of Object.keys(p.inputs)) {
        const v = p.inputs[k];
        if (v && typeof v.value === 'string') v.value = '';
      }
    }
    psave();
  }

  // 活跃的轮次列表，用于离开面板时回写折叠状态
  const liveTurnLists = [];
  let replaying = false;   // 重放历史轮次期间，跳过"刷新日志"等副作用

  // 实验 12 的审批进度必须持久化：声明在渲染器里的话，切换视图就丢，刷新更不用说，
  // 恢复出来的「批准 / 拒绝」按钮会点不动。
  function gateStateOf() {
    const p = panelOf('exp12');
    if (!p.gate || typeof p.gate !== 'object') p.gate = { goal: '', pending: null };
    return p.gate;
  }

  function captureInputs(panel) {
    if (!panel) return;
    const inputs = {};
    stageEl.querySelectorAll('input[id], textarea[id]').forEach(el => {
      inputs[el.id] = el.type === 'checkbox' ? { checked: !!el.checked } : { value: el.value };
    });
    if (Object.keys(inputs).length) panelOf(panel).inputs = inputs;
  }

  function restoreInputs(panel) {
    const p = panelStore[panel];
    if (!p || !p.inputs) return;
    stageEl.querySelectorAll('input[id], textarea[id]').forEach(el => {
      const v = p.inputs[el.id];
      if (!v) return;
      if (el.type === 'checkbox') el.checked = !!v.checked;
      else if (typeof v.value === 'string') el.value = v.value;
      // 触发 input 事件，让自适应高度之类的监听重新计算
      try { el.dispatchEvent(new Event('input', { bubbles: true })); } catch {}
    });
  }

  /* 离开当前面板前快照：折叠状态 + 输入框草稿。
     注意用 renderedPanel 而不是 current —— 点击导航时 current 已经被改成
     新面板了，而此刻 DOM 还是旧面板的，用 current 会把草稿存错位置。 */
  let renderedPanel = null;
  function captureCurrentPanel() {
    const panel = renderedPanel;
    renderedPanel = null;
    if (!panel) return;
    liveTurnLists.forEach(t => { try { t.capture(); } catch {} });
    liveTurnLists.length = 0;
    captureInputs(panel);
    psave();
  }


  const FLAGS = {
    Barcelona:'🇪🇸', Paris:'🇫🇷', Tokyo:'🇯🇵', 'Cape Town':'🇿🇦', Bali:'🇮🇩',
    'New York City':'🇺🇸', Cairo:'🇪🇬', Sydney:'🇦🇺', Berlin:'🇩🇪',
    'Rio de Janeiro':'🇧🇷', Istanbul:'🇹🇷', 'Chiang Mai':'🇹🇭',
  };
  const flagOf = (k) => FLAGS[k] || '📍';

  /* ---------- 工具 ---------- */
  function esc(s) { return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }

  function md(text) {
    const lines = esc(text).split('\n');
    let html = '', inList = false, inTable = false;
    const inline = t => t
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/`(.+?)`/g, '<code>$1</code>')
      .replace(/(^|[^*])\*([^*\n]+?)\*/g, '$1<em>$2</em>');

    const closeList = () => { if (inList) { html += '</ul>'; inList = false; } };
    const closeTable = () => { if (inTable) { html += '</tbody></table>'; inTable = false; } };

    for (const raw of lines) {
      const line = raw.trimEnd();
      if (!line.trim()) { closeList(); closeTable(); continue; }

      // 表格
      if (/^\s*\|.*\|\s*$/.test(line)) {
        const cells = line.trim().slice(1, -1).split('|').map(c => c.trim());
        if (/^[\s\-:|]+$/.test(line.replace(/\|/g, ''))) continue;  // 分隔行
        if (!inTable) {
          closeList();
          html += '<table><thead><tr>' + cells.map(c => `<th>${inline(c)}</th>`).join('') + '</tr></thead><tbody>';
          inTable = true;
        } else {
          html += '<tr>' + cells.map(c => `<td>${inline(c)}</td>`).join('') + '</tr>';
        }
        continue;
      } else closeTable();

      const h = line.match(/^(#{1,4})\s+(.*)$/);
      if (h) { closeList(); html += `<h3>${inline(h[2])}</h3>`; continue; }

      const li = line.match(/^\s*[-*•]\s+(.*)$/) || line.match(/^\s*\d+[.)]\s+(.*)$/);
      if (li) { if (!inList) { html += '<ul>'; inList = true; } html += `<li>${inline(li[1])}</li>`; continue; }

      closeList();
      html += `<p>${inline(line)}</p>`;
    }
    closeList(); closeTable();
    return html;
  }

  function setStatus(t, cls) { statusEl.className = 'status ' + (cls || ''); statusEl.innerHTML = '<span class="dot"></span>' + t; }

  function hideToast() {
    toastEl.classList.remove('show');
    clearTimeout(toast._t);
  }

  /* 轻提示。可带一个动作按钮（如「撤销」）。
     注意：.toast 是 pointer-events:none，按钮自己开了 auto；
     文案一律走 textContent，不拼 innerHTML。 */
  function toast(msg, { action, onAction, duration } = {}) {
    toastEl.textContent = '';
    const span = document.createElement('span');
    span.textContent = msg;
    toastEl.appendChild(span);

    if (action && typeof onAction === 'function') {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'toast-action';
      btn.textContent = action;
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        hideToast();
        onAction();
      });
      toastEl.appendChild(btn);
    }

    toastEl.classList.add('show');
    clearTimeout(toast._t);
    toast._t = setTimeout(() => toastEl.classList.remove('show'), duration || 2400);
  }

  function setBusy(v) {
    busy = v;
    $$('.btn, .btn-send').forEach(b => { if (!b.dataset.keepEnabled) b.disabled = v; });
  }

  // 会话失效时统一回口令页，避免"页面开着但接口全 401"的错乱状态
  let authRedirecting = false;
  function backToGate() {
    if (authRedirecting) return;
    authRedirecting = true;
    // 只回首页：会话失效往往是在调接口时发现的，
    // 带着 /api/xxx 做 next 会导致登录后又落在一个接口地址上。
    location.href = '/_gate?next=' + encodeURIComponent('/');
  }

  async function api(path, body, method = 'POST') {
    const opt = { method, headers: { 'Content-Type': 'application/json' } };
    if (body !== undefined) opt.body = JSON.stringify(body);
    const r = await fetch(path, opt);
    if (r.status === 401 || r.status === 403) { backToGate(); throw new Error('会话已过期，请重新输入口令'); }
    if (!r.ok) {
      let detail = `HTTP ${r.status}`;
      try { const j = await r.json(); detail = j.detail || detail; } catch {}
      throw new Error(detail);
    }
    return r.json();
  }

  const loadingHtml = (t = '执行中…') =>
    `<div class="card"><div class="loading"><div class="spinner"></div>${esc(t)}</div></div>`;

  /* ---------- 导航 ---------- */
  function renderNav() {
    navEl.innerHTML = '';

    const chatBtn = document.createElement('button');
    chatBtn.className = 'nav-item' + (current === 'chat' ? ' active' : '');
    chatBtn.dataset.view = 'chat';
    chatBtn.innerHTML = `<span class="nav-no">✦</span><span class="nav-body"><span class="nav-title">自由问答</span><span class="nav-badge">RAG</span></span>`;
    navEl.appendChild(chatBtn);

    for (const g of META.groups) {
      const box = document.createElement('div');
      box.className = 'nav-group';
      box.innerHTML = `<div class="nav-group-title">${esc(g.group)}</div>`;
      for (const it of g.items) {
        const b = document.createElement('button');
        b.className = 'nav-item' + (current === it.id ? ' active' : '');
        b.dataset.view = it.id;
        b.innerHTML = `<span class="nav-no">${it.no}</span><span class="nav-body"><span class="nav-title">${esc(it.title)}</span>${it.badge ? `<span class="nav-badge">${esc(it.badge)}</span>` : ''}</span>`;
        box.appendChild(b);
      }
      navEl.appendChild(box);
    }

    $$('.nav-item', navEl).forEach(b => b.addEventListener('click', () => {
      if (busy) { toast('请等待当前任务完成'); return; }
      current = b.dataset.view;
      $$('.nav-item', navEl).forEach(x => x.classList.toggle('active', x === b));
      sidebar.classList.remove('open');
      render();
    }));
  }

  /* ---------- 入口 ---------- */
  function render() {
    // 重建 DOM 之前，先把"要离开的面板"快照下来（轮次折叠态 + 输入框草稿）
    captureCurrentPanel();

    if (current === 'chat') {
      renderChat();
      renderedPanel = current;
      restoreInputs(current);
      return;
    }
    const exp = META.experiments.find(e => e.id === current);
    if (!exp) return;
    topTitle.textContent = `实验 ${exp.no} · ${exp.title}`;
    topSub.textContent = exp.desc;
    stageEl.innerHTML = '';
    const w = document.createElement('div');
    w.className = 'wrap';
    stageEl.appendChild(w);

    w.innerHTML = `
      <div class="exp-intro">
        <h2><span class="no">实验 ${exp.no}</span>${esc(exp.title)}</h2>
        <p>${esc(exp.desc)}</p>
        ${exp.source ? `<div class="exp-src">📄 对应基线：${esc(exp.source)}</div>` : ''}
        ${exp.note ? `<div class="exp-note">⚠️ ${esc(exp.note)}</div>` : ''}
      </div>
      <div id="expBody"></div>`;

    const body = $('#expBody', w);
    const handler = RENDERERS[exp.id];
    if (!handler) {
      body.innerHTML = `<div class="card"><p class="muted">该实验暂未实现。</p></div>`;
      renderedPanel = current;
      restoreInputs(current);
      return;
    }
    // exp15 的渲染器是异步的（要先取阶段列表），草稿回填要等它铺完 DOM
    const r = handler(body, exp);
    renderedPanel = current;
    if (r && typeof r.then === 'function') {
      r.then(() => { if (renderedPanel === exp.id) restoreInputs(exp.id); }).catch(() => {});
    } else {
      restoreInputs(current);
    }
  }

  /* 这个面板到底有没有对话？不能只看 turns 存不存在 ——
     turnList 一挂载就会把 store.turns 初始化成 {}，空对象也是"真值"。 */
  function panelHasChat(panel) {
    const p = panelStore[panel];
    if (!p) return false;
    if (p.turns && Object.values(p.turns).some(v => Array.isArray(v) && v.length)) return true;
    if (p.chat && ((p.chat.bubbles || []).length || (p.chat.history || []).length)) return true;
    if (p.gate && p.gate.pending) return true;
    return false;
  }

  /* ---------- 清空当前面板的对话（Esc Esc） ----------
     复用「存数据 + 用同一渲染函数重放」的既有机制：
     先快照 → 清数据 → render() 重建 DOM，不手工删节点，
     这样轮次里的折叠/审批按钮监听都是重新挂上的，不会变成死按钮。 */
  function clearCurrentPanel() {
    const panel = renderedPanel || current;

    // 先把 DOM 的最新状态（折叠态、草稿）落盘：既保证快照是最新的，
    // 也顺带把 renderedPanel 置空，让紧接着的 render() 不会把空态写回去。
    captureCurrentPanel();

    const snapshot = JSON.parse(JSON.stringify(panelStore[panel] || {}));
    const had = panelHasChat(panel);

    purgePanel(panel);
    render();
    setStatus('就绪', 'ready');

    if (!had) { toast('当前面板没有可清空的对话'); return; }

    let undone = false;
    toast('已清空当前对话', {
      action: '撤销',
      duration: 7000,
      onAction: () => {
        if (undone) return;
        undone = true;
        panelStore[panel] = snapshot;
        psave();
        // 只有人还停在这个面板上才需要重绘；已切走的话切回来自然就有
        if (renderedPanel === panel) { renderedPanel = null; render(); }
        toast('已恢复');
      },
    });
  }

  /* =========================================================
     自由问答
     ========================================================= */
  function renderChat() {
    topTitle.textContent = '自由问答';
    topSub.textContent = '基于内置知识库检索 + 大模型生成';
    stageEl.innerHTML = `<div class="wrap"><div class="card">
      <div class="card-head"><span class="card-title">💬 和小坤聊聊</span>
      <span class="card-hint">答案基于知识库检索生成</span></div>
      <div class="chat-box" id="chatBox">
        <div class="msg assistant"><div class="avatar">🌴</div>
          <div class="bubble">你好，我是小坤。问我关于目的地的事——季节、花费、签证、亮点都可以。</div></div>
      </div>
      <div class="samples" id="chatSamples">
        ${['我想找一个温暖的海滩度假地，有什么推荐？','巴黎几月份去最合适？大概要花多少钱？','我有日均 800 元预算，10 月出行，哪些地方合适？','签证比较麻烦的目的地有哪些？']
          .map(s => `<button class="sample">${esc(s)}</button>`).join('')}
      </div>
    </div></div>
    <div class="composer"><div class="composer-inner">
      <textarea id="chatInput" rows="1" placeholder="问点关于旅行的事…（Enter 发送）"></textarea>
      <button class="btn-send" id="chatSend">➤</button>
    </div></div>`;

    const box = $('#chatBox'), input = $('#chatInput'), send = $('#chatSend');
    const st = panelChat('chat');

    // 还原上次的对话：切换视图 / 刷新浏览器都不丢
    if (st.bubbles.length) {
      box.insertAdjacentHTML('beforeend', st.bubbles.map(m => m.role === 'user'
        ? `<div class="msg user"><div class="avatar">🙋</div><div class="bubble">${esc(m.text)}</div></div>`
        : `<div class="msg assistant"><div class="avatar">🌴</div><div class="bubble">${m.html}</div></div>`).join(''));
      const sp = $('#chatSamples'); if (sp) sp.remove();   // 聊过了就不再显示示例
      box.scrollTop = box.scrollHeight;
    }

    const grow = () => { input.style.height = 'auto'; input.style.height = Math.min(input.scrollHeight, 150) + 'px'; };
    input.addEventListener('input', grow);
    input.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); go(input.value); } });
    send.addEventListener('click', () => go(input.value));
    $$('#chatSamples .sample').forEach(b => b.addEventListener('click', () => go(b.textContent)));
    input.focus();

    async function go(q) {
      q = (q || '').trim();
      if (!q || busy) return;
      setBusy(true); input.value = ''; grow(); setStatus('思考中…', 'busy');
      $('#chatSamples')?.remove();

      box.insertAdjacentHTML('beforeend',
        `<div class="msg user"><div class="avatar">🙋</div><div class="bubble">${esc(q).replace(/\n/g, '<br>')}</div></div>`);
      const t = document.createElement('div');
      t.className = 'msg assistant';
      t.innerHTML = `<div class="avatar">🌴</div><div class="bubble"><div class="typing"><span></span><span></span><span></span></div></div>`;
      box.appendChild(t);
      const bubble = $('.bubble', t);
      box.scrollTop = box.scrollHeight;

      let text = '', started = false, sources = [];
      try {
        const resp = await fetch('/api/chat/stream', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ question: q, history: st.history }),
        });
        if (resp.status === 401 || resp.status === 403) { backToGate(); return; }
        if (!resp.ok || !resp.body) throw new Error('HTTP ' + resp.status);
        const reader = resp.body.getReader(), dec = new TextDecoder();
        let buf = '';
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buf += dec.decode(value, { stream: true });
          const parts = buf.split('\n\n'); buf = parts.pop();
          for (const part of parts) {
            const line = part.trim();
            if (!line.startsWith('data:')) continue;
            let ev; try { ev = JSON.parse(line.slice(5).trim()); } catch { continue; }
            if (ev.type === 'sources') sources = ev.sources || [];
            else if (ev.type === 'delta') {
              if (!started) { bubble.innerHTML = ''; started = true; }
              text += ev.text;
              bubble.innerHTML = md(text) + '<span class="cursor"></span>';
              box.scrollTop = box.scrollHeight;
            } else if (ev.type === 'done') bubble.innerHTML = md(text);
            else if (ev.type === 'error') bubble.innerHTML = `<div class="err-box">⚠️ ${esc(ev.message)}</div>`;
          }
        }
        if (!started) bubble.innerHTML = md(text || '（未收到回复）');
        if (text) st.history.push({ role: 'user', content: q }, { role: 'assistant', content: text });
        if (st.history.length > 16) st.history = st.history.slice(-16);
        if (sources.length) bubble.insertAdjacentHTML('beforeend', sourcesHtml(sources));
        // 记住气泡：切换视图 / 刷新后据此还原
        st.bubbles.push({ role: 'user', text: q });
        st.bubbles.push({ role: 'assistant', html: bubble.innerHTML });
        if (st.bubbles.length > MAX_BUBBLES) st.bubbles = st.bubbles.slice(-MAX_BUBBLES);
        psave();
        setStatus('就绪', 'ready');
      } catch (e) {
        bubble.innerHTML = `<div class="err-box">⚠️ 请求失败：${esc(e.message)}</div>`;
        setStatus('出错', 'error');
      } finally { setBusy(false); input.focus(); box.scrollTop = box.scrollHeight; }
    }
  }

  function sourcesHtml(sources) {
    return `<div class="sources"><div class="sources-label">📚 知识库来源 · ${sources.length} 条</div>
      <div class="sources-grid">${sources.map(s => `
        <div class="src-card">
          <div class="src-head"><span class="src-name">${flagOf(s.key)} ${esc(s.name_zh)}</span>
          <span class="src-score">${s.score}</span></div>
          <div class="src-region">${esc(s.region)}</div>
          <div class="src-row"><b>季节</b><span>${esc(s.best_season)}</span></div>
          <div class="src-row"><b>花费</b><span>${esc(s.daily_cost)}</span></div>
          <div class="src-tags">${(s.highlights||[]).map(h => `<span class="src-tag">${esc(h)}</span>`).join('')}</div>
        </div>`).join('')}</div></div>`;
  }

  function stepsHtml(steps) {
    if (!steps || !steps.length) return '';
    return `<div class="steps"><div class="steps-title">🔧 工具调用 · ${steps.length} 次</div>
      ${steps.map(s => `<div class="step">
        <div class="step-head">⚙ ${esc(s.tool)}</div>
        <div class="step-args">参数 ${esc(JSON.stringify(s.arguments))}</div>
        <div class="step-res ${String(s.result).includes('失败') ? 'err' : ''}">返回 ${esc(String(s.result).slice(0, 300))}</div>
      </div>`).join('')}</div>`;
  }

  /* =========================================================
     通用：单轮问答面板
     ========================================================= */
  /* ---------------------------------------------------------
     通用：轮次累积列表
     每轮结果独立成一个可折叠块，历史累积保留，不覆盖上一轮。
     新轮次开始时自动折叠更早的轮次，避免页面无限变长。
     返回 { add(q) -> 本轮容器, count() }
     --------------------------------------------------------- */
  /* 轮次列表：每轮一个可折叠块，历史累积保留。
     panel + list 决定它把数据存在哪里；paint 决定切回来时怎么重绘。 */
  function turnList(container, { panel = '', list = 'main', paint = null, label = '第', foldOthers = true } = {}) {
    container.classList.add('turn-list');
    const store = panel ? panelOf(panel) : null;
    if (store && !store.turns) store.turns = {};
    let items = (store && store.turns[list]) || [];
    let round = items.length;

    // 折叠按钮用事件委托 —— 重放出来的 DOM 不用重新绑定监听
    container.addEventListener('click', e => {
      const btn = e.target && e.target.closest ? e.target.closest('.turn-fold') : null;
      if (!btn || !container.contains(btn)) return;
      const wrap = btn.closest('.turn');
      if (!wrap) return;
      btn.textContent = wrap.classList.toggle('folded') ? '展开' : '收起';
    });

    function sync() { if (store) { store.turns[list] = items; psave(); } }

    function foldOthersNow() {
      if (!foldOthers) return;
      const all = container.querySelectorAll('.turn');
      all.forEach((el, i) => {
        if (i < all.length - 1) {
          el.classList.add('folded');
          const fb = $('.turn-fold', el); if (fb) fb.textContent = '展开';
        }
      });
    }

    function mount(item, no, autoFold) {
      const wrap = document.createElement('section');
      wrap.className = 'turn';
      const head = document.createElement('div');
      head.className = 'turn-head';
      head.innerHTML = `
        <span class="turn-no">${esc(label)} ${no} 轮</span>
        <span class="turn-q">${esc(item.q || '')}</span>
        <button class="turn-fold" type="button" title="折叠/展开">收起</button>`;
      const bodyEl = document.createElement('div');
      bodyEl.className = 'turn-body';
      wrap.appendChild(head);
      wrap.appendChild(bodyEl);
      if (item.folded) {
        wrap.classList.add('folded');
        const fb = $('.turn-fold', head); if (fb) fb.textContent = '展开';
      }
      container.appendChild(wrap);
      if (autoFold) foldOthersNow();
      return bodyEl;
    }

    /* 重放历史轮次：用同一个 paint 重绘，按钮监听随之重建 */
    replaying = true;
    items.forEach((item, i) => {
      const bodyEl = mount(item, i + 1, false);
      if (item.error) {
        bodyEl.innerHTML = `<div class="card"><div class="err-box">⚠️ ${esc(item.error)}</div></div>`;
      } else if (item.payload !== undefined && paint) {
        try { paint(bodyEl, item.payload); }
        catch (e) { bodyEl.innerHTML = `<div class="card"><div class="err-box">⚠️ 历史轮次恢复失败：${esc(e.message)}</div></div>`; }
      }
    });
    replaying = false;

    function add(q) {
      round += 1;
      const item = { q };
      items.push(item);
      const bodyEl = mount(item, round, true);
      // 超出上限就裁掉最旧的（数据与 DOM 一起裁）
      while (items.length > MAX_TURNS) {
        items.shift();
        const first = container.querySelector('.turn');
        if (first) first.remove();
      }
      sync();
      return bodyEl;
    }

    /* 把本轮的接口返回记到最后一个轮次上；重复调用=覆盖（实验12 审批续跑复用同一轮） */
    function commit(payload) {
      const item = items[items.length - 1];
      if (!item) return;
      item.payload = payload;
      delete item.error;
      sync();
    }

    function fail(message) {
      const item = items[items.length - 1];
      if (!item) return;
      item.error = message;
      delete item.payload;
      sync();
    }

    function last() {
      const all = container.querySelectorAll('.turn');
      return all.length ? $('.turn-body', all[all.length - 1]) : null;
    }

    /* 离开面板前：把折叠状态记回数据里 */
    function capture() {
      const all = container.querySelectorAll('.turn');
      all.forEach((el, i) => {
        if (items[i]) items[i].folded = el.classList.contains('folded');
      });
      sync();
    }

    if (panel) liveTurnLists.push({ capture });

    return { add, commit, fail, last, capture, count: () => round, items: () => items };
  }

  function singleTurnPanel(body, exp, { onRun, render, extraOpts }) {
    const inputId = 'in_' + exp.id;
    body.innerHTML = `
      <div class="card">
        <div class="input-row">
          <textarea id="${inputId}" rows="2" placeholder="${esc(exp.placeholder || '请输入…')}"></textarea>
          <button class="btn primary" id="run">运行</button>
        </div>
        ${extraOpts ? `<div class="toggles">${extraOpts}</div>` : ''}
        <div class="samples">${(exp.samples || []).map(s => `<button class="sample">${esc(s)}</button>`).join('')}</div>
      </div>
      <div id="out" class="turn-list"></div>`;

    const input = $('#' + inputId, body), runBtn = $('#run', body), out = $('#out', body);
    const turns = turnList(out, { panel: exp.id, paint: render });

    const go = async (q) => {
      q = (q ?? input.value).trim();
      if (!q || busy) return;
      input.value = '';   // 提交后清空：内容已转移到下方轮次块
      setBusy(true); runBtn.disabled = true; setStatus('执行中…', 'busy');
      const turnBody = turns.add(q);
      turnBody.innerHTML = loadingHtml();
      try {
        const data = await onRun(q, body);
        render(turnBody, data);
        turns.commit(data);   // 记住本轮数据，切走再回来能重放
        setStatus('完成', 'ready');
      } catch (e) {
        turnBody.innerHTML = `<div class="card"><div class="err-box">⚠️ ${esc(e.message)}</div></div>`;
        turns.fail(e.message);
        setStatus('出错', 'error');
      } finally {
        setBusy(false); runBtn.disabled = false;
        turnBody.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      }
    };
    runBtn.addEventListener('click', () => go());
    input.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); go(); } });
    $$('.sample', body).forEach(b => b.addEventListener('click', () => go(b.textContent)));
    return { go, input, out, turns };
  }

  /* 通用：闲聊式多轮面板（实验2 / 6） */
  function chatPanel(body, exp, { onTurn, render, extraOpts }) {
    const st = panelChat(exp.id);   // 气泡与模型上下文一起持久化

    // 恢复上次离开时的对话气泡，避免切走再切回后记录消失
    const restored = st.bubbles.length
      ? st.bubbles.map(m => m.role === 'user'
          ? `<div class="msg user"><div class="avatar">🙋</div><div class="bubble">${esc(m.text)}</div></div>`
          : `<div class="msg assistant"><div class="avatar">🌴</div><div class="bubble">${m.html}</div></div>`).join('')
      : '';

    body.innerHTML = `
      <div class="card" style="padding-bottom:14px">
        ${extraOpts ? `<div class="toggles" style="margin:0 0 12px">${extraOpts}</div>` : ''}
        <div class="chat-box" id="cb">
          <div class="msg assistant"><div class="avatar">🌴</div>
            <div class="bubble">${esc(exp.samples?.[0] ? '试试下面这些问题，这是一个多轮对话——第二问会用到第一问的上下文。' : '开始吧。')}</div></div>
          ${restored}
        </div>
        <div class="samples" id="sp">${(exp.samples||[]).map(s => `<button class="sample">${esc(s)}</button>`).join('')}</div>
      </div>
      <div class="composer"><div class="composer-inner">
        <textarea id="ci" rows="1" placeholder="${esc(exp.placeholder || '输入…')}"></textarea>
        <button class="btn-send" id="cs">➤</button>
      </div></div>`;

    const box = $('#cb', body), input = $('#ci', body), send = $('#cs', body);
    const grow = () => { input.style.height = 'auto'; input.style.height = Math.min(input.scrollHeight, 150) + 'px'; };
    input.addEventListener('input', grow);
    input.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); go(); } });
    send.addEventListener('click', go);
    $$('#sp .sample', body).forEach(b => b.addEventListener('click', () => go(b.textContent)));

    async function go(preset) {
      const q = (typeof preset === 'string' ? preset : input.value).trim();
      if (!q || busy) return;
      setBusy(true); send.disabled = true; input.value = ''; grow(); setStatus('思考中…', 'busy');

      box.insertAdjacentHTML('beforeend',
        `<div class="msg user"><div class="avatar">🙋</div><div class="bubble">${esc(q)}</div></div>`);
      const t = document.createElement('div');
      t.className = 'msg assistant';
      t.innerHTML = `<div class="avatar">🌴</div><div class="bubble"><div class="typing"><span></span><span></span><span></span></div></div>`;
      box.appendChild(t);
      const bubble = $('.bubble', t);
      box.scrollTop = box.scrollHeight;

      try {
        const data = await onTurn(q, st.history, body);
        const answer = data.answer || '';
        bubble.innerHTML = md(answer);
        const extraHtml = render ? render(data, st) : '';
        if (extraHtml) bubble.insertAdjacentHTML('beforeend', extraHtml);
        st.history.push({ role: 'user', content: q }, { role: 'assistant', content: answer });
        if (st.history.length > 16) st.history = st.history.slice(-16);
        // 记住界面气泡，切走 / 刷新后据此还原
        st.bubbles.push({ role: 'user', text: q });
        st.bubbles.push({ role: 'assistant', html: bubble.innerHTML });
        if (st.bubbles.length > MAX_BUBBLES) st.bubbles = st.bubbles.slice(-MAX_BUBBLES);
        psave();
        setStatus('第 ' + (st.history.length / 2) + ' 轮', 'ready');
      } catch (e) {
        bubble.innerHTML = `<div class="err-box">⚠️ ${esc(e.message)}</div>`;
        setStatus('出错', 'error');
      } finally { setBusy(false); send.disabled = false; input.focus(); box.scrollTop = box.scrollHeight; }
    }
  }

  /* =========================================================
     各实验渲染器
     ========================================================= */
  const RENDERERS = {

    /* 实验 1：多工具 Agent */
    exp1(b, exp) {
      singleTurnPanel(b, exp, {
        onRun: q => api('/api/exp/exp1', { question: q }),
        render: (out, d) => {
          out.innerHTML = `<div class="card">
            <div class="card-head"><span class="card-title">🌴 回答</span>
            <span class="card-hint">耗时 ${d.elapsed}s · 调用工具 ${d.steps.length} 次</span></div>
            <div class="bubble">${md(d.answer)}</div>
            ${stepsHtml(d.steps)}</div>`;
        },
      });
    },

    /* 实验 2：会话记忆 */
    exp2(b, exp) {
      chatPanel(b, exp, {
        onTurn: (q, hist) => api('/api/exp/exp2', { question: q, history: hist }),
        render: d => stepsHtml(d.steps) +
          `<div class="src-region" style="margin-top:8px">本轮为第 ${d.turns} 轮对话（历史已随请求带上）</div>`,
      });
    },

    /* 实验 3：结构化输出 */
    exp3(b, exp) {
      singleTurnPanel(b, exp, {
        onRun: q => api('/api/exp/exp3', { question: q }),
        render: (out, d) => {
          if (!d.ok) {
            out.innerHTML = `<div class="card"><div class="err-box">⚠️ 结构化解析失败：${esc(d.error || '')}
              <div class="hash-box" style="margin-top:9px">${esc((d.raw || '').slice(0, 500))}</div></div></div>`;
            return;
          }
          out.innerHTML = `<div class="card">
            <div class="card-head"><span class="card-title">📋 结构化推荐</span>
            <span class="card-hint">${d.recommendations.length} 条 · 已通过本地校验</span></div>
            <div class="rec-grid">${d.recommendations.map(r => `
              <div class="rec">
                <div class="rec-top"><span class="rec-name">${esc(r.destination)}</span>
                <span class="rec-flag ${r.available ? 'ok' : 'no'}">${r.available ? '可预订' : '不可订'}</span></div>
                <div class="rec-row"><b>最佳季节</b><span>${esc(r.best_season)}</span></div>
                <div class="rec-row"><b>预估预算</b><span>$${r.estimated_budget_usd}</span></div>
                <div class="rec-tags">${(r.highlights||[]).map(h => `<span class="rec-tag">${esc(h)}</span>`).join('')}</div>
              </div>`).join('')}</div>
            <div class="rec-note"><b>个性化说明：</b>${esc(d.personalized_note)}</div>
          </div>`;
        },
      });
    },

    /* 实验 4：工具箱复用 */
    exp4(b, exp) {
      singleTurnPanel(b, exp, {
        onRun: q => api('/api/exp/exp4', { question: q }),
        render: (out, d) => {
          const counts = Object.entries(d.tool_counts || {})
            .map(([k, v]) => `<span class="rec-tag">${esc(k)} × ${v}</span>`).join('');
          out.innerHTML = `<div class="card">
            <div class="card-head"><span class="card-title">🧰 工具箱复用</span>
            <span class="card-hint">同一套工具，被有序调用了 ${d.steps.length} 次</span></div>
            <div class="metrics">${Object.entries(d.tool_counts||{}).map(([k,v]) => `
              <div class="metric"><div class="metric-val">${v}</div><div class="metric-key">${esc(k)}</div></div>`).join('')}
            </div>
            <div class="bubble" style="margin-top:14px">${md(d.answer)}</div>
            ${stepsHtml(d.steps)}</div>`;
        },
      });
    },

    /* 实验 5：RAG */
    exp5(b, exp) {
      singleTurnPanel(b, exp, {
        extraOpts: `<label class="toggle"><input type="checkbox" id="optCheck"> 切换为「爱核对版」（对每个目的地再检索一次）</label>`,
        onRun: (q, body) => api('/api/exp/exp5', { question: q, options: { checker: $('#optCheck', body)?.checked } }),
        render: (out, d) => {
          out.innerHTML = `<div class="card">
            <div class="card-head"><span class="card-title">📚 RAG 回答</span>
            <span class="card-hint">${d.mode === 'checker' ? '爱核对版' : '普通版'} · 命中 ${d.sources.length} 条资料</span></div>
            <div class="bubble">${md(d.answer)}</div>
            ${sourcesHtml(d.sources)}</div>`;
        },
      });
    },

    /* 实验 6：上下文管理 */
    exp6(b, exp) {
      chatPanel(b, exp, {
        extraOpts: `<label class="toggle"><input type="checkbox" id="optSum"> 启用摘要工具（让模型主动把偏好写进摘要记录）</label>`,
        onTurn: (q, hist, body) => api('/api/exp/exp6', { question: q, history: hist, options: { summarize: $('#optSum', body)?.checked } }),
        render: d => {
          let h = stepsHtml(d.steps);
          if (d.summaries && d.summaries.length) {
            h += `<div class="steps"><div class="steps-title">📝 已记录的偏好摘要</div>
              ${d.summaries.map(s => `<div class="step"><div class="step-res">${esc(s)}</div></div>`).join('')}</div>`;
          }
          return h;
        },
      });
    },

    /* 实验 7：多智能体 */
    exp7(b, exp) {
      singleTurnPanel(b, exp, {
        onRun: q => api('/api/exp/exp7', { question: q }),
        render: (out, d) => {
          out.innerHTML = `<div class="card">
            <div class="card-head"><span class="card-title">👥 多智能体接力</span>
            <span class="card-hint">${d.trace.length} 个智能体 · 总耗时 ${d.elapsed}s</span></div>
            ${d.trace.map((s, i) => `
              <div class="card agent-card" style="box-shadow:none;margin-bottom:10px">
                <div class="agent-name">🤖 ${esc(s.agent)}</div>
                <div class="agent-role">职责：${esc(s.role)}${s.tools.length ? ` · 调用工具：${s.tools.map(esc).join('、')}` : ''}</div>
                <div class="agent-out">${md(s.output)}</div>
              </div>
              ${i < d.trace.length - 1 ? '<div class="flow-arrow">↓ 交接</div>' : ''}`).join('')}
          </div>`;
        },
      });
    },

    /* 实验 8：规划者 + 管家 */
    exp8(b, exp) {
      singleTurnPanel(b, exp, {
        onRun: q => api('/api/exp/exp8', { question: q }),
        render: (out, d) => {
          if (!d.plan_ok) {
            out.innerHTML = `<div class="card"><div class="err-box">⚠️ 计划解析失败，模型返回的不是合法 JSON
              <div class="hash-box" style="margin-top:9px">${esc((d.plan_raw || '').slice(0, 600))}</div></div></div>`;
            return;
          }
          const p = d.plan;
          out.innerHTML = `
            <div class="card">
              <div class="card-head"><span class="card-title">🗂 规划者产出的任务清单</span>
              <span class="card-hint">${p.destination} · ${p.trip_duration_days} 天 · 预算 $${p.total_estimated_budget_usd}</span></div>
              <table class="tbl">
                <thead><tr><th>优先级</th><th>#</th><th>任务</th><th>指派给</th><th>依赖</th></tr></thead>
                <tbody>${p.subtasks.map(t => `<tr>
                  <td><span class="risk ${t.priority === 'high' ? 'high' : t.priority === 'low' ? 'low' : 'medium'}">${esc(t.priority)}</span></td>
                  <td>${t.task_id}</td><td>${esc(t.description)}</td>
                  <td class="mono">${esc(t.assigned_agent)}</td>
                  <td class="muted">${(t.dependencies||[]).join(', ') || '—'}</td>
                </tr>`).join('')}</tbody>
              </table>
              ${p.notes ? `<div class="rec-note" style="margin-top:12px">${esc(p.notes)}</div>` : ''}
            </div>
            <div class="card">
              <div class="card-head"><span class="card-title">🎩 管家执行结果</span>
              <span class="card-hint">调用工具 ${d.steps.length} 次</span></div>
              <div class="bubble">${md(d.execution)}</div>
              ${stepsHtml(d.steps)}
            </div>`;
        },
      });
    },

    /* 实验 9：工作流 */
    async exp9(b, exp) {
      const graph = await api('/api/exp/exp9/graph', undefined, 'GET');
      const panel = singleTurnPanel(b, exp, {
        onRun: q => api('/api/exp/exp9', { question: q }),
        render: (out, d) => {
          out.innerHTML = `
            <div class="card">
              <div class="card-head"><span class="card-title">🔀 工作流执行</span>
              <span class="card-hint">${d.rounds} 轮 · ${d.approved ? '已获批准' : '未通过'} · ${d.elapsed}s</span></div>
              ${renderFlow(graph.edges)}
              <div style="margin-top:14px">${d.stages.map(s => `
                <div class="timeline-item">
                  <div class="tl-dot ${s.status.includes('批准') ? 'ok' : s.status.includes('打回') ? 'wait' : ''}">${s.round}</div>
                  <div class="tl-body">
                    <div class="tl-head">${esc(s.stage)}
                      <span class="badge-${s.status.includes('批准') ? 'ok' : s.status.includes('打回') ? 'no' : 'ok'}">${esc(s.status)}</span></div>
                    <div class="tl-text">${md(s.text)}</div>
                  </div>
                </div>`).join('')}</div>
            </div>
            <div class="card">
              <div class="card-head"><span class="card-title">✅ 最终推荐</span></div>
              <div class="bubble">${md(d.final)}</div>
            </div>`;
        },
      });
      // 在输入卡片上方插入流程图
      const first = $('.card', b);
      first.insertAdjacentHTML('beforebegin', `
        <div class="card">
          <div class="card-head"><span class="card-title">🗺 工作流拓扑</span>
          <span class="card-hint">声明式：先画图，再执行</span></div>
          ${renderFlow(graph.edges)}
          <div class="hash-box" style="margin-top:11px">${esc(graph.mermaid)}</div>
        </div>`);
    },

    /* 实验 10：元认知 */
    exp10(b, exp) {
      singleTurnPanel(b, exp, {
        onRun: q => api('/api/exp/exp10', { question: q }),
        render: (out, d) => {
          const fb = d.fallback;
          out.innerHTML = `
            <div class="card">
              <div class="card-head"><span class="card-title">🔄 回退状态</span>
              <span class="card-hint">${fb.triggered ? '已触发回退' : '主系统正常'}</span></div>
              ${fb.triggered ? `
                <div class="gate-action">
                  <div class="lbl">主系统失败</div>
                  <div class="txt mono">${esc(fb.reason || '')}</div>
                </div>
                ${fb.backup_used ? `<div class="rec-note">✅ 已自动切换到备用系统：${esc(fb.backup_result || '')}</div>` : ''}`
                : `<div class="tl-text">主系统直接命中，无需回退。试试其他目的地看回退效果。</div>`}
            </div>
            <div class="card">
              <div class="card-head"><span class="card-title">🌴 回答</span>
              <span class="card-hint">耗时 ${d.elapsed}s</span></div>
              <div class="bubble">${md(d.answer)}</div>
              ${stepsHtml(d.steps)}
            </div>
            <div class="card">
              <div class="card-head"><span class="card-title">🧪 第三方质量评估</span></div>
              ${scoresHtml(d.scores)}
              <div class="bubble" style="margin-top:11px">${md(d.evaluation)}</div>
            </div>`;
        },
      });
    },

    /* 实验 11：可观测性 */
    exp11(b, exp) {
      singleTurnPanel(b, exp, {
        onRun: q => api('/api/exp/exp11', { question: q }),
        render: (out, d) => {
          const m = d.metrics;
          const maxMs = Math.max(...d.timeline.map(t => t.ms), 1);
          out.innerHTML = `
            <div class="card">
              <div class="card-head"><span class="card-title">📊 可观测指标</span></div>
              <div class="metrics">
                <div class="metric"><div class="metric-val">${(m.total_ms/1000).toFixed(2)}s</div><div class="metric-key">总耗时</div></div>
                <div class="metric"><div class="metric-val">${m.tool_calls}</div><div class="metric-key">工具调用</div></div>
                <div class="metric"><div class="metric-val">${m.answer_chars}</div><div class="metric-key">回答字数</div></div>
                <div class="metric"><div class="metric-val">≈${m.est_tokens}</div><div class="metric-key">估算 tokens</div></div>
              </div>
              <div class="bars">${d.timeline.map(t => `
                <div class="bar-row"><span class="bar-label">${esc(t.stage)}</span>
                <span class="bar-track"><span class="bar-fill" style="width:${Math.round(t.ms/maxMs*100)}%"></span></span>
                <span class="bar-val">${t.ms} ms</span></div>`).join('')}</div>
            </div>
            <div class="card">
              <div class="card-head"><span class="card-title">🌴 回答</span></div>
              <div class="bubble">${md(d.answer)}</div>
              ${stepsHtml(d.steps)}
            </div>
            <div class="card">
              <div class="card-head"><span class="card-title">🧪 质量评分</span></div>
              ${scoresHtml(d.scores)}
              <div class="bubble" style="margin-top:11px">${md(d.evaluation)}</div>
            </div>`;
        },
      });
    },

    /* 实验 12：审批关卡 */
    exp12(b, exp) {
      // 审批状态存在 panelStore 里（切视图 / 刷新都不丢）
      const state = gateStateOf();

      b.innerHTML = `
        <div class="card">
          <div class="input-row">
            <textarea id="goal" rows="2" placeholder="${esc(exp.placeholder)}"></textarea>
            <button class="btn primary" id="run">提交目标</button>
          </div>
          <div class="samples">${(exp.samples||[]).map(s => `<button class="sample">${esc(s)}</button>`).join('')}</div>
        </div>
        <div id="gateOut" class="turn-list"></div>
        <div class="card">
          <div class="card-head"><span class="card-title">📜 审计日志</span>
            <span class="card-hint"><button class="btn sm" id="refreshLog">刷新</button>
            <button class="btn sm danger" id="clearLog" style="margin-left:7px">清空</button></span></div>
          <div id="logBox"><div class="muted" style="font-size:12.5px">暂无记录</div></div>
        </div>`;

      const out = $('#gateOut', b), goal = $('#goal', b);
      // currentTurn 必须在 turnList 之前声明：重放历史轮次时会调用 renderResult，
      // 它要读 currentTurn（此时为 null → 自动落在"最后一个轮次"上）。
      let currentTurn = null;
      const turns = turnList(out, { panel: 'exp12', paint: paintResult });
      currentTurn = turns.last();   // 指向最新一轮，审批续跑写回这里，不新开一轮

      async function refreshLog() {
        try {
          const d = await api('/api/exp/exp12/log', undefined, 'GET');
          const box = $('#logBox', b);
          if (!d.entries.length) { box.innerHTML = `<div class="muted" style="font-size:12.5px">暂无记录</div>`; return; }
          box.innerHTML = d.entries.map(e => `
            <div class="timeline-item">
              <div class="tl-dot ${e.decision === 'approve' ? 'ok' : e.decision === 'deny' ? 'no' : 'wait'}">
                ${e.decision === 'approve' ? '✓' : e.decision === 'deny' ? '✕' : '!'}</div>
              <div class="tl-body">
                <div class="tl-head">
                  <span class="risk ${e.risk_tier}">${e.risk_label || e.risk_tier}</span>
                  <span>${esc(e.decision)}</span>
                  <span class="muted" style="margin-left:auto;font-size:11px">${esc((e.ts||'').slice(11,19))}</span>
                </div>
                <div class="tl-text">${esc(e.action)}</div>
                <div class="tl-text muted">${esc(e.reason)}</div>
              </div>
            </div>`).join('');
        } catch (e) { toast('日志读取失败'); }
      }

      // turnList 的重放回调签名是 (容器, 数据)，这里转发给 renderResult(数据, 目标容器)
      function paintResult(el, d) { renderResult(d, el); }

      function renderResult(d, target) {
        // 输入框此时已清空，兜底优先用已记住的本轮目标
        state.goal = d.goal || state.goal || goal.value;
        // 写入当前轮次容器；没传就落到最后一轮（重放历史 / 日志刷新时会走到这）
        const out = target || currentTurn || (() => {
          const last = b.querySelector('.turn:last-child .turn-body');
          return last || null;
        })();
        if (!out) return;
        if (d.need_approval && d.pending) {
          state.pending = d.pending;
          out.innerHTML = `
            <div class="card">
              <div class="card-head"><span class="card-title">⏸ 高风险动作，已拦下等待审批</span></div>
              <div class="gate-action">
                <div class="lbl">待审批动作 · <span class="risk high">高风险</span></div>
                <div class="txt">${esc(d.pending.action)}</div>
              </div>
              <div class="gate-btns">
                <button class="btn primary" id="ap">✓ 批准</button>
                <button class="btn danger" id="dn">✕ 拒绝（让模型重提一版）</button>
                <button class="btn" id="es">↑ 上报</button>
              </div>
            </div>
            ${attemptsHtml(d.attempts)}`;
          $('#ap', out).onclick = () => resume('approve');
          $('#dn', out).onclick = () => resume('deny');
          $('#es', out).onclick = () => resume('escalate');
          setStatus('等待人工审批', 'busy');
        } else {
          state.pending = null;   // 本轮已了结，别把待审批动作留给下一次
          out.innerHTML = `
            <div class="card">
              <div class="card-head"><span class="card-title">${
                d.status === 'approved' ? '✅ 已批准执行' :
                d.status === 'escalated' ? '↑ 已上报' :
                d.status === 'max_revisions_reached' ? '⚠️ 达到最大修订次数' : '结束'}</span></div>
              ${d.denied_reason ? `<div class="rec-note" style="background:var(--red-soft);color:var(--red)">${esc(d.denied_reason)}</div>` : ''}
              ${d.final ? `<div class="gate-action"><div class="lbl">最终动作</div>
                <div class="txt">${esc(d.final.action)}</div>
                <div class="tl-text muted" style="margin-top:5px">${esc(d.final.reason)}</div></div>` : ''}
            </div>
            ${attemptsHtml(d.attempts)}`;
          setStatus('就绪', 'ready');
        }
        psave();   // 审批进度落盘
        if (!replaying) refreshLog();
      }

      async function resume(decision) {
        if (!state.pending) return;
        setBusy(true); setStatus('处理中…', 'busy');
        try {
          const d = await api('/api/exp/exp12/resume', {
            goal: state.goal,
            action: state.pending.action,
            human_decision: decision,
            attempt: state.pending.attempt ?? 0,
          });
          renderResult(d);
          turns.commit(d);   // 覆盖本轮数据：审批续跑属于同一轮，不新开一轮
        } catch (e) {
          (currentTurn || out).insertAdjacentHTML('beforeend',
            `<div class="card"><div class="err-box">⚠️ ${esc(e.message)}</div></div>`);
          setStatus('出错', 'error');
        } finally { setBusy(false); }
      }

      async function run() {
        const g = goal.value.trim();
        if (!g || busy) return;
        state.goal = g;      // 先记住本轮目标，再清空输入框
        goal.value = '';     // 提交后清空：内容已转移到下方轮次块
        psave();
        setBusy(true); setStatus('规划动作中…', 'busy');
        currentTurn = turns.add(g);
        currentTurn.innerHTML = loadingHtml('让模型提出动作并过风险关卡…');
        try {
          const d = await api('/api/exp/exp12', { question: g });
          renderResult(d);
          turns.commit(d);
          currentTurn.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
        } catch (e) {
          currentTurn.innerHTML = `<div class="card"><div class="err-box">⚠️ ${esc(e.message)}</div></div>`;
          turns.fail(e.message);
          setStatus('出错', 'error');
        } finally { setBusy(false); }
      }

      $('#run', b).addEventListener('click', run);
      goal.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); run(); } });
      $$('.sample', b).forEach(s => s.addEventListener('click', () => { goal.value = s.textContent; run(); }));
      $('#refreshLog', b).addEventListener('click', refreshLog);
      $('#clearLog', b).addEventListener('click', async () => {
        await api('/api/exp/exp12/log', undefined, 'DELETE');
        refreshLog(); toast('审计日志已清空');
      });
      refreshLog();
    },

    /* 实验 13：长期记忆图谱 */
    exp13(b, exp) {
      b.innerHTML = `
        <div class="card">
          <div class="card-head"><span class="card-title">🧠 记住一段话</span>
          <span class="card-hint">抽取三元组存入知识图谱</span></div>
          <div class="kg-input">
            <input type="text" id="kgIn" placeholder="例如：我想 10 月去东京，喜欢美食和摄影，预算 800 一天">
            <button class="btn primary" id="kgAdd">记住</button>
          </div>
          <div class="samples" id="kgSamples">
            ${['我想 10 月去东京，喜欢美食和摄影，预算 800 一天','计划去巴塞罗那，主要想看建筑，预算比较充足','喜欢海滩和潜水，想找个便宜点的地方','打算 4 月去日本，一个人，喜欢寺庙和历史']
              .map(s => `<button class="sample">${esc(s)}</button>`).join('')}
          </div>
        </div>
        <div class="card">
          <div class="card-head"><span class="card-title">🕸 知识图谱</span>
            <span class="card-hint"><button class="btn sm" id="kgReset">清空图谱</button></span></div>
          <div class="kg-stats" id="kgStats"></div>
          <div class="kg-triples" id="kgTriples"><div class="muted" style="font-size:12.5px">图谱还是空的，先在上面记一段话。</div></div>
        </div>
        <div class="card">
          <div class="card-head"><span class="card-title">💭 跨会话提问</span>
          <span class="card-hint">基于图谱回答，换新会话照样记得</span></div>
          <div class="input-row">
            <input type="text" id="kgQ" placeholder="例如：根据你记住的，推荐个目的地给我">
            <button class="btn primary" id="kgAsk">提问</button>
          </div>
          <div class="samples" id="kgAskSamples">
            ${['根据你记住的，推荐个目的地给我','我预算有限，有什么便宜又好玩的地方？','我喜欢 4 月出行，帮我挑一个']
              .map(s => `<button class="sample">${esc(s)}</button>`).join('')}
          </div>
          <div id="kgAns" class="turn-list"></div>
        </div>`;

      const stats = $('#kgStats', b), triples = $('#kgTriples', b);
      const kgTurns = turnList($('#kgAns', b), { panel: 'exp13', paint: paintAsk });

      function paint(graph) {
        stats.innerHTML = `
          <div class="metric"><div class="metric-val">${graph.triple_count}</div><div class="metric-key">三元组</div></div>
          <div class="metric"><div class="metric-val">${graph.nodes.length}</div><div class="metric-key">节点</div></div>
          <div class="metric"><div class="metric-val">${graph.edges.length}</div><div class="metric-key">关系</div></div>`;
        if (!graph.edges.length) {
          triples.innerHTML = `<div class="muted" style="font-size:12.5px">图谱还是空的，先在上面记一段话。</div>`;
          return;
        }
        triples.innerHTML = graph.edges.map(e =>
          `<span class="triple"><span class="s">${esc(e.from)}</span><span class="p">${esc(e.label)}</span><span class="o">${esc(e.to)}</span></span>`
        ).join('');
      }

      async function reload() { paint(await api('/api/exp/exp13/graph', undefined, 'GET')); }

      async function remember() {
        const t = $('#kgIn', b).value.trim();
        if (!t) return;
        try {
          const d = await api('/api/exp/exp13/remember', { text: t });
          paint(d.graph);
          toast(`抽到 ${d.added} 条三元组`);
          $('#kgIn', b).value = '';
        } catch (e) { toast('失败：' + e.message); }
      }

      $('#kgReset', b).addEventListener('click', async () => {
        const d = await api('/api/exp/exp13', undefined, 'DELETE');
        paint(d.graph); toast('图谱已清空');
      });

      // 一轮提问的渲染：抽成具名函数，切回来时用它重放（事件监听随之重建）
      function paintAsk(box, d) {
        box.innerHTML = `
          <div class="steps"><div class="steps-title">🔍 图谱检索命中的关系 · ${d.used.length} 条</div>
            <div class="kg-triples">${d.used.map(e =>
              `<span class="triple"><span class="s">${esc(e.from)}</span><span class="p">${esc(e.label)}</span><span class="o">${esc(e.to)}</span></span>`).join('')}</div></div>
          <div class="card" style="margin-top:12px;box-shadow:none"><div class="bubble">${md(d.answer)}</div></div>`;
      }

      async function ask(preset) {
        const q = (preset ?? $('#kgQ', b).value).trim();
        if (!q || busy) return;
        $('#kgQ', b).value = '';   // 提交后清空：内容已转移到下方轮次块
        setBusy(true); setStatus('检索图谱…', 'busy');
        const box = kgTurns.add(q);
        box.innerHTML = loadingHtml('从图谱检索并生成回答…');
        try {
          const d = await api('/api/exp/exp13/ask', { question: q });
          paintAsk(box, d);
          kgTurns.commit(d);
          setStatus('完成', 'ready');
        } catch (e) {
          box.innerHTML = `<div class="err-box" style="margin-top:12px">⚠️ ${esc(e.message)}</div>`;
          kgTurns.fail(e.message);
          setStatus('出错', 'error');
        } finally {
          setBusy(false);
          box.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
        }
      }

      // 记住区示例：只预填到输入框，不提交（方便改完再点「记住」）
      $$('#kgSamples .sample', b).forEach(s => s.addEventListener('click', () => { $('#kgIn', b).value = s.textContent; }));
      // 提问区示例：点击即提问，与其他实验的示例行为一致
      $$('#kgAskSamples .sample', b).forEach(s => s.addEventListener('click', () => ask(s.textContent)));

      $('#kgAdd', b).addEventListener('click', remember);
      $('#kgIn', b).addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); remember(); } });
      $('#kgAsk', b).addEventListener('click', () => ask());
      $('#kgQ', b).addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); ask(); } });

      reload();
    },

    /* 实验 14：加密收据 */
    exp14(b, exp) {
      b.innerHTML = `<div class="card">
        <div class="input-row">
          <button class="btn primary" id="run" style="width:100%">🔐 运行完整演示（签名 → 篡改 → 串链 → 篡改链 → 自动收据）</button>
        </div>
        <div class="exp-note" style="margin-top:11px">这一步不调用大模型，纯粹是密码学演示。Ed25519 签名 + SHA-256 哈希链。</div>
      </div><div id="out" class="turn-list"></div>`;

      const out = $('#out', b);
      const turns = turnList(out, { panel: 'exp14', paint: paintReceipt });

      $('#run', b).addEventListener('click', async () => {
        if (busy) return;
        setBusy(true); setStatus('签名中…', 'busy');
        const turnBody = turns.add('运行完整加密收据演示');
        turnBody.innerHTML = loadingHtml('生成密钥并签收据…');
        try {
          const d = await api('/api/exp/exp14', {});
          if (!d.ok) throw new Error(d.error || '运行失败');
          paintReceipt(turnBody, d);
          turns.commit(d);
          setStatus('完成', 'ready');
        } catch (e) {
          turnBody.innerHTML = `<div class="card"><div class="err-box">⚠️ ${esc(e.message)}</div></div>`;
          turns.fail(e.message);
          setStatus('出错', 'error');
        } finally {
          setBusy(false);
          turnBody.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
        }
      });

      // 一次演示的渲染：抽成具名函数供重放
      function paintReceipt(el, d) {
        el.innerHTML = `
            ${stepCard('① 签第一张收据', `公钥（Ed25519, 32 字节）：<div class="hash-box" style="margin-top:7px">${esc(d.public_key)}</div>
              <div style="margin-top:11px"><span class="badge-${d.step1.valid ? 'ok' : 'no'}">验签 ${d.step1.valid ? '通过' : '失败'}</span></div>`,
              `<table class="tbl"><tbody>
                ${Object.entries(d.step1.payload).map(([k,v]) =>
                  `<tr><td class="muted" style="width:170px">${esc(k)}</td><td class="mono">${esc(typeof v==='object'?JSON.stringify(v):String(v))}</td></tr>`).join('')}
              </tbody></table>`)}

            ${stepCard('② 篡改收据', `攻击者把 policy_id 从 <span class="mono">${esc(d.step2.original_policy)}</span>
              改成 <span class="mono">${esc(d.step2.tampered_policy)}</span>` +
              `<div style="margin-top:11px"><span class="badge-${d.step2.valid_after_tamper ? 'ok' : 'no'}">
                篡改后验签 ${d.step2.valid_after_tamper ? '通过（异常！）' : '失败（符合预期）'}</span></div>
              <div class="tl-text muted" style="margin-top:7px">改字段 → 规范字节变了 → SHA-256 变了 → 与签名时的哈希对不上 → 验签必然失败。</div>`)}

            ${stepCard('③ 把收据串成链', `模拟一次真实订票：查航班 → 占座 → 确认预订，每一步留一张收据。
              <div style="margin-top:11px"><span class="badge-${d.step3.all_valid ? 'ok' : 'no'}">
                整条链 ${d.step3.all_valid ? '全部有效' : '存在无效项'}</span></div>`,
              chainHtml(d.step3.chain, true))}

            ${stepCard('④ 篡改链条中间那张', `把占座时长从 30 分钟改成 9999 分钟——比实际授权宽松得多。
              攻击者改了参数，为了"自圆其说"也得改哈希；但哈希一改，签名（针对旧哈希算的）就对不上了。
              <div class="tl-text muted" style="margin-top:9px">预期结果：收据 #0 仍有效；#1 签名失败；#2 因为引用了 #1 的哈希，链接校验也随之失败（级联暴露）。</div>`,
              chainHtml(d.step4.chain, true))}

            ${stepCard('⑤ 自动收据包装器', `ReceiptedTool 把普通函数包一层，每次调用自动生成签名收据并串成链，
              而调用方完全感觉不到被包装过（返回值一字不改）。共调用 ${d.step5.calls} 次。`,
              chainHtml(d.step5.chain, true))}`;
      }

      function stepCard(title, desc, extra = '') {
        return `<div class="card">
          <div class="card-head"><span class="card-title">${title}</span></div>
          <div class="tl-text">${desc}</div>
          ${extra ? `<div style="margin-top:13px">${extra}</div>` : ''}
        </div>`;
      }

      function chainHtml(chain, showHash) {
        return chain.map(c => {
          const r = c.receipt || {};
          return `<div class="chain-line">
            <span class="chain-idx">${c.index}</span>
            <span class="chain-tool">${esc(c.tool)}</span>
            ${showHash ? `<span class="chain-hash">prev=${esc((r.previous_receipt_hash || 'null').slice(0, 22))}…</span>` : ''}
            <span class="checks">
              <span class="${c.signature_valid ? 'badge-ok' : 'badge-no'}">签名</span>
              <span class="${c.chain_link_valid ? 'badge-ok' : 'badge-no'}">链链接</span>
              <span class="${c.sequence_valid ? 'badge-ok' : 'badge-no'}">序号</span>
            </span>
          </div>`;
        }).join('');
      }
    },

    /* 实验 15：端到端集成 */
    async exp15(b, exp) {
      const meta = await api('/api/exp/exp15/stages', undefined, 'GET');
      b.innerHTML = `
        <div class="card">
          <div class="card-head"><span class="card-title">🔗 选择要执行的阶段</span>
          <span class="card-hint">按序执行，实时查看每阶段产出</span></div>
          <div class="stage-picker" id="picker">
            ${meta.stages.map(s => `<label class="stage-pick">
              <input type="checkbox" id="stg_${s.id}" value="${s.id}" checked>
              <span><b>${esc(s.name)}</b><br><span class="muted" style="font-size:11px">${esc(s.desc)}</span></span>
            </label>`).join('')}
          </div>
          <div class="input-row">
            <textarea id="pq" rows="2" placeholder="${esc(exp.placeholder)}"></textarea>
            <button class="btn primary" id="prun">执行流水线</button>
          </div>
          <div class="samples">${(exp.samples||[]).map(s => `<button class="sample">${esc(s)}</button>`).join('')}</div>
        </div>
        <div id="pout" class="turn-list"></div>`;

      const out = $('#pout', b), q = $('#pq', b);
      const turns = turnList(out, { panel: 'exp15', paint: paintPipeline });

      async function run() {
        const text = q.value.trim();
        if (!text || busy) return;
        const stages = $$('#picker input:checked', b).map(i => i.value);
        if (!stages.length) { toast('至少选择一个阶段'); return; }
        q.value = '';   // 提交后清空：内容已转移到下方轮次块
        setBusy(true); setStatus(`执行 ${stages.length} 个阶段…`, 'busy');
        const turnBody = turns.add(text);
        turnBody.innerHTML = loadingHtml('按序执行流水线…（多阶段可能耗时较久）');
        try {
          const d = await api('/api/exp/exp15', { question: text, options: { stages } });
          paintPipeline(turnBody, d);
          turns.commit(d);
          setStatus('完成', 'ready');
        } catch (e) {
          turnBody.innerHTML = `<div class="card"><div class="err-box">⚠️ ${esc(e.message)}</div></div>`;
          turns.fail(e.message);
          setStatus('出错', 'error');
        } finally {
          setBusy(false);
          turnBody.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
        }
      }

      // 一次流水线执行的渲染：抽成具名函数供重放
      function paintPipeline(el, d) {
        el.innerHTML = `<div class="card">
            <div class="card-head"><span class="card-title">📈 执行汇总</span>
              <span class="card-hint">${d.ok_count}/${d.runs.length} 成功 · 总耗时 ${(d.total_ms/1000).toFixed(1)}s</span></div>
            <div class="bars">${d.runs.map(r => {
              const max = Math.max(...d.runs.map(x => x.ms), 1);
              return `<div class="bar-row"><span class="bar-label">${esc(r.name)}</span>
                <span class="bar-track"><span class="bar-fill" style="width:${Math.round(r.ms/max*100)}%;background:${r.status==='error'?'var(--red)':'var(--accent)'}"></span></span>
                <span class="bar-val">${r.ms} ms</span></div>`;
            }).join('')}</div>
          </div>
          ${d.runs.map(r => `
            <div class="pipe-item ${r.status}">
              <div class="pipe-head">
                <span class="tl-dot ${r.status === 'ok' ? 'ok' : 'no'}">${r.status === 'ok' ? '✓' : '✕'}</span>
                ${esc(r.name)}
                ${r.extra && r.extra.sources ? `<span class="muted" style="font-size:11px">来源 ${r.extra.sources.join('、')}</span>` : ''}
                ${r.extra && r.extra.agents ? `<span class="muted" style="font-size:11px">${r.extra.agents.join(' → ')}</span>` : ''}
                ${r.extra && r.extra.approved !== undefined ? `<span class="badge-${r.extra.approved ? 'ok' : 'no'}">${r.extra.approved ? '已批准' : '未通过'}</span>` : ''}
                <span class="pipe-ms">${r.ms} ms</span>
              </div>
              <div class="pipe-out">${esc(r.output)}</div>
            </div>`).join('')}`;
      }

      $('#prun', b).addEventListener('click', run);
      q.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); run(); } });
      $$('.sample', b).forEach(s => s.addEventListener('click', () => { q.value = s.textContent; }));
    },
  };

  function renderFlow(edges) {
    return `<div style="display:flex;flex-wrap:wrap;gap:6px;align-items:center;font-size:12.5px">
      ${edges.map(e => `<span class="triple">
        <span class="s">${esc(e.from)}</span>
        <span class="p">${e.label ? esc(e.label) + ' →' : '→'}</span>
        <span class="o">${esc(e.to)}</span></span>`).join('')}
    </div>`;
  }

  function scoresHtml(scores) {
    if (!scores || !Object.keys(scores).length) return `<div class="muted" style="font-size:12.5px">未解析到结构化评分（见下方评估全文）</div>`;
    const names = { completeness: '完整性', accuracy: '准确性', helpfulness: '有用性', overall: '总体' };
    return `<div class="score-chips">${Object.entries(scores).map(([k, v]) =>
      `<div class="score-chip"><div class="v ${v <= 2 ? 'low' : ''}">${v}/5</div><div class="k">${names[k] || k}</div></div>`).join('')}</div>`;
  }

  function attemptsHtml(attempts) {
    if (!attempts || !attempts.length) return '';
    return `<div class="card">
      <div class="card-head"><span class="card-title">🔁 提议与审批轨迹</span>
      <span class="card-hint">共 ${attempts.length} 次尝试</span></div>
      ${attempts.map(a => `
        <div class="timeline-item">
          <div class="tl-dot ${a.decision === 'approve' ? 'ok' : a.decision === 'deny' ? 'no' : 'wait'}">
            ${a.decision === 'approve' ? '✓' : a.decision === 'deny' ? '✕' : a.decision === 'pending' ? '!' : '↑'}</div>
          <div class="tl-body">
            <div class="tl-head">
              <span class="risk ${a.risk_tier}">${a.risk_label || a.risk_tier}</span>
              <span>第 ${a.attempt} 次 · ${esc(a.decision)}</span>
            </div>
            <div class="tl-text">${esc(a.action)}</div>
            <div class="tl-text muted">${esc(a.reason)}</div>
          </div>
        </div>`).join('')}
    </div>`;
  }

  /* ---------- 启动 ---------- */
  async function boot() {
    try {
      const [h, m] = await Promise.all([
        api('/api/health', undefined, 'GET'),
        api('/api/exps', undefined, 'GET'),
      ]);
      modelNameEl.textContent = h.model || 'deepseek-chat';
      META = m;
      setStatus('就绪', 'ready');
    } catch (e) {
      setStatus('服务未就绪', 'error');
      stageEl.innerHTML = `<div class="wrap"><div class="card"><div class="err-box">⚠️ 无法连接后端：${esc(e.message)}</div></div></div>`;
      return;
    }
    renderNav();
    render();
  }

  // 刷新 / 关页面前把当前面板快照写盘，这样 F5 回来还是离开时的样子
  window.addEventListener('pagehide', () => { try { captureCurrentPanel(); } catch {} });

  /* ---------- 快捷键：Esc 连按两次 = 清空当前面板的对话 ----------
     单次 Esc：若焦点在输入框且有内容，先清掉草稿；无论哪种情况都提示一下，
     免得连击窗口里的第一下让人以为没反应。
     和输入框的 Enter 提交是两条独立分支，互不影响。 */
  const ESC_GAP = 1200;
  let lastEscAt = 0;

  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape' && e.key !== 'Esc') return;
    if (e.repeat) return;                       // 长按 Esc 会连发重复事件，不算连击
    if (busy) { toast('请等待当前任务完成'); return; }
    if (sidebar.classList.contains('open')) {   // 窄屏下 Esc 先关侧边栏
      sidebar.classList.remove('open');
      lastEscAt = 0;
      return;
    }

    const now = Date.now();
    if (now - lastEscAt <= ESC_GAP) { lastEscAt = 0; clearCurrentPanel(); return; }
    lastEscAt = now;

    const el = document.activeElement;
    const isText = el && (el.tagName === 'TEXTAREA'
      || (el.tagName === 'INPUT' && ['text', 'search', ''].includes(el.type || '')));
    if (isText && el.value) {
      el.value = '';
      // 触发 input 事件，让自适应高度之类的监听重新计算
      try { el.dispatchEvent(new Event('input', { bubbles: true })); } catch {}
      toast('已清空输入框 · 再按一次 Esc 清空当前对话');
    } else {
      toast('再按一次 Esc 清空当前对话');
    }
  });

  btnMenu.addEventListener('click', () => {
    if (window.innerWidth <= 860) sidebar.classList.toggle('open');
    else sidebar.classList.toggle('collapsed');
  });

  // 退出登录：作废服务端会话并清 Cookie，回到口令页
  const btnLogout = $('#btnLogout');
  if (btnLogout) btnLogout.addEventListener('click', async () => {
    try {
      await fetch('/_logout', { method: 'POST' });
    } catch {}
    clearPanelStore();   // 同一标签页换人用时，别把上一个人的对话留在这儿
    location.href = '/_gate';
  });

  document.addEventListener('click', e => {
    if (window.innerWidth <= 860 && sidebar.classList.contains('open')
        && !sidebar.contains(e.target) && e.target !== btnMenu) sidebar.classList.remove('open');
  });

  boot();
})();
