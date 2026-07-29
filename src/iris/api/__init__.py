"""API HTTP de IRIS: historial de detecciones y administración de usuarios.

Este es un subsistema nuevo e independiente de ``iris-monitor``: un proceso
de larga duración separado (``iris-api``) que expone, por HTTP, el historial
de detecciones almacenado en MongoDB y la administración de usuarios/roles
almacenada en SQLite (``iris.users_store``). Comparte el mismo almacén de
configuración (``iris.config_store``) que ``iris-monitor``, pero no depende
de él ni lo reemplaza.
"""
