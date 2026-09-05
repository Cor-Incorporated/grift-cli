# P1c 先行研究 — corpus v2026.11 候補リスト（n=47 → 100+）（2026-08-22）

**位置づけ**: Phase 1 指示 WP-P1c の先行研究成果物（第3波指示 2026-08-22）。**分布ビルド（v2026.11）はまだ行わない** — admission 実行時に pins-v2026.11.toml として確定する。
**調査方法**: `gh` API（2026-08-22 時点）。SHA = default branch HEAD（admission 時に再固定する）。コミット数 = Link header 実測。tests = git-tree 走査（test dir / manifest の框架名）。既存 v2026.09 pin 37件 + golden 8件と重複なし（除外チェック済み）。衛生 needle 4語のヒットなし。

## 目標と充足見込み

| クラス | 目標 | 候補数 | 備考 |
|---|---|---|---|
| C（AI駆動）narratable | 30+ | **28**（tests あり・≥20コミット: 25 strong + 3 partial + 2 heavy） | 2件（autobe 686MB / vibe-vibe 415MB）はクローン重量で除外すると 26 — 「30未満でも所見として逐語記録」は P1c-4 の精神どおり |
| D（テンプレ） | 20+ | **29** | cookiecutter/copier/boilerplate/starter の4系統 |
| B 補充 | — | **8** | 個人メンテの実務ツール |
| 合計 | 100+（47+53以上） | **72** | 47 + 72 = 119（全採用であれば） |

## C class（35候補・narratable 優先でソート）

| repo | sha | license | tests | commits | 選定理由 / エビデンス |
|---|---|---|---|---|---|
| kenlasko/monize | ff758e55 | AGPL-3.0 | yes | 4640 | README: "100% written by AI. I've done practically zero manual changes" |
| adamtwiss/coda | 6531e16a | GPL-3.0 | yes | 2558 | "every line of code was written by Claude Code"（UCI チェスエンジン） |
| Yeachan-Heo/oh-my-claudecode | 94e71c36 | MIT | yes | 3559 | Claude Code 設定フレームワーク・38.7k★・個人 |
| onlook-dev/onlook | 423e2e92 | Apache-2.0 | yes | 1640 | 2024 AI-native 製品 "Cursor for Designers"・26.5k★ |
| tiann/hapi | be1ef2a2 | AGPL-3.0 | yes | 1388 | weishu 製・Claude Code/Codex/Cursor Agent セッション実行 |
| cloudflare/vibesdk | 89c5f3a8 | MIT | yes | 1123 | 公式 vibe-coding SDK（2025） |
| deutsia/deutsia-radio | 38499d6f | Apache-2.0 | yes | 1168 | README: "Built with Claude Code" |
| kevinpbuckley/VibeUE | b0bb5b93 | MIT | no | 1185 | AI-Powered UE 開発（tests なし→非narratable） |
| aipotheosis-labs/aci | 3e4a82fa | Apache-2.0 | yes | 856 | "Infra to Power Unified MCP Servers and VibeOps" |
| infiniteNIL/swish | c6fdb5ba | Apache-2.0 | partial | 698 | Lisp-in-Swift・"started out being written with Claude Code" |
| oisee/vibing-steampunk | 3bb165f8 | MIT | yes | 655 | SAP ADT への MCP ブリッジ |
| wonderwhy-er/DesktopCommanderMCP | 9bd8422d | MIT | yes | 554 | 9.4k★ MCP サーバ（2024・個人） |
| kcenon/claude_code_agent | e7ed2a10 | BSD-3-Clause | yes | 470 | Claude Agent SDK 製 AD-SDLC 自動化 |
| google/adk-python | d9f4d3d2 | Apache-2.0 | yes | 3875 | Agent Development Kit（pinned autogen と同アーキタイプ） |
| awslabs/mcp | 100b55b6 | Apache-2.0 | yes | 1797 | AWS MCP servers・README "Vibe Coding & Development" |
| smtg-ai/claude-squad | ce1ffb43 | AGPL-3.0 | yes | 222 | AI コーディングエージェントセッション管理・8.4k★ |
| zilliztech/claude-context | 6fc318b4 | MIT | yes | 217 | MCP context サーバ・12.4k★ |
| jihe520/mindpocket | caf493d3 | none | yes | 161 | README に "VIBE CODING" 節 |
| AdamLaurie/raiden-pico | dcc9be60 | none | partial | 141 | "All the code and test scripts… written and tested by Claude" |
| claude-world/claude-world-studio | a7ff6365 | MIT | yes | 83 | Claude World Studio エージェントビルダ |
| automazeio/ccpm | 7d7e4623 | MIT | no | 87 | Claude Code パッケージマネージャ（2025）・8.3k★ |
| sudomichael/agentgraphed | 0fc90d59 | MIT | yes | 80 | Claude Code/Codex 向け履歴可視化 |
| DeadWaveWave/demo2apk | 1405c440 | none | yes | 67 | "Turn your Vibe Coding ideas into runnable Android Apps" |
| run-llama/vibe-llama | cb28f060 | MIT | partial | 39 | LlamaIndex vibe-coding スタック |
| nexu-io/html-anything | f2cfd34c | Apache-2.0 | yes | 39 | "Your local agent writes it" |
| AkbarDevop/ai-job-agent | 9ce47d29 | MIT | no | 35 | badge "Built with Claude Code" |
| zarazhangrui/frontend-slides | 9906a34d | MIT | no | 30 | Claude Code スライドプラグイン・27.9k★・個人 |
| THU-Team-Eureka/EurekAgent | fb96df89 | AGPL-3.0 | no | 26 | badge "built on Claude Code" |
| joonlab/MacPilot | 9333dc22 | MIT | yes | 28 | "Built end-to-end with Claude Code" |
| CooperCyberCoffee/opencti_mcp_server | fa2ab0cc | NOASSERTION | no | 28 | Claude Desktop ↔ OpenCTI |
| omarshahine/claude-rename-agent | b978958a | MIT | no | 24 | Claude Agent SDK 製（ex-Microsoft VP） |
| mlstr0m/node-peek | dd1b8b96 | GPL-3.0 | yes | 21 | "The code was written by Claude from my specs" |
| hugoguerrap/crypto-claude-desk | e72d2996 | MIT | yes | 20 | 暗号トレードデスク |
| datawhalechina/vibe-vibe | f2e121d9 | none | yes | 410 | vibe-coding チュートリアル集・⚠415MB |
| wrtnlabs/autobe | f5de9927 | AGPL-3.0 | yes | 1654 | AI バックエンドジェネレータ・⚠686MB |

