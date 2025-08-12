import logging
import os

# Callable をインポート
from typing import (  # Dict, Any を追加
    Annotated,
    Any,
    Dict,
    List,
    Literal,
    Optional,
    Union,
)

# SecretStr をインポート
from pydantic import BaseModel, DirectoryPath, Field, SecretStr

# YamlConfigSettingsSource, DotEnvSettingsSource, PydanticBaseSettingsSource をインポート
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,  # YamlConfigSettingsSource をインポート
)

# --- Method Specific Settings ---
# 各メソッド固有の設定モデルは変更なし (ただし、不要な Field デフォルト値は削除検討)


class WebSearchSettings(BaseModel):
    """Web検索メソッド固有の設定"""

    provider: str = Field(
        "tavily", description="使用するWeb検索プロバイダー (例: tavily, google)"
    )
    # APIキーは環境変数 (TAVILY_API_KEY など) から読み込むことを推奨するため、モデルからは削除しても良い
    # api_key: Optional[str] = Field(None, description="Web検索APIキー")
    num_results: int = Field(5, description="取得する検索結果の数")


class LocalSearchSettings(BaseModel):
    """ローカル検索メソッド固有の設定"""

    target_directory: DirectoryPath = Field(
        ..., description="検索対象のディレクトリパス"
    )
    # allowed_extensions は現在 LocalSearchMethod で直接使用されていないためコメントアウト
    # allowed_extensions: List[str] = Field(
    #     [".md", ".txt", ".py"], description="検索対象のファイル拡張子リスト"
    # )
    # recursive も LocalSearchMethod で True 固定のためコメントアウト
    # recursive: bool = Field(True, description="サブディレクトリも再帰的に検索するかどうか")
    file_pattern: str = Field(
        "*.*", description="検索するファイルパターン"
    )  # file_pattern を追加


class SummarizeSettings(BaseModel):
    """要約メソッド固有の設定"""

    chunk_size: int = Field(4000, description="要約処理時のテキストチャンクサイズ")
    overlap: int = Field(200, description="チャンク間のオーバーラップ文字数")
    # map_prompt_name: Optional[str] = Field(None, description="カスタムMapプロンプト名")
    # combine_prompt_name: Optional[str] = Field(None, description="カスタムCombineプロンプト名")


class KeywordExtractSettings(BaseModel):
    """キーワード抽出メソッド固有の設定"""

    num_keywords: int = Field(10, description="抽出するキーワードの最大数")
    # prompt_name: Optional[str] = Field(None, description="カスタムキーワード抽出プロンプト名")


# --- Method Config Definitions using Discriminated Unions ---


class BaseMethodConfig(BaseModel):
    """メソッド設定の基底クラス (method_name を持つ)"""

    method_name: str
    enabled: bool = True


class WebSearchConfig(BaseMethodConfig):
    """Web検索メソッドの設定"""

    method_name: Literal["web_search"]
    # default_factory を lambda で修正 + type: ignore[call-arg]
    settings: WebSearchSettings = Field(default_factory=lambda: WebSearchSettings())  # type: ignore[call-arg]


class LocalSearchConfig(BaseMethodConfig):
    """ローカル検索メソッドの設定"""

    method_name: Literal["local_search"]
    settings: LocalSearchSettings


class SummarizeConfig(BaseMethodConfig):
    """要約メソッドの設定"""

    method_name: Literal["summarize"]
    # default_factory を lambda で修正 + type: ignore[call-arg]
    settings: SummarizeSettings = Field(default_factory=lambda: SummarizeSettings())  # type: ignore[call-arg]


class KeywordExtractConfig(BaseMethodConfig):
    """キーワード抽出メソッドの設定"""

    method_name: Literal["keyword_extract"]
    # default_factory を lambda で修正 + type: ignore[call-arg]
    settings: KeywordExtractSettings = Field(
        default_factory=lambda: KeywordExtractSettings()  # type: ignore[call-arg]
    )


# 判別可能な Union 型を定義
AnySearchMethodConfig = Annotated[
    Union[WebSearchConfig, LocalSearchConfig],
    Field(discriminator="method_name"),
]

