"""Clientes de sistemas externos que mIA consulta en el momento (no solo al sincronizar).

A diferencia de ``ingestion/`` (que lee fuentes para volcarlas en la base de datos propia),
un conector de aquí se llama también en vivo durante una conversación: abrir un documento,
mandar un correo, o -en el futuro- leer un fichaje de Conectia/A3.
"""

from __future__ import annotations
