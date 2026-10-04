"""mIA · asistente conversacional de RRHH de Sunset Beach Club."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("mia")
except PackageNotFoundError:  # ejecución desde el código fuente sin instalar
    __version__ = "0.0.0"

__all__ = ["__version__"]
