#!/usr/bin/python3 -I
"""Launch the approved Cockpit bridge with transactional default-bus caching.

Cockpit 337/362 cache an empty Bus before connecting. Without a root session bus,
retrying that cached object raises EINVAL outside channel error handling, killing
all clients. Discard a newly cached bus when construction/attachment fails, then
propagate the original error so Cockpit closes only that channel.
"""
from functools import wraps


def install_bus_retry(bus_type):
    for kind in ('system', 'user'):
        method = 'default_' + kind
        cache = '_default_' + kind + '_instance'
        original = getattr(bus_type, method)

        def wrap(original, cache):
            @wraps(original)
            def connect(*args, **kwargs):
                before = getattr(bus_type, cache)
                try:
                    return original(*args, **kwargs)
                except OSError:
                    if before is None:
                        setattr(bus_type, cache, None)
                    raise
            return connect

        setattr(bus_type, method, staticmethod(wrap(original, cache)))


def main():
    from cockpit._vendor.systemd_ctypes import Bus
    install_bus_retry(Bus)
    from cockpit.bridge import main as cockpit_main
    cockpit_main()


if __name__ == '__main__':
    main()
