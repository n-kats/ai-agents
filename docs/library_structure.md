# ライブラリ構造マップ

この資料は、エージェント・マネージャ・チャネルなどライブラリ内部の主要コンポーネントと依存関係をマーメイド図で俯瞰します。ディレクトリ構成については `docs/directory_structure.md` を参照してください。

## Mermaid 図

```mermaid
graph LR
    library((NKAA Library))

    subgraph Framework Core
        library --> agent_api[Agent Abstractions\n(BaseAgent, AgentConfig)]
        library --> manager_api[Manager Layer\n(StandardManager)]
        library --> channel_api[Channel System\n(ChannelManager, ChannelTools)]
        library --> persistence_api[Persistence Layer\n(JsonLinesStateMixin など)]
        agent_api --> tool_injection[Tool Injection\n(ToolAdapter, ChannelTools)]
        manager_api --> agent_api
        manager_api --> channel_api
        channel_api --> persistence_api
    end

    subgraph Presets & Tooling
        library --> presets[Presets Package]
        presets --> preset_agents[Preset Agents\n(SimpleAgentConfig など)]
        presets --> preset_tools[Preset Tools\n(LLMCallTool, InputTool)]
        presets --> preset_managers[Preset Managers\n(single_agent_model)]
        preset_managers --> manager_api
        preset_agents --> agent_api
        preset_tools --> tool_injection
    end

    subgraph Samples & Legacy
        library --> samples[Samples]
        samples --> presets
        library --> legacy[Legacy Implementations]
        legacy -.-> manager_api
        legacy -.-> agent_api
    end
```

## ディレクトリ概要
- `Agent Abstractions` : エージェント共通のライフサイクル管理・ツール注入インタフェースを定義し、プリセットや拡張エージェントがここを基盤に構築されます。
- `Manager Layer` : チャネル管理やエージェントの初期化責務を統合し、プリセットマネージャを通じて利用者が再利用します。
- `Channel System` : メッセージキュー、チャネル検索、未読管理などの共通処理を提供し、マネージャとエージェント双方から呼び出されます。
- `Persistence Layer` : エージェント・チャネル両方の状態永続化を担当し、既定実装として JSON Lines ベースのミックスインを用意します。
- `Presets Package` : 実用的な構成例を束ね、標準マネージャ／エージェント実装とツールセットを差し替え可能にします。
- `Samples` : フレームワークの利用イメージを具体的なコードで示し、新しいプリセットやツールの検証を補助します。
- `Legacy Implementations` : 過去の試作をアーカイブし、設計方針の比較検討用に残しています（現行コードから参照のみ）。
