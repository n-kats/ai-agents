# ライブラリ構造マップ

この資料は、エージェント・マネージャ・チャネルなどライブラリ内部の主要コンポーネントと依存関係をマーメイド図で俯瞰します。ディレクトリ構成については `docs/directory_structure.md` を参照してください。

## Mermaid 図

```mermaid
graph LR
    subgraph Agents["エージェント系"]
        agent_api["Agent Abstractions<br/>(BaseAgent, AgentConfig)"]
        preset_agents["Preset Agents<br/>(SimpleAgentConfig など)"]
    end

    subgraph Managers["マネージャ系"]
        manager_layer["StandardManager<br/>(Lifecycle Orchestration)"]
        preset_managers["Preset Managers<br/>(single_agent_model)"]
    end

    subgraph Channels["チャネル系"]
        channel_contracts["Channel Contracts<br/>(ChannelManager API)"]
        channel_runtime["Channel Runtime<br/>(Queue, Search, Snapshot)"]
    end

    subgraph Persistence["永続化系"]
        persistence_contracts["Persistence Interfaces<br/>(StateRepository など)"]
        persistence_runtime["Persistence Layer<br/>(JsonLinesStateMixin)"]
    end

    subgraph Tooling["ツール系"]
        tool_injection["Tool Injection<br/>(ToolAdapter, ChannelTools)"]
        preset_tools["Preset Tools<br/>(LLMCallTool, InputTool)"]
    end

    agent_api -->|初期化要求| manager_layer
    manager_layer -->|ライフサイクル制御| agent_api
    manager_layer -->|チャネル管理| channel_runtime
    channel_contracts -->|契約提示| channel_runtime
    channel_runtime -->|状態保存| persistence_runtime
    persistence_contracts -->|契約提示| persistence_runtime
    agent_api -->|ツール要求| tool_injection
    tool_injection -->|チャネル操作| channel_runtime
    preset_managers -->|実装連携| manager_layer
    preset_agents -->|実装連携| agent_api
    preset_tools -->|実装連携| tool_injection
```

## コンポーネント概要
- **エージェント系** (`Agent Abstractions`, `Preset Agents`) : エージェントのライフサイクル定義とプリセットによる具体的な初期化方法を提供します。
- **マネージャ系** (`StandardManager`, `Preset Managers`) : 複数チャネルやエージェントの制御を担い、プリセットで即利用できる orchestration を定義します。
- **チャネル系** (`Channel Contracts`, `Channel Runtime`) : メッセージキューや検索・参加処理を束ね、マネージャから呼び出される具体実装を提供します。
- **永続化系** (`Persistence Interfaces`, `Persistence Layer`) : チャネルやエージェント状態の保存契約と既定実装を示し、ランタイムが永続化戦略を切り替えやすくします。
- **ツール系** (`Tool Injection`, `Preset Tools`) : エージェントへツール群を注入する仕組みと、プリセットで用意した代表的なツール実装をまとめています。
- **プリセット基盤** (`Presets Package`) : 個別概念を組み合わせた構成テンプレートを提供し、利用者が設定なしでフレームワークを試せるようにします。
