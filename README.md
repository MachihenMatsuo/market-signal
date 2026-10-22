# 食の補助金・行政ウォッチ（旧仮称：Market Signal Japan）

飲食・食品の事業者向けに、**補助金・公募の締切と、国の発表**を毎週自動でまとめ、
公開ページとメールで届ける仕組みです。GitHubの上で、毎日・毎週、決まった時刻に自動で動きます。

## 情報源（商用の配信に使ってよいことを、利用規約で確かめたものだけ）

| 情報源 | 中身 | 利用条件 |
|---|---|---|
| jGrants 公開API（デジタル庁） | 受付中の補助金（締切・対象地域・業種） | API利用規約。「出典：J グランツ」と、加工した旨の表示が必要 |
| 農林水産省 RSS | 報道発表 | 公共データ利用規約（第1.0版）。出典の記載で商用利用可 |
| ミラサポplus RSS（中小企業庁） | 補助金のお知らせ | 公共データ利用規約（第1.0版） |

使っていないもの：消費者庁・厚生労働省のRSS（メールマガジン等での再配布を断っている）、
J-Net21（商業目的の利用を禁止）、厚生労働省の食品回収情報（営利目的の複製・頒布を禁止）、
PR TIMES等（有償目的の利用を禁止）。使う場合は各機関の許可が必要です。

## 公開ページ（https://hojokin.machihen.com/）

毎朝の収集のあとに、次のページを作り直して公開します（号とは別。検索から来る人の入口）。

| ページ | 中身 |
|---|---|
| トップ `/` | 締切が近いもの（30日以内）、この14日間に受付が始まったもの、毎週のまとめ |
| 受付中の一覧 `/list/` | 飲食・食品の事業者が使える受付中の補助金・公募すべて（締切が近い順） |
| 業態別 `/gyotai/…` | 飲食店／食品製造・加工／食品卸・小売（その業態向け＋業種を問わないもの） |
| 都道府県別 `/chiiki/…` | その都道府県が対象のものが3件以上ある所だけ作る（＋全国対象のもの）。一覧 `/chiiki/` |
| 号 `/issues/日付.html` | 毎週月曜のメールと同じ内容 |

- 情報源に3日続けて載っていない補助金は、受付を終えた可能性があるので一覧から外します。
- 業種が絞られていて、食に関わる業種（製造業・卸売業、小売業・宿泊業、飲食サービス業・農業、林業・漁業）を含まないものは載せません（`config/rules.yaml` の `food_related_industries`）。
- 閲覧数：Cloudflare Web Analytics（サイト hojokin.machihen.com）。検索：Google Search Console（ドメイン machihen.com、アカウント ma20da1@gmail.com）。

## 毎週の流れ

1. **集める（毎日6:17）**：`config/sources.yaml` の情報源だけを1日1回見に行く
2. **振り分ける**：判定基準 `config/rules.yaml` で、載せるか・業態・地域・重要度を決める
3. **機械で照合する（人の確認の代わり）**
   - 出典のURLが開けるものだけ載せる
   - 公表日が対象期間内のもの、締切が過ぎていないものだけ載せる
   - 題名・日付・締切・地域は、情報源のデータをそのまま使う（AIは事実を書かない）
   - AIの見立てに、原文にない数字が入っていたら捨てる
4. **ページとメールを作って配信する（毎週月曜6:23）**
5. **異常があれば配信を止める**：0件、リンク切れが3割超、前の号と同じ内容、送信者の表示が未記入
   → 止めたときは、GitHubに「今週の配信を止めました」という知らせ（Issue）が立ち、メールで届きます
6. **数字を記録する**：`data/metrics.csv`（件数、照合で除いた数、AIの利用額、登録者数）

## 初回設定

| | 内容 | 状況 |
|---|---|---|
| 1 | ドメイン machihen.com をCloudflareで管理。info@ と matsuo.dai@ はGmailへ転送 | 済（2026年10月20日） |
| 2 | Brevo：無料プランで登録、machihen.com を認証、送信元 news@machihen.com を登録 | 済 |
| 3 | Brevo：登録者リスト「食の補助金・行政ウォッチ 登録者」（番号3）と登録フォームを作成 | 済 |
| 4 | 送信者の表示（まちへん合同会社・住所・info@machihen.com）を `config/settings.yaml` に記入 | 済 |
| 5 | Brevo：電話番号の確認（最初の配信の前に必要） | 松尾さん |
| 6 | GitHub：アカウント MachihenMatsuo に公開リポジトリ `market-signal` を作り、Claudeと連携。公開ページ https://machihenmatsuo.github.io/market-signal/ を公開 | 済（2026年10月20日） |
| 7 | Brevo：APIキー（権限：Email campaigns＝All、Contacts＝Read、期限2027年10月20日）を発行し、GitHubの Secrets に `EMAIL_API_KEY` として登録。接続を確認 | 済（2026年10月20日） |
| 7-2 | 閲覧数の集計：Cloudflare Web Analytics。検索：Google Search Console（ドメイン machihen.com をDNSで確認）に sitemap.xml を送信 | 済（2026年10月22日） |
| 7-3 | 公開アドレスを https://hojokin.machihen.com/ に変更（CloudflareのCNAME、GitHub Pagesの独自ドメイン、HTTPSを必須に） | 済（2026年10月22日） |
| 8 | （任意）AI：Anthropic の Console でAPIキーを発行し、月の上限額を設定 → Secrets に `ANTHROPIC_API_KEY` | 松尾さん |

- `EMAIL_API_KEY` が未登録の間は、公開ページだけ更新し、メールは送らずにGitHubで知らせます。
- 登録フォームは今は「確認メールなし」です。Brevo側で取引メール（システムから送るメール）が使えるようになったら、
  フォームの Settings で「Double confirmation email」（本人がリンクを押して登録が確定する方式）に切り替えます。

## 毎月・ふだんの作業

| いつ | すること |
|---|---|
| 毎月最初の月曜 | 「月1回の点検」のIssueに出る3件を原文と見比べる（15分） |
| 知らせが来たとき | 「配信を止めました」「登録者が上限に近い」などのIssueを見る |

## 費用の上限

- AI：月2,000円で自動的に止まる（実際の見込みは月113〜281円）。キーを登録しなければ0円
- GitHub：公開リポジトリの範囲で0円
- Brevo：無料プラン（1日300通まで）
- Cloudflare：無料プラン（DNSとメール転送）
- ドメイン：machihen.com の更新費（年1回、登録先の料金）

## 手元で動かす（確認用）

```
pip install -r requirements.txt
PYTHONPATH=src python -m pytest -q tests                    # テスト
MS_NOW=2026-10-20T12:00:00+09:00 PYTHONPATH=src python tests/preview.py   # 見本データで通しテスト
PYTHONPATH=src python -m market_signal weekly --dry-run      # 本番データで試す（メールは送らない）
```
