# IRIS Dashboard

SPA React + TypeScript para `iris-api`.

```bash
cp .env.example .env
npm install
npm run dev
```

`VITE_API_BASE_URL` debe apuntar a la API (por defecto
`http://localhost:8000`). El origen del frontend debe estar incluido en
`API_CORS_ORIGINS`.

Vistas:

- `/`: monitoreo por cámara con captura y último análisis Alibaba.
- `/history`: historial filtrable de detecciones.
- `/admin`: usuarios, cámaras y configuración persistente del motor (sólo admin).

Validación:

```bash
npm run build
npm run lint
```
