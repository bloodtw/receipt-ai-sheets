/**
 * AI 智慧刷卡簽單 & 收據轉存 Google 試算表 - Google Apps Script 中繼腳本
 *
 * 【使用教學】：
 * 1. 打開您的 Google 試算表 (https://sheets.google.com)。
 * 2. 點選頂端選單的「擴充功能」->「Apps Script」。
 * 3. 清空原本的程式碼，將本檔案全部內容複製並貼上到編輯器中。
 * 4. 點選右上角的「部署」->「新部署」。
 * 5. 點擊齒輪圖示，選擇「網頁應用程式 (Web App)」。
 *    - 說明：簽單轉存 API
 *    - 執行身分：我 (您的 Google 帳號)
 *    - 誰可以存取：任何人 (Anyone)  <- 重要！這樣前端網頁才能傳送資料
 * 6. 點擊「部署」，並授予必要的 Google 試算表權限。
 * 7. 複製產生的「網頁應用程式網址 (Web App URL)」，貼到前端網頁的設定中即可！
 */

function doGet(e) {
  var action = e.parameter.action;
  var spreadsheetId = e.parameter.spreadsheetId;

  var ss;
  if (spreadsheetId) {
    try {
      ss = SpreadsheetApp.openById(spreadsheetId);
    } catch (err) {
      return responseJson({ success: false, error: "找不到指定的試算表，請確認 ID 與存取權限" });
    }
  } else {
    ss = SpreadsheetApp.getActiveSpreadsheet();
  }

  // 動作 1：取得試算表內所有的工作表 (Tabs) 分頁名稱
  if (action === "getSheets") {
    var sheets = ss.getSheets();
    var sheetNames = sheets.map(function(s) {
      return s.getName();
    });
    return responseJson({
      success: true,
      spreadsheetName: ss.getName(),
      sheets: sheetNames
    });
  }

  return responseJson({ success: true, message: "AI 刷卡簽單 Apps Script 伺服器運作正常！" });
}

function doPost(e) {
  try {
    var postData = "";
    if (e.postData && e.postData.contents) {
      postData = e.postData.contents;
    }
    var data = JSON.parse(postData);

    var spreadsheetId = data.spreadsheetId;
    var ss;
    if (spreadsheetId) {
      ss = SpreadsheetApp.openById(spreadsheetId);
    } else {
      ss = SpreadsheetApp.getActiveSpreadsheet();
    }

    var sheetName = data.sheetName || "工作表1";
    var sheet = ss.getSheetByName(sheetName);

    // 如果該工作表不存在，自動新建一個
    if (!sheet) {
      sheet = ss.insertSheet(sheetName);
    }

    var lastRow = sheet.getLastRow();

    // 如果工作表是空的且啟用自動表頭，寫入精美的標題列
    if (lastRow === 0 && data.autoHeader && data.header) {
      sheet.appendRow(data.header);
      var headerRange = sheet.getRange(1, 1, 1, data.header.length);
      headerRange.setBackground("#fee2e2"); // 典雅淺粉紅背景
      headerRange.setFontColor("#991b1b");  // 深紅文字
      headerRange.setFontWeight("bold");
      headerRange.setHorizontalAlignment("center");
      sheet.setFrozenRows(1);
    }

    // 追加寫入明細資料列
    if (data.rows && data.rows.length > 0) {
      var startRow = sheet.getLastRow() + 1;
      var numRows = data.rows.length;
      var numCols = data.rows[0].length;

      var range = sheet.getRange(startRow, 1, numRows, numCols);
      range.setValues(data.rows);

      // 針對負數折扣欄位給予紅色醒目提示
      for (var r = 0; r < data.rows.length; r++) {
        var rowData = data.rows[r];
        // 假設第 6 欄為金額，若是負數加紅底標示
        var price = Number(rowData[5]);
        if (price < 0) {
          sheet.getRange(startRow + r, 6).setFontColor("#dc2626").setFontWeight("bold");
        }
      }
    }

    return responseJson({
      success: true,
      message: "成功存入 " + (data.rows ? data.rows.length : 0) + " 筆紀錄",
      sheetName: sheetName,
      spreadsheetId: ss.getId(),
      spreadsheetUrl: ss.getUrl()
    });

  } catch (err) {
    return responseJson({
      success: false,
      error: err.toString()
    });
  }
}

function responseJson(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
