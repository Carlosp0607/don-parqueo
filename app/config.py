import os

from dotenv import load_dotenv

load_dotenv()

# Fallar rápido si falta el secreto, en lugar de firmar tokens con un valor vacío.
JWT_SECRET = os.environ.get("JWT_SECRET")
if not JWT_SECRET:
    raise RuntimeError("Falta JWT_SECRET en el archivo .env. El servidor no puede iniciar.")

JWT_ALGORITMO = "HS256"
HORAS_SESION = 8

# Conexión a PostgreSQL. En Supabase o Render se usa DATABASE_URL completa.
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/parqueadero")

# Contraseña del administrador inicial. Solo se usa la primera vez, cuando la base está vacía.
ADMIN_INICIAL_PASSWORD = os.environ.get("ADMIN_INICIAL_PASSWORD")

# Cookie segura (HTTPS) solo en producción.
PRODUCCION = os.environ.get("ENTORNO", "").lower() == "produccion"

# Credenciales del demo público (usuario invitado de solo lectura).
DEMO_NIT = os.environ.get("DEMO_NIT")
DEMO_USER = os.environ.get("DEMO_USER")
DEMO_PASS = os.environ.get("DEMO_PASS")

# Clave del panel del dueño del SaaS. Sin ella, el panel queda apagado.
ADMIN_MASTER_KEY = os.environ.get("ADMIN_MASTER_KEY")
