# Sistema de Rifa

Aplicación web para vender boletas de rifa (3.333 boletas, cada una con 3 números
de 4 cifras entre `0000` y `9999`, igual que la lotería). Varios vendedores pueden
usarla al mismo tiempo desde distintos dispositivos; cada número solo se le puede
asignar a una persona, y el sistema avisa en el momento si un número ya está ocupado.

## Funcionalidades

- **Login por vendedor** (usuario y contraseña), protegido contra fuerza bruta
  (máximo 5 intentos por minuto por IP). Hay un rol de **administrador**.
- **Registrar cliente**: formulario con datos personales (nombre, documento, teléfono,
  dirección, correo) y los 3 números elegidos. Cada número se valida **en vivo** contra
  la base de datos y muestra "Libre ✓" u "Ocupado ✗" mientras se escribe. El correo, si
  se indica, se valida con formato.
- **Mapa de números**: vista de los 10.000 números posibles (0000-9999) coloreados por
  disponibilidad, con buscador rápido de un número puntual.
- **Listado de boletas** (paginado): los vendedores ven sus propias ventas; el
  administrador ve todas y puede buscar por nombre, documento o teléfono. Cada boleta
  se puede **editar** (datos de contacto del cliente; los números no cambian) por el
  vendedor que la vendió o por un administrador.
- **Panel de administrador**: crear/activar/desactivar vendedores, ver el **historial de
  ventas de cada vendedor** (total de boletas, números vendidos, primera/última venta),
  y exportar todas las boletas a CSV (los campos se sanean contra fórmulas maliciosas
  tipo CSV injection).
- **Sorteo del ganador** (solo administrador): registra el número que salió ganador y el
  sistema muestra automáticamente si fue vendido y a quién, con historial de sorteos
  anteriores.
- **Consulta pública de números**: sin necesidad de iniciar sesión, cualquier cliente
  puede buscar por su cédula/documento y ver su nombre y los números que compró (no se
  expone teléfono, dirección ni correo). Protegida contra abuso (máximo 10 consultas por
  minuto por IP).
- La base de datos impide, incluso si dos vendedores registran al mismo tiempo, que un
  número quede asignado dos veces (el número es la llave primaria de la tabla), y lo
  mismo pasa si dos administradores crean un vendedor con el mismo usuario a la vez.
- **Protección CSRF** en todos los formularios y **registro de eventos** (logins,
  boletas registradas, altas/bajas de vendedores) en el log de la aplicación.

## Ejecutar en tu computador

Requiere Python 3.10 o superior.

```bash
cd rifa_sistema
python -m venv venv
venv\Scripts\activate        # En Windows (PowerShell: venv\Scripts\Activate.ps1)
pip install -r requirements.txt
python app.py
```

Abre `http://127.0.0.1:5000` en el navegador.

Al arrancar por primera vez (`python app.py`) se crea automáticamente la base de datos
y un usuario administrador con una **contraseña aleatoria**, que se imprime una sola vez
en la consola:

```
Usuario admin creado -> usuario: admin / contraseña: <contraseña generada> (¡cámbiala!)
```

Guarda esa contraseña o cámbiala de inmediato creando un nuevo admin desde el panel de
vendedores y desactivando el usuario `admin` original.

Si necesitas volver a generarla (por ejemplo en un despliegue donde `python app.py` no
se ejecuta directamente), usa el comando:

```bash
flask --app app.py seed-admin
```

Este comando solo crea el admin si todavía no existe ningún vendedor en la base de datos.

### Variables de entorno

- `SECRET_KEY` — clave secreta usada para firmar sesiones y tokens CSRF. **Obligatoria**
  si defines `DATABASE_URL` (es decir, en cualquier despliegue real); la app no arranca
  sin ella en ese caso. Genera una con:
  ```bash
  python -c "import secrets; print(secrets.token_hex(32))"
  ```
- `DATABASE_URL` — cadena de conexión a la base de datos (ver sección de despliegue).

### Migraciones de esquema

Los cambios en `models.py` ya no se aplican solos: se gestionan con Flask-Migrate
(Alembic). Después de modificar un modelo:

