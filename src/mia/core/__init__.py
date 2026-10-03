"""Piezas transversales a todos los módulos.

Hoy solo contiene ``i18n`` (español/inglés). El resto de lo que conceptualmente es «core»
-configuración, logging, observabilidad, identidad y permisos- ya vive en ``settings.py``,
``observability/`` y ``auth/`` y funciona bien donde está: no se ha movido aquí sin necesidad
real (cambio mínimo coherente), solo se añade lo genuinamente nuevo.
"""

from __future__ import annotations
