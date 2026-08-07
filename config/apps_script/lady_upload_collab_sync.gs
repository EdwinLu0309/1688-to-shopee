/**
 * 【Lady】蝦皮上架協作檔 — 商品清單同步（獨立排程版；自 upload_collab_sync.gs Nail 版移植）
 *
 * 用途：把「【Lady】商品主表(1-1)」的商品清單（商品編號/分類/品名）定時同步進「共用雲的
 *   員工上架協作檔」。員工在協作檔手填的平台狀態欄（D 起：蝦皮ID/標題/詳情/圖片/選項圖/
 *   影片/優化/備註/蝦皮折扣）以「商品編號」為 key 原封保留，主表新增的商品自動補列。
 *
 * 設計要點（與 syncStatusTab 同款：依主表順序重建、手填以編號帶回）：
 *   - 每次依「商品表」順序重建協作表 → 協作表排序永遠跟主表一模一樣。
 *   - 手填欄(D..)以商品編號為 key 帶回，主表怎麼插列/重排都不會錯位、不丟員工資料。
 *   - 只讀主表「商品表」，不碰「蝦皮處理狀態」→ 完全不影響 master_reader / 資產包生產線。
 *   - 主表已刪、協作檔仍有的孤兒編號：不丟，移到清單最後。
 *
 * ── 安裝（一次性，都在你 Google 帳號下做）──
 *   1) 打開 Lady 協作檔 → 擴充功能 → Apps Script → 貼上本檔 → 儲存。
 *   2) 編輯器上方選 setupCollab → 執行 → 跳授權請同意
 *      （自動：分頁改名/建「蝦皮狀態」＋寫 12 欄表頭＋首輪灌入商品清單）。
 *   3) 回協作檔確認清單被填好（~195 商品）。
 *   4) 選 installSchedule → 執行 → 裝好「每 30 分鐘」排程（重複執行會先清舊觸發器，不疊加）。
 */

var MASTER_ID  = '1SsRfXyh65ViZ0x8TYj1wLq9SCDFvGiDtkMdpuggE7ps';  // 【Lady】商品主表(1-1)
var MASTER_TAB = '商品表';                                        // 商品識別來源分頁
var COLLAB_ID  = '★TODO_貼上Lady協作檔ID';   // 【Lady】員工上架協作檔（Edwin 建檔後把 /d/ 後那串貼進來）
var COLLAB_TAB = '蝦皮狀態';                                      // 協作檔的分頁名

var IDENTITY_WIDTH = 3;   // A商品編號 / B分類 / C品名（由程式同步）
var MANUAL_START   = 4;   // D 欄起＝員工手填第一欄（以編號帶回、不被覆蓋）

var COLLAB_HDR = ['商品編號', '分類', '品名', '蝦皮ID', '標題', '詳情', '圖片',
                  '選項圖', '影片', '優化', '備註', '蝦皮折扣'];   // 比照 Nail 12 欄

/** 一次性初始化：把協作檔分頁備妥（改名/建立「蝦皮狀態」＋表頭）→ 首輪同步灌入商品。 */
function setupCollab() {
  var ss = SpreadsheetApp.openById(COLLAB_ID);
  var dst = ss.getSheetByName(COLLAB_TAB);
  if (!dst) {
    // 沒有目標分頁：唯一一張且是空表就直接改名（吃掉預設「工作表1」），否則另建新分頁
    var sheets = ss.getSheets();
    if (sheets.length === 1 && sheets[0].getLastRow() === 0) {
      dst = sheets[0].setName(COLLAB_TAB);
    } else {
      dst = ss.insertSheet(COLLAB_TAB);
    }
  }
  dst.getRange(1, 1, 1, COLLAB_HDR.length).setValues([COLLAB_HDR])
     .setFontWeight('bold').setBackground('#d9ead3').setHorizontalAlignment('center');
  dst.setFrozenRows(1);
  syncUploadCollab(true);
  try { ss.toast('初始化完成：表頭已建、商品清單已灌入', '上架協作同步', 6); } catch (e) {}
  Logger.log('setupCollab 完成');
}

