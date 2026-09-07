"""
Actividad 1 - Semana 4
App robusta (Flask) que hace uso de TiDB Serverless (compatible con MySQL)
como base de datos en la nube.

Funcionalidad:
- Dashboard con estadísticas (total estudiantes, programas, promedio de semestre)
- CRUD completo de estudiantes (crear, ver, editar, eliminar)
- Activar / desactivar estudiantes sin borrarlos
- Búsqueda y filtro por programa
- Base de datos normalizada: tabla `programas` con clave foránea desde
  `estudiantes` (en vez de repetir el texto del programa en cada fila)
- Historial de cambios (auditoría) por estudiante
- Login de usuarios con roles (admin / profesor) para proteger la app
"""

import os
import functools
from datetime import datetime

from flask import Flask, render_template, request, redirect, url_for, flash, session
import pymysql
import certifi
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "clave-de-desarrollo-cambiar-en-produccion")

DB_NAME = os.getenv("DB_NAME", "actividad_semana4")

# certifi.where() da un certificado CA válido multiplataforma (Windows/Mac/Linux)
SSL_CA_PATH = os.getenv("DB_SSL_CA") or certifi.where()

DB_CONFIG_BASE = {
    "host": os.getenv("DB_HOST"),
    "port": int(os.getenv("DB_PORT", 4000)),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "ssl": {"ca": SSL_CA_PATH},
    "cursorclass": pymysql.cursors.DictCursor,
}

DB_CONFIG = {**DB_CONFIG_BASE, "database": DB_NAME}

# Credenciales del usuario admin que se crea automáticamente la primera vez
# que la tabla `usuarios` está vacía (puedes cambiarlas luego desde la BD).
ADMIN_NOMBRE = os.getenv("ADMIN_NOMBRE", "Administrador")
ADMIN_CORREO = os.getenv("ADMIN_CORREO", "admin@uptc.edu.co")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")

PROGRAMAS_SEMILLA = [
    "Ingeniería de Sistemas",
    "Ingeniería Electrónica",
    "Ingeniería Industrial",
    "Ingeniería Civil",
    "Administración de Empresas",
    "Otro",
]


@app.context_processor
def inject_globals():
    return {
        "db_name_display": DB_NAME,
        "usuario_actual": session.get("usuario_nombre"),
        "rol_actual": session.get("usuario_rol"),
    }


def get_connection():
    return pymysql.connect(**DB_CONFIG)


# ---------------------------------------------------------------------------
# Utilidades de migración (para no romper una base ya creada con el esquema
# viejo: una sola tabla `estudiantes` con `programa` como texto libre)
# ---------------------------------------------------------------------------

def _column_exists(cursor, table, column_name):
    cursor.execute(
        """
        SELECT COUNT(*) AS existe FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s AND column_name = %s
        """,
        (DB_NAME, table, column_name),
    )
    return cursor.fetchone()["existe"] > 0


def _add_column_if_missing(cursor, table, column_def_sql, column_name):
    if not _column_exists(cursor, table, column_name):
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column_def_sql}")


def _index_exists(cursor, table, index_name):
    cursor.execute(
        """
        SELECT COUNT(*) AS existe FROM information_schema.statistics
        WHERE table_schema = %s AND table_name = %s AND index_name = %s
        """,
        (DB_NAME, table, index_name),
    )
    return cursor.fetchone()["existe"] > 0


def _add_index_if_missing(cursor, table, index_name, index_sql):
    if not _index_exists(cursor, table, index_name):
        try:
            cursor.execute(index_sql)
        except pymysql.err.OperationalError:
            pass  # el motor no soporta ese tipo de índice/constraint; se ignora


def _migrar_programa_texto_a_tabla(cursor):
    """Si `estudiantes` viene de una versión anterior con columna `programa`
    (VARCHAR) en vez de `programa_id` (FK), migra los datos automáticamente:
    1. Crea en `programas` cada nombre distinto que ya exista en `estudiantes`.
    2. Agrega la columna `programa_id` si falta.
    3. Copia el id correspondiente desde `programas` según el texto viejo.
    """
    if not _column_exists(cursor, "estudiantes", "programa"):
        return  # ya está en el esquema nuevo, nada que migrar

    cursor.execute("SELECT DISTINCT programa FROM estudiantes WHERE programa IS NOT NULL")
    nombres_existentes = [row["programa"] for row in cursor.fetchall()]
    for nombre in nombres_existentes:
        cursor.execute(
            "INSERT IGNORE INTO programas (nombre) VALUES (%s)", (nombre,)
        )

    _add_column_if_missing(cursor, "estudiantes", "programa_id INT NULL", "programa_id")

    cursor.execute(
        """
        UPDATE estudiantes e
        JOIN programas p ON p.nombre = e.programa
        SET e.programa_id = p.id
        WHERE e.programa_id IS NULL
        """
    )

    # Si ya no quedan filas sin migrar, es seguro quitar la columna vieja
    cursor.execute("SELECT COUNT(*) AS pendientes FROM estudiantes WHERE programa_id IS NULL")
    if cursor.fetchone()["pendientes"] == 0:
        try:
            cursor.execute("ALTER TABLE estudiantes DROP COLUMN programa")
            cursor.execute("ALTER TABLE estudiantes MODIFY programa_id INT NOT NULL")
        except pymysql.err.OperationalError:
            pass


