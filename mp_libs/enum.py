"""Enum Support Library

Use this until, hopefully, one day micropython has built-in support for enum types.
"""


class Enum():
    """Extremely basic/hacky Enum class"""
    def __new__(cls, *args, **kwargs):
        if cls is Enum:
            raise TypeError("Cannot instantiate Enum class directly")
        return super().__new__(cls)

    def __setattr__(self, key, value) -> None:
        raise AttributeError(f"Cannot modify '{key}' in {self.__class__.__name__} enum")

    @classmethod
    def _cls_vars(cls) -> dict:
        return {k: v for k, v in cls.__dict__.items() if not callable(v) and not k.startswith("__")}

    @classmethod
    def contains(cls, value) -> bool:
        return value in cls._cls_vars().values()

    @classmethod
    def print(cls) -> str:
        return str(cls._cls_vars())
