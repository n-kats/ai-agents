from .local_search import LocalSearchMethod
from .web_search import WebSearchMethod

__all__ = ["WebSearchMethod", "LocalSearchMethod"]
# flake8: noqa
# search メソッドをパッケージから直接インポートできるようにする
from nkaa.legacy.research_agent_v2.methods.search.web_search import WebSearchMethod

# 他の検索メソッド (例: LocalSearchMethod) もここに追加する
# from .local_search import LocalSearchMethod
