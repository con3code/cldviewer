# cldviewer — Claude Code セッションログビューア

> **English:** A single-file, dependency-free (Python 3 standard library only) viewer for
> [Claude Code](https://claude.com/claude-code) session logs stored under `~/.claude/projects/`.
> It groups logs by project, shows your prompts as a timeline first, and lets you expand
> Claude's responses and the detailed reasoning / tool-call logs on demand. Includes scoped
> keyword search, CSV / Markdown export, copy buttons, pinning, merging logs from several
> locations, and merging projects whose working path has changed. Run `python3 cldviewer.py`
> and a browser opens. `python3 cldviewer.py export -o cld.html` produces a standalone HTML
> that needs no Python. The UI is bilingual: click the **EN / 日本語** button in the sidebar to
> switch, or start with `python3 cldviewer.py --lang en` (also `CLDVIEWER_LANG=en`) to make
> English the default for the UI, CSV headers and CLI messages.

`~/.claude/projects/` に蓄積される Claude Code のセッションログ（JSONL）を、
プロジェクト（作業フォルダ）単位で時系列に振り返るためのビューアです。

- **Python 3 の標準ライブラリだけで動く単一ファイル**（`cldviewer.py`）。コピーするだけでどの端末でも動く
- 最初は「自分が出した依頼」だけが時系列に並び、必要に応じて「応答」「推論・実行ログ」を段階的に展開
- 複数のログの場所（別ドライブなど）の統合、パスが変わって分かれたプロジェクトの統合
- 範囲別のキーワード検索、CSV / Markdown 書き出し、コピーボタン、ピン留め
- Python が無い端末向けに、データ埋め込み済みの単体 HTML を書き出せる

## 動作環境

- Python 3.8 以降（追加パッケージ不要）
- ブラウザ（Chrome / Safari / Edge / Firefox の最近の版）

## 使い方

### 起動

```bash
python3 cldviewer.py                 # ~/.claude/projects を読み込み、ブラウザが開く（http://localhost:8765/）
python3 cldviewer.py --port 9000     # ポートを変える（使用中なら自動で次のポートを探す）
python3 cldviewer.py --no-browser    # ブラウザを自動で開かない
python3 cldviewer.py --lang en       # 英語で起動（UI の初期言語・CSV の見出し・CLI のメッセージ）
python3 cldviewer.py list            # プロジェクト一覧を端末に表示
```

終了は Ctrl+C です。

### 表示言語

- 画面左上の **EN / 日本語** ボタンでいつでも切り替えられます。選んだ言語はブラウザに記憶されます。
- `--lang en` または環境変数 `CLDVIEWER_LANG=en` で、UI の初期言語、CSV の見出し、CLI のメッセージとヘルプを英語にできます。
- 書き出した単体 HTML でも同じボタンで切り替えられます。

### ログの場所を増やす（別ドライブ・別端末のログ）

```bash
python3 cldviewer.py --dir /path/to/projects                                  # 場所を指定
python3 cldviewer.py --dir ~/.claude/projects --dir /Volumes/HDD/claude-projects  # 複数の場所をまとめて表示
```

- 画面左下の「ログの場所」欄からもディレクトリを追加・削除できます。追加した場所は
  `~/.config/cldviewer/roots.json` に保存され、次回以降は指定なしで自動的に読み込まれます。
- 複数の場所に同じプロジェクトフォルダがある場合は 1 つのタイムラインに統合されます。
  同じセッション ID のファイルが両方にあるときは大きい方を採用します。
- 外れているドライブは赤い取り消し線で表示され、読み込みはスキップされます。
- `--no-config` を付けると、保存済みの設定（ログの場所・プロジェクト統合）を読み込みません。

### パスが変わって分かれたプロジェクトを統合する

ドライブ移動などで作業パスが変わると、Claude Code はログを別フォルダに記録するため別プロジェクトに見えます。

- 作業フォルダの末尾名が同じプロジェクトは、サイドバー上部に「統合候補」として自動的に提示されます。
  「統合」で 1 クリックでまとめられ、「選択」を押すと候補をチェック済みの状態で確認しながら選べます。
- 手動で統合するにはサイドバーの「統合…」で選択モードに入り、2 つ以上にチェックを入れて名前を付けます。
  既存の統合プロジェクトを含めて選ぶと、その構成も展開して 1 つにまとめます。
- 統合プロジェクトの画面では構成元のパスが 📂1、📂2 の印付きで表示され、各セッションのチップにも
  同じ印が付きます。「名前を変更」「統合を解除」もここから行えます。
- 定義は `~/.config/cldviewer/groups.json` に保存されます。ログ自体は一切変更しません。
- `export` / `csv` の `--project` には統合後の名前も使えます。

### 単体 HTML の書き出し（Python が無い端末で見る）

```bash
python3 cldviewer.py export -o cld.html --project keydisp   # 特定プロジェクトだけ（パスや名前の部分一致、複数可）
python3 cldviewer.py export -o cld.html --light             # 全プロジェクト、推論・ツールログを省いて軽量に
python3 cldviewer.py export -o cld.html --project keydisp --images   # 画像も埋め込む（サイズ大）
```

書き出した HTML はブラウザで開くだけで、検索・展開・CSV 書き出しがそのまま使えます。
ログの場所の追加やプロジェクト統合はサーバ側の機能なので、書き出し版では使えません。
ツールログを含めて全プロジェクトを書き出すと大きくなるので、対象を絞るか `--light` を使ってください。

### CSV の書き出し

ブラウザの「書き出し / コピー」メニューから（現在の絞り込み結果が対象）、または CLI で書き出せます。
Excel でそのまま開けるよう UTF-8（BOM 付き）で出力します。

```bash
python3 cldviewer.py csv --project keydisp --mode prompts   # 依頼だけ
python3 cldviewer.py csv --project keydisp --mode pairs     # 依頼と応答（要約・所要時間・ツール回数付き）
python3 cldviewer.py csv --project keydisp --mode full      # 推論・ツール呼び出し・通知を含む全体
python3 cldviewer.py csv --project keydisp --mode pairs -o out.csv
```

画面のメニューにはこのほか「Markdown をコピー（依頼のみ / 依頼と応答）」と
「プレーンテキストをコピー（1 行 1 依頼）」があります。

## 画面の見方

### サイドバー（左）

- プロジェクト一覧（セッション数・サイズ・最終更新・統合の有無）。上の欄で絞り込めます
- 「統合…」ボタン、統合候補の提示
- 下部に「ログの場所」の一覧と追加欄、キー操作のヘルプ

### タイムライン（右）

- 選んだプロジェクトの全セッションを日付ごとに時系列で並べます。セッションは色付きチップで区別でき、
  チップをクリックするとそのセッションだけに絞れます。チップにマウスを乗せると ID・期間・コスト・
  ファイルの場所が表示されます
- 各ターン（1 つの依頼とそれに対する処理）のカード
  - 時刻、種別バッジ、セッション印、所要時間、ツール呼び出し回数、モデル、ピン留め（★）、依頼のコピー
  - 依頼の本文（長いものは折りたたみ）
  - Claude 自身によるターンの要約（記録があれば「要約」行として表示）
  - 「応答」: Claude の返答・報告を Markdown 描画で表示。個別と全体のコピーボタン付き
  - 「詳細（推論・実行ログ）」: 推論、ツール呼び出し（入力と結果、所要時間、エラー表示）、
    通知、圧縮サマリー、サブエージェントの動作ログ。各ステップはクリックで開閉、
    コマンド・入力・結果ごとにコピーボタン付き
- 「応答を全展開」「詳細を全展開」「全て閉じる」で一括操作

### 種別バッジ

| 表示 | 意味 |
|---|---|
| 依頼 | 自分が入力したプロンプト |
| 依頼(割込) | Claude の作業中に送った追加メッセージ |
| コマンド | `/init` などのスラッシュコマンド |
| シェル | `!` によるシェルコマンド実行 |
| 他エージェント: 名前 | 別セッションの Claude から届いたメッセージ。**既定で 1 行に畳んで表示**し、クリックで展開 |
| 継続 / 自動 | 前セッションからの継続や、依頼なしで始まったターン（「依頼のあるターンのみ」を外すと表示） |

バックグラウンドタスクの完了通知やサブエージェントの最終報告は依頼としては数えず、
「詳細」の通知行に入ります（「通知・システム行を表示」で確認できます）。

### 検索と絞り込み

- キーワード検索は範囲を「依頼 / 応答 / 全体（推論・ツールログ含む）」から選べます。
  スペース区切りで AND 検索、大文字小文字は区別しません。一致箇所はハイライトされ、
  該当するパネル（応答や詳細）は自動で開きます
- 日付範囲、セッション、ピン留めのみ、他エージェントメッセージの表示有無で絞り込めます
- 並び順は「古い順」「新しい順」を選べます（選択はブラウザに記憶）。書き出しも表示中の順序に従います
- 依頼に貼り付けた画像や、ツール結果に含まれる画像（スクリーンショットなど）はサムネイル表示され、
  クリックで拡大できます（Esc で閉じる、新しいタブで開くリンク付き）。「画像を表示」で切り替え可能です
- 絞り込み結果はそのまま CSV / Markdown 書き出しの対象になります

### キー操作

| キー | 動作 |
|---|---|
| `/` | 検索欄にフォーカス |
| `j` / `k` | 次 / 前のターンへ移動 |
| `o` | 応答を開閉 |
| `d` | 詳細を開閉 |
| `p` | ピン留め |
| `c` | 依頼をコピー |
| `Esc` | 検索をクリア |

## 仕組みと補足

- 解析結果は `~/.cache/cldviewer/` にキャッシュされ、更新されたログファイルだけ再解析します
  （`--no-cache` で無効化）。初回は大きなログの解析に数秒かかることがあります
- 「ログを更新」ボタンで、表示中のプロジェクトのログを読み直せます（Claude Code が動作中でも可）
- ツールの入出力は 1 件 20,000 文字で丸めています（`cldviewer.py` 冒頭の `MAX_TEXT`）。
  テキスト上では画像を `[image]` に置き換え、画像データ自体はキャッシュに入れず、
  サムネイル表示時にログファイルの該当行から直接読み出します（単体 HTML では `--images` を付けたときのみ埋め込み）
- 大きなプロジェクトでも軽いように、推論・ツールログは展開時にサーバから取得します。
  「全体」範囲の検索はサーバ側で行います
- ピン留めはブラウザの localStorage に保存されます（プロジェクトごと）
- サーバは `127.0.0.1` にのみ待ち受けます。他の端末から見たい場合は `--host 0.0.0.0` を指定してください
  （ログには作業内容がそのまま含まれるため、信頼できるネットワークでのみ使ってください）

## ファイル構成

| ファイル | 内容 |
|---|---|
| `cldviewer.py` | 本体（解析・サーバ・CLI・内蔵 UI、日本語/英語の文言辞書） |
| `~/.cache/cldviewer/` | 解析キャッシュ（消しても再生成されます） |
| `~/.config/cldviewer/roots.json` | 画面から追加したログの場所 |
| `~/.config/cldviewer/groups.json` | プロジェクト統合の定義 |

## ライセンス

MIT License
