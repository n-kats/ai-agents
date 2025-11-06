# ライブラリ構造マップ

この資料は、エージェント・マネージャ・チャネルなどライブラリ内部の主要コンポーネントと依存関係をマーメイド図で俯瞰します。ディレクトリ構成については [docs/directory_structure.md](./directory_structure.md) を参照してください。

## Mermaid 図

```mermaid
graph TB
    subgraph AgentsCluster["エージェント系"]
        agent_contract["抽象: Agent Abstractions<br/>(BaseAgent, AgentConfig)"]
        agent_impl["具体: Preset Agents<br/>(SimpleAgentConfig など)"]
    end

    subgraph ManagersCluster["マネージャ系"]
        manager_contract["抽象: BaseManager / ManagerConfig"]
        manager_impl["具体: StandardManager<br/>+ Preset Managers"]
    end

    subgraph ChannelsCluster["チャネル系"]
        channel_contract["抽象: Channel Contracts<br/>(ChannelManager API)"]
        channel_impl["具体: Channel Runtime<br/>(Queue, Search, Snapshot)"]
    end

    subgraph PersistenceCluster["永続化系"]
        persistence_contract["抽象: Persistence Interfaces<br/>(StateRepository など)"]
        persistence_impl["具体: Persistence Layer<br/>(JsonLinesStateMixin)"]
    end

    subgraph ToolingCluster["ツール系"]
        tool_contract["抽象: Tool Injection API<br/>(ToolAdapter, ChannelTools)"]
        tool_impl["具体: Preset Tools<br/>(LLMCallTool, InputTool)"]
    end

    manager_contract -->|初期化契約| agent_contract
    manager_impl -->|ライフサイクル制御| agent_impl
    manager_contract -->|チャネル契約| channel_contract
    manager_impl -->|チャネル管理| channel_impl
    channel_contract -->|契約提示| channel_impl
    channel_impl -->|状態保存| persistence_impl
    persistence_contract -->|契約提示| persistence_impl
    agent_contract -->|ツール要求| tool_contract
    tool_contract -->|供給| tool_impl
    tool_impl -->|利用支援| agent_impl
    manager_impl -->|ツール注入| tool_contract
    agent_contract -->|準拠| agent_impl
    manager_contract -->|準拠| manager_impl
    channel_contract -->|準拠| channel_impl
    persistence_contract -->|準拠| persistence_impl
    tool_contract -->|準拠| tool_impl
```

## コンポーネント概要
- **エージェント系**：`BaseAgent`・`AgentConfig` などの抽象契約を起点に、`SimpleAgentConfig` などプリセットエージェントが具体実装として従います。
- **マネージャ系**：`BaseManager` とその設定契約を基礎とし、`StandardManager` やプリセットマネージャがオーケストレーションを担います。
- **チャネル系**：`ChannelManager` API などの契約が、優先度キューや検索・参加処理を備えたランタイム実装へつながります。
- **永続化系**：`StateRepository` などの抽象化に対し、`JsonLinesStateMixin` を代表とする実装が状態保存を実現します。
- **ツール系**：`ToolAdapter` や `ChannelTools` の契約が、`LLMCallTool` などプリセットツールを通じてエージェントへ機能を供給します。
