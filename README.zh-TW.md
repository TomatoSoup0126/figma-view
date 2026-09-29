# figma-view

[English](README.md) | 繁體中文

Claude Code plugin。Figma MCP 額度不夠，或帳號只有 View seat 時，改從 Figma 網頁版讀圖層規格和截圖。

- **node-id 模式**：網址帶 `node-id` 就直接讀那個圖層，約 5 秒，不呼叫模型，也不送資料到外部。
- **描述模式**：用文字描述要找的圖層，由 Jev（TypeSafe）搜尋並逐層下探。

讀得到：Layout（尺寸、圓角、border、auto layout 的方向、Hug/Fill、Gap、padding）、Typography、Colors（token 名與 hex）、文字內容、父層元件。讀不到：CSS、variables。

## 安裝

```
/plugin marketplace add TomatoSoup0126/figma-view
/plugin install figma-view@figma-view
```

**不用 plugin 的裝法**：把 `plugins/figma-view/skills/inspect/` 複製到 `~/.claude/skills/figma-inspect/`。這樣裝的話，skill 選單會顯示 `/inspect`，輸入 `/figma-inspect` 也叫得出來。要更新時得自己重新複製一次。

## 要自己準備的東西

- `git`、[`uv`](https://docs.astral.sh/uv/)
- Chrome 裝好 [Claude in Chrome](https://claude.com/chrome) 擴充功能，並在那個 profile 登入 Figma
- 第一次使用時，Chrome 會跳出「Allow remote debugging?」，要按允許
- 能連 GitHub：第一次使用時，會自動下載開源套件 [jev-ultrafast](https://github.com/browser-use/jev-ultrafast)，用來操作 Chrome 和呼叫 Jev。預設放在 `~/.cache/jev-ultrafast`，要放別的位置可以設環境變數 `JEV_DIR`。
- 描述模式需要環境變數 `TYPESAFE_API_KEY`。沒設定的話只能用 node-id 模式

## 使用

在 Claude Code 貼 Figma 連結並問規格，或輸入 `/figma-view:inspect <網址> [要找的圖層]`。

最準的用法：在 Figma 對圖層按右鍵 → **Copy link to selection**，貼上帶 node-id 的連結。只有文字描述時，把圖層名稱照 Figma 上的寫法用「」括起來，例如「在「Frame 1234」這個 frame」。

描述模式偶爾會選錯圖層，沒把握時 skill 會請你確認截圖。

## 注意

- **資料外送**：描述模式會把你的要求、頁面名和圖層名送到 TypeSafe。使用前先確認公司允許把設計稿內容送到外部服務。
- **唯讀**：只會點頁面、圖層、展開箭頭、搜尋框和 Properties 分頁，不會改檔案、分享或留言。
- 這個 skill 預設使用者是 View seat（Dev Mode 被鎖）。有 Dev Mode 權限的話，Figma MCP 能拿到更多資訊（CSS、variables）。

## 授權

[MIT](LICENSE)
