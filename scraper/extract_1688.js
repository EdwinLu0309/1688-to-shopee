/*
 * 1688 商品資料抽取器（Chrome MCP 注入用）
 * ------------------------------------------------------------------
 * 背景：現代 1688（detail.1688.com）已移除 window.__INIT_DATA__ 等全域變數，
 *       舊的 data_extractor.py（Playwright + __INIT_DATA__）已失效。
 *       且 Playwright 開 1688 會被反爬擋下，所以抓取改走「已登入的真實 Chrome
 *       + Chrome MCP 注入此 JS」。此檔是目前實際可用的抽取邏輯。
 *
 * 把資料從瀏覽器送回硬碟的方法（實測比較）：
 *   - fetch 到本機 server  ✗ 被 1688 的 CSP 擋（連 localhost 都不行，會卡住）
 *   - clipboard.writeText  ✗ 注入的 JS 沒有 user activation，寫不進去
 *   - MCP 回傳整包 JSON    ✗ 回傳字串約 1000 字就被截斷；base64 還會被過濾擋掉
 *   - Blob 下載到 ~/Downloads ✓ 唯一穩定可行 → 採用此法
 *     注意：Chrome 對「自動下載多檔」有站台權限，第一次會問、之後記住。
 *           需把 detail.1688.com 的「自動下載」設為「允許」，下載才會穩定。
 *
 * 用法：
 *   1.（一次性）Chrome 設定 → detail.1688.com 自動下載 = 允許
 *   2. 在已登入、已開啟 detail.1688.com/offer/<id>.html 的分頁注入此檔
 *      → 下載 {item_id}.json 到 ~/Downloads
 *   3. `python main.py images --ingest-downloads`
 *      → 搬進 output/ 並下載主圖/細節圖/SKU 圖
 *
 * 抽取來源（2026-06 實測有效）：
 *   - 主圖     ：DOM `.od-gallery-list img`
 *   - SKU 色卡 ：`.sku-filter-button` → 圖在 `img`，名稱在 `.label-name`
 *   - 細節圖   ：`window.offer_details.content`（商品描述 HTML，內含 <img>）
 *   - 原圖還原 ：砍掉 URL 第一個圖片副檔名之後的所有 CDN 後綴
 *               （_.webp / _sum.jpg / _800x800 等）
 */
(() => {
  const norm = (u) => {
    if (!u) return "";
    u = String(u).trim();
    if (u.startsWith("//")) u = "https:" + u;
    return u.startsWith("http") ? u : "";
  };

  // 砍掉第一個圖片副檔名之後的所有後綴，取回原圖
  const orig = (u) => {
    u = norm(u);
    if (!u) return "";
    const m = u.match(/\.(jpg|jpeg|png|webp|gif)/i);
    return m ? u.slice(0, m.index) + m[0] : u;
  };

  const uniq = (a) => [...new Set(a.filter(Boolean))];

  // item_id：從網址 /offer/<id>.html 取
  const itemId = (location.href.match(/offer\/(\d+)\.html/) || [])[1] || "unknown";

  // ── 主圖 ──
  const main = uniq(
    [...document.querySelectorAll(".od-gallery-list img, .od-gallery-list-wapper img")]
      .map((i) => orig(i.getAttribute("src") || i.getAttribute("data-src") || ""))
  );

  // ── SKU 色卡（name -> url）+ skus 清單 ──
  const sku_images = {};
  const skus = [];
  document.querySelectorAll(".sku-filter-button").forEach((btn) => {
    const img = btn.querySelector("img");
    const nameEl = btn.querySelector(".label-name");
    const name = (nameEl ? nameEl.textContent : btn.textContent || "").trim();
    const u = img ? orig(img.getAttribute("src") || img.getAttribute("data-src") || "") : "";
    if (name && u) sku_images[name] = u;
    if (name) {
      skus.push({ sku_id: "", attributes: { 规格: name }, price: 0, stock: 0, image_url: u });
    }
  });

  // ── 細節圖（從描述 HTML 抓 <img>）──
  const detailHtml = (window.offer_details && window.offer_details.content) || "";
  const detail = [];
  const re = /<img[^>]+(?:data-lazyload-src|data-src|src)=["']([^"']+)["']/gi;
  let m;
  while ((m = re.exec(detailHtml))) {
    const u = orig(m[1]);
    if (u && /alicdn/.test(u)) detail.push(u);
  }

  const data = {
    item_id: itemId,
    title: (document.title || "").replace(/ - 阿里巴巴$/, "").trim(),
    description: "",
    categories: [],
    shop_name: "",
    shop_url: "",
    shop_location: "",
    shop_ratings: {},
    min_order: 0,
    origin_price: 0,
    price_ranges: [],
    attributes: {},
    main_images: main,
    detail_images: uniq(detail),
    video_url: "",
    sku_images,
    skus,
  };

  // Blob 下載完整 JSON 到 ~/Downloads（唯一穩定的回傳硬碟方式）
  let delivered = false;
  try {
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = itemId + ".json";
    document.body.appendChild(a);
    a.click();
    a.remove();
    delivered = true;
  } catch (e) {
    delivered = false;
  }

  return {
    item_id: itemId,
    title: data.title,
    main: main.length,
    detail: data.detail_images.length,
    sku: Object.keys(sku_images).length,
    sku_names: Object.keys(sku_images),
    delivered,
    ok: main.length > 0,
  };
})();