**narratable C の内訳**: 25 strong + 3 partial（swish / raiden-pico / vibe-llama）+ 2 heavy（vibe-vibe / autobe — クローン重量で除外するなら 26）。目標 30+ に対し 26〜28 で届く可能性が高いが、**届かなかった場合も「比較不能/不足」を所見として逐語記録する**（P1c-4・D-narratable 前例に準拠）。

## D class（29候補）

| repo | sha | license | tests | commits | 選定理由 |
|---|---|---|---|---|---|
| drivendataorg/cookiecutter-data-science | 0f6b163c | MIT | yes | 185 | 定番 DS cookiecutter |
| cookiecutter-flask/cookiecutter-flask | e5666c23 | MIT | yes | 2195 | 2013年からの Flask テンプレ |
| cjolowicz/cookiecutter-hypermodern-python | af0fd99e | MIT | yes | 1179 | hypermodern Python テンプレ（半休止） |
| ionelmc/cookiecutter-pylibrary | 609b67c6 | BSD-2-Clause | yes | 1208 | Python ライブラリテンプレ |
| osprey-oss/cookiecutter-uv | d7123d28 | MIT | yes | 120 | 2024 uv ベース |
| arthurhenrique/cookiecutter-fastapi | 6418a161 | MIT | yes | 169 | FastAPI+ML |
| lacion/cookiecutter-golang | d8e034b7 | MIT | yes | 63 | Go サービス |
| pytest-dev/cookiecutter-pytest-plugin | 8f38e95b | MIT | yes | 307 | pytest プラグインテンプレ（半休止） |
| superlinear-ai/substrate | ad9b9f61 | MIT | yes | 256 | copier 製 Python テンプレ |
| NLeSC/python-template | 1d1b6bb8 | Apache-2.0 | yes | 1391 | 研究ソフト copier テンプレ |
| pawamoy/copier-uv | a8fa3af2 | ISC | yes | 873 | 2024 copier・個人 |
| serious-scaffold/ss-python | 9222f049 | MIT | yes | 754 | 活発な copier スキャフォールド |
| browniebroke/pypackage-template | f361dcc5 | MIT | yes | 1529 | copier・個人 |
| lincc-frameworks/python-project-template | a7522ba4 | BSD-3-Clause | yes | 636 | 天文学コミュニティ copier |
| sahat/hackathon-starter | cd28225a | MIT | yes | 3057 | 定番 Node ボイラープレート・35k★ |
| ixartz/Next-js-Boilerplate | 51dfd23b | MIT | yes | 1734 | 個人・13k★ |
| ixartz/SaaS-Boilerplate | e3952a7e | MIT | yes | 180 | 2024 SaaS スターター・個人 |
| hagopj13/node-express-boilerplate | 179ae84e | MIT | yes | 241 | REST API ボイラープレート（2024-07 休止） |
| vercel/next-forge | f189de79 | MIT | yes | 1496 | 公式 Next.js テンプレ |
| mikestefanello/pagoda | 02a6db27 | MIT | yes | 281 | Go Web スターター・個人 |
| fullstackhero/dotnet-starter-kit | 3f2959e6 | MIT | yes | 2588 | .NET スターター・個人 |
| brocoders/nestjs-boilerplate | 9620f159 | MIT | yes | 2126 | NestJS ボイラープレート |
| obytes/react-native-template-obytes | fd9b358e | MIT | yes | 711 | RN テンプレ |
| rappasoft/laravel-boilerplate | a91de1ef | none | yes | 3006 | Laravel・個人 |
| wasp-lang/open-saas | cbd30162 | MIT | yes | 637 | 無料 SaaS スターター |
| n8n-io/self-hosted-ai-starter-kit | 662bd889 | Apache-2.0 | no | 40 | docker-compose AI スターター（最小コミット型）・15k★ |
| lissy93/cv | 36cb7728 | MIT | no | 122 | 個人 CV "generated from template" |
| pal-robotics/tiago_robot | f1c33c92 | Apache-2.0 | partial | 1523 | ROS "generated from template files" |
| JCodesMore/ai-website-cloner-template | 92872bc4 | MIT | no | 68 | "AI Website Cloner Template"・32.7k★（C/D 境界・D 分類） |

