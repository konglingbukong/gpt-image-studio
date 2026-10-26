# Balance Sync extension · 余额同步扩展

**English** · [中文](#中文)

OpenAI has no API for your credit balance — it's only shown on the billing page of platform.openai.com. This small Chrome / Edge extension reads that one figure and sends it to your local GPT Image Studio, so the balance in the workbench is always the real one (top-ups included). No calibrating, no manual entries.

- Reads **only** the "Credit balance" amount on the billing page — no cookies, tokens or other data
- Sends it **only** to `http://127.0.0.1:<port>` on your own computer (the workbench accepts extension requests on that single endpoint)
- Optional background refresh (default every 6 hours): opens the billing page in a background tab, reads the figure, closes the tab

## Install (about a minute)

1. Open `chrome://extensions` (Chrome) or `edge://extensions` (Edge)
2. Turn on **Developer mode**
3. Click **Load unpacked** and choose this `extension` folder
4. While logged in to platform.openai.com, open **Settings → Billing** once. The extension icon then shows your balance, and the workbench shows "Synced from OpenAI"

Click the extension icon to see the last reading, sync right away, change the refresh interval, or set the workbench port (default 8765).

For exact spending *between* syncs, also add an **admin key** under Settings → Balance in the workbench (created at platform.openai.com → Settings → Admin keys; organization owners only).

---

## 中文

OpenAI 没有查余额的接口，余额只显示在 platform.openai.com 的账单页上。这个 Chrome / Edge 小扩展只读取这一个数字，同步给本机的 GPT Image 工作台，所以工作台里的余额永远是真实的（充值也会自动算进去），不用校准，也不用手动记。

- **只读**账单页上「Credit balance」那一个金额，不碰 cookie、令牌或任何其他数据
- **只发给**你自己电脑上的 `http://127.0.0.1:<端口>`（工作台只在这一个接口上接受扩展的请求）
- 可选后台刷新（默认每 6 小时）：在后台标签页里打开账单页，读完数字就关掉

## 安装（大约 1 分钟）

1. 打开 `chrome://extensions`（Chrome）或 `edge://extensions`（Edge）
2. 打开右上角的「**开发者模式**」
3. 点「**加载解压缩的扩展**」，选择这个 `extension` 文件夹
4. 在登录 platform.openai.com 的状态下，打开一次 **Settings → Billing**。之后扩展图标上会显示余额，工作台也会显示「OpenAI 后台同步」

点扩展图标可以看最近一次读到的余额、立即同步、改刷新间隔、设置工作台端口（默认 8765）。

想让两次同步之间的花费也精确，再在工作台「设置 → 余额」里填上**管理员 Key**（在 platform.openai.com → Settings → Admin keys 创建，只有组织 Owner 能建）。
