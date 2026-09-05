# Scrapos の内容を Facebook Page に自動投稿する

Meta Graph API（Pages API）を使い、Scrapos のコンテンツを **Facebook Page として** 投稿する手順です。

この機能は **Cognito の Facebook ログインとは別物** です。ログイン用の Identity Provider は「誰が Scrapos に入れるか」だけを扱い、Page への投稿権限は持ちません。投稿用には Meta Developer のアプリと **Page Access Token** が必要です。

現状の Scrapos はコンテンツがまだデータベースではなくデモデータです。投稿の実体は `poster.services.facebook_service.FacebookPageService` と、次の管理コマンドです。

| コマンド | 用途 |
|---|---|
| `python manage.py facebook_page_status` | 設定の有無と Page 名を確認（トークンは出さない） |
| `python manage.py exchange_facebook_token --user-token …` | 短いユーザー用トークンを Page 用トークンに交換 |
| `python manage.py publish_facebook_post …` | 本文またはデモコンテンツを Page に投稿 |

Integrations 画面の「Connect」ボタンや Poster のスケジュール UI からの自動配信は、まだつながっていません。

---

## 事前にそろえるもの

1. [Meta for Developers](https://developers.facebook.com/) のアカウント（作成済み）
2. 投稿先になる **Facebook Page**（自分が管理者で、`CREATE_CONTENT` ができること）
3. その Page を所有する Facebook アカウントで、developers.facebook.com にログインできること
4. ローカルなら Scrapos の `.env`（git には入れない。`manage.py` が自動で読む）

個人プロフィールのタイムラインへ API で投稿することはできません。対象は Page だけです。

---

## 1. Meta アプリを作る

1. [Meta for Developers](https://developers.facebook.com/apps/) を開く
2. **アプリを作成** を選ぶ
3. 用途は **その他（Other）** または **ビジネス**。種類は **ビジネス** が無難です
4. アプリ名は例: `Scrapos Page Publisher`（Cognito 用の既存アプリとは分ける）
5. 連絡先メールを入れて作成する

ダッシュボードで **アプリ ID** と **アプリシークレット** を控えます。シークレットは「表示」した瞬間だけコピーし、チャットや issue に貼らないでください。

---

## 2. 必要なプロダクトを足す

アプリダッシュボードの **製品を追加** から、次を追加します。

1. **Facebook ログイン**（または Facebook ログイン for Business）
   - 開発中のトークン取得と、将来 Integrations 画面で OAuth 接続するときに使います
   - 有効な OAuth リダイレクト URI は、Graph API Explorer だけ使う段階では空のままで構いません
2. ドキュメント上は **Pages API** を使います。別途「Pages」製品が選択肢にあれば追加します

**Use cases**（ユースケース）画面がある場合は、Page のコンテンツ管理に相当するものを選び、権限をそこで要求します。

---

## 3. 権限（Permissions）

投稿に必要な権限は次です。Graph API Explorer と、本番の App Review の両方で同じ名前です。

| 権限 | 役割 |
|---|---|
| `pages_show_list` | 管理している Page の一覧 |
| `pages_read_engagement` | Page の投稿を読む（確認用） |
| `pages_manage_posts` | Page として投稿する |
| `pages_manage_metadata` | Page メタデータ（セットアップ確認用） |

動画を上げるなら `publish_video` も必要です。コメント操作までするなら `pages_manage_engagement` が追加で要ります。Scrapos の第一版はテキスト / リンク / 画像 URL だけです。

開発モードでは、**アプリの管理者・開発者・テスター** が管理する Page にだけ投稿できます。他人の Page へ出す本番利用は、後述の App Review が必要です。

1. アプリの **役割（Roles）** で、投稿に使う Facebook ユーザーを管理者または開発者にする
2. 同じユーザーが、投稿先 Page の管理者であること

---

## 4. Graph API Explorer で短いトークンを取る

1. [Graph API Explorer](https://developers.facebook.com/tools/explorer/) を開く
2. 右上の **Meta App** で、今作ったアプリを選ぶ
3. **User or Page** はいったん **User Token** のまま
4. **Permissions** で上表の権限を追加し、**Generate Access Token** を押す
5. Facebook の同意画面で、対象 Page へのアクセスを許可する
6. クエリを `GET /me/accounts` にして **Submit**

応答の各要素に `id`（Page ID）と `access_token`（Page Access Token）が入ります。Explorer の **User or Page** をその Page に切り替えてから、次を試せます。

```http
POST /{page-id}/feed
message=Scrapos からのテスト投稿
```

成功すると `{"id": "{page-id}_{post-id}"}` が返り、Page に投稿が見えます。

Explorer のユーザー用トークンは **1〜2 時間** で切れます。このまま `.env` に入れないでください。次の手順で長い Page トークンに交換します。

---

## 5. Scrapos で長い Page トークンに交換する

`.env.example` を `.env` にコピーし、アプリ資格情報だけ入れます（Page トークンはまだ空でよい）。Windows なら `copy .env.example .env`。Django が `.env` を自動で読むので、`set` や `source` は不要です。

```bash
FACEBOOK_APP_ID=<アプリ ID>
FACEBOOK_APP_SECRET=<アプリシークレット>
FACEBOOK_GRAPH_API_VERSION=v22.0
```

Explorer で今出した **User Token** を渡し、交換します。

```bash
python manage.py exchange_facebook_token --user-token "<Explorer の User Token>"
```

標準出力に次が出ます。

- 約 60 日有効な **long-lived user token**
- 管理下 Page ごとの `FACEBOOK_PAGE_ID` と `FACEBOOK_PAGE_ACCESS_TOKEN`

Page 用トークンは、アプリと Page の関係が切れない限り **期限なし** になることがほとんどです。表示は一度きりなので、その場で `.env` か Secrets Manager に移してください。コマンドはファイルに書きません。

```bash
FACEBOOK_APP_ID=<アプリ ID>
FACEBOOK_APP_SECRET=<アプリシークレット>
FACEBOOK_PAGE_ID=<選んだ Page の id>
FACEBOOK_PAGE_ACCESS_TOKEN=<その Page の access_token>
FACEBOOK_GRAPH_API_VERSION=v22.0
```

確認（トークンは表示されません）:

```bash
python manage.py facebook_page_status
```

`publish_ready: yes` と Page 名が出れば投稿できます。

---

## 6. Scrapos の内容を投稿する

コンテンツがデータベースになるまでは、デモ id（`frontend_demo.data.CONTENT_ITEMS`）か、本文を直接渡します。

```bash
# 実投稿の前に本文だけ確認
python manage.py publish_facebook_post --content-id CT-902 --dry-run

# デモコンテンツを即時投稿
python manage.py publish_facebook_post --content-id CT-902

# 本文を直接指定
python manage.py publish_facebook_post --message "2月入学のリマインダーです。"

# リンク付き
python manage.py publish_facebook_post --message "奨学金のまとめ" --link "https://example.org/scholarships"

# 公開画像 URL で写真投稿
python manage.py publish_facebook_post --content-id CT-902 --image-url "https://example.org/hero.jpg"

# Facebook の予約投稿（今から 10 分〜30 日）
python manage.py publish_facebook_post --message "明日のお知らせ" --schedule-at "2026-09-03T10:00:00+10:00"
```

成功すると `Published Facebook post {id}` だけが出ます。トークンはログにも出ません。

コードから呼ぶ場合:

```python
from poster.services.facebook_service import FacebookPageService

FacebookPageService().publish(
    message="Studying in Australia: a 2026 guide",
    link="https://example.org/guide",
)
```

Graph API の例外はすべて `poster.exceptions` に変換されます。ビューやテンプレートは Facebook の生エラーを見ません。

---

## 7. 本番（Live）と App Review

| 対象 | 必要なもの |
|---|---|
| 自分（アプリの管理者 / 開発者 / テスター）が管理する Page | 開発モードのままで投稿できる |
| 上記以外の人の Page | アプリを **Live** にし、権限の **高度なアクセス（Advanced Access）** を App Review で通す。多くの場合 Business Verification も必要 |

App Review では、レビュアーが「Scrapos が Page に投稿する」流れを再現できる手順を出します。スクリーンショットと、テスト用 Page / テストユーザーを用意します。

本番のトークンは ECS タスク定義から Secrets Manager を参照する形にしてください。`.env` や GitLab CI 変数に生トークンを置かないこと。既存の Django / Cognito シークレットと同じパターンです。`docs/gitlab-ci-variables.md` と `docs/authentication.md` を参照。

---

## 8. セキュリティ

- Page Access Token は Page として何でも投稿できる鍵です。git、issue、監査ログの `metadata`、テンプレートに載せない
- `scrapos.facebook` ロガーはイベント名と Graph のエラーコードだけを出します
- Cognito の Facebook ログイン用アプリと、投稿用アプリは分けた方が権限の説明が簡単です
- トークンが漏れたら Meta アプリダッシュボードでリセットし、`.env` / Secrets Manager を更新する

---

## 9. まだないもの（次の実装）

- Integrations 画面の Facebook **Connect**（OAuth で Page を選ぶ UI）
- Poster / Schedule / Calendar からこのサービスを呼ぶジョブ
- コンテンツの本番モデル（いまはデモ行）
- Instagram 投稿（別 API。Facebook Page に紐づく Professional アカウントが必要）

それらを足すときも、Graph API への呼び出しは `FacebookPageService` だけに閉じ、トークンは設定または暗号化ストアに置いてください。
