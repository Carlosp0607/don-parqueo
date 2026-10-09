# Don Parqueo: sistema multiempresa para parqueaderos

Enfoque: diseño de API REST, aislamiento de datos multiempresa y transacciones SQL.

Aplicación web para administrar parqueaderos. Registra entradas y salidas de vehículos,
calcula el cobro según la tarifa, controla los turnos de caja, maneja mensualidades y
genera reportes de ingresos exportables a Excel.

Atiende varias empresas desde una sola instalación: cada empresa ve únicamente su propia información.

## Tecnologías

- **Python + FastAPI**: servidor y API REST
- **PostgreSQL**: base de datos (Supabase en producción)
- **JWT**: inicio de sesión y control de acceso por roles
- **pytest + GitHub Actions**: pruebas automáticas en cada cambio
- **HTML, CSS y JavaScript**: interfaz, servida desde `public/`

## Qué hace

- **Ingreso y salida de vehículos.** Al confirmar la salida recalcula el total con la hora exacta y
  guarda el cierre y los pagos en una sola transacción: o queda todo o no queda nada.
- **Tarifas configurables.** Por minuto, hora, día o mixto, con escalones y redondeo, por tipo de vehículo.
- **Pagos.** Efectivo, tarjeta, QR, Nequi, Daviplata, Bre-B o transferencia; un cobro puede dividirse en varios métodos.
- **Turnos de caja.** Apertura con base y cierre con arqueo: muestra lo esperado por el sistema y la diferencia.
- **Mensualidades.** Suscripciones por vehículo, periodos pagados y cálculo de meses vencidos.
- **Reportes.** Ingresos por día y por método, movimientos filtrables, top de placas y exportación a Excel.
- **Usuarios y roles.** Administrador y operador. El invitado del demo solo puede consultar.
- **Multiempresa.** Toda consulta va filtrada por la empresa del token; ninguna empresa ve datos de otra.
- **Seguridad.** Bloqueo tras 5 intentos fallidos de login, consultas parametrizadas contra inyección SQL,
  páginas del panel protegidas por cookie de sesión y corte de acceso por plan vencido.

## Ejecución local

Requisitos: Python 3.12 y PostgreSQL.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # y llenar los valores
uvicorn app.main:app --reload
```

La aplicación queda en http://localhost:8000 y la documentación de la API en http://localhost:8000/docs.

La primera vez, con la base vacía, el servidor aplica `schema.sql` solo y crea el usuario `admin`
de la empresa de ejemplo (NIT `900123456-7`) con la clave de `ADMIN_INICIAL_PASSWORD`.

## Pruebas

```bash
pytest
```

- `tests/test_seguridad.py`: ninguna petición avanza sin token válido ni sin `id_empresa`
  (aislamiento entre empresas), el invitado no puede escribir y las rutas de administrador bloquean al operador.
- `tests/test_cobro.py`: cálculo del cobro en todos los modos de tarifa, métodos de pago,
  valores de caja en pesos y meses vencidos de las mensualidades.

## Estructura

```
app/
  main.py          Arranque, manejo de errores y páginas HTML
  config.py        Variables de entorno
  db.py            Conexión a PostgreSQL y migración inicial
  seguridad.py     JWT, roles y aislamiento por empresa
  tarifa.py        Cálculo del cobro
  utiles.py        Funciones de apoyo
  routers/         Endpoints de la API
public/            Interfaz
schema.sql         Tablas, vistas y datos iniciales
tests/             Pruebas
render.yaml        Despliegue en Render
```

## API

Todos los endpoints van bajo `/api` y requieren `Authorization: Bearer <token>`, salvo el login.

| Recurso | Para qué sirve |
|---|---|
| `/api/auth` | Inicio y cierre de sesión |
| `/api/vehiculos`, `/api/tipos-vehiculos` | Vehículos y tipos con su capacidad |
| `/api/movimientos` | Ingresos, salidas, cobro y facturas |
| `/api/tarifas` | Consulta y actualización de tarifas |
| `/api/turnos` | Apertura, cierre e historial de caja |
| `/api/mensualidades` | Suscripciones y sus pagos |
| `/api/reportes`, `/api/dashboard` | Reportes, estadísticas y Excel |
| `/api/empresa`, `/api/usuarios` | Datos de la empresa, logo, QR de pago y usuarios |
