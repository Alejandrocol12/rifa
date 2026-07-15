import logging
import os
import secrets

from flask import Flask

from extensions import csrf, db, limiter, login_manager, migrate

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("rifa")


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = _get_secret_key()
    app.config["SQLALCHEMY_DATABASE_URI"] = _get_database_uri()
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)

    from models import Vendedor

    @login_manager.user_loader
    def load_user(user_id):
        return Vendedor.query.get(int(user_id))

    from routes import bp as main_bp

    app.register_blueprint(main_bp)

    return app


def _get_database_uri():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        return "sqlite:///rifa.db"
    # Usamos el driver psycopg (v3) en vez de psycopg2: psycopg2-binary suele
    # fallar en contenedores minimalistas (Railway/Nixpacks) con el error
    # "libpq.so.5: cannot open shared object file" porque no encuentra la
    # librería del sistema; psycopg[binary] no depende de eso. Railway (y la
    # mayoría de hostings) entregan la URL como postgres:// o postgresql://,
    # que SQLAlchemy interpretaría con psycopg2 por defecto si no se lo
    # indicamos explícitamente.
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql+psycopg://", 1)
    elif database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


def _get_secret_key():
    secret_key = os.environ.get("SECRET_KEY")
    if secret_key:
        return secret_key
    if os.environ.get("DATABASE_URL"):
        # Hay DATABASE_URL configurada: asumimos un despliegue real, no un
        # entorno de desarrollo local. Sin SECRET_KEY propia, las sesiones
        # y el CSRF quedarían protegidos por una clave pública y predecible.
        raise RuntimeError(
            "Falta la variable de entorno SECRET_KEY. Genera una con "
            "`python -c \"import secrets; print(secrets.token_hex(32))\"` "
            "y defínela antes de arrancar la aplicación."
        )
    logger.warning(
        "SECRET_KEY no está definida: usando una clave temporal solo válida "
        "para esta ejecución local. No uses esto en producción."
    )
    return secrets.token_hex(32)


def _crear_admin_inicial():
    from models import Vendedor

    if Vendedor.query.count() == 0:
        password = secrets.token_urlsafe(9)
        admin = Vendedor(username="admin", nombre="Administrador", is_admin=True)
        admin.set_password(password)
        db.session.add(admin)
        db.session.commit()
        logger.info("Usuario admin creado -> usuario: admin / contraseña: %s (¡cámbiala!)", password)
        print(f"Usuario admin creado -> usuario: admin / contraseña: {password} (¡cámbiala!)")


app = create_app()


@app.cli.command("seed-admin")
def seed_admin_command():
    """Crea el usuario admin inicial si todavía no existe ningún vendedor."""
    _crear_admin_inicial()


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        _crear_admin_inicial()
    app.run(debug=True, host="0.0.0.0", port=5000)
