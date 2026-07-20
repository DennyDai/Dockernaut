from typing import Any


class WayweaverError(RuntimeError):
    code = "WAYWEAVER_ERROR"
    retryable = False

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        retryable: bool | None = None,
    ):
        super().__init__(message)
        self.details = details or {}
        if retryable is not None:
            self.retryable = retryable


class ConfigError(WayweaverError):
    code = "CONFIG_ERROR"


class CapabilityError(WayweaverError):
    code = "CAPABILITY_UNAVAILABLE"


class ContractError(WayweaverError):
    code = "INVALID_PARAMS"


class SurfaceError(WayweaverError):
    code = "STALE_SURFACE"
    retryable = True


class ActionError(WayweaverError):
    code = "ACTION_FAILED"
    retryable = True


class ProtocolError(WayweaverError):
    code = "PROTOCOL_ERROR"
    retryable = True


def error_payload(error: Exception) -> dict[str, Any]:
    if isinstance(error, WayweaverError):
        payload: dict[str, Any] = {
            "code": error.code,
            "message": str(error),
            "retryable": error.retryable,
        }
        if error.details:
            payload["details"] = error.details
        return payload
    return {
        "code": "INTERNAL_ERROR",
        "message": str(error),
        "retryable": False,
    }
