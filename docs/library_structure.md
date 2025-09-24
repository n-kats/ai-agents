# ライブラリ構造マップ

この資料は、エージェント・マネージャ・チャネルなどライブラリ内部の主要コンポーネントと依存関係をマーメイド図で俯瞰します。ディレクトリ構成については `docs/directory_structure.md` を参照してください。

## Mermaid 図

```mermaid
graph LR
    subgraph Framework Core
        agent_api["Agent Abstractions<br/>(BaseAgent, AgentConfig)"]
        manager_api["Manager Layer<br/>(StandardManager)"]
        channel_api["Channel System<br/>(ChannelManager, ChannelTools)"]
        persistence_api["Persistence Layer<br/>(JsonLinesStateMixin など)"]
        tool_injection["Tool Injection<br/>(ToolAdapter, ChannelTools)"]
        manager_api --> agent_api
        manager_api --> channel_api
        channel_api --> persistence_api
        agent_api --> tool_injection
    end

    subgraph Presets & Tooling
        presets["Presets Package"]
        preset_agents["Preset Agents<br/>(SimpleAgentConfig など)"]
        preset_tools["Preset Tools<br/>(LLMCallTool, InputTool)"]
        preset_managers["Preset Managers<br/>(single_agent_model)"]
        presets --> preset_agents
        presets --> preset_tools
        presets --> preset_managers
        preset_managers --> manager_api
        preset_agents --> agent_api
        preset_tools --> tool_injection
    end
```

## コンポーネント概要
- `Agent Abstractions` : エージェント共通のライフサイクル管理・ツール注入インタフェースを定義し、プリセットや拡張エージェントがここを基盤に構築されます。
- `Manager Layer` : チャネル管理やエージェントの初期化責務を統合し、プリセットマネージャを通じて利用者が再利用します。
- `Channel System` : メッセージキュー、チャネル検索、未読管理などの共通処理を提供し、マネージャとエージェント双方から呼び出されます。
- `Persistence Layer` : エージェント・チャネル両方の状態永続化を担当し、既定実装として JSON Lines ベースのミックスインを用意します。
- `Presets Package` : 実用的な構成例を束ね、標準マネージャ／エージェント実装とツールセットを差し替え可能にします。
