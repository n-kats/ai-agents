import logging


def safe_execute(func, *args, **kwargs):
    """
    指定した関数を安全に実行し、例外発生時にはエラーログを出力してNoneを返す。
    """
    try:
        return func(*args, **kwargs)
    except Exception as e:
        logging.error(f"Error occurred in {func.__name__}: {e}")
        return None


def get_mock_object(name, **kwargs):
    """
    ユニットテスト用のモックオブジェクトを生成する。
    """

    class MockObject:
        def __init__(self, **attrs):
            self.__dict__.update(attrs)

        def __repr__(self):
            return f"<MockObject {name}: {self.__dict__}>"

    return MockObject(**kwargs)


# その他、ユーティリティ関数をここに実装する
