/* 辦公室訂餐系統 - 前端 SPA */
(function () {
  "use strict";

  const state = { me: null, unread: 0, route: null };

  // ---------- 小工具 ----------
  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));
  const esc = (s) => String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  const nts = (n) => "NT$" + (Number(n) || 0).toLocaleString("zh-TW");
  const int = (v) => { const n = parseInt(v, 10); return isNaN(n) ? 0 : n; };

  function fmtDt(s) {
    if (!s) return "—";
    let d;
    if (typeof s === "string" && !s.includes("T")) {
      d = new Date(s.replace(" ", "T") + "Z");
    } else {
      d = new Date(s);
    }
    if (isNaN(d.getTime())) return s;
    return d.toLocaleString("zh-TW", { timeZone: "Asia/Taipei" });
  }

  const STATUS = {
    open: { label: "進行中", cls: "open" },
    closed: { label: "已結單", cls: "closed" },
  };
  const PAY = {
    unpaid: { label: "未付款", cls: "unpaid" },
    pending: { label: "付款中", cls: "pending" },
    paid: { label: "已付款", cls: "paid" },
  };

  function toast(msg, type) {
    const el = $("#toast");
    el.textContent = msg;
    el.className = "toast " + (type || "");
    setTimeout(() => el.classList.add("hidden"), 2600);
  }

  async function api(path, opts) {
    opts = opts || {};
    opts.headers = Object.assign({ "Content-Type": "application/json" }, opts.headers || {});
    const resp = await fetch(path, opts);
    let data = {};
    try { data = await resp.json(); } catch (e) { /* ignore */ }
    if (!resp.ok) {
      const err = new Error(data.error || ("HTTP " + resp.status));
      err.status = resp.status;
      throw err;
    }
    return data;
  }

  const apiJson = (path, method, body) =>
    api(path, { method, body: body == null ? undefined : JSON.stringify(body) });

  // ---------- 列印 ----------
  function printHtml(title, bodyHtml) {
    const w = window.open("", "_blank");
    if (!w) { toast("請允許彈出視窗以列印", "err"); return; }
    w.document.write(`
      <!DOCTYPE html>
      <html lang="zh-Hant"><head><meta charset="utf-8">
      <title>${esc(title)}</title>
      <style>
        body { font-family: "Microsoft JhengHei", "PingFang TC", sans-serif; color: #111; margin: 20px 24px; }
        h1 { font-size: 20px; margin: 0 0 4px; }
        .meta { color: #666; font-size: 13px; margin-bottom: 14px; }
        h2 { font-size: 15px; margin: 16px 0 6px; border-bottom: 1px solid #ccc; padding-bottom: 4px; }
        table { width: 100%; border-collapse: collapse; font-size: 13px; }
        th, td { border: 1px solid #bbb; padding: 5px 8px; text-align: left; vertical-align: top; }
        th { background: #eee; font-weight: 600; }
        td.num, th.num { text-align: right; white-space: nowrap; }
        .tot { font-weight: 700; background: #f5f5f5; }
        .muted { color: #666; }
        .mb { margin-bottom: 12px; }
        @media print { body { margin: 10mm; } }
      </style></head><body>
      <h1>${esc(title)}</h1>
      <div class="meta">列印時間：${fmtDt(new Date().toISOString())}${state.me ? "　列印者：" + esc(state.me.name) : ""}</div>
      ${bodyHtml}
      <script>window.onload = function(){ window.print(); }</script>
      </body></html>`);
    w.document.close();
    w.focus();
  }

  // ---------- 認證 ----------
  async function refreshMe() {
    try {
      const data = await api("/api/auth/me");
      state.me = data.user;
      state.unread = data.unread;
      return true;
    } catch (e) {
      state.me = null;
      return false;
    }
  }

  // ---------- 導覽 ----------
  function renderNav() {
    const nav = $("#navbar");
    const links = $("#nav-links");
    const userBox = $("#nav-user");
    if (!state.me) { nav.classList.add("hidden"); return; }
    nav.classList.remove("hidden");

    const items = [
      { href: "#/orders", label: "訂單" },
      { href: "#/vendors", label: "廠商商品" },
      { href: "#/notifications", label: "通知" + (state.unread ? ' <span class="badge">' + state.unread + "</span>" : "") },
    ];
    if (state.me.role === "admin") items.push({ href: "#/users", label: "帳號管理" });

    links.innerHTML = items.map(i =>
      '<a href="' + i.href + '" class="' + (state.route === i.href ? "active" : "") + '">' + i.label + "</a>"
    ).join("");

    userBox.innerHTML =
      '<span>' + esc(state.me.name) + (state.me.role === "admin" ? ' <span class="chip admin">管理員</span>' : "") + "</span>" +
      '<button id="btn-logout">登出</button>';

    const btn = $("#btn-logout");
    if (btn) btn.onclick = async () => {
      await api("/api/auth/logout", { method: "POST" });
      state.me = null;
      location.hash = "#/login";
    };
  }

  // ---------- 路由 ----------
  async function router() {
    const hash = location.hash || "#/login";
    const m = hash.match(/^#\/([^/?]+)/);
    const base = m ? m[1] : "";
    const parts = hash.replace(/^#\//, "").split("/").filter(Boolean);
    const query = new URLSearchParams(hash.split("?")[1] || "");
    const raw = hash.split("?")[0];

    if (!state.me) {
      if (base === "login") return viewLogin();
      if (base === "s") return viewShare(parts.slice(1).join("/"), query);
      return viewLogin();
    }

    state.route = raw;
    renderNav();

    if (base === "login") { location.hash = "#/orders"; return; }
    if (base === "s") return viewShare(parts.slice(1).join("/"), query);
    if (base === "orders") {
      if (parts.length >= 3 && parts[2] === "payments") return viewPayments(int(parts[1]));
      if (parts.length >= 2) return viewOrderDetail(int(parts[1]), query);
      return viewOrders();
    }
    if (base === "vendors") return viewVendors();
    if (base === "users") return state.me.role === "admin" ? viewUsers() : viewOrders();
    if (base === "notifications") return viewNotifications();
    viewOrders();
  }

  // ---------- 登入 ----------
  function viewLogin() {
    $("#navbar").classList.add("hidden");
    const v = $("#view");
    v.innerHTML = `
      <div class="auth-wrap">
        <div class="auth-card">
          <h1>訂餐 / 下午茶訂購系統</h1>
          <form id="form-login">
            <label>Email</label><input type="email" name="email" required autocomplete="username">
            <label>密碼</label><input type="password" name="password" required autocomplete="current-password">
            <button class="primary" type="submit">登入</button>
          </form>
          <div class="auth-switch">還沒有帳號？<a id="link-register">申請帳號</a></div>
        </div>
      </div>`;

    $("#form-login").onsubmit = async (e) => {
      e.preventDefault();
      const f = e.target;
      try {
        const data = await apiJson("/api/auth/login", "POST", {
          email: f.email.value, password: f.password.value,
        });
        state.me = data.user;
        toast("登入成功", "ok");
        location.hash = "#/orders";
      } catch (err) { toast(err.message, "err"); }
    };

    $("#link-register").onclick = () => {
      v.innerHTML = `
        <div class="auth-wrap">
          <div class="auth-card">
            <h1>申請帳號</h1>
            <form id="form-register">
              <label>姓名</label><input name="name" required>
              <label>Email</label><input type="email" name="email" required>
              <label>密碼（至少 6 碼）</label><input type="password" name="password" required minlength="6">
              <label>邀請碼（如系統有設定）</label><input name="register_token">
              <button class="primary" type="submit">送出申請</button>
            </form>
            <div class="auth-switch">已有帳號？<a id="link-back">返回登入</a></div>
          </div>
        </div>`;
      $("#link-back").onclick = () => viewLogin();
      $("#form-register").onsubmit = async (e) => {
        e.preventDefault();
        const f = e.target;
        try {
          await apiJson("/api/auth/register", "POST", {
            name: f.name.value, email: f.email.value,
            password: f.password.value, register_token: f.register_token.value,
          });
          toast("註冊成功，請登入", "ok");
          viewLogin();
        } catch (err) { toast(err.message, "err"); }
      };
    };
  }

  // ---------- 訂單列表 ----------
  async function viewOrders() {
    const v = $("#view");
    let data;
    try { data = await api("/api/orders"); }
    catch (err) { return errPage(v, err); }

    const isAdmin = state.me.role === "admin";
    v.innerHTML = `
      <div class="page-head">
        <h1>訂單列表</h1>
        <div class="flex">
          <button id="btn-print-orders">列印</button>
          ${isAdmin ? '<button class="primary" id="btn-new-order">＋ 新增訂單</button>' : ""}
        </div>
      </div>
      ${data.orders.length === 0 ? '<div class="empty">目前沒有訂單</div>' : ""}
      ${data.orders.map(o => `
        <div class="card order-card" data-id="${o.id}">
          <div class="spread">
            <div>
              <div style="font-weight:700;font-size:15px">${esc(o.title)}
                <span class="chip ${STATUS[o.status] ? STATUS[o.status].cls : ""}">${STATUS[o.status] ? STATUS[o.status].label : o.status}</span>
              </div>
              <div class="muted">${esc(o.vendor_name || "未指定廠商")} · ${o.user_count} 人 · ${o.item_count} 項</div>
            </div>
            <div class="amount ${o.status === "closed" ? "ok-color" : ""}">${nts(o.total)}</div>
          </div>
          <div class="row mt">
            <span class="chip ${o.status === "open" ? "unpaid" : "paid"}">我的：${nts(o.my_total)}（${o.my_count} 項）</span>
          </div>
          ${isAdmin ? `
          <div class="row mt">
            <span class="chip ${o.paid_total >= o.total ? "paid" : "unpaid"}">已收款 ${nts(o.paid_total)}</span>
            ${o.paid_total < o.total ? `<span class="chip unpaid">未收款 ${nts(o.total - o.paid_total)}</span>` : ""}
          </div>` : ""}
        </div>`).join("")}
    `;

    $("#btn-print-orders").onclick = () => {
      const rows = data.orders.map(o => `
        <tr>
          <td>#${o.id}</td>
          <td>${esc(o.title)}</td>
          <td>${STATUS[o.status] ? STATUS[o.status].label : o.status}</td>
          <td>${esc(o.vendor_name || "未指定廠商")}</td>
          <td class="num">${o.user_count} 人</td>
          <td class="num">${o.item_count} 項</td>
          <td class="num">${nts(o.total)}</td>
          ${isAdmin ? `<td class="num">已收 ${nts(o.paid_total)}${o.paid_total < o.total ? '<br><span class="muted">未收 ' + nts(o.total - o.paid_total) + "</span>" : ""}</td>` : ""}
        </tr>`).join("");
      printHtml("訂單列表", `
        <table>
          <thead><tr><th>編號</th><th>訂單</th><th>狀態</th><th>廠商</th><th class="num">人數</th><th class="num">項目</th><th class="num">總金額</th>${isAdmin ? '<th class="num">收款</th>' : ""}</tr></thead>
          <tbody>${rows || '<tr><td colspan="8" class="muted">目前沒有訂單</td></tr>'}</tbody>
        </table>`);
    };

    if (isAdmin) {
      $("#btn-new-order").onclick = () => modalOrderForm(null, async () => { await viewOrders(); });
    }
    $$(".order-card").forEach(c => {
      c.onclick = () => { location.hash = "#/orders/" + c.dataset.id; };
    });
  }

  // ---------- 新增/編輯訂單 Modal ----------
  async function modalOrderForm(order, onSaved) {
    const vendors = (await api("/api/vendors")).vendors;
    let selectedVids = order && order.vendor_ids ? order.vendor_ids.slice() : (order && order.vendor_id ? [order.vendor_id] : []);
    const mask = document.createElement("div");
    mask.className = "modal-mask";
    mask.innerHTML = `
      <div class="modal">
        <h3>${order ? "編輯訂單" : "新增訂單"}</h3>
        <label>訂單標題</label><input id="f-title" value="${order ? esc(order.title) : ""}">
        <label>廠商（可複選）</label>
        <div id="f-vendor-list" class="vendor-check-list">
          ${vendors.map(x => `
            <label class="check">
              <input type="checkbox" class="f-vendor-cb" value="${x.id}" ${selectedVids.indexOf(x.id) >= 0 ? "checked" : ""}>
              ${esc(x.name)}
            </label>`).join("")}
          ${vendors.length === 0 ? '<div class="empty">尚未建立廠商，請先到「廠商商品」新增。</div>' : ""}
        </div>
        <label>取餐/送達日期</label><input id="f-order_date" value="${order ? esc(order.order_date || "") : ""}">
        <label>截止訂購時間</label><input id="f-deadline" value="${order ? esc(order.deadline || "") : ""}">
        <label>備註</label><textarea id="f-note" rows="2">${order ? esc(order.note || "") : ""}</textarea>
        <div class="flex mt">
          <button class="primary" id="f-save">儲存</button>
          <button id="f-cancel">取消</button>
        </div>
      </div>`;
    document.body.appendChild(mask);
    $("#f-cancel", mask).onclick = () => mask.remove();
    $("#f-save", mask).onclick = async () => {
      const vids = $$(".f-vendor-cb:checked", mask).map(cb => int(cb.value));
      const body = {
        title: $("#f-title", mask).value,
        vendor_ids: vids,
        order_date: $("#f-order_date", mask).value,
        deadline: $("#f-deadline", mask).value,
        note: $("#f-note", mask).value,
      };
      try {
        if (order) await apiJson("/api/orders/" + order.id, "PUT", body);
        else await apiJson("/api/orders", "POST", body);
        mask.remove();
        toast("已儲存", "ok");
        onSaved();
      } catch (err) { toast(err.message, "err"); }
    };
  }

  // ---------- QR 連結訂購 Modal ----------
  function modalShare(oid, orderTitle) {
    const mask = document.createElement("div");
    mask.className = "modal-mask";
    mask.innerHTML = `
      <div class="modal">
        <h3>QR 連結訂購</h3>
        <p class="muted">產生一個限時連結，掃碼者不需登入即可點餐（以電話 / Email / LINE 辨識）。</p>
        <label>有效期限</label>
        <select id="s-minutes">
          <option value="60">1 小時</option>
          <option value="180">3 小時</option>
          <option value="360">6 小時</option>
          <option value="720">12 小時</option>
          <option value="1440" selected>24 小時</option>
        </select>
        <div id="s-result" class="mt">
          <div id="s-qr" class="qr-box"></div>
          <div class="spread"><span id="s-url" class="muted break"></span></div>
          <div class="flex mt">
            <button class="primary" id="s-copy">複製連結</button>
            <button id="s-regen">重新產生</button>
          </div>
        </div>
        <div class="flex mt">
          <button class="primary" id="s-gen">產生 QR</button>
          <button id="s-cancel">關閉</button>
        </div>
      </div>`;
    document.body.appendChild(mask);

    const qrBox = $("#s-qr", mask);
    const urlEl = $("#s-url", mask);
    const resBox = $("#s-result", mask);
    resBox.style.display = "none";
    let currentUrl = "";

    const gen = async () => {
      try {
        const data = await apiJson("/api/orders/" + oid + "/share", "POST", {
          minutes: int($("#s-minutes", mask).value),
        });
        currentUrl = data.url;
        qrBox.innerHTML = "";
        new QRCode(qrBox, { text: data.url, width: 180, height: 180 });
        urlEl.textContent = data.url;
        resBox.style.display = "";
        toast("QR 已產生，有效至 " + data.expires_at.replace("T", " "), "ok");
      } catch (err) { toast(err.message, "err"); }
    };

    $("#s-cancel", mask).onclick = () => mask.remove();
    $("#s-gen", mask).onclick = gen;
    $("#s-regen", mask).onclick = gen;
    $("#s-copy", mask).onclick = async () => {
      try {
        await navigator.clipboard.writeText(currentUrl);
        toast("已複製連結", "ok");
      } catch (err) {
        const ta = document.createElement("textarea");
        ta.value = currentUrl;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        ta.remove();
        toast("已複製連結", "ok");
      }
    };
  }

  // ---------- 訂單明細 ----------
  async function viewOrderDetail(oid, query) {
    query = query || new URLSearchParams();
    if (query.get("lp") === "ok") toast("LINE Pay 付款完成", "ok");
    const v = $("#view");
    let d;
    try { d = await api("/api/orders/" + oid); }
    catch (err) { return errPage(v, err); }

    const o = d.order;
    const canEdit = o.status === "open" || d.is_admin;
    const myQty = {};
    const myItemMap = {};
    d.my_items.forEach(it => { myQty[it.product_id] = it.quantity; myItemMap[it.product_id] = it; });
    const myTotal = d.my_items.reduce((s, it) => s + it.line_total, 0);
    const mePay = d.my_payment;
    const allUsers = Object.keys(d.totals);

    const itemsByUser = {};
    d.items.forEach(it => {
      (itemsByUser[it.user_id] = itemsByUser[it.user_id] || { name: it.user_name, items: [] });
      itemsByUser[it.user_id].items.push(it);
    });

    v.innerHTML = `
      <div class="page-head">
        <div>
          <h1>${esc(o.title)} <span class="chip ${STATUS[o.status] ? STATUS[o.status].cls : ""}">${STATUS[o.status] ? STATUS[o.status].label : o.status}</span></h1>
          <div class="muted">${d.vendors.length ? "廠商：" + d.vendors.map(v => esc(v.name)).join("、") : "未指定廠商"} · 建立於 ${fmtDt(o.created_at)}</div>
        </div>
        <div class="flex">
          <button id="btn-back">← 回列表</button>
          <button id="btn-print-order">列印</button>
          ${d.is_admin ? '<button id="btn-payments" class="primary">收款看板</button>' : ""}
          ${d.is_admin && o.status === "open" ? '<button id="btn-share">QR 連結訂購</button>' : ""}
          ${d.is_admin && o.status === "open" ? '<button id="btn-close">結單</button>' : ""}
          ${d.is_admin && o.status === "closed" ? '<button id="btn-reopen">重新開單</button>' : ""}
          ${d.is_admin ? '<button id="btn-edit">編輯</button><button id="btn-del" class="danger">刪除</button>' : ""}
        </div>
      </div>

      ${o.order_date || o.deadline || o.note ? `
      <div class="card">
        <div class="detail-row"><span class="k">取餐日期</span><span>${esc(o.order_date || "—")}</span></div>
        <div class="detail-row"><span class="k">截止時間</span><span>${esc(o.deadline || "—")}</span></div>
        ${o.note ? '<div class="detail-row"><span class="k">備註</span><span>' + esc(o.note) + "</span></div>" : ""}
      </div>` : ""}

      ${canEdit ? `
      <div class="card">
        <h3>點餐</h3>
        ${d.products.length === 0 ? '<div class="empty">此廠商尚未建立商品</div>' : `
        <div class="product-grid">
          ${d.products.map(p => {
            const ordered = myItemMap[p.id];
            const hasOpts = p.options && p.options.length > 0;
            return `
            <div class="product-item">
              <div class="pname">${esc(p.name)}</div>
              <div class="pprice">${nts(p.price)}</div>
              ${p.note ? '<div class="muted">' + esc(p.note) + "</div>" : ""}
              ${ordered && ordered.options_desc ? '<div class="p-optdesc">' + esc(ordered.options_desc) + "</div>" : ""}
              ${hasOpts ? `
              <div class="qty-input" data-pid="${p.id}">
                <button class="primary" data-act="config">${ordered ? "修改 " + ordered.quantity + " 份" : "選購"}</button>
                ${ordered ? '<button class="danger" data-act="remove">移除</button>' : ""}
              </div>` : `
              <div class="qty-input" data-pid="${p.id}">
                <button data-act="minus">−</button>
                <input type="number" min="0" value="${myQty[p.id] || 0}">
                <button data-act="plus">＋</button>
              </div>`}
            </div>`;
          }).join("")}
        </div>`}
      </div>` : ""}

      <div class="card">
        <h3>我的訂購 ${canEdit ? "" : "（已結單）"}</h3>
        ${d.my_items.length === 0 ? '<div class="empty">尚未訂購任何商品</div>' : `
        <table>
          <thead><tr><th>商品</th><th class="num">單價</th><th class="num">數量</th><th class="num">小計</th>${canEdit ? "<th></th>" : ""}</tr></thead>
          <tbody>
            ${d.my_items.map(it => `
              <tr>
                <td>${esc(it.product_name)}${it.options_desc ? '<div class="p-optdesc">' + esc(it.options_desc) + "</div>" : ""}</td>
                <td class="num">${nts(it.unit_price)}</td>
                <td class="num">${it.quantity}</td>
                <td class="num">${nts(it.line_total)}</td>
                ${canEdit ? `<td class="num"><button class="danger" data-del-item="${it.id}">移除</button></td>` : ""}
              </tr>`).join("")}
            <tr><td colspan="${canEdit ? 4 : 3}" style="font-weight:700">合計</td><td class="num amount">${nts(myTotal)}</td>${canEdit ? "<td></td>" : ""}</tr>
          </tbody>
        </table>`}
      </div>

      ${mePay ? `
      <div class="card">
        <h3>我的付款狀態</h3>
        <div class="detail-row"><span class="k">應付金額</span><span class="amount">${nts(mePay.total)}</span></div>
        <div class="detail-row"><span class="k">收款狀態</span><span><span class="chip ${(PAY[mePay.status] || {}).cls || "unpaid"}">${(PAY[mePay.status] || { label: mePay.status }).label}</span></span></div>
        ${mePay.method ? '<div class="detail-row"><span class="k">付款方式</span><span>' + esc(mePay.method) + "</span></div>" : ""}
        ${mePay.paid_at ? '<div class="detail-row"><span class="k">付款時間</span><span>' + fmtDt(mePay.paid_at) + "</span></div>" : ""}
        ${mePay.status !== "paid" ? `<div class="flex mt"><button id="btn-pay" class="ok">線上付款（LINE Pay）</button></div>` : ""}
      </div>` : ""}

      <div class="card">
        <h3>全部訂購明細（${allUsers.length} 人）</h3>
        ${d.items.length === 0 ? '<div class="empty">尚無人訂購</div>' : `
          ${Object.entries(itemsByUser).map(([uid, g]) => {
            const t = (d.totals[uid] || {}).total || 0;
            return `
            <div class="mb">
              <div class="spread"><strong>${esc(g.name)}</strong><span class="amount">${nts(t)}</span></div>
              <table>
                <tbody>
                  ${g.items.map(it => `<tr><td>${esc(it.product_name)}${it.options_desc ? '<div class="p-optdesc">' + esc(it.options_desc) + "</div>" : ""}</td><td class="num">${nts(it.unit_price)} × ${it.quantity}</td><td class="num">${nts(it.line_total)}</td></tr>`).join("")}
                </tbody>
              </table>
            </div>`;
          }).join("")}
          <div class="spread mt"><strong>總計</strong><span class="amount">${nts(Object.values(d.totals).reduce((s, x) => s + (x.total || 0), 0))}</span></div>`}
      </div>

      ${d.payments_summary ? `
      <div class="card">
        <h3>收款狀態</h3>
        <div class="row mb">
          <span class="chip paid">已收款 ${nts(d.payments_summary.paid_total)}</span>
          <span class="chip unpaid">未收款 ${nts(d.payments_summary.unpaid_total)}</span>
          <span class="chip ${d.payments_summary.unpaid_total === 0 ? "paid" : "unpaid"}">${d.payments_summary.paid_users}/${d.payments_summary.total_users} 人已付款</span>
        </div>
        <table>
          <thead><tr><th>成員</th><th class="num">應付</th><th>狀態</th></tr></thead>
          <tbody>
            ${d.payments_summary.board.map(b => `
              <tr>
                <td>${esc(b.user_name)}</td>
                <td class="num amount ${b.status === "paid" ? "ok-color" : ""}">${nts(b.live_total || b.amount)}</td>
                <td><span class="chip ${(PAY[b.status] || {}).cls || "unpaid"}">${(PAY[b.status] || { label: b.status }).label}</span></td>
              </tr>`).join("")}
          </tbody>
        </table>
      </div>` : ""}
    `;

    // 事件
    $("#btn-back").onclick = () => { location.hash = "#/orders"; };
    $("#btn-print-order").onclick = () => {
      const detailHtml = `
        ${o.order_date || o.deadline || o.note ? `
        <table class="mb">
          <tr><th style="width:100px">取餐日期</th><td>${esc(o.order_date || "—")}</td></tr>
          <tr><th>截止時間</th><td>${esc(o.deadline || "—")}</td></tr>
          ${o.note ? `<tr><th>備註</th><td>${esc(o.note)}</td></tr>` : ""}
        </table>` : ""}
        <h2>全部訂購明細（${Object.keys(itemsByUser).length} 人）</h2>
        ${d.items.length === 0 ? '<div class="muted">尚無人訂購</div>' : `
        ${Object.entries(itemsByUser).map(([uid, g]) => {
          const t = (d.totals[uid] || {}).total || 0;
          return `
          <div class="mb">
            <strong>${esc(g.name)}</strong>　<span>${nts(t)}</span>
            <table>
              <tbody>
                ${g.items.map(it => `<tr><td>${esc(it.product_name)}${it.options_desc ? '<div class="muted">' + esc(it.options_desc) + "</div>" : ""}</td><td class="num">${nts(it.unit_price)} × ${it.quantity}</td><td class="num">${nts(it.line_total)}</td></tr>`).join("")}
              </tbody>
            </table>
          </div>`;
        }).join("")}
        <table><tbody>
          <tr class="tot"><td>總計</td><td class="num">${nts(Object.values(d.totals).reduce((s, x) => s + (x.total || 0), 0))}</td></tr>
        </tbody></table>`}
        ${d.payments_summary ? `
        <h2>收款狀態</h2>
        <table>
          <thead><tr><th>成員</th><th class="num">應付</th><th>狀態</th><th>方式</th></tr></thead>
          <tbody>
            ${d.payments_summary.board.map(b => `
              <tr>
                <td>${esc(b.user_name)}</td>
                <td class="num">${nts(b.live_total || b.amount)}</td>
                <td>${(PAY[b.status] || { label: b.status }).label}</td>
                <td>${esc(b.method || "—")}</td>
              </tr>`).join("")}
            <tr class="tot"><td>合計</td><td class="num">已收 ${nts(d.payments_summary.paid_total)}</td><td class="num">未收 ${nts(d.payments_summary.unpaid_total)}</td><td></td></tr>
          </tbody>
        </table>` : ""}`;
      printHtml(o.title, detailHtml);
    };
    if (d.is_admin) {
      $("#btn-payments").onclick = () => { location.hash = "#/orders/" + oid + "/payments"; };
      if ($("#btn-share")) $("#btn-share").onclick = () => {
        modalShare(oid, o.title);
      };
      if ($("#btn-close")) $("#btn-close").onclick = async () => {
        if (!confirm("確定結單？結單後一般成員將無法再修改訂購內容。")) return;
        try { await apiJson("/api/orders/" + oid + "/close", "POST", {}); toast("已結單", "ok"); viewOrderDetail(oid); }
        catch (err) { toast(err.message, "err"); }
      };
      if ($("#btn-reopen")) $("#btn-reopen").onclick = async () => {
        try { await apiJson("/api/orders/" + oid + "/reopen", "POST", {}); toast("已重新開單", "ok"); viewOrderDetail(oid); }
        catch (err) { toast(err.message, "err"); }
      };
      if ($("#btn-edit")) $("#btn-edit").onclick = () => {
        modalOrderForm(o, () => viewOrderDetail(oid));
      };
      if ($("#btn-del")) $("#btn-del").onclick = async () => {
        if (!confirm("確定刪除此訂單？所有訂購與收款資料都會移除。")) return;
        try { await apiJson("/api/orders/" + oid, "DELETE", {}); location.hash = "#/orders"; }
        catch (err) { toast(err.message, "err"); }
      };
    }

    // 點餐數量調整 / 選項選購
    $$(".qty-input", v).forEach(w => {
      const pid = int(w.dataset.pid);
      const input = $("input", w);
      if (input) {
        const setQty = async (q) => {
          input.value = q;
          try {
            await apiJson("/api/orders/" + oid + "/items", "POST", { product_id: pid, quantity: q });
            toast(q > 0 ? "已更新數量" : "已移除該商品", "ok");
            viewOrderDetail(oid);
          } catch (err) { toast(err.message, "err"); }
        };
        $('[data-act="minus"]', w).onclick = () => setQty(Math.max(0, int(input.value) - 1));
        $('[data-act="plus"]', w).onclick = () => setQty(int(input.value) + 1);
        input.onchange = () => setQty(Math.max(0, int(input.value)));
      }
      const cfg = $('[data-act="config"]', w);
      if (cfg) cfg.onclick = () => {
        const p = d.products.find(x => x.id === pid);
        if (p) modalOrderItem(oid, p, myItemMap[pid] || null, () => viewOrderDetail(oid));
      };
      const rm = $('[data-act="remove"]', w);
      if (rm) rm.onclick = async () => {
        const it = myItemMap[pid];
        if (!it) return;
        try {
          await apiJson("/api/orders/" + oid + "/items/" + it.id, "DELETE", {});
          toast("已移除", "ok");
          viewOrderDetail(oid);
        } catch (err) { toast(err.message, "err"); }
      };
    });

    // 移除我的明細
    $$("[data-del-item]", v).forEach(btn => {
      btn.onclick = async () => {
        try {
          await apiJson("/api/orders/" + oid + "/items/" + btn.dataset.delItem, "DELETE", {});
          toast("已移除", "ok");
          viewOrderDetail(oid);
        } catch (err) { toast(err.message, "err"); }
      };
    });

    // 線上付款
    const payBtn = $("#btn-pay");
    if (payBtn) payBtn.onclick = async () => {
      try {
        const data = await apiJson("/api/payments/" + mePay.id + "/linepay", "POST", {});
        const win = window.open(data.paymentUrl.web, "_blank");
        if (!win) location.href = data.paymentUrl.web;
        toast("LINE Pay 付款視窗已開啟", "ok");
      } catch (err) { toast(err.message, "err"); }
    };
  }

  // ---------- 選項選購 Modal ----------
  function modalOrderItem(oid, product, prefill, onSaved) {
    const defs = product.options || [];
    const current = (prefill && prefill.options) || {};
    let fields = "";
    defs.forEach(d => {
      const prices = d.prices || {};
      const priceTag = (c) => (prices[c] ? " ＋NT$" + prices[c] : "");
      if (d.type === "select") {
        fields += `
          <label>${esc(d.label)}</label>
          <select data-opt="${esc(d.key)}">
            <option value="">（不選）</option>
            ${d.choices.map(c => `<option value="${esc(c)}" data-price="${prices[c] || ""}" ${current[d.key] === c ? "selected" : ""}>${esc(c)}${priceTag(c)}</option>`).join("")}
          </select>`;
      } else if (d.type === "multi") {
        const picked = current[d.key] || [];
        fields += `
          <div class="mb"><label>${esc(d.label)}</label>
          ${d.choices.map(c => `<label class="check"><input type="checkbox" data-opt="${esc(d.key)}" value="${esc(c)}" data-price="${prices[c] || ""}" ${picked.indexOf(c) >= 0 ? "checked" : ""}> ${esc(c)}${priceTag(c)}</label>`).join("")}
          </div>`;
      } else {
        fields += `
          <label>${esc(d.label)}</label>
          <input data-opt="${esc(d.key)}" value="${esc(current[d.key] || "")}" placeholder="${esc(d.placeholder || "")}">`;
      }
    });

    const mask = document.createElement("div");
    mask.className = "modal-mask";
    mask.innerHTML = `
      <div class="modal">
        <h3>${esc(product.name)}</h3>
        <div class="pprice mb">${nts(product.price)} / 份</div>
        ${defs.length ? fields : ""}
        <label>數量</label>
        <div class="qty-input">
          <button data-act="minus">−</button>
          <input id="opt-qty" type="number" min="1" value="${prefill ? prefill.quantity : 1}">
          <button data-act="plus">＋</button>
        </div>
        <div class="opt-total spread"><span>小計（含加價）</span><span id="opt-total"></span></div>
        <div class="flex mt">
          <button class="primary" id="opt-save">${prefill ? "儲存修改" : "加入訂單"}</button>
          <button id="opt-cancel">取消</button>
        </div>
      </div>`;
    document.body.appendChild(mask);

    const qtyInput = $("#opt-qty", mask);
    const totalEl = $("#opt-total", mask);
    const changeQty = (q) => { qtyInput.value = Math.max(1, q); };
    const recompute = () => {
      let s = 0;
      $$("select[data-opt]", mask).forEach(sel => {
        const o = sel.selectedOptions[0];
        if (o && o.dataset.price) s += int(o.dataset.price);
      });
      $$("input[type=checkbox][data-opt]:checked", mask).forEach(cb => {
        if (cb.dataset.price) s += int(cb.dataset.price);
      });
      totalEl.textContent = nts((product.price + s) * Math.max(1, int(qtyInput.value)));
    };
    $('[data-act="minus"]', mask).onclick = () => { changeQty(int(qtyInput.value) - 1); recompute(); };
    $('[data-act="plus"]', mask).onclick = () => { changeQty(int(qtyInput.value) + 1); recompute(); };
    qtyInput.onchange = recompute;
    $$("select[data-opt]", mask).forEach(sel => { sel.onchange = recompute; });
    $$("input[type=checkbox][data-opt]", mask).forEach(cb => { cb.onchange = recompute; });
    $("#opt-cancel", mask).onclick = () => mask.remove();
    recompute();

    $("#opt-save", mask).onclick = async () => {
      const options = {};
      $$("[data-opt]", mask).forEach(el => {
        if (el.type === "checkbox") {
          if (el.checked) (options[el.dataset.opt] = options[el.dataset.opt] || []).push(el.value);
          return;
        }
        if (el.value !== "") options[el.dataset.opt] = el.value;
      });
      try {
        await apiJson("/api/orders/" + oid + "/items", "POST", {
          product_id: product.id,
          quantity: Math.max(1, int(qtyInput.value)),
          options,
        });
        mask.remove();
        toast("已更新訂購", "ok");
        onSaved();
      } catch (err) { toast(err.message, "err"); }
    };
  }

  // ---------- QR 一頁式訂購 ----------
  async function viewShare(token, query) {
    $("#navbar").classList.add("hidden");
    const v = $("#view");
    let d;
    try { d = await api("/api/share/" + encodeURIComponent(token)); }
    catch (err) { return errPage(v, err); }

    v.innerHTML = `
      <div class="share-head">
        <h1>${esc(d.order.title)}</h1>
        ${d.order.deadline ? '<div class="muted">截止：' + fmtDt(d.order.deadline) + "</div>" : ""}
        ${d.order.note ? '<div class="muted" style="white-space:pre-wrap">' + esc(d.order.note) + "</div>" : ""}
      </div>`;

    if (!d.identified) {
      // 身份辨識
      const card = document.createElement("div");
      card.className = "card";
      card.innerHTML = `
        <h3>確認身份</h3>
        <p class="muted">輸入您的電話 / Email 或 LINE 辨識碼，之後可查詢與修改自己的訂購。</p>
        <form id="s-ident">
          <label>電話 / Email / LINE</label>
          <input name="identifier" required placeholder="例如 0912-345-678">
          <button class="primary" type="submit">繼續</button>
        </form>
        <p class="muted mt">訂購人帳號將自動建立。</p>`;
      v.appendChild(card);
      $("#s-ident", card).onsubmit = async (e) => {
        e.preventDefault();
        try {
          await apiJson("/api/share/" + encodeURIComponent(token) + "/identify", "POST", {
            identifier: e.target.identifier.value.trim(),
          });
          toast("身份確認完成", "ok");
          viewShare(token);
        } catch (err) { toast(err.message, "err"); }
      };
      return;
    }

    // 已辨識：顯示點餐介面
    const myMap = {};
    d.my_items.forEach(it => { myMap[it.product_id] = it; });
    const myTotal = d.my_items.reduce((s, it) => s + it.line_total, 0);

    d.vendors.forEach(vendor => {
      const sec = document.createElement("div");
      sec.className = "card";
      sec.innerHTML = `
        <div class="share-vendor"><h3>${esc(vendor.name)}</h3>${vendor.note ? '<span class="muted">' + esc(vendor.note) + "</span>" : ""}</div>
        <div class="product-grid">
          ${vendor.products.length === 0 ? '<div class="empty">此廠商尚未建立商品</div>' : vendor.products.map(p => {
            const ordered = myMap[p.id];
            const hasOpts = p.options && p.options.length > 0;
            return `
            <div class="product-item">
              <div class="pname">${esc(p.name)}</div>
              <div class="pprice">${nts(p.price)}</div>
              ${p.note ? '<div class="muted">' + esc(p.note) + "</div>" : ""}
              ${ordered && ordered.options_desc ? '<div class="p-optdesc">' + esc(ordered.options_desc) + "</div>" : ""}
              ${hasOpts ? `
              <div class="qty-input">
                <button class="primary" data-share-config="${p.id}">${ordered ? "修改 " + ordered.quantity + " 份" : "選購"}</button>
                ${ordered ? '<button class="danger" data-share-rm="' + p.id + '">移除</button>' : ""}
              </div>` : `
              <div class="qty-input">
                <button data-share-minus="${p.id}">−</button>
                <input type="number" min="0" value="${ordered ? ordered.quantity : 0}" data-share-qty="${p.id}">
                <button data-share-plus="${p.id}">＋</button>
              </div>`}
            </div>`;
          }).join("")}
        </div>`;
      v.appendChild(sec);
    });

    const mine = document.createElement("div");
    mine.className = "card";
    mine.innerHTML = `
      <h3>我的訂購</h3>
      ${d.my_items.length === 0 ? '<div class="empty">尚未訂購任何商品</div>' : `
      <table>
        <thead><tr><th>商品</th><th class="num">單價</th><th class="num">數量</th><th class="num">小計</th><th></th></tr></thead>
        <tbody>
          ${d.my_items.map(it => `
            <tr>
              <td>${esc(it.product_name)}${it.options_desc ? '<div class="p-optdesc">' + esc(it.options_desc) + "</div>" : ""}</td>
              <td class="num">${nts(it.unit_price)}</td>
              <td class="num">${it.quantity}</td>
              <td class="num">${nts(it.line_total)}</td>
              <td class="num"><button class="danger" data-share-delitem="${it.id}">移除</button></td>
            </tr>`).join("")}
          <tr><td colspan="3" style="font-weight:700">合計</td><td class="num amount">${nts(myTotal)}</td><td></td></tr>
        </tbody>
      </table>`}
      <p class="muted mt"><button id="s-reset" class="linklike">使用其他身份</button></p>`;
    v.appendChild(mine);

    // 事件：點餐
    const setQty = async (pid, q) => {
      try {
        await apiJson("/api/orders/" + d.order.id + "/items", "POST", { product_id: pid, quantity: q });
        toast(q > 0 ? "已更新數量" : "已移除該商品", "ok");
        viewShare(token);
      } catch (err) { toast(err.message, "err"); }
    };
    $$("[data-share-qty]", v).forEach(inp => {
      const pid = int(inp.dataset.shareQty);
      $$("[data-share-minus]", v).forEach(b => {
        if (int(b.dataset.shareMinus) === pid) b.onclick = () => setQty(pid, Math.max(0, int(inp.value) - 1));
      });
      $$("[data-share-plus]", v).forEach(b => {
        if (int(b.dataset.sharePlus) === pid) b.onclick = () => setQty(pid, int(inp.value) + 1);
      });
      inp.onchange = () => setQty(pid, Math.max(0, int(inp.value)));
    });
    $$("[data-share-config]", v).forEach(btn => {
      btn.onclick = () => {
        const pid = int(btn.dataset.shareConfig);
        let prod = null;
        d.vendors.forEach(vendor => vendor.products.forEach(p => { if (p.id === pid) prod = p; }));
        if (prod) modalOrderItem(d.order.id, prod, myMap[pid] || null, () => viewShare(token));
      };
    });
    $$("[data-share-rm]", v).forEach(btn => {
      btn.onclick = async () => {
        const pid = int(btn.dataset.shareRm);
        const it = myMap[pid];
        if (!it) return;
        try {
          await apiJson("/api/orders/" + d.order.id + "/items/" + it.id, "DELETE", {});
          toast("已移除", "ok");
          viewShare(token);
        } catch (err) { toast(err.message, "err"); }
      };
    });
    $$("[data-share-delitem]", v).forEach(btn => {
      btn.onclick = async () => {
        try {
          await apiJson("/api/orders/" + d.order.id + "/items/" + btn.dataset.shareDelitem, "DELETE", {});
          toast("已移除", "ok");
          viewShare(token);
        } catch (err) { toast(err.message, "err"); }
      };
    });
    $("#s-reset", v).onclick = async () => {
      try { await apiJson("/api/auth/logout", "POST", {}); } catch (e) { /* ignore */ }
      viewShare(token);
    };
  }

  // ---------- 收款看板 ----------
  async function viewPayments(oid) {
    const v = $("#view");
    let d;
    try { d = await api("/api/orders/" + oid + "/payments"); }
    catch (err) { return errPage(v, err); }

    v.innerHTML = `
      <div class="page-head">
        <div>
          <h1>收款看板 — ${esc(d.order.title)}</h1>
          <div class="muted">已收款 ${nts(d.paid_total)} · 未收款 ${nts(d.unpaid_total)}</div>
        </div>
        <div class="flex">
          <button id="btn-back">← 回訂單</button>
          <button class="primary" id="btn-remind-all">催款全部未付款</button>
        </div>
      </div>

      <div class="card">
        <table>
          <thead><tr><th>成員</th><th class="num">應付</th><th>狀態</th><th>方式</th><th>管道</th><th>動作</th></tr></thead>
          <tbody>
            ${d.board.map(b => `
              <tr>
                <td>${esc(b.user_name)}</td>
                <td class="num amount ${b.status === "paid" ? "ok-color" : ""}">${nts(b.live_total || b.amount)}</td>
                <td><span class="chip ${(PAY[b.status] || {}).cls || "unpaid"}">${(PAY[b.status] || { label: b.status }).label}</span></td>
                <td class="muted">${esc(b.method || "—")}${b.paid_at ? "<br>" + fmtDt(b.paid_at) : ""}</td>
                <td class="muted">${b.has_line ? "LINE" : ""}${b.has_line && b.email ? "<br>" : ""}${b.email ? "Email" : ""}${!b.has_line && !b.email ? "—" : ""}</td>
                <td>
                  ${b.status !== "paid" ? `
                  <div class="flex">
                    <button data-paid="${b.id}" data-method="cash">現金收款</button>
                    <button data-paid="${b.id}" data-method="transfer">轉帳收款</button>
                    <button data-lp="${b.id}">LINE Pay 連結</button>
                  </div>
                  <div class="row mt">
                    <select data-channel="${b.id}">
                      <option value="all">管道：全部</option>
                      <option value="app">系統通知</option>
                      <option value="line">LINE</option>
                      <option value="email">Email</option>
                    </select>
                    <button data-remind="${b.id}">催款</button>
                  </div>` : `
                  <button data-unmark="${b.id}" class="danger">改回未付款</button>
                  `}
                </td>
              </tr>`).join("")}
          </tbody>
        </table>
      </div>

      ${d.reminder_logs.length ? `
      <div class="card">
        <h3>催款紀錄</h3>
        <table>
          <thead><tr><th>時間</th><th>對象</th><th>管道</th><th>結果</th></tr></thead>
          <tbody>
            ${d.reminder_logs.slice(0, 50).map(l => `
              <tr>
                <td>${fmtDt(l.created_at)}</td>
                <td>#${l.user_id}</td>
                <td>${esc({ app: "系統通知", line: "LINE", email: "Email" }[l.channel] || l.channel)}</td>
                <td class="${l.status === "sent" ? "ok-color" : "muted"}">${esc({ sent: "已送出", failed: "失敗", skipped: "略過" }[l.status] || l.status)}${l.detail ? " · " + esc(l.detail) : ""}</td>
              </tr>`).join("")}
          </tbody>
        </table>
      </div>` : ""}
    `;

    $("#btn-back").onclick = () => { location.hash = "#/orders/" + oid; };
    $("#btn-remind-all").onclick = async () => {
      if (!confirm("確定對所有未付款成員送出催款通知？")) return;
      try {
        const res = await apiJson("/api/orders/" + oid + "/remind-all", "POST", {});
        toast("已送出：" + res.summary.reminded + " 人", "ok");
        viewPayments(oid);
      } catch (err) { toast(err.message, "err"); }
    };
    $$("[data-paid]", v).forEach(btn => {
      btn.onclick = async () => {
        try {
          await apiJson("/api/payments/" + btn.dataset.paid + "/mark-paid", "POST", { method: btn.dataset.method });
          toast("已標記收款", "ok");
          viewPayments(oid);
        } catch (err) { toast(err.message, "err"); }
      };
    });
    $$("[data-unmark]", v).forEach(btn => {
      btn.onclick = async () => {
        if (!confirm("改回未付款？")) return;
        try {
          await apiJson("/api/payments/" + btn.dataset.unmark + "/unmark", "POST", {});
          toast("已改回未付款", "ok");
          viewPayments(oid);
        } catch (err) { toast(err.message, "err"); }
      };
    });
    $$("[data-lp]", v).forEach(btn => {
      btn.onclick = async () => {
        try {
          const data = await apiJson("/api/payments/" + btn.dataset.lp + "/linepay", "POST", {});
          const win = window.open(data.paymentUrl.web, "_blank");
          if (!win) location.href = data.paymentUrl.web;
        } catch (err) { toast(err.message, "err"); }
      };
    });
    $$("[data-remind]", v).forEach(btn => {
      btn.onclick = async () => {
        const pid = btn.dataset.remind;
        const sel = $('[data-channel="' + pid + '"]', v);
        const channel = sel ? sel.value : "all";
        try {
          const res = await apiJson("/api/payments/" + pid + "/remind", "POST", { channel });
          const sent = res.results.filter(x => x.status === "sent").length;
          toast("已催款 " + esc(res.user_name) + "（送出 " + sent + " 管道）", "ok");
          viewPayments(oid);
        } catch (err) { toast(err.message, "err"); }
      };
    });
  }

  // ---------- 廠商與商品 ----------
  async function viewVendors() {
    const v = $("#view");
    let data;
    try { data = await api("/api/vendors"); }
    catch (err) { return errPage(v, err); }
    const isAdmin = state.me.role === "admin";

    const productsByVendor = {};
    if (isAdmin) {
      const pd = await api("/api/products?active=0");
      pd.products.forEach(p => {
        (productsByVendor[p.vendor_id] = productsByVendor[p.vendor_id] || []).push(p);
      });
    }

    v.innerHTML = `
      <div class="page-head">
        <h1>廠商與商品</h1>
        <div class="flex">
          <button id="btn-print-vendors">列印</button>
          ${isAdmin ? '<button class="primary" id="btn-new-vendor">＋ 新增廠商</button>' : ""}
        </div>
      </div>
      ${data.vendors.length === 0 ? '<div class="empty">尚未建立廠商資料</div>' : ""}
      ${data.vendors.map(x => `
        <div class="card">
          <div class="spread">
            <div>
              <strong>${esc(x.name)}</strong>
              <div class="muted">${esc(x.phone || "")}${x.address ? " · " + esc(x.address) : ""}${x.note ? " · " + esc(x.note) : ""}</div>
              <div class="muted">${x.product_count} 項商品</div>
            </div>
            ${isAdmin ? `
              <div class="flex">
                <button data-edit-vendor="${x.id}">編輯</button>
                <button data-del-vendor="${x.id}" class="danger">刪除</button>
                <button data-add-product="${x.id}" class="primary">＋ 商品</button>
              </div>` : ""}
          </div>
          ${isAdmin && productsByVendor[x.id] ? `
          <div class="mt">
            <table>
              <thead><tr><th>商品</th><th class="num">價格</th><th>備註</th><th>選項</th><th>狀態</th><th></th></tr></thead>
              <tbody>
                ${productsByVendor[x.id].map(p => `
                  <tr>
                    <td>${esc(p.name)}</td>
                    <td class="num">${nts(p.price)}</td>
                    <td class="muted">${esc(p.note || "")}</td>
                    <td class="muted">${p.options && p.options.length ? p.options.length + " 項自訂" : "—"}</td>
                    <td>${p.active ? "啟用" : '<span style="color:var(--danger)">停用</span>'}</td>
                    <td>
                      <div class="flex">
                        <button data-edit-product="${p.id}">編輯</button>
                        <button data-toggle-product="${p.id}" class="danger">${p.active ? "停用" : "啟用"}</button>
                      </div>
                    </td>
                  </tr>`).join("")}
              </tbody>
            </table>
          </div>` : ""}
        </div>`).join("")}
    `;

    $("#btn-print-vendors").onclick = () => {
      const html = data.vendors.map(x => {
        const prods = productsByVendor[x.id] || [];
        return `
        <div class="mb">
          <h2>${esc(x.name)}</h2>
          <div class="muted">${esc(x.phone || "")}${x.address ? " · " + esc(x.address) : ""}${x.note ? " · " + esc(x.note) : ""}</div>
          ${prods.length ? `
          <table>
            <thead><tr><th>商品</th><th class="num">價格</th><th>備註</th><th>選項</th><th>狀態</th></tr></thead>
            <tbody>
              ${prods.map(p => `
                <tr>
                  <td>${esc(p.name)}</td>
                  <td class="num">${nts(p.price)}</td>
                  <td class="muted">${esc(p.note || "")}</td>
                  <td class="muted">${p.options && p.options.length ? p.options.length + " 項自訂" : "—"}</td>
                  <td>${p.active ? "啟用" : "停用"}</td>
                </tr>`).join("")}
            </tbody>
          </table>` : '<div class="muted">尚無商品</div>'}
        </div>`;
      }).join("");
      printHtml("廠商與商品", html || '<div class="muted">尚未建立廠商資料</div>');
    };

    if (!isAdmin) return;

    $("#btn-new-vendor").onclick = () => modalVendor(null, () => viewVendors());
    $$("[data-edit-vendor]", v).forEach(btn => {
      const vd = data.vendors.find(x => x.id == btn.dataset.editVendor);
      btn.onclick = () => modalVendor(vd, () => viewVendors());
    });
    $$("[data-del-vendor]", v).forEach(btn => {
      btn.onclick = async () => {
        if (!confirm("確定刪除此廠商？（有訂單的廠商無法刪除）")) return;
        try { await apiJson("/api/vendors/" + btn.dataset.delVendor, "DELETE", {}); toast("已刪除", "ok"); viewVendors(); }
        catch (err) { toast(err.message, "err"); }
      };
    });
    $$("[data-add-product]", v).forEach(btn => {
      btn.onclick = () => modalProduct(null, int(btn.dataset.addProduct), () => viewVendors());
    });
    $$("[data-edit-product]", v).forEach(btn => {
      btn.onclick = async () => {
        const pid = int(btn.dataset.editProduct);
        const pd = await api("/api/products?active=0");
        const prod = pd.products.find(x => x.id === pid);
        if (prod) modalProduct(prod, null, () => viewVendors());
      };
    });
    $$("[data-toggle-product]", v).forEach(btn => {
      btn.onclick = async () => {
        const pid = int(btn.dataset.toggleProduct);
        const pd = await api("/api/products?active=0");
        const prod = pd.products.find(x => x.id === pid);
        if (!prod) return;
        try {
          await apiJson("/api/products/" + pid, "PUT", { active: prod.active ? 0 : 1 });
          toast(prod.active ? "已停用" : "已啟用", "ok");
          viewVendors();
        } catch (err) { toast(err.message, "err"); }
      };
    });
  }

  async function modalVendor(vendor, onSaved) {
    const mask = document.createElement("div");
    mask.className = "modal-mask";
    mask.innerHTML = `
      <div class="modal">
        <h3>${vendor ? "編輯廠商" : "新增廠商"}</h3>
        <label>名稱</label><input id="f-name" value="${vendor ? esc(vendor.name) : ""}">
        <label>電話</label><input id="f-phone" value="${vendor ? esc(vendor.phone || "") : ""}">
        <label>地址</label><input id="f-address" value="${vendor ? esc(vendor.address || "") : ""}">
        <label>備註</label><input id="f-note" value="${vendor ? esc(vendor.note || "") : ""}">
        <div class="flex mt"><button class="primary" id="f-save">儲存</button><button id="f-cancel">取消</button></div>
      </div>`;
    document.body.appendChild(mask);
    $("#f-cancel", mask).onclick = () => mask.remove();
    $("#f-save", mask).onclick = async () => {
      const body = {
        name: $("#f-name", mask).value,
        phone: $("#f-phone", mask).value,
        address: $("#f-address", mask).value,
        note: $("#f-note", mask).value,
      };
      try {
        if (vendor) await apiJson("/api/vendors/" + vendor.id, "PUT", body);
        else await apiJson("/api/vendors", "POST", body);
        mask.remove(); toast("已儲存", "ok"); onSaved();
      } catch (err) { toast(err.message, "err"); }
    };
  }

  async function modalProduct(product, vendorId, onSaved) {
    const defs = (product && Array.isArray(product.options)) ? product.options.slice() : [];
    const mask = document.createElement("div");
    mask.className = "modal-mask";
    mask.innerHTML = `
      <div class="modal">
        <h3>${product ? "編輯商品" : "新增商品"}</h3>
        <label>商品名稱</label><input id="f-name" value="${product ? esc(product.name) : ""}">
        <label>價格（NT$）</label><input id="f-price" type="number" min="0" value="${product ? product.price : ""}">
        <label>備註</label><input id="f-note" value="${product ? esc(product.note || "") : ""}">
        <div class="opt-head"><strong>客製化選項</strong><button id="opt-add">＋ 新增選項</button></div>
        <div id="opt-list"></div>
        <div class="flex mt"><button class="primary" id="f-save">儲存</button><button id="f-cancel">取消</button></div>
      </div>`;
    document.body.appendChild(mask);

    const renderOptList = () => {
      const list = $("#opt-list", mask);
      list.innerHTML = defs.map((d, i) => {
        const priceMap = d.prices || {};
        const fmtChoice = (c) => (priceMap[c] ? c + ":" + priceMap[c] : c);
        return `
        <div class="opt-row" data-i="${i}">
          <input class="ok-label" value="${esc(d.label)}" placeholder="顯示名稱（如 冰量）">
          <input class="ok-key" value="${esc(d.key)}" placeholder="欄位代號（如 ice）">
          <select class="ok-type">
            <option value="select" ${d.type === "select" ? "selected" : ""}>單選</option>
            <option value="multi" ${d.type === "multi" ? "selected" : ""}>多選</option>
            <option value="text" ${d.type === "text" ? "selected" : ""}>文字</option>
          </select>
          <input class="ok-choices" value="${esc(d.type === "text" ? (d.placeholder || "") : (d.choices || []).map(fmtChoice).join(", "))}" placeholder="單選/多選：名稱:加價，逗號分隔；文字：顯示提示">
          <button class="ok-del danger">✕</button>
        </div>`;
      }).join("");
      $$(".ok-del", list).forEach(btn => {
        btn.onclick = () => { defs.splice(int(btn.parentElement.dataset.i), 1); renderOptList(); };
      });
    };
    renderOptList();

    $("#f-cancel", mask).onclick = () => mask.remove();
    $("#opt-add", mask).onclick = () => {
      defs.push({ key: "", label: "", type: "select", choices: [] });
      renderOptList();
    };
    $("#f-save", mask).onclick = async () => {
      const options = [];
      $$(".opt-row", mask).forEach(row => {
        const label = $(".ok-label", row).value.trim();
        const key = $(".ok-key", row).value.trim();
        const type = $(".ok-type", row).value;
        if (!label || !key) return;
        const d = { key, label, type };
        const extra = $(".ok-choices", row).value;
        if (type === "text") {
          d.placeholder = extra.trim();
        } else {
          const parts = extra.split(",").map(s => s.trim()).filter(Boolean);
          const choices = [];
          const prices = {};
          parts.forEach(pt => {
            const m = pt.match(/^(.*?):(\d+)$/);
            if (m && m[1].trim()) {
              choices.push(m[1].trim());
              prices[m[1].trim()] = int(m[2]);
            } else {
              choices.push(pt);
            }
          });
          d.choices = choices;
          if (Object.keys(prices).length) d.prices = prices;
        }
        options.push(d);
      });
      const body = {
        name: $("#f-name", mask).value,
        price: int($("#f-price", mask).value),
        note: $("#f-note", mask).value,
        options,
      };
      try {
        if (product) await apiJson("/api/products/" + product.id, "PUT", body);
        else await apiJson("/api/products", "POST", Object.assign({ vendor_id: vendorId }, body));
        mask.remove(); toast("已儲存", "ok"); onSaved();
      } catch (err) { toast(err.message, "err"); }
    };
  }

  // ---------- 帳號管理 ----------
  async function viewUsers() {
    const v = $("#view");
    let data;
    try { data = await api("/api/users"); }
    catch (err) { return errPage(v, err); }

    v.innerHTML = `
      <div class="page-head">
        <h1>帳號管理</h1>
        <div class="flex">
          <button id="btn-print-users">列印</button>
          <button class="primary" id="btn-new-user">＋ 新增帳號</button>
        </div>
      </div>
      <div class="card">
        <table>
          <thead><tr><th>姓名</th><th>Email</th><th>角色</th><th>LINE 使用者代碼</th><th>LINE 通知</th><th>動作</th></tr></thead>
          <tbody>
            ${data.users.map(u => `
              <tr>
                <td>${esc(u.name)}</td>
                <td>${esc(u.email)}</td>
                <td>${u.role === "admin" ? '<span class="chip admin">管理員</span>' : "成員"}</td>
                <td>${u.line_id ? esc(u.line_id) : "—"}</td>
                <td>${u.has_line ? "已設定" : "—"}</td>
                <td>
                  <button data-edit-user="${u.id}" class="danger">編輯</button>
                  ${u.id !== state.me.id ? `<button data-del-user="${u.id}" class="danger">刪除</button>` : ""}
                </td>
              </tr>`).join("")}
          </tbody>
        </table>
      </div>
    `;

    $("#btn-print-users").onclick = () => {
      const rows = data.users.map(u => `
        <tr>
          <td>${esc(u.name)}</td>
          <td>${esc(u.email)}</td>
          <td>${u.role === "admin" ? "管理員" : "成員"}</td>
          <td>${u.line_id || "—"}</td>
          <td>${u.has_line ? "已設定" : "—"}</td>
        </tr>`).join("");
      printHtml("帳號管理", `
        <table>
          <thead><tr><th>姓名</th><th>Email</th><th>角色</th><th>LINE 使用者代碼</th><th>LINE 通知</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>`);
    };

    $("#btn-new-user").onclick = () => modalUser(null, () => viewUsers());
    $$("[data-edit-user]", v).forEach(btn => {
      const u = data.users.find(x => x.id == btn.dataset.editUser);
      btn.onclick = () => modalUser(u, () => viewUsers());
    });
    $$("[data-del-user]", v).forEach(btn => {
      btn.onclick = async () => {
        if (!confirm("確定刪除此帳號？其訂購與收款資料會一併刪除。")) return;
        try { await apiJson("/api/users/" + btn.dataset.delUser, "DELETE", {}); toast("已刪除", "ok"); viewUsers(); }
        catch (err) { toast(err.message, "err"); }
      };
    });
  }

  function modalUser(user, onSaved) {
    const mask = document.createElement("div");
    mask.className = "modal-mask";
    mask.innerHTML = `
      <div class="modal">
        <h3>${user ? "編輯帳號" : "新增帳號"}</h3>
        <label>姓名</label><input id="f-name" value="${user ? esc(user.name) : ""}">
        <label>Email</label><input id="f-email" type="email" value="${user ? esc(user.email) : ""}">
        <label>角色</label>
        <select id="f-role">
          <option value="member" ${user && user.role === "member" ? "selected" : ""}>成員</option>
          <option value="admin" ${user && user.role === "admin" ? "selected" : ""}>管理員</option>
        </select>
        <label>LINE ID 名稱（選填，作「使用者代碼」供 QR/辨識）</label><input id="f-line-id" value="${user ? esc(user.line_id || "") : ""}" placeholder="例如 tienfa_hsu">
        <label>LINE User ID（選填，U 開頭，供推播通知）</label><input id="f-line" value="${user ? esc(user.line_user_id || "") : ""}" placeholder="LINE Messaging API 的 User ID">${user && (user.has_line || user.line_user_id) ? '<div class="muted mt">已設定推播 LINE：' + esc(user.line_user_id) + "</div>" : ""}
        <label>${user ? "重設密碼（留空則不變）" : "密碼（至少 6 碼）"}</label><input id="f-password" type="password">
        <div class="flex mt"><button class="primary" id="f-save">儲存</button><button id="f-cancel">取消</button></div>
      </div>`;
    document.body.appendChild(mask);
    $("#f-cancel", mask).onclick = () => mask.remove();
    $("#f-save", mask).onclick = async () => {
      const body = {
        name: $("#f-name", mask).value,
        email: $("#f-email", mask).value,
        role: $("#f-role", mask).value,
        line_user_id: $("#f-line", mask).value,
        line_id: $("#f-line-id", mask).value,
        password: $("#f-password", mask).value,
      };
      try {
        if (user) await apiJson("/api/users/" + user.id, "PUT", body);
        else await apiJson("/api/users", "POST", body);
        mask.remove(); toast("已儲存", "ok"); onSaved();
      } catch (err) { toast(err.message, "err"); }
    };
  }

  // ---------- 通知 ----------
  async function viewNotifications() {
    const v = $("#view");
    let data;
    try { data = await api("/api/notifications"); }
    catch (err) { return errPage(v, err); }

    v.innerHTML = `
      <div class="page-head">
        <h1>通知</h1>
        <button class="primary" id="btn-read-all">全部標為已讀</button>
      </div>
      ${data.notifications.length === 0 ? '<div class="empty">沒有通知</div>' : ""}
      ${data.notifications.map(n => `
        <div class="card" data-nid="${n.id}" style="${n.read ? "opacity:.55" : ""}">
          <div class="spread">
            <strong>${esc(n.title)}</strong>
            <span class="muted">${fmtDt(n.created_at)}</span>
          </div>
          <div class="mt" style="white-space:pre-wrap">${esc(n.message)}</div>
          ${!n.read ? '<button class="mt" data-read="' + n.id + '">標為已讀</button>' : ""}
        </div>`).join("")}
    `;

    $("#btn-read-all").onclick = async () => {
      try { await apiJson("/api/notifications/read-all", "POST", {}); viewNotifications(); }
      catch (err) { toast(err.message, "err"); }
    };
    $$("[data-read]", v).forEach(btn => {
      btn.onclick = async () => {
        try { await apiJson("/api/notifications/" + btn.dataset.read + "/read", "POST", {}); viewNotifications(); }
        catch (err) { toast(err.message, "err"); }
      };
    });
  }

  // ---------- 錯誤頁 ----------
  function errPage(v, err) {
    v.innerHTML = `
      <div class="card">
        <h3>發生錯誤</h3>
        <p>${esc(err.message)}</p>
        <button id="btn-back">返回</button>
      </div>`;
    $("#btn-back").onclick = () => { location.hash = "#/orders"; };
  }

  // ---------- 啟動 ----------
  async function boot() {
    await refreshMe();
    window.addEventListener("hashchange", router);
    await router();
  }

  boot();
})();