def _seed_programas(cursor):
    cursor.execute("SELECT COUNT(*) AS total FROM programas")
    if cursor.fetchone()["total"] == 0:
        for nombre in PROGRAMAS_SEMILLA:
            cursor.execute("INSERT IGNORE INTO programas (nombre) VALUES (%s)", (nombre,))


def _seed_admin(cursor):
    cursor.execute("SELECT COUNT(*) AS total FROM usuarios")
    if cursor.fetchone()["total"] == 0:
        cursor.execute(
            """
            INSERT INTO usuarios (nombre, correo, password_hash, rol)
            VALUES (%s, %s, %s, 'admin')
            """,
            (ADMIN_NOMBRE, ADMIN_CORREO, generate_password_hash(ADMIN_PASSWORD)),
        )


def init_db():
    """Crea la base de datos, las tablas, la vista y migra datos si hace falta."""
    conn = pymysql.connect(**DB_CONFIG_BASE)
    try:
        with conn.cursor() as cursor:
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}`")
        conn.commit()
    finally:
        conn.close()

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS programas (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    nombre VARCHAR(100) NOT NULL UNIQUE,
                    facultad VARCHAR(100) NULL,
                    duracion_semestres INT NULL
                )
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS usuarios (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    nombre VARCHAR(100) NOT NULL,
                    correo VARCHAR(150) NOT NULL UNIQUE,
                    password_hash VARCHAR(255) NOT NULL,
                    rol ENUM('admin', 'profesor') NOT NULL DEFAULT 'profesor',
                    fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS estudiantes (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    nombre VARCHAR(100) NOT NULL,
                    correo VARCHAR(150) NULL,
                    programa_id INT NOT NULL,
                    semestre INT NOT NULL,
                    activo TINYINT(1) NOT NULL DEFAULT 1,
                    fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    fecha_actualizacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        ON UPDATE CURRENT_TIMESTAMP,
                    CONSTRAINT fk_estudiante_programa
                        FOREIGN KEY (programa_id) REFERENCES programas(id)
                )
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS historial_cambios (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    estudiante_id INT NOT NULL,
                    usuario_id INT NULL,
                    accion ENUM('creado', 'editado', 'activado', 'desactivado', 'eliminado')
                        NOT NULL,
                    detalle TEXT NULL,
                    fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
                )
                """
            )

            # --- Migraciones para bases creadas con versiones anteriores ---
            _migrar_programa_texto_a_tabla(cursor)
            _add_column_if_missing(cursor, "estudiantes", "correo VARCHAR(150) NULL", "correo")
            _add_column_if_missing(
                cursor, "estudiantes", "activo TINYINT(1) NOT NULL DEFAULT 1", "activo"
            )
            _add_column_if_missing(
                cursor, "estudiantes",
                "fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP", "fecha_registro"
            )
            _add_column_if_missing(
                cursor, "estudiantes",
                "fecha_actualizacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP "
                "ON UPDATE CURRENT_TIMESTAMP", "fecha_actualizacion"
            )

            _add_index_if_missing(
                cursor, "estudiantes", "uq_estudiantes_correo",
                "ALTER TABLE estudiantes ADD CONSTRAINT uq_estudiantes_correo UNIQUE (correo)"
            )
            _add_index_if_missing(
                cursor, "estudiantes", "idx_estudiantes_activo",
                "CREATE INDEX idx_estudiantes_activo ON estudiantes(activo)"
            )
            _add_index_if_missing(
                cursor, "estudiantes", "idx_estudiantes_programa",
                "CREATE INDEX idx_estudiantes_programa ON estudiantes(programa_id)"
            )
            try:
                cursor.execute(
                    "ALTER TABLE estudiantes ADD CONSTRAINT chk_semestre_valido "
                    "CHECK (semestre BETWEEN 1 AND 12)"
                )
            except pymysql.err.OperationalError:
                pass  # ya existe o el motor no soporta CHECK; se valida igual en la app

            _seed_programas(cursor)
            _seed_admin(cursor)

            cursor.execute(
                """
                CREATE OR REPLACE VIEW vista_estadisticas_programa AS
                SELECT p.id AS programa_id, p.nombre AS programa,
                       COUNT(e.id) AS cantidad,
                       COALESCE(SUM(e.activo), 0) AS activos,
                       ROUND(AVG(e.semestre), 1) AS promedio_semestre
                FROM programas p
                LEFT JOIN estudiantes e ON e.programa_id = p.id
                GROUP BY p.id, p.nombre
                """
            )
        conn.commit()
    finally:
        conn.close()


def get_programas():
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM programas ORDER BY nombre")
            return cursor.fetchall()
    finally:
        conn.close()


def registrar_historial(cursor, estudiante_id, accion, detalle=None):
    cursor.execute(
        """
        INSERT INTO historial_cambios (estudiante_id, usuario_id, accion, detalle)
        VALUES (%s, %s, %s, %s)
        """,
        (estudiante_id, session.get("usuario_id"), accion, detalle),
    )


# ---------------------------------------------------------------------------
# Autenticación
# ---------------------------------------------------------------------------

def login_required(vista):
    @functools.wraps(vista)
    def envoltura(*args, **kwargs):
        if not session.get("usuario_id"):
            flash("Inicia sesión para continuar.", "error")
            return redirect(url_for("login", next=request.path))
        return vista(*args, **kwargs)
    return envoltura


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        correo = request.form.get("correo", "").strip()
        password = request.form.get("password", "")

        conn = get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM usuarios WHERE correo = %s", (correo,))
                usuario = cursor.fetchone()
        finally:
            conn.close()

        if usuario and check_password_hash(usuario["password_hash"], password):
            session["usuario_id"] = usuario["id"]
            session["usuario_nombre"] = usuario["nombre"]
            session["usuario_rol"] = usuario["rol"]
            destino = request.args.get("next") or url_for("dashboard")
            return redirect(destino)

        flash("Correo o contraseña incorrectos.", "error")

    return render_template("login.html")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("Sesión cerrada.", "success")
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# Rutas
# ---------------------------------------------------------------------------

@app.route("/")
@login_required
def dashboard():
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS total FROM estudiantes")
            total = cursor.fetchone()["total"]

            cursor.execute("SELECT COUNT(*) AS total FROM estudiantes WHERE activo = 1")
            total_activos = cursor.fetchone()["total"]

            cursor.execute(
                "SELECT COUNT(*) AS total FROM vista_estadisticas_programa WHERE cantidad > 0"
            )
            total_programas = cursor.fetchone()["total"]

            cursor.execute("SELECT AVG(semestre) AS promedio FROM estudiantes")
            promedio_semestre = cursor.fetchone()["promedio"] or 0

            cursor.execute(
                """
                SELECT programa, cantidad FROM vista_estadisticas_programa
                WHERE cantidad > 0 ORDER BY cantidad DESC
                """
            )
            por_programa = cursor.fetchall()

            cursor.execute(
                """
                SELECT e.*, p.nombre AS programa
                FROM estudiantes e
                JOIN programas p ON p.id = e.programa_id
                ORDER BY e.id DESC LIMIT 5
                """
            )
            recientes = cursor.fetchall()
    finally:
        conn.close()

    max_cantidad = max([p["cantidad"] for p in por_programa], default=1)

    return render_template(
        "dashboard.html",
        total=total,
        total_activos=total_activos,
        total_programas=total_programas,
        promedio_semestre=round(promedio_semestre, 1),
        por_programa=por_programa,
        max_cantidad=max_cantidad,
        recientes=recientes,
    )


@app.route("/estudiantes")
@login_required
def lista_estudiantes():
    busqueda = request.args.get("q", "").strip()
    programa_filtro = request.args.get("programa", "").strip()

    query = """
        SELECT e.*, p.nombre AS programa
        FROM estudiantes e
        JOIN programas p ON p.id = e.programa_id
        WHERE 1=1
    """
    params = []

    if busqueda:
        query += " AND (e.nombre LIKE %s OR e.correo LIKE %s)"
        params.extend([f"%{busqueda}%", f"%{busqueda}%"])

    if programa_filtro:
        query += " AND p.id = %s"
        params.append(programa_filtro)

    query += " ORDER BY e.id DESC"

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(query, params)
            estudiantes = cursor.fetchall()
    finally:
        conn.close()

    return render_template(
        "lista.html",
        estudiantes=estudiantes,
        programas=get_programas(),
        busqueda=busqueda,
        programa_filtro=programa_filtro,
    )


@app.route("/estudiantes/nuevo", methods=["GET", "POST"])
@login_required
def nuevo_estudiante():
    if request.method == "POST":
        nombre = request.form["nombre"].strip()
        correo = request.form.get("correo", "").strip()
        programa_id = request.form.get("programa_id")
        semestre = request.form.get("semestre", "")

        errores = []
        if not nombre or not programa_id or not semestre:
            errores.append("Completa los campos obligatorios (nombre, programa, semestre).")
        elif not semestre.isdigit() or not (1 <= int(semestre) <= 12):
            errores.append("El semestre debe ser un número entre 1 y 12.")

        if errores:
            for e in errores:
                flash(e, "error")
            return render_template(
                "form.html", programas=get_programas(), estudiante=request.form
            )

        conn = get_connection()
        try:
            with conn.cursor() as cursor:
                # Blindaje contra doble clic / reenvío del formulario: si ya existe
                # un estudiante con los mismos datos creado en los últimos 10
                # segundos, no lo vuelve a insertar.
                cursor.execute(
                    """
                    SELECT id FROM estudiantes
                    WHERE nombre = %s AND programa_id = %s AND semestre = %s
                      AND fecha_registro >= NOW() - INTERVAL 10 SECOND
                    """,
                    (nombre, programa_id, semestre),
                )
                if cursor.fetchone():
                    flash(f"Estudiante '{nombre}' agregado correctamente.", "success")
                    return redirect(url_for("lista_estudiantes"))

                cursor.execute(
                    """
                    INSERT INTO estudiantes (nombre, correo, programa_id, semestre, activo)
                    VALUES (%s, %s, %s, %s, 1)
                    """,
                    (nombre, correo or None, programa_id, semestre),
                )
                nuevo_id = cursor.lastrowid
                registrar_historial(cursor, nuevo_id, "creado", f"Registro creado: {nombre}")
            conn.commit()
        except pymysql.err.IntegrityError:
            flash("Ya existe un estudiante con ese correo.", "error")
            return render_template(
                "form.html", programas=get_programas(), estudiante=request.form
            )
        finally:
            conn.close()

        flash(f"Estudiante '{nombre}' agregado correctamente.", "success")
        return redirect(url_for("lista_estudiantes"))

    return render_template("form.html", programas=get_programas(), estudiante=None)


@app.route("/estudiantes/<int:id>/editar", methods=["GET", "POST"])
@login_required
def editar_estudiante(id):
    conn = get_connection()
    try:
        if request.method == "POST":
            nombre = request.form["nombre"].strip()
            correo = request.form.get("correo", "").strip()
            programa_id = request.form.get("programa_id")
            semestre = request.form.get("semestre", "")

            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE estudiantes
                    SET nombre = %s, correo = %s, programa_id = %s, semestre = %s
                    WHERE id = %s
                    """,
                    (nombre, correo or None, programa_id, semestre, id),
                )
                registrar_historial(cursor, id, "editado", f"Datos actualizados: {nombre}")
            conn.commit()
            flash(f"Estudiante '{nombre}' actualizado.", "success")
            return redirect(url_for("lista_estudiantes"))

        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT e.*, p.nombre AS programa
                FROM estudiantes e JOIN programas p ON p.id = e.programa_id
                WHERE e.id = %s
                """,
                (id,),
            )
            estudiante = cursor.fetchone()
    finally:
        conn.close()

    if not estudiante:
        flash("No se encontró ese estudiante.", "error")
        return redirect(url_for("lista_estudiantes"))

    return render_template("form.html", programas=get_programas(), estudiante=estudiante)


@app.route("/estudiantes/<int:id>/toggle", methods=["POST"])
@login_required
def toggle_estudiante(id):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE estudiantes SET activo = NOT activo WHERE id = %s", (id,))
            cursor.execute("SELECT activo, nombre FROM estudiantes WHERE id = %s", (id,))
            fila = cursor.fetchone()
            accion = "activado" if fila and fila["activo"] else "desactivado"
            registrar_historial(cursor, id, accion, f"Cambio de estado: {fila['nombre'] if fila else id}")
        conn.commit()
    finally:
        conn.close()
    return redirect(url_for("lista_estudiantes"))


@app.route("/estudiantes/<int:id>/eliminar", methods=["POST"])
@login_required
def eliminar_estudiante(id):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT nombre FROM estudiantes WHERE id = %s", (id,))
            fila = cursor.fetchone()
            registrar_historial(cursor, id, "eliminado", f"Registro eliminado: {fila['nombre'] if fila else id}")
            cursor.execute("DELETE FROM estudiantes WHERE id = %s", (id,))
        conn.commit()
    finally:
        conn.close()
    flash("Estudiante eliminado.", "success")
    return redirect(url_for("lista_estudiantes"))


@app.route("/historial")
@login_required
def historial():
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT h.*, u.nombre AS usuario_nombre
                FROM historial_cambios h
                LEFT JOIN usuarios u ON u.id = h.usuario_id
                ORDER BY h.fecha DESC
                LIMIT 100
                """
            )
            registros = cursor.fetchall()
    finally:
        conn.close()
    return render_template("historial.html", registros=registros)


if __name__ == "__main__":
    init_db()
    port = int(os.getenv("PORT", 5000))
    app.run(debug=True, host="0.0.0.0", port=port)