/** 主排程函式：依主表「商品表」順序重建協作表，手填欄以商品編號帶回（不錯位、不丟資料）。 */
function syncUploadCollab(silent) {
  var src = SpreadsheetApp.openById(MASTER_ID).getSheetByName(MASTER_TAB);
  var dst = SpreadsheetApp.openById(COLLAB_ID).getSheetByName(COLLAB_TAB);
  if (!src) throw new Error('主表找不到分頁：' + MASTER_TAB);
  if (!dst) throw new Error('協作檔找不到分頁：' + COLLAB_TAB + '（先執行 setupCollab）');

  // 1) 讀主表「商品表」：依出現順序取唯一編號 → [分類, 品名]
  //    欄位：A商品編號(1) B分類(2) C子分類(3) D品名(4)
  var mOrder = [], info = {}, mSeen = {};
  var mLast = src.getLastRow();
  if (mLast >= 2) {
    var mv = src.getRange(2, 1, mLast - 1, 4).getValues();
    for (var i = 0; i < mv.length; i++) {
      var code = String(mv[i][0]).trim();
      if (!code || mSeen[code]) continue;
      mSeen[code] = true;
      mOrder.push(code);
      info[code] = [mv[i][1], mv[i][3]];   // [分類, 品名]
    }
  }

  // 2) 讀協作檔既有列：以編號存 B:C(分類/品名) 與手填欄(D..)，供重建時帶回
  var dLast = dst.getLastRow();
  var totalW = Math.max(dst.getLastColumn(), MANUAL_START);   // 至少含到 D 欄
  var manW = totalW - (MANUAL_START - 1);                     // 手填欄數（D..）
  var store = {};   // code -> {bc:[分類,品名], man:[...手填...]}
  if (dLast >= 2) {
    var rows = dst.getRange(2, 1, dLast - 1, totalW).getValues();
    for (var k = 0; k < rows.length; k++) {
      var kc = String(rows[k][0]).trim();
      if (!kc || (kc in store)) continue;
      store[kc] = { bc: [rows[k][1], rows[k][2]], man: rows[k].slice(MANUAL_START - 1, totalW) };
    }
  }

  // 3) 依主表順序組整列（手填以編號帶回、新編號留空）；主表已無的孤兒接在最後
  var out = [];
  var emptyMan = new Array(manW).fill('');
  mOrder.forEach(function (code) {
    var man = (store[code] && store[code].man) ? store[code].man : emptyMan.slice();
    out.push([code, info[code][0], info[code][1]].concat(man));
  });
  var orphan = 0;
  for (var oc in store) {
    if (mSeen[oc]) continue;                       // 主表還有的已在上面處理
    out.push([oc, store[oc].bc[0], store[oc].bc[1]].concat(store[oc].man));
    orphan++;
  }

  // 4) 一次覆寫整區（原子性較好、不留空窗），再清掉尾端多餘的舊列
  var nOut = out.length;
  if (nOut) dst.getRange(2, 1, nOut, totalW).setValues(out);
  var tail = (dLast - 1) - nOut;
  if (tail > 0) dst.getRange(2 + nOut, 1, tail, totalW).clearContent();

  var msg = '同步完成：' + mOrder.length + ' 個商品依主表順序重建' +
            (orphan ? '；孤兒 ' + orphan + ' 列移到最後（主表已無）' : '');
  if (!silent) { try { dst.getParent().toast(msg, '上架協作同步', 6); } catch (e) {} }
  Logger.log(msg);
}

/** 安裝每 30 分鐘排程（重複安裝會先清舊的，不會疊加；比照 Nail）。 */
function installSchedule() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'syncUploadCollab') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('syncUploadCollab')
    .timeBased()
    .everyMinutes(30)   // 可改 .everyHours(1) / (2) ...
    .create();
  Logger.log('已安裝每 30 分鐘排程：syncUploadCollab');
}

/** 解除排程（要停用時用）。 */
function removeSchedule() {
  var n = 0;
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'syncUploadCollab') { ScriptApp.deleteTrigger(t); n++; }
  });
  Logger.log('已移除 ' + n + ' 個排程');
}
