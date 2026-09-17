# Instagram コメントを API で管理する（作成 / 取得 / 返信 / 削除）

Meta Graph API で、**自分の Instagram Professional アカウントの投稿**に対するコメントを扱います。Cognito の Facebook ログインとも、Facebook Page への投稿とも別の権限です。同じ Meta アプリと **Page Access Token** を流用できます。

Scrapos 側は `poster.services.instagram_comments.InstagramCommentService` と次のコマンドです。

```bash
python manage.py instagram_comment media
python manage.py instagram_comment list --media-id <IG_MEDIA_ID>
python manage.py instagram_comment create --media-id <IG_MEDIA_ID> --message "テストコメント"
python manage.py instagram_comment reply --comment-id <IG_COMMENT_ID> --message "返信です"
python manage.py instagram_comment delete --comment-id <IG_COMMENT_ID>
```

トークンはログにも画面にも出しません。

---

## できること / できないこと

| 操作 | API | 誰として行われるか |
|---|---|---|
| 作成 | `POST /{ig-media-id}/comments` | **自分の Professional アカウント**が、自分の投稿にコメントする |
| 取得 | `GET /{ig-media-id}/comments` | その投稿のコメント一覧 |
| 返信 | `POST /{ig-comment-id}/replies` | 自分のアカウントが、トップレベルコメントに返信する |
| 削除 | `DELETE /{ig-comment-id}` | 投稿の持ち主（自分）だけが消せる |

API では他人のアカウントになりすましてコメントは作れません。テスト用の「一般ユーザーのコメント」が必要なら、別の Instagram アプリからその投稿に手動で書き、そのコメント ID に返信・削除します。

返信の返信は、トップレベルコメントに付きます。非表示コメントやライブ配信のコメントは対象外です。

---

## 1. Instagram を Page に接続する

1. Instagram を **Professional**（ビジネスまたはクリエイター）にする
2. 投稿に使っている **Facebook Page** に、そのアカウントを接続する  
   Instagram アプリ → 設定 → アカウントのリンク / Facebook Page
3. 同じ Facebook ユーザーが、その Page の管理者であること

Page が無いと Instagram Graph API（Facebook Login 経由）は使えません。

---

## 2. Meta アプリの権限

投稿用に作ったアプリで足します。

| 権限 | 用途 |
|---|---|
| `instagram_basic` | アカウントとメディアの読み取り |
| `instagram_manage_comments` | コメントの作成・返信・削除 |
| `pages_show_list` | 管理 Page の一覧 |
| `pages_read_engagement` | Page / メディアの読み取り |

開発モードでは、アプリの管理者・開発者・テスターが管理するアカウントだけです。

Graph API Explorer で User Token を出し、権限を付けてから `GET /me/accounts?fields=id,name,access_token,instagram_business_account` を実行します。

応答例:

```json
{
  "data": [{
    "id": "1120028241199416",
    "access_token": "…",
    "instagram_business_account": { "id": "1789…" }
  }]
}
```

`instagram_business_account` が無い Page は、まだ Instagram がつながっていません。

長い Page トークンへの交換は Facebook 投稿と同じです。

```bash
python manage.py exchange_facebook_token --user-token "<Explorer の User Token>"
```

---

## 3. Scrapos の `.env`

```bash
FACEBOOK_PAGE_ID=<Page の id>
FACEBOOK_PAGE_ACCESS_TOKEN=<Page トークン>
INSTAGRAM_ACCOUNT_ID=<instagram_business_account.id>
FACEBOOK_GRAPH_API_VERSION=v22.0
```

`INSTAGRAM_ACCOUNT_ID` を空にすると、Page から自動取得を試みます。トークンは git に入れないでください。

```bash
python manage.py instagram_comment media
```

投稿が一覧されれば接続できています。投稿が無いときは、Instagram アプリでテスト投稿を 1 本上げてから再実行します。

---

## 4. テストコメントの一連の操作

Windows（`.env` を置いたリポジトリのルート）:

```bat
python manage.py instagram_comment media
python manage.py instagram_comment list --media-id "<上の media id>"
python manage.py instagram_comment create --media-id "<media id>" --message "Scrapos test comment"
python manage.py instagram_comment list --media-id "<media id>"
python manage.py instagram_comment reply --comment-id "<list で出た comment id>" --message "Scrapos test reply"
python manage.py instagram_comment delete --comment-id "<消したい comment id>"
```

Explorer だけでも同じことができます。

```http
GET    /{ig-user-id}/media?fields=id,caption,permalink
GET    /{ig-media-id}/comments?fields=id,text,username,timestamp
POST   /{ig-media-id}/comments?message=Scrapos test comment
POST   /{ig-comment-id}/replies?message=Scrapos test reply
DELETE /{ig-comment-id}
```

ホストは `https://graph.facebook.com/v22.0`、クエリに `access_token=`（Page トークン）を付けます。

---

## 5. 本番（他人のアカウント）

自分のテストアカウントだけなら開発モードで足ります。顧客の Instagram を扱うなら App Review で `instagram_manage_comments` の Advanced Access が必要です。トークンは Secrets Manager に置き、git やチャットには貼らないでください。
