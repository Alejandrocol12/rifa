from datetime import datetime

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db


class Vendedor(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    nombre = db.Column(db.String(120), nullable=False)
    telefono = db.Column(db.String(30))
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    activo = db.Column(db.Boolean, default=True, nullable=False)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)

    boletas = db.relationship(
        "Boleta", backref="vendedor", lazy=True, foreign_keys="Boleta.vendedor_id"
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Cliente(db.Model):
    # El documento/cédula es la llave primaria: es el único dato que no se
    # repite entre personas, así que un mismo cliente nunca queda duplicado
    # aunque compre boletas distintas o lo atienda otro vendedor.
    documento = db.Column(db.String(30), primary_key=True)
    nombre = db.Column(db.String(150), nullable=False)
    telefono = db.Column(db.String(30), nullable=False)
    direccion = db.Column(db.String(200))
    email = db.Column(db.String(120))
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)

    boletas = db.relationship("Boleta", backref="cliente", lazy=True)


class Boleta(db.Model):
    # Cada boleta es un grupo de 3 números vendido en un solo momento; un
    # mismo cliente puede tener varias boletas (si vuelve a comprar más
    # números), cada una con su propio cobro de $100.000 repartido en los
    # 4 premios que se juegan con esos números ($25.000 cada uno).
    PRECIO_TOTAL = 100000
    PRECIO_POR_PREMIO = 25000

    id = db.Column(db.Integer, primary_key=True)
    vendedor_id = db.Column(db.Integer, db.ForeignKey("vendedor.id"), nullable=False)
    cliente_documento = db.Column(db.String(30), db.ForeignKey("cliente.documento"), nullable=False)
    fecha = db.Column(db.DateTime, default=datetime.utcnow)

    pagado_premio1 = db.Column(db.Boolean, default=False, nullable=False)
    pagado_premio2 = db.Column(db.Boolean, default=False, nullable=False)
    pagado_premio3 = db.Column(db.Boolean, default=False, nullable=False)
    pagado_premio4 = db.Column(db.Boolean, default=False, nullable=False)

    # Una boleta anulada libera sus números (se borran de NumeroAsignado para
    # que se puedan volver a vender), pero la fila se conserva para dejar
    # rastro de que existió y quién la anuló.
    anulada = db.Column(db.Boolean, default=False, nullable=False)
    fecha_anulacion = db.Column(db.DateTime)
    anulada_por_id = db.Column(db.Integer, db.ForeignKey("vendedor.id"))
    numeros_anulados = db.Column(db.String(50))

    numeros = db.relationship(
        "NumeroAsignado", backref="boleta", lazy=True, cascade="all, delete-orphan"
    )
    historial_pagos = db.relationship(
        "HistorialPago", backref="boleta", lazy=True,
        order_by="HistorialPago.fecha.desc()", cascade="all, delete-orphan",
    )
    anulada_por = db.relationship("Vendedor", foreign_keys=[anulada_por_id])

    @property
    def premios_pagados(self):
        return sum(
            [self.pagado_premio1, self.pagado_premio2, self.pagado_premio3, self.pagado_premio4]
        )

    @property
    def monto_pagado(self):
        return self.premios_pagados * self.PRECIO_POR_PREMIO

    @property
    def pago_completo(self):
        return self.premios_pagados == 4


class HistorialPago(db.Model):
    # Registro de auditoría: cada vez que alguien marca o desmarca un premio
    # como pagado en una boleta, queda una fila aquí con quién y cuándo.
    id = db.Column(db.Integer, primary_key=True)
    boleta_id = db.Column(db.Integer, db.ForeignKey("boleta.id"), nullable=False)
    numero_premio = db.Column(db.Integer, nullable=False)
    marcado = db.Column(db.Boolean, nullable=False)
    vendedor_id = db.Column(db.Integer, db.ForeignKey("vendedor.id"), nullable=False)
    fecha = db.Column(db.DateTime, default=datetime.utcnow)

    vendedor = db.relationship("Vendedor")


class NumeroAsignado(db.Model):
    # El propio número (0000-9999) es la llave primaria: la base de datos
    # impide por sí sola que dos boletas se queden con el mismo número,
    # incluso si dos vendedores lo intentan al mismo tiempo.
    numero = db.Column(db.String(4), primary_key=True)
    boleta_id = db.Column(db.Integer, db.ForeignKey("boleta.id"), nullable=False)
    fecha = db.Column(db.DateTime, default=datetime.utcnow)


class Sorteo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    numero = db.Column(db.String(4), nullable=False)
    # A cuál de los 4 premios (cada uno pagado por separado, $25.000 c/u)
    # corresponde este sorteo; determina si el ganador alcanzó a pagarlo.
    numero_premio = db.Column(db.Integer, nullable=False)
    etiqueta = db.Column(db.String(80))
    fecha = db.Column(db.DateTime, default=datetime.utcnow)
    registrado_por_id = db.Column(db.Integer, db.ForeignKey("vendedor.id"), nullable=False)

    registrado_por = db.relationship("Vendedor")


class ConfiguracionRifa(db.Model):
    # Fila única (id=1) con ajustes generales de la rifa que se muestran
    # públicamente. Cada uno de los 4 premios se sortea en su propia fecha
    # (no todos el mismo día), así que cada uno tiene su propio campo; esa
    # misma fecha funciona como plazo límite para pagar ese premio.
    id = db.Column(db.Integer, primary_key=True)
    fecha_premio1 = db.Column(db.DateTime)
    fecha_premio2 = db.Column(db.DateTime)
    fecha_premio3 = db.Column(db.DateTime)
    fecha_premio4 = db.Column(db.DateTime)

    def fecha_premio(self, numero_premio):
        return getattr(self, f"fecha_premio{numero_premio}")

    @classmethod
    def obtener(cls):
        config = cls.query.get(1)
        if config is None:
            config = cls(id=1)
            db.session.add(config)
            db.session.commit()
        return config
