"""Usuarios de la empresa. Todo exige rol administrador."""
import bcrypt
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app import db
from app.seguridad import ApiError, Usuario, solo_admin
from app.utiles import como_bool, cuerpo_json

router = APIRouter(prefix="/api/usuarios", tags=["usuarios"])

ROLES = ("admin", "operador")


def cifrar(clave) -> str:
    return bcrypt.hashpw(str(clave).encode(), bcrypt.gensalt(10)).decode()


@router.get("")
def listar(u: Usuario = Depends(solo_admin)):
    usuarios = db.filas(db.consultar(
        """SELECT id_usuario AS id, id_usuario, nombre, usuario_login, rol, activo,
                  fecha_creacion, ultimo_acceso
           FROM usuarios WHERE id_empresa = %s ORDER BY nombre ASC""",
        (u.id_empresa,),
    ))
    return {"success": True, "data": usuarios, "usuarios": usuarios}


@router.post("")
def crear(cuerpo: dict = Depends(cuerpo_json), u: Usuario = Depends(solo_admin)):
    nombre, login = cuerpo.get("nombre"), cuerpo.get("usuario_login")
    clave, rol = cuerpo.get("password"), cuerpo.get("rol")
    if not (nombre and login and clave and rol):
        raise ApiError(400, "Todos los campos son obligatorios")
    if rol not in ROLES:
        raise ApiError(400, "Rol inválido (admin u operador)")
    if len(str(clave)) < 6:
        raise ApiError(400, "La contraseña debe tener al menos 6 caracteres")

    login = str(login).strip()
    if db.uno(
        "SELECT 1 FROM usuarios WHERE lower(usuario_login) = lower(%s) AND id_empresa = %s",
        (login, u.id_empresa),
    ):
        raise ApiError(409, "El nombre de usuario ya está registrado")

    nuevo = db.uno(
        """INSERT INTO usuarios (id_empresa, nombre, usuario_login, contrasena, rol, activo)
           VALUES (%s, %s, %s, %s, %s, TRUE) RETURNING id_usuario""",
        (u.id_empresa, str(nombre).strip(), login, cifrar(clave), rol),
    )
    return JSONResponse(
        {"success": True, "message": "Usuario creado exitosamente", "usuario_id": nuevo["id_usuario"]},
        status_code=201,
    )


@router.put("/{id_usuario}/estado")
def cambiar_estado(id_usuario: int, cuerpo: dict = Depends(cuerpo_json), u: Usuario = Depends(solo_admin)):
    if cuerpo.get("activo") is not None:
        activo = como_bool(cuerpo["activo"])
    else:
        activo = str(cuerpo.get("estado") or "").upper() == "ACTIVO"

    if id_usuario == u.id and not activo:
        raise ApiError(400, "No puede desactivar su propio usuario")

    if db.ejecutar(
        "UPDATE usuarios SET activo = %s WHERE id_usuario = %s AND id_empresa = %s",
        (activo, id_usuario, u.id_empresa),
    ) == 0:
        raise ApiError(404, "Usuario no encontrado")
    return {"success": True, "message": "Estado del usuario actualizado"}


@router.put("/{id_usuario}")
def actualizar(id_usuario: int, cuerpo: dict = Depends(cuerpo_json), u: Usuario = Depends(solo_admin)):
    campos, valores = [], []
    if cuerpo.get("nombre"):
        campos.append("nombre = %s")
        valores.append(str(cuerpo["nombre"]).strip())
    if cuerpo.get("usuario_login"):
        campos.append("usuario_login = %s")
        valores.append(str(cuerpo["usuario_login"]).strip())
    if cuerpo.get("rol"):
        if cuerpo["rol"] not in ROLES:
            raise ApiError(400, "Rol inválido")
        campos.append("rol = %s")
        valores.append(cuerpo["rol"])
    if cuerpo.get("password"):
        if len(str(cuerpo["password"])) < 6:
            raise ApiError(400, "La contraseña debe tener al menos 6 caracteres")
        campos.append("contrasena = %s")
        valores.append(cifrar(cuerpo["password"]))
    if not campos:
        raise ApiError(400, "No hay datos para actualizar")

    if db.ejecutar(
        f"UPDATE usuarios SET {', '.join(campos)} WHERE id_usuario = %s AND id_empresa = %s",
        (*valores, id_usuario, u.id_empresa),
    ) == 0:
        raise ApiError(404, "Usuario no encontrado")
    return {"success": True, "message": "Usuario actualizado"}


@router.delete("/{id_usuario}")
def eliminar(id_usuario: int, u: Usuario = Depends(solo_admin)):
    """Baja lógica: nunca se borra, porque movimientos, pagos y turnos lo referencian."""
    if id_usuario == u.id:
        raise ApiError(400, "No puede eliminar su propio usuario")
    if db.ejecutar(
        "UPDATE usuarios SET activo = FALSE WHERE id_usuario = %s AND id_empresa = %s",
        (id_usuario, u.id_empresa),
    ) == 0:
        raise ApiError(404, "Usuario no encontrado")
    return {"success": True, "message": "Usuario desactivado"}
