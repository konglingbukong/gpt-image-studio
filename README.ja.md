# GPT Image スタジオ

[English](README.md) · [中文](README.zh-CN.md) · **日本語** · [한국어](README.ko.md) · [Русский](README.ru.md)

**ご自身の OpenAI API キーで `gpt-image-2.5` を使う画像生成ワークベンチです。AI エージェントに一言頼むだけで画像を生成でき、ローカルの Web ギャラリーで画像・1 枚ごとの費用・残高をリアルタイムに確認できます。**

![GPT Image スタジオ：ギャラリー](docs/screenshot.png)

*エージェントに頼むと、すぐに表示されます：*

![AI エージェントが生成中の様子を Web ギャラリーがリアルタイムで表示](docs/agent-sync.png)

## できること

- **AI エージェントから直接生成**：Claude Code、Codex などコマンドを実行できるエージェントに「2K 16:9 で〇〇の画像を」と頼むだけ。公式 API を呼び出してローカルに保存し、費用も教えてくれます。
- **Web ギャラリーとリアルタイム同期**：エージェントが生成している間はページに「生成中」カードとタイマーが表示され、完成すると結果に切り替わります。ページから直接生成することもできます。
- **すべてのパラメータに対応**：gpt-image-2.5 の sunburst / flare、1K / 2K / 4K の任意のアスペクト比（最大 3840×2160）、品質 low から **xhigh / max** まで、参考画像は最大 16 枚、マスクによる部分再描画。
- **費用の管理**：1 枚ごとの費用を OpenAI が返す実際のトークン使用量から計算し、今日・今月・累計の支出を集計します。残高を一度補正すれば、残りの金額を自動で追跡します（OpenAI には残高 API がないため、これが最も正確な方法です）。
- **ギャラリー機能**：お気に入り、状態での絞り込み（完了 / 生成中 / 失敗）、検索、設定のワンクリック再利用、結果を参考画像にして続けて編集。削除した画像は `.trash` フォルダに移動し、完全には消えません。
- **どこでも使える**：同じページを GitHub Pages に置けます。ローカルサービスが動いているパソコンで開くと自動で接続し、それ以外の端末では「ブラウザモード」で動作します（キーと画像はそのブラウザ内に保存）。
- **5 言語対応**：English・中文・日本語・한국어・Русский。ブラウザの言語に合わせて表示され、ページ上で切り替えもできます。
- **中継サービス対応**：one-api、new-api などの OpenAI 互換中継サービスに対応。画像 URL の応答、枚数課金、中継サービスの実残高の取得もできます（下の「中継サービス」を参照）。
- **依存関係なし**：Python 3.9 以上だけで動きます。`pip install` は不要です。

## インストール

### Claude Code のスキルとして（おすすめ）

```bash
git clone https://github.com/konglingbukong/gpt-image-studio ~/.claude/skills/gpt-image
```

1. `start.bat`（Windows）または `sh start.sh`（macOS / Linux）を実行すると、ブラウザで `http://127.0.0.1:8765` が開きます。
2. 設定 → API で OpenAI API キーを入力し、「接続テスト」（無料）をクリックします。
3. Claude Code に画像の生成を頼みます。

キーは環境変数 `OPENAI_API_KEY` や `config.json` でも指定できます（`config.example.json` を参照。`config.json` は git の管理対象外です）。

### Web ページだけ使う（インストール不要）

**https://konglingbukong.github.io/gpt-image-studio/** を開き、設定でキーを入力すれば生成できます。この場合はブラウザモードで動作します。キーと画像はブラウザ内だけに保存され、ブラウザが OpenAI と直接通信するため、第三者のサーバーは経由しません。

### その他のエージェント（Codex・Cursor・Gemini・Antigravity・WorkBuddy など）

エージェントが対応している方法を選んでください。

**① MCP（ほとんどのエージェントが対応）**：`scripts/mcp_server.py` を MCP サーバーとして登録すると、`generate_image`・`check_connection`・`get_spending` の 3 つのツールが使えるようになります。`<path>` はクローンしたフォルダに置き換えてください。

- **Claude Code**：`claude mcp add gpt-image -- python <path>/scripts/mcp_server.py`
- **Codex**（`~/.codex/config.toml`）：
  ```toml
  [mcp_servers.gpt-image]
  command = "python"
  args = ["<path>/scripts/mcp_server.py"]
  ```
- **Cursor / Gemini CLI / JSON で設定するその他のクライアント**（`mcpServers`）：
  ```json
  { "mcpServers": { "gpt-image": { "command": "python", "args": ["<path>/scripts/mcp_server.py"] } } }
  ```

