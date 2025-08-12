# flake8: noqa
# analysis メソッドをパッケージから直接インポートできるようにする
from nkaa.research_agent_v2.methods.analysis.summarize import SummarizeMethod

# 他の分析メソッド (例: KeywordExtractMethod) もここに追加する
from nkaa.research_agent_v2.methods.analysis.keyword_extract import (
    KeywordExtractMethod,
)