AnyAnalysisMethodConfig = Annotated[
    Union[SummarizeConfig, KeywordExtractConfig],
    Field(discriminator="method_name"),
]


# --- Top Level Settings ---


class LLMSettings(BaseModel):
    """LLMクライアント関連の設定"""

    provider: str = Field(
        "openai", description="使用するLLMプロバイダー (例: openai, anthropic, ollama)"
    )
    model_name: str = Field("gpt-4o", description="使用するモデル名")
    # APIキーは環境変数 (OPENAI_API_KEY など) から読み込むことを推奨
    # api_key: Optional[str] = Field(None, description="LLM APIキー")
    temperature: float = Field(
        0.7, ge=0.0, le=1.0, description="生成時の温度パラメータ"
    )
    max_tokens: Optional[int] = Field(None, description="最大生成トークン数")
    extra_params: Optional[Dict[str, Any]] = Field(
        None, description="プロバイダー固有の追加パラメータ"
    )


class Settings(BaseSettings):
    """アプリケーション全体の設定モデル"""

    # model_config で設定ソースとその優先順位を customise_sources を使って定義
    model_config = SettingsConfigDict(
        env_file=".env",  # .env ファイルのパス (DotEnvSettingsSource で使用)
        yaml_file="config.yaml",  # YAML ファイルのパス (YamlConfigSettingsSource で使用)
        env_nested_delimiter="__",
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,  # DotEnvSettingsSource を使用
        file_secret_settings: PydanticBaseSettingsSource,
        # yaml_settings 引数は自動では渡されないため削除
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """設定ソースの読み込み順序をカスタマイズ (init_settings を最優先に変更)"""
        # YamlConfigSettingsSource を手動でインスタンス化
        yaml_config_source = YamlConfigSettingsSource(settings_cls)
        return (
            init_settings,  # 1. init 引数 (テストなどで直接指定する値を最優先)
            env_settings,  # 2. 環境変数
            yaml_config_source,  # 3. YAML ファイル (config.yaml)
            dotenv_settings,  # 4. .env ファイル
            file_secret_settings,  # 5. Docker secrets など
            # Pydantic モデルのデフォルト値は自動的に最後に適用される
        )

    log_level: str = Field(
        "INFO", description="ログレベル (DEBUG, INFO, WARNING, ERROR, CRITICAL)"
    )

    # default_factory を削除し、Pydantic のデフォルト生成に任せる
    llm: LLMSettings = Field(description="LLM設定")

    # 型ヒントを判別可能な Union 型に変更
    # デフォルト値を明示的に空リスト [] に変更
    search_methods: List[AnySearchMethodConfig] = Field(
        default=[], description="使用する検索メソッドのリストと設定"
    )
    analysis_methods: List[AnyAnalysisMethodConfig] = Field(
        default=[], description="使用する分析メソッドのリストと設定"
    )

    # --- Agent Workflow Settings ---
    max_replan_attempts: int = Field(3, description="再計画の最大試行回数")

    # --- API Keys (Optional, prefer environment variables) ---
    # 環境変数から自動で読み込まれるため、モデルに明示的に定義する必要性は低い
    # 必要であれば、alias を使って環境変数名をマッピングできる
    # 型を SecretStr に変更
    openai_api_key: Optional[SecretStr] = Field(None, alias="OPENAI_API_KEY")
    tavily_api_key: Optional[SecretStr] = Field(None, alias="TAVILY_API_KEY")
    anthropic_api_key: Optional[SecretStr] = Field(None, alias="ANTHROPIC_API_KEY")
    # alias を削除して YAML からの読み込みを優先させる試み
    ollama_base_url: Optional[str] = Field(None, description="Ollama APIのベースURL")


# --- Helper function to load settings ---

# グローバルな設定インスタンスキャッシュ (必要であれば)
_settings_instance: Optional[Settings] = None


def load_settings(
    config_path: str = "config.yaml", force_reload: bool = False
) -> Settings:
    """
    設定を読み込み、Settingsオブジェクトを生成またはキャッシュから返す。
    優先度: 環境変数 > YAMLファイル > .envファイル > デフォルト値

    Args:
        config_path (str): YAML設定ファイルのパス。Settings.model_config の yaml_file を
                           実行時に変更することは推奨されないため、主にログ出力や存在確認用。
                           pydantic-settings は model_config で指定されたパスを直接参照する。
        force_reload (bool): キャッシュを無視して強制的に再読み込みするかどうか。

    Returns:
        Settings: アプリケーション設定オブジェクト。
    """
    global _settings_instance
    if _settings_instance is None or force_reload:
        yaml_file_path = Settings.model_config.get(
            "yaml_file", config_path
        )  # 設定クラスからパス取得試行

        # YAML ファイルの存在確認 (オプション)
        if isinstance(yaml_file_path, str) and not os.path.exists(yaml_file_path):
            logging.warning(
                f"設定ファイル '{yaml_file_path}' が見つかりません。"
                "環境変数、.env、デフォルト値のみを使用します。"
            )
            # yaml_file が存在しない場合、pydantic-settings はエラーを出さずに無視するはず

        try:
            # Settings クラスをインスタンス化するだけで、
            # pydantic-settings が model_config に基づいて自動的に設定を読み込む
            # mypy の call-arg エラーを抑制
            _settings_instance = Settings()  # type: ignore[call-arg]

            # 読み込み成功ログ
            log_sources = ["デフォルト値"]
            if _settings_instance.model_config.get("env_file") and os.path.exists(
                str(_settings_instance.model_config.get("env_file"))
            ):
                log_sources.append(
                    f"'{_settings_instance.model_config.get('env_file')}'"
                )
            if isinstance(yaml_file_path, str) and os.path.exists(yaml_file_path):
                log_sources.append(f"'{yaml_file_path}'")
            if os.environ:
                log_sources.append("環境変数")
            logging.info(f"{', '.join(log_sources)} から設定を読み込みました。")

            # --- デバッグログ (メソッドリストの内容確認) ---
            # customise_sources を使ったので、Settings() 呼び出し時にログ出力しても
            # 全てのソースが読み込まれた後の状態が確認できるはず
            logging.debug(
                "--- Settings インスタンス化後の内容 (customise_sources適用後) ---"
            )
            logging.debug(f"  Log Level: {_settings_instance.log_level}")
            logging.debug(f"  LLM Provider: {_settings_instance.llm.provider}")
            logging.debug(f"  LLM Model: {_settings_instance.llm.model_name}")
            logging.debug(
                f"  Search Methods (len={len(_settings_instance.search_methods)}):"
            )
            # ループを分ける (mypy の型推論補助のため)
            search_method: AnySearchMethodConfig
            for i, search_method in enumerate(_settings_instance.search_methods):
                logging.debug(
                    f"    [{i}] Name: {search_method.method_name}, Enabled: {search_method.enabled}, Settings: {search_method.settings}"
                )
            logging.debug(
                f"  Analysis Methods (len={len(_settings_instance.analysis_methods)}):"
            )
            analysis_method: AnyAnalysisMethodConfig
            for i, analysis_method in enumerate(_settings_instance.analysis_methods):
                logging.debug(
                    f"    [{i}] Name: {analysis_method.method_name}, Enabled: {analysis_method.enabled}, Settings: {analysis_method.settings}"
                )
            logging.debug(
                f"  Max Replan Attempts: {_settings_instance.max_replan_attempts}"
            )
            logging.debug(
                f"  OpenAI Key Loaded: {bool(_settings_instance.openai_api_key)}"
            )
            logging.debug(
                f"  Tavily Key Loaded: {bool(_settings_instance.tavily_api_key)}"
            )
            logging.debug("--- デバッグログここまで ---")

        except Exception as e:
            logging.error(
                f"設定の読み込み中に重大なエラーが発生しました: {e}", exc_info=True
            )
            # エラー発生時の挙動: 例外を再送出するか、デフォルト設定で続行するか
            # ここでは例外を再送出して、起動時に問題を明確にする
            raise RuntimeError(
                "設定ファイルの読み込みまたは検証に失敗しました。"
            ) from e

    return _settings_instance


# get_settings 関数は load_settings に統合されたため不要
