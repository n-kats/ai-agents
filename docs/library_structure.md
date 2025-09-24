# ライブラリ構造マップ

この資料は、エージェント・マネージャ・チャネルなどライブラリ内部の主要コンポーネントと依存関係をマーメイド図で俯瞰します。ディレクトリ構成については `docs/directory_structure.md` を参照してください。

## Mermaid 図

```mermaid
graph TB
    subgraph Abstract["抽象層 (Conceptual Contracts)"]
        agent_api["Agent Abstractions<br/>(BaseAgent, AgentConfig)"]
        channel_contracts["Channel Contracts<br/>(ChannelManager API)"]
        persistence_contracts["Persistence Interfaces<br/>(StateRepository など)"]
    end

    subgraph CoreRuntime["実装層 (Core Runtime)"]
        manager_layer["StandardManager<br/>(Lifecycle Orchestration)"]
        channel_runtime["Channel Runtime<br/>(Queue, Search, Snapshot)"]
        persistence_runtime["Persistence Layer<br/>(JsonLinesStateMixin)"]
        tool_injection["Tool Injection<br/>(ToolAdapter, ChannelTools)"]
    end

    subgraph Extensions["応用層 (Presets & Extensions)"]
        presets["Presets Package"]
        preset_managers["Preset Managers<br/>(single_agent_model)"]
        preset_agents["Preset Agents<br/>(SimpleAgentConfig など)"]
        preset_tools["Preset Tools<br/>(LLMCallTool, InputTool)"]
    end

    agent_api -->|契約提示| manager_layer
    channel_contracts -->|契約提示| channel_runtime
    persistence_contracts -->|契約提示| persistence_runtime
    manager_layer -->|ライフサイクル制御| tool_injection
    tool_injection -->|ツール注入| channel_runtime
    channel_runtime -->|状態保存| persistence_runtime
    manager_layer -->|プリセット基盤| presets
    presets -->|構成提供| preset_managers
    presets -->|構成提供| preset_agents
    presets -->|構成提供| preset_tools
    preset_managers -->|具体化| manager_layer
    preset_agents -->|実装連携| agent_api
    preset_tools -->|実装連携| tool_injection
```

## コンポーネント概要
- **抽象層** (`Agent Abstractions`, `Channel Contracts`, `Persistence Interfaces`) : ライブラリ全体で共有されるインタフェースや契約を提示し、実装層やプリセットが従うべき境界を定義します。
- **実装層** (`StandardManager`, `Channel Runtime`, `Persistence Layer`, `Tool Injection`) : 抽象層の契約に沿った実装を提供し、ランタイムでのチャネル管理やツール注入を担います。
- **応用層** (`Presets Package`, `Preset Managers`, `Preset Agents`, `Preset Tools`) : 実装層を組み合わせた再利用可能なセットを提供し、利用者が即座に活用できる構成を提示します。