**② スキルフォルダ**：`SKILL.md` 形式に対応したエージェント（Codex、WorkBuddy など）は、このフォルダをスキルディレクトリに置くだけで使えます。

**③ 説明ファイル**：コマンドを実行できるその他のエージェントには、[AGENTS.md](AGENTS.md) を読ませてください。

どの方法でも、画像は同じフォルダに保存され、Web ワークベンチにリアルタイムで表示されます。

**動作確認済み**：Claude Code、Codex（ChatGPT デスクトップ版を含む）、WorkBuddy、Antigravity、DeepSeek Harness（dsh）。対応状況の一覧、エージェントごとの設定方法、インターフェース仕様、新しいエージェントの追加手順は **[docs/INTEGRATIONS.md](docs/INTEGRATIONS.md)** にあります。お使いのエージェントが未対応の場合は、Issues で「対応リクエスト」を作成するか、[CONTRIBUTING.md](CONTRIBUTING.md) を参考に接続して PR を送ってください。

## 中継サービス（OpenAI 互換プロキシ）

OpenAI に直接つなぐのではなく、中継サービス（one-api、new-api など）経由で gpt-image を使う人も多くいます。これらにも対応しています。

- **設定方法**：設定 → API の API URL に中継サービスのアドレス（通常 `/v1` で終わる）、API Key にそのキーを入力します。モデル名が異なる場合（例：`gpt-image-2.5`）は、モデルメニューに直接入力してください。
- **画像 URL**：base64 データの代わりに画像のリンクを返す中継サービスにも対応しています。画像は自動でダウンロードして保存します。
- **厳格な中継サービス**：公式 API 専用のパラメータ（`moderation`、`output_format`、`background`）を拒否される場合は、「**基本パラメータのみ送信**」をオンにしてください。該当するエラーが出たときは、メッセージでもこの設定を案内します。
- **枚数課金**：多くの中継サービスは 1 枚ごとの課金です。「料金 → 1 枚あたりの料金」を入力すると、トークンではなく枚数で費用を計算します。
- **実際の残高**：one-api / new-api 形式の請求エンドポイントに対応していれば、中継サービスの実際の残高を自動で取得します。補正は不要です。
- **接続テスト**：`GET /models` しか実装していない中継サービスでも使えます。

コマンドラインでは `config.json` の `"api_url"`、`"api_key"`、`"model"`、`"minimal_params": true`、`"rates": {"per_image": 0.04}`、`"balance_source": "auto" | "relay" | "manual"` で設定します。

## コマンドライン

```bash
python scripts/gen.py --prompt-file prompt.txt --size "2K 16:9" --quality high --name cover
python scripts/gen.py --prompt "an orange cat" --size 1024x1024 --quality low
python scripts/gen.py --prompt-file p.txt --ref face.png --ref outfit.png --size "4K 9:16"
python scripts/gen.py --check          # キーとネットワークのテスト（無料）
python scripts/gen.py ... --json       # 1 行の JSON を出力（スクリプト・連携用）
```

すべてのパラメータは [SKILL.md](SKILL.md) に記載しています。コマンドラインのメッセージは英語が既定です（`config.json` に `"lang": "zh"` を書くと中国語になります）。

## 個人設定

スキルフォルダに `rules.local.md` を作成し、既定の仕様やプロンプトの書き方など、ご自身の好みを書いておくと、エージェントは生成前にそれを読みます。このファイルは git の管理対象外です。

## セキュリティ

- ローカルサービスは `127.0.0.1` のみで待ち受け、`Host` と `Origin` の両方を確認します。ローカルのページと、`config.json` の `allowed_origins` に記載したサイトからのリクエストだけを受け付けるため、他の Web ページに悪用されてお金を使われることはありません。
- キーは設定した API URL（既定は OpenAI 公式）にのみ送信されます。

## 料金について

費用は `config.json` の `rates`（USD / 100 万トークン）で計算します。既定値は執筆時点の gpt-image-2.5 の価格です（テキスト入力 5、画像入力 8、画像出力 30）。**OpenAI が価格を改定したら、設定 → 料金 で更新してください。** 表示される残高は推定値で、正確な金額は OpenAI のダッシュボードで確認してください。

## クレジット

UI のレイアウトは [CookSleep/gpt_image_playground](https://github.com/CookSleep/gpt_image_playground)（MIT）を参考にしています。コードは独自に作成しました。

## ライセンス

[MIT](LICENSE)
