"""Singleton decorator

Provides a decorator for making classes a singleton.
"""


def singleton(cls):
    """Singleton decorator"""
    instance = None

    def get_instance(*args, **kwargs):
        nonlocal instance
        if instance is None:
            instance = cls(*args, **kwargs)
        return instance

    return get_instance
