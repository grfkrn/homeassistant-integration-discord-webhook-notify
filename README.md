# Discord Webhook Notify（自作 Home Assistant カスタム統合）

Home Assistant から Discord の Webhook へ通知するカスタム統合です。設定はすべて GUI で行い、YAML は不要です。**ローカルファイル（カメラのスナップショット画像や動画クリップ）の添付**に対応しているのが特徴です。

- バージョン: 1.0.0
- ドメイン: `discord_webhook_notify`（既存の同種統合とは競合しない専用ドメイン）
- 追加依存: なし（Home Assistant 標準の aiohttp のみ使用）

## 既存の同種統合（bensonrodney 版）との違い

精査で見つかった制約を中心に直しています。

| 項目 | 本統合 | bensonrodney 版 v1.0.7 |
|---|---|---|
| ローカルファイル添付 | **対応**（画像・動画等、25MB まで） | 非対応（URL のみ） |
| URL 画像 | embed 表示（Discord が取得）＋「URL を HA が取り込んで添付」も可 | embed 表示のみ |
| メッセージ単位の username / avatar 差し替え | 対応 | 非対応（ドキュメントのみ記載） |
| Webhook URL の検証 | **discord.com の正規形式のみ許可**、重複判定は Webhook ID 単位 | `http` で始まれば何でも可 |
| 429（レート制限） | Retry-After を見て最大2回再送 | 再送なし |
| embed + 画像の合計上限 | 合計10件に制限（Discord の上限どおり） | 別々に数えるため超過しうる |
| 設定画面の日本語表示 | 対応 | 英語のみ |

## インストール

1. このフォルダ内の `custom_components/discord_webhook_notify` を、Home Assistant の `config/custom_components/` にコピーする
2. Home Assistant を再起動する

HACS のカスタムリポジトリとして使うこともできます（リポジトリ直下に `custom_components` がある構成です）。

## 設定（GUI のみ）

1. 設定 → デバイスとサービス → 「統合を追加」→ **Discord Webhook Notify**
2. 入力項目:
   - **名前**: 通知サービスの名前になります（`notify.<名前>`）。半角英数字を推奨（例: `discord_alerts`）
   - **Webhook URL**: Discord のチャンネル設定 → 連携サービス → Webhook で発行した URL。`https://discord.com/api/webhooks/` 形式以外は受け付けません
   - **投稿名**（任意）: Discord 上の投稿者名
   - **アバターURL**（任意）
   - **TTS**: 通常はオフ
3. 確認画面で「テストメッセージを送信」を押すと、その場で Discord にテスト投稿が届きます。問題なければ「保存」
4. 2つ目以降のチャンネルは、同じ手順を繰り返します。後からの変更は、エントリの「設定」から同じ画面で行えます（テスト送信も可能）

## 使い方

オートメーションのアクションで `notify.<名前>` を選び、メッセージを書くだけです。追加データ（`data:`）で次が使えます。

| キー | 内容 |
|---|---|
| `title` | タイトル。太字で本文の上に付きます |
| `data.embeds` | Discord embed のリスト（そのまま送信、本文・画像と合わせて最大10件） |
| `data.images` | 画像 URL のリスト。embed として表示されます。URL は Discord のサーバーから取得できる必要があります |
| `data.files` | **添付ファイル**のリスト。ローカルパス（HA の許可ディレクトリ内）または http(s) URL（HA がダウンロードして添付）。画像・動画は Discord 上でインライン表示されます。1ファイル 25MB まで、最大10件 |
| `data.username` / `data.avatar_url` | このメッセージだけの投稿名・アバター差し替え |
| `data.tts` | このメッセージだけ TTS を有効化 |
| `data.allowed_mentions` | Discord へそのまま渡します。例: `{"parse": []}` でメンションの通知をすべて止められます |

### 例1: カメラのスナップショットを添付して通知

先に `camera.snapshot` で画像を保存し、続けて通知します（アクションを2つ並べます）。

```yaml
# アクション1: スナップショット保存
action: camera.snapshot
target:
  entity_id: camera.entrance
data:
  filename: /config/www/snapshots/entrance.jpg

# アクション2: Discord へ画像付き通知
action: notify.discord_alerts
data:
  title: "玄関カメラ"
  message: "動きを検知しました"
  data:
    files:
      - /config/www/snapshots/entrance.jpg
```

### 例2: 画像 URL を埋め込む

```yaml
action: notify.discord_alerts
data:
  message: "今日の天気"
  data:
    images:
      - "https://example.com/weather.png"
```

### 添付ファイルの置き場所（許可ディレクトリ）

ローカルファイルは、Home Assistant の許可ディレクトリ内にあるものだけ添付できます（安全のため、それ以外はスキップしてエラーログを残します）。`/config/www/` 配下はそのまま使えます。それ以外の場所を使いたい場合は `configuration.yaml` に追加してください。

```yaml
homeassistant:
  allowlist_external_dirs:
    - /config/www
    - /media/frigate/clips
```

## 注意点

- Webhook URL はパスワード相当の情報です。Config Entry として HA 内に保存されます（HA の標準動作）。バックアップ一式の取り扱いに注意してください
- Discord の制限: 本文 2000 文字（超過分は切り捨て）、embed は合計10件まで、ファイルは 1件 25MB まで
- 統合エントリを削除・改名した後は、古い `notify.<名前>` サービスを確実に消すため HA の再起動を推奨します
- 方式は旧来の notify プラットフォーム（`notify.<名前>` サービス）です。既存の `platform: rest` 時代のオートメーションと同じ呼び方で使えます

## ライセンス

MIT License（`LICENSE` ファイル参照）。著作権者は grfkrn です。

## ロゴについて

`brand/` の Discord ロゴは、精査対象だった bensonrodney/homeassistant-discord（MIT ライセンス）に同梱されていたものを利用しています。Discord の商標は Discord Inc. に帰属します。

## テスト

```bash
uv venv .venv --python 3.13
uv pip install --python .venv/bin/python -r requirements_test.txt
.venv/bin/python -m pytest tests/
```

Home Assistant 2026.2.3 / pytest-homeassistant-custom-component 0.13.316 で、テスト25件（config flow 10件 / notify 13件 / init 2件）の全件合格を確認済みです。
