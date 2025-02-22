"""
Initial version borrowed from micropython's micropython-lib:
https://github.com/micropython/micropython-lib/blob/master/python-stdlib/collections-defaultdict/collections/defaultdict.py
"""


class defaultdict:  # pylint: disable=invalid-name
    """Basic defaultdict implementation for micropython"""
    @staticmethod
    def __new__(cls, default_factory=None, **kwargs):
        # Some code (e.g. urllib.urlparse) expects that basic defaultdict
        # functionality will be available to subclasses without them
        # calling __init__().
        self = super(defaultdict, cls).__new__(cls)
        self.d = {}
        return self

    def __init__(self, default_factory=None, **kwargs):
        self.d = kwargs
        self.default_factory = default_factory

    def __contains__(self, key):
        return key in self.d

    def __delitem__(self, key):
        del self.d[key]

    def __getitem__(self, key):
        try:
            return self.d[key]
        except KeyError:
            v = self.__missing__(key)
            self.d[key] = v
            return v

    def __iter__(self):
        return iter(self.d)

    def __len__(self):
        return len(self.d)

    def __missing__(self, key):
        if self.default_factory is None:
            raise KeyError(key)
        return self.default_factory()

    def __setitem__(self, key, v):
        self.d[key] = v

    def items(self):
        return iter(self.d.items())

    def keys(self):
        return iter(self.d.keys())

    def values(self):
        return iter(self.d.values())
