class DockernautError(RuntimeError):
    pass


class ConfigError(DockernautError):
    pass


class CapabilityError(DockernautError):
    pass


class ActionError(DockernautError):
    pass


class ProtocolError(DockernautError):
    pass
