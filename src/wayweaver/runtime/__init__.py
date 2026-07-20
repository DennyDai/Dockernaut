from .._version import __version__ as RUNTIME_VERSION

LINUX_COMMANDS = (
    "wayweaver-applications",
    "wayweaver-atspi",
    "wayweaver-clipboard",
    "wayweaver-x11-record",
)


def linux_path_export() -> str:
    return (
        'export PATH="${XDG_CACHE_HOME:-$HOME/.cache}/wayweaver/runtime/'
        f"{RUNTIME_VERSION}/bin:/opt/wayweaver/runtime/{RUNTIME_VERSION}/bin:$PATH"
        '"; '
    )


def windows_uia_command() -> str:
    script = rf"$env:LOCALAPPDATA\Wayweaver\runtime\{RUNTIME_VERSION}\uia.ps1"
    return (
        "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass "
        f'-File "{script}"'
    )
