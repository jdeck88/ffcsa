

class DictClass(dict):
    """ Simple snippet to use dict as a class object """
    __getattr__ = dict.get
    __setattr__ = dict.__setitem__
    __delattr__ = dict.__delitem__