## B supplements（8候補）

| repo | sha | license | tests | commits | 選定理由 |
|---|---|---|---|---|---|
| dalance/procs | 6fc5a2d2 | MIT | yes | 2242 | Rust 製 ps 代替・個人・活発 |
| ajeetdsouza/zoxide | b16321f7 | MIT | yes | 629 | 38.8k★・個人・活発 |
| folke/lazy.nvim | 306a0552 | Apache-2.0 | yes | 1736 | neovim プラグインマネージャ・21.4k★ |
| folke/snacks.nvim | 882c996c | Apache-2.0 | yes | 2709 | 2024+ 個人フラッグシップ・8k★ |
| kuba--/zip | f57d98fb | MIT | yes | 387 | ポータブル C zip・個人・活発 |
| karlicoss/promnesia | 29692c5f | MIT | yes | 1509 | ブラウザ履歴・個人・活発 |
| antonmedv/fx | 63eb255a | MIT | yes | 791 | JSON ビューア・個人・20.6k★ |
| mvdan/sh | 8673bd18 | BSD-3-Clause | yes | 4234 | shfmt・個人（コミット数が上限近く） |

## 除外記録（admission の透明性）

- **コミット数上限 (>5000) で不採用**: ryokun6/ryos (6777), CherryHQ/cherry-studio (8540), jesseduffield/lazygit (8156), mitchellh/ghostty (17439), cookiecutter/cookiecutter-django (9319)
- **クローン寸法で不採用**: pulkitxm/claude-directory (12.9GB), datawhalechina/easy-vibe (549MB)
- **コミット <20（非narratable だがアーキタイプ的）**: karpathy/reader3 (1), karpathy/llm-council (5), ammaarreshi/gemma-chat (9), EnzeD/vibe-coding (19), Julian-Ivanov/jarvis-voice-assistant (8), sa4hnd/vibra-code (7), bedriyan/medkit-app (1), LiuMengxuan04/vibe-resume (11), e01-ai/starfall (10), josephg/claude-mail (11) — **非narratable C として埋め戻し可能**
- **D 代替で落選**: Buuntu/fastapi-react（休止）, coryhouse/react-slingshot（休止）, jupyterlab/extension-template（org）, scientific-python/cookie（org）, fmind/cookiecutter-mlops-package（12コミット）, CleverProgrammers/react-challenge-amazon-clone（4コミット）, wakatime/vim-wakatime（"Generated from" 未確認）

## 不確実性の注記（admission 時に再検証する項目）

1. SHA・コミット数は 2026-08-22 取得時点。admission 時に再固定
2. `license: none` は SPDX ファイルなし — 権利区分「公開・解析目的ピン留めのみ」と記録（再配布しない）
3. B「個人メンテ」はメンテナ知識によるもので contributor API 検証前
4. tests 判定は git-tree 走査。最終的な narratable 判定は **CLI 実行（`grift analyze --scope repo`）の test_frameworks 観測**で確定する（admission の本体）
