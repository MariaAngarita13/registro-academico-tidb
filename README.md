# Registro Académico — Actividad Semana 4 (TiDB Serverless)

Aplicación web en **Flask** para la gestión de estudiantes, programas académicos e historial de cambios, usando **TiDB Serverless** (compatible con MySQL) como base de datos en la nube.

Proyecto académico — Actividad 1, Semana 4.

## Requisitos previos

- Python 3.10 o superior.
- Cuenta en TiDB Cloud.
- Base de datos/cluster TiDB Serverless.
- Credenciales de conexión a TiDB.
- Git instalado (opcional).

## Funcionalidades

- **Login** con roles (`admin`) para proteger la aplicación.
- **Dashboard** con estadísticas: total de estudiantes, activos, programas distintos y promedio de semestre.
- **CRUD completo de estudiantes**: crear, listar, editar y eliminar.
- **Activar / desactivar** estudiantes sin borrarlos de la base de datos.
- **Búsqueda y filtro** de estudiantes por nombre, correo o programa.
- **Modelo de datos normalizado**: tabla `programas` referenciada por `estudiantes` mediante clave foránea (en vez de repetir el texto del programa en cada fila).
- **Historial de cambios (auditoría)**: cada creación, edición, activación, desactivación o eliminación queda registrada con el usuario y la fecha.
- **Migraciones automáticas**: si la base ya existía con un esquema anterior (columna `programa` como texto libre), la app la migra sola al arrancar.

## Tecnologías

| Componente         | Tecnología                                   |
|--------------------|----------------------------------------------|
| Backend            | Python 3 + Flask 3.0                         |
| Base de datos      | TiDB Serverless (MySQL-compatible), AWS `sa-east-1` (São Paulo) |
| Driver de BD       | PyMySQL + certifi (SSL)                      |
| Autenticación      | Werkzeug (hash de contraseñas)               |
| Frontend           | Jinja2 + HTML/CSS propio (`static/style.css`)|
| Despliegue         | Render                                       |

## Estructura del proyecto

```
├── app.py                  # Lógica de la aplicación, rutas y creación del esquema (init_db)
├── requirements.txt        # Dependencias de Python
├── .env.example            # Variables de entorno necesarias (renombrar a .env)
├── static/
│   └── style.css
└── templates/
    ├── base.html            # Layout general (menú lateral)
    ├── login.html
    ├── dashboard.html
    ├── lista.html            # Listado, búsqueda y filtro de estudiantes
    ├── form.html             # Formulario crear/editar estudiante
    └── historial.html        # Auditoría de cambios
```

## Modelo de datos (resumen)

- `programas` — catálogo de programas académicos.
- `usuarios` — cuentas de acceso a la app (`admin` / `profesor`).
- `estudiantes` — datos del estudiante, con `programa_id` como llave foránea hacia `programas`.
- `historial_cambios` — auditoría: qué se hizo, sobre qué estudiante, quién lo hizo y cuándo.
- Vista `vista_estadisticas_programa` — cantidad de estudiantes, activos y promedio de semestre por programa, usada en el dashboard.



## Ejecución local (resumen rápido)

```bash
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
copy .env.example .env       # y completar con tus credenciales de TiDB Cloud
python app.py
```

La primera vez que corre, `init_db()` crea la base de datos, las tablas, la vista y un usuario **admin** por defecto (ver `.env` / `Documentacion_Tecnica.docx` para las credenciales iniciales).
