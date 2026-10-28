[English](https://github.com/Cor-Incorporated/grift-cli/blob/main/README.en.md) | **日本語**

# grift

grift を使うと、エンジニアがこれまでどんなコードを、どれくらい、テストで確かめながら変えてきたかを、git（コードの変更を 1 件ずつ記録する仕組み）に残った記録から件数つきで知ることができます。点数や順位はつけません。

## 立場ごとの使い方

### 案件を探しているエンジニアの方

1 人で書いてきたリポジトリ（コードと変更の記録を置く場所）なら、`grift repo` で、どの領域をどれくらい触ってきたか、変更にテストを伴わせてきたかを件数つきで確かめられます。ほかの人と書いたリポジトリでは、identity ファイル（誰がどのメールアドレスで書いたかの一覧）に自分を書き、`grift actor` で自分の変更だけを数えてください。経歴書に書いた経験の横に、確かめられる事実を添えられます。見せるリポジトリを選ぶのも、共有するかどうかを決めるのも本人です。

### エンジニアを案件に紹介する営業の方

候補者が共有してくれた記録を、なぜその人を推薦するのかを説明する材料として使えます。数値は「何件のうち何件か」と一緒に伝えてください。1 つの数値で足切りする使い方や、人に順位を付ける使い方は、[利用規範](docs/norms.md)に準拠しない使い方と定めています。

### エンジニアを探している案件の担当者の方

`grift project --init --out .tep/project.toml` で書式のひな形を作り、求める領域やテストの進め方を書き込みます。`grift align` がその要求と候補者の記録を項目ごとに並べます。合計点や合否は出しません。並んだ数値は面談で何を聞くかを決める材料にしてください。

## 試す

エンジニアの方は次の 3 行で自分のリポジトリを見られます。

```bash
pipx install grift-cli
cd your-repo
grift repo
```

grift が動くのに要るのは、Python 3.11 以上と git だけです。結果は画面に出るだけで、ファイルは作らず、どこにも送りません。保存するときは `--out DIR` を、JSON で受け取るときは `--format json` を付けます。`grift` が見つからないと言われたら、`pipx ensurepath` を実行してからターミナルを開き直してください。

## 出力の読み方

`grift repo` の画面には、リポジトリ全体について次のような値が出ます。どの値にも「何件のうち何件か」が付きます。

- 変えた部分の区分（作業領域）: テスト、ドキュメント、CI、画面（フロントエンド）など 11 の区分ごとに、その区分のファイルを触った commit（変更 1 件ごとの記録）が何件あったか。
- 変更のペース（変更リズム）: 直近 180 日に変更を出した日数と、変更と変更のあいだが何日空いたか。労働時間や速さではありません。
- テストの付け方（検証の形）: テストのファイルを含む commit の割合と、テストの種類（unit、integration など）。
- 関わった人の一覧: 人ごとの commit の件数。並びは ID の順で、件数の多い順ではありません。

JSON（`--format json`）と `grift analyze` の出力には、次の値も入ります。

- 帰属の区別: その変更が誰の仕事か。identity ファイルに載せた人、ほかの人、bot（自動で動くアカウント）、自動で作られたファイル、元のリポジトリ（fork 元）から引き継いだ変更などを 11 通りに分けます。
- テスト併修率（JSON では `test_cochange`）: 本番のコードを変えた commit のうち、同じ commit でテストも変えた割合です。たとえば、本番のコードを変えた commit が 40 件あり、そのうち 12 件でテストも変えていれば「40 件のうち 12 件」と書きます（架空の例）。

`grift align` の出力では、案件側が書いた要求と記録から数えた値を項目ごとに並べ、重なり、範囲外、0 件、未観測、要求なしの 5 通りで書きます。

`grift actor`（本人が名乗った ID と同意の記録があるとき）と `grift project` の Markdown の先頭には、記録から見える進め方を平易な文で書きます。`grift actor` と `grift align` には、面談で確かめたいことを問いとして並べます。文と問いは[決定表](docs/trait-profile.md)で数字から選び、点数やタイプ名にはしません。管理者が登録した ID や、公開リポジトリから推定したまとまりの actor レポートには文を出さず、出していない理由を書きます。照らし合わせの問いも、本人が名乗った ID と同意の記録があるときだけ出します。

測れなかった値は 0 にせず、「観測できなかった」と理由を書きます（出力では `not_observed`）。記録が無いことは、経験が無いことを意味しません。母数（数えた件数の合計）が 20 に満たないときは、レポートの文面に率を書かず、件数だけを書きます。

数値ごとの説明は [docs/metrics-guide.md](docs/metrics-guide.md) にあります。griftai.org と cor-jp.com で使う言葉（検査値、テスト併修率、手戻り率、磨き直し、コードの新しさ）と CLI の言葉の[対応表](docs/metrics-guide.md#サイトの訳語と-cli-の語の対応表)も、ここにまとめています。

## なぜ作ったか

人材紹介会社や SES の営業がエンジニアを案件に推薦するとき、手元にある材料は経歴書と面談の印象がほとんどです。一方で、commit の数のような「活動量」は、生成 AI を使えば簡単に膨らみます。Cor.株式会社は git の記録から確かめられる事実だけを数え方と一緒に取り出せるように grift を作り、オープンソース（MIT ライセンス）として公開しました。

ただし、grift の数値も形だけの変更で動くことがあります。分かっている膨らませ方の一部（たとえば変更を出した日数）は、レポートの数値の横に書き添えています。

## 自己申告の診断や経歴書との違い

MBTI のような性格診断は、本人が質問に答えた内容からタイプを出します。経歴書も本人が書いたものです。どちらも、本人が自分をどう見ているかにもとづきます（grift は MBTI と関係も提携もありません）。

grift は質問をしません。git に残った変更の記録を数え、傾向と、その根拠になった件数を出します。人をタイプに分けたり、名前を付けたりはしません。同じ時点の履歴を、同じ人の一覧と同じ版で数えれば、誰が実行しても同じ値になるので、受け取った側が計算し直して確かめられます。ただし、同じ値が出ることは、値の正しさや、仕事の質や優秀さの証明にはなりません。会議や設計の相談、非公開のリポジトリなど、git に残らない仕事も見えません。

## TEP（Technical Evidence Pipeline）

TEP（Technical Evidence Pipeline）は、grift が使っている手法の名前です。git の履歴から確かめられる事実を取り出し、何を、どの期間で、何件のうち何件と数えたかを添えて出し、受け取った側が同じ手順で計算し直せるようにする、という一連の決まりを指します。grift はその手順を実行するコマンドで、計測に生成 AI（LLM）は使いません。

数値の使い方は[利用規範（norms）](docs/norms.md)の 7 条で決めています。記録が無いことを実績が無いと読まない、1 つの数値だけで足切りしない、本人の同意なく第三者を調べない、監視に転用しない、複数の数値に重みを付けて 1 つの点数にしない、などです。この規範に従うことを、「TEP」の名を使う条件にしています。

## 主なコマンド

- `grift repo`: リポジトリ全体の記録を出します。
- `grift actor ID`: 1 人（actor）の記録を出します。ID は identity ファイルの canonical_id か、identity が無いときに履歴から作る actor id です。
- `grift project`: リポジトリの運用の形を観測するか、案件側が宣言した要求（`--requirements`）を読み込みます。`--init --out FILE` で要求の書式のひな形を作れます。
- `grift align`: 宣言と記録を項目ごとに並べます。総合点は出しません。
- `grift verify`: 保存したレポートを同じ条件で計算し直し、一致するかを確かめます。結果は `VERIFIED`（一致）、`MISMATCH`（不一致）、`CANNOT_VERIFY`（確かめられない）のどれかです。

1 人の記録と案件の要求を並べるときは、次のように実行します。

```bash
grift actor candidate_001 --identity .tep/identity.toml --format both --out actor-report.json
grift project --requirements .tep/project.toml --format both --out project-out
grift align \
  --actor-report actor-report.json \
  --project-report project-out/project.json \
  --format both --out alignment-out
```

複数人の記録の書き出し、identity の書き方、公開 Forge からの取得、署名、終了コード、以前の版からの更新の注意は [docs/usage.md](docs/usage.md) にまとめています。

## データの扱い

grift は手元の PC で動きます。ネットワークに接続するのは、`--fetch-public`、`grift update`、`grift contribute --open` などを明示したときだけです。接続する操作の一覧は [docs/usage.md](docs/usage.md#ネットワークに接続する操作) にあります。この CLI には、当社へデータを自動で送る機能はありません。今後もこの CLI には入れません。当社が grift を組み込んだアプリケーションやサービスを別に提供する場合、そこでのデータの扱いはそのサービスの利用規約とプライバシーポリシーで定めます。

参照分布をつくるためにレポートの値を提出する `grift contribute` は、本人が選んだときだけ動きます。提出先は公開リポジトリの [tep-contributions](https://github.com/Cor-Incorporated/tep-contributions) で、PR を作る最後のボタンは本人が押します。

## GitHub Actions で使う

```yaml
permissions:
  contents: read
steps:
  - uses: actions/checkout@v4
    with:
      fetch-depth: 0
      persist-credentials: false
  - uses: actions/setup-python@v5
    with:
      python-version: "3.12"
  - uses: Cor-Incorporated/grift-cli@v0.9.1
    with:
      scope: repo
      comment: false
```

`grift analyze` を実行して、要約を `$GITHUB_STEP_SUMMARY` に書き、report.md と report.json を artifact に上げます。観測値を合否や閾値には変えません。

- 呼び出し元のリポジトリの全履歴と、Python 3.11 以上が要ります。checkout していない、または shallow clone のときは、計測の前に止まります（fail-closed、exit 2）。入力が決まりに合わないときも fail-closed で止まります。
- `contents: read` と `comment: false` で動かし、PR のコードに write 権限の token を渡さないでください。`comment: true` の経路は実装していますが、このプロジェクトの CI は読み取り専用で動かしているため、その経路はまだ確かめていません。信頼できる後段の workflow を設計するまでは、PR のコードに write 権限を付けません。

## ドキュメント

- [コマンドの詳しい使い方](docs/usage.md)
- [レポートの読み方](docs/metrics-guide.md)
- [利用規範（norms）](docs/norms.md)
- [指標の検証と限界](docs/validation.md)。数値を出すときの設計の選択とその限界、公開 117 リポジトリで指標を確かめた結果（差が出た比較と出なかった比較の両方）を載せています
- 出力の形式: [report-v2](docs/report-v2.md)、[report-v1](docs/report-schema.md)、[alignment](docs/alignment-schema.md)、[project](docs/project-schema.md)、[identity](docs/identity-schema.md)、[export](docs/export-schema.md)、[ローカル export の入力](docs/input-export-schema.md)
- [変更履歴（CHANGELOG）](CHANGELOG.md)と、0.9.1 への[移行の注意](docs/migration-v091.md)

製品サイトは [griftai.org](https://griftai.org) です。

## 関わり方

- 質問や不具合の報告は、公開リポジトリの [Issues](https://github.com/Cor-Incorporated/grift-cli/issues) にお願いします。
- コードや文書に手を入れたい人は [CONTRIBUTING.md](CONTRIBUTING.md) を読んでください。行動規範は [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) です。
- 脆弱性は公開の Issue に書かず、[SECURITY.md](SECURITY.md) の方法で知らせてください。
- 検証用データに入っている、公開 commit のメタデータ由来のメールアドレスの削除依頼も Issues で受け付けます。非公開で連絡する方法は [tep-contributions](https://github.com/Cor-Incorporated/tep-contributions) の README にあります。代理で連絡すれば依頼した人の名前は伏せられますが、公開済みの corpus のデータそのものが非公開になるわけではありません。

## License

MIT. See [LICENSE](LICENSE).
