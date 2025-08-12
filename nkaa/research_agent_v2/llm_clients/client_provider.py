import logging  # Add this import
from typing import Dict, Optional

from langchain_anthropic import ChatAnthropic  # 必要に応じて追加
from langchain_community.chat_models import ChatOllama  # 必要に応じて追加
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

# SecretStr をインポート
from pydantic import SecretStr

# LLMSettings ではなく Settings 全体を使うように変更
from nkaa.research_agent_v2.config.settings import (  # LLMSettings もインポート
    Settings,
)

# キャッシュされたクライアントインスタンス
# Configure basic logging for debugging during tests
# Note: In a real application, configure logging more robustly.
# Basic config might interfere if the application using this module also configures logging.
try:
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    # Prevent adding multiple handlers if basicConfig was already called
    if len(logging.getLogger().handlers) > 1:
        logging.getLogger().handlers.pop()
except Exception:
    # Ignore potential errors during basicConfig in test environments
    pass

_llm_client_cache: Dict[str, BaseChatModel] = {}
_log = logging.getLogger(__name__)  # Use a specific logger


def get_llm_client(settings: Settings) -> BaseChatModel:  # 引数を Settings 全体に変更
    _log.debug(
        "--- get_llm_client function entered ---"
    )  # Add log at the very beginning
    _log.debug(f"Received settings.llm.provider: {settings.llm.provider}")
    """
    指定されたアプリケーション設定に基づいて、LangChainのChatModelインスタンスを取得する。
    同じ設定のクライアントはキャッシュして再利用する。

    Args:
        settings: アプリケーション設定オブジェクト (Settings)。

    Returns:
        BaseChatModel のインスタンス。

    Raises:
        ValueError: サポートされていないプロバイダーが指定された場合。
        ImportError: 必要なライブラリがインストールされていない場合。
    """
    # LLM 固有の設定を取得
    llm_settings = settings.llm

    # キャッシュキーを作成 (設定内容に基づいて一意なキーを生成)
    cache_key = f"{llm_settings.provider}_{llm_settings.model_name}_{llm_settings.temperature}_{llm_settings.max_tokens}"
    _log.debug(f"Calculated cache_key: {cache_key}")
    # APIキーはキャッシュキーに含めない (セキュリティと、キーが変わってもモデル自体は同じ可能性があるため)

    if cache_key in _llm_client_cache:
        _log.debug(f"Cache hit for key: {cache_key}")
        return _llm_client_cache[cache_key]
    _log.debug(f"Cache miss for key: {cache_key}")

    provider = llm_settings.provider.lower()
    _log.debug(f"Normalized provider: {provider}")  # Log the normalized provider
    model_name = llm_settings.model_name
    temperature = llm_settings.temperature
    max_tokens = llm_settings.max_tokens
    # その他のプロバイダー固有設定を取得 (例: llm_settings.extra_params)
    # extra_params = getattr(llm_settings, "extra_params", {}) # LLMSettings に extra_params があれば

    # APIキーをトップレベルの Settings から取得 (型ヒントを SecretStr に変更)
    api_key: Optional[SecretStr] = None
    if provider == "openai":
        api_key = settings.openai_api_key
        _log.debug(
            f"Provider is openai, api_key loaded: {bool(api_key and api_key.get_secret_value())}"
        )
    elif provider == "anthropic":
        api_key = settings.anthropic_api_key
        _log.debug(
            f"Provider is anthropic, api_key loaded: {bool(api_key and api_key.get_secret_value())}"
        )
    # No specific API key for ollama or tavily in this logic block

    client: BaseChatModel
    # extra_params は現在使用されていないため削除
    # extra_params は LLMSettings から取得する想定
    extra_params = llm_settings.extra_params or {}

    if provider == "openai":
        _log.debug("Entering openai block")
        # APIキーのチェックを修正
        if not api_key or not api_key.get_secret_value():
            _log.error("OpenAI API key missing or empty.")
            raise ValueError(
                "OpenAI APIキーが設定されていません。環境変数 OPENAI_API_KEY または設定ファイルを確認してください。"
            )
        try:
            _log.debug("Instantiating ChatOpenAI...")
            # max_tokens を直接渡すように修正
            client = ChatOpenAI(
                model=model_name,
                api_key=api_key,  # SecretStr | None を渡す
                temperature=temperature,
                max_tokens=max_tokens,  # 直接渡す
                # model_kwargs は不要なら削除、または他のパラメータ用
                # model_kwargs=extra_params if extra_params else {},
            )
            _log.debug("ChatOpenAI instantiated successfully.")
        except ImportError:
            _log.error("langchain-openai not installed.")
            raise ImportError(
                "OpenAIクライアントを使用するには 'langchain-openai' をインストールしてください。"
            )
        except Exception as e:
            _log.error(f"Error instantiating ChatOpenAI: {e}", exc_info=True)
            raise ValueError(f"OpenAIクライアントの初期化に失敗しました: {e}")

    # --- 他のプロバイダーのサポートを追加 ---
    elif provider == "anthropic":
        _log.debug("Entering anthropic block")
        # APIキーのチェックを修正
        if not api_key or not api_key.get_secret_value():
            _log.error("Anthropic API key missing or empty.")
            raise ValueError(
                "Anthropic APIキーが設定されていません。環境変数 ANTHROPIC_API_KEY または設定ファイルを確認してください。"
            )
        try:
            _log.debug("Instantiating ChatAnthropic...")
            # from langchain_anthropic import ChatAnthropic # 上部でインポート済み
            client = ChatAnthropic(
                model=model_name,
                api_key=api_key,  # SecretStr | None を渡す
                temperature=temperature,
                max_tokens=max_tokens
                if max_tokens is not None
                else 1024,  # Anthropic は max_tokens
                # **extra_params, # 必要に応じて追加パラメータを渡す
            )
            _log.debug("ChatAnthropic instantiated successfully.")
        except ImportError:
            _log.error("langchain-anthropic not installed.")
            raise ImportError(
                "Anthropicクライアントを使用するには 'langchain-anthropic' をインストールしてください。"
            )
        except Exception as e:
            _log.error(f"Error instantiating ChatAnthropic: {e}", exc_info=True)
            raise ValueError(f"Anthropicクライアントの初期化に失敗しました: {e}")

    elif provider == "ollama":
        _log.debug("Entering ollama block")
        try:
            _log.debug("Instantiating ChatOllama...")
            # from langchain_community.chat_models import ChatOllama # 上部でインポート済み
            # Ollama の場合、APIキーは通常不要で、base_url が重要になる場合がある
            # Settings に ollama_base_url を追加するか、extra_params で渡す想定
            base_url = settings.ollama_base_url or extra_params.get(
                "base_url", "http://localhost:11434"
            )  # デフォルト値
            _log.debug(f"Using Ollama base_url: {base_url}")
            client = ChatOllama(
                model=model_name,
                base_url=base_url,
                temperature=temperature,
                # Ollama は max_tokens を直接サポートしない場合がある (モデルやバージョンによる)
                # num_predict で制御するケースも: num_predict=max_tokens if max_tokens else -1
                # **{k: v for k, v in extra_params.items() if k != "base_url"}, # base_url 以外を渡す
            )
            _log.debug("ChatOllama instantiated successfully.")
        except ImportError:
            _log.error("langchain-community not installed.")
            raise ImportError(
                "Ollamaクライアントを使用するには 'langchain-community' をインストールしてください。"
            )
        except Exception as e:
            _log.error(f"Error instantiating ChatOllama: {e}", exc_info=True)
            raise ValueError(f"Ollamaクライアントの初期化に失敗しました: {e}")

    else:
        _log.error(f"Unsupported provider: {provider}")
        raise ValueError(f"サポートされていないLLMプロバイダーです: {provider}")

    _log.debug(f"Caching client for key: {cache_key}")
    # クライアントをキャッシュ
    _llm_client_cache[cache_key] = client
    return client