```bash
flask --app app.py db migrate -m "descripción del cambio"
flask --app app.py db upgrade
```

La carpeta `migrations/` debe subirse al repositorio (no va en `.gitignore`).

### Tests

```bash
pip install -r requirements-dev.txt
pytest
```

## Desplegar en internet (para que los vendedores accedan desde cualquier lugar)

### Railway (recomendado)

1. Sube esta carpeta a un repositorio de GitHub (público o privado, da igual).
2. En [railway.app](https://railway.app), inicia sesión con GitHub y crea un
   **New Project → Deploy from GitHub repo**, seleccionando este repositorio. Railway
   detecta que es una app de Python y usa el `Procfile` automáticamente — no hay que
   configurar build/start command a mano.
3. Dentro del mismo proyecto, agrega la base de datos: **+ New → Database → Add
   PostgreSQL**. Railway la deja lista sola.
4. Entra a la configuración de tu servicio web (no la de la base de datos) → pestaña
   **Variables**, y agrega:
   - `SECRET_KEY`: un valor aleatorio propio. Genera uno con:
     ```bash
     python -c "import secrets; print(secrets.token_hex(32))"
     ```
   - `DATABASE_URL`: en vez de escribirla a mano, usa "Add Reference" / `${{ }}` y
     apunta a la variable `DATABASE_URL` que expone el servicio de PostgreSQL que
     acabas de crear — así se mantiene sincronizada si Railway la rota.
   - `FLASK_APP`: `app.py`
5. Railway despliega automáticamente. El primer arranque ya corre las migraciones solo
   (están encadenadas en el `Procfile`: `flask db upgrade && gunicorn app:app`).
6. Crea el usuario administrador **una sola vez**, ejecutando un comando contra el
   servicio ya desplegado. La forma más simple es instalar la
   [Railway CLI](https://docs.railway.com/guides/cli) en tu computador y correr:
   ```bash
   railway login
   railway link          # selecciona este proyecto
   railway run flask --app app.py seed-admin
   ```
   Anota la contraseña que imprime — no se vuelve a mostrar.
7. Railway te da un dominio público gratis (`tu-proyecto.up.railway.app`); puedes
   agregar un dominio propio desde **Settings → Networking** si quieres.

### Render (alternativa)

Los mismos pasos aplican en [render.com](https://render.com): crea un **Web Service**
apuntando al repositorio, agrega una base de datos **PostgreSQL** desde el dashboard,
copia su "Internal Database URL" a la variable `DATABASE_URL` del Web Service, y define
`SECRET_KEY`. **Evita el plan gratuito** para esto: el servicio se duerme tras 15
minutos sin uso y la base de datos gratuita se borra a los 30 días — nada de eso es
aceptable con dinero real de por medio.

### ⚠️ Importante sobre la base de datos

Por defecto el sistema usa un archivo SQLite (`rifa.db`) pensado solo para desarrollo
local. **No sirve en producción**: en la mayoría de hostings el disco no es permanente,
así que el archivo se borra en cada reinicio y se pierden todas las boletas. Por eso
el paso de agregar PostgreSQL y definir `DATABASE_URL` no es opcional para un
despliegue real — la app ya está preparada para usarla automáticamente en cuanto esa
variable existe.

## Estructura del proyecto

```
rifa_sistema/
├── app.py                  # Configuración y arranque de la app Flask
├── extensions.py            # Instancias de SQLAlchemy, Login, CSRF, Limiter, Migrate
├── models.py                 # Modelos: Vendedor, Cliente, Boleta, NumeroAsignado, Sorteo, ConfiguracionRifa
├── routes.py                  # Todas las rutas/vistas
├── migrations/                 # Historial de migraciones de esquema (Flask-Migrate)
├── templates/                   # Plantillas HTML
├── static/css/style.css          # Estilos
├── static/js/main.js              # Verificación en vivo de números
├── tests/                          # Suite de pruebas (pytest)
├── requirements.txt
├── requirements-dev.txt             # requirements.txt + pytest
├── Procfile                          # Comando de arranque para Railway/Render
└── .env.example                       # Qué variables de entorno hacen falta
```
