import csv
import io
import logging
import re
from datetime import datetime
from functools import wraps

from flask import Blueprint, Response, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from extensions import db, limiter
from models import Boleta, Cliente, ConfiguracionRifa, HistorialPago, NumeroAsignado, Sorteo, Vendedor

bp = Blueprint("main", __name__)
logger = logging.getLogger("rifa")

NUMERO_RE = re.compile(r"^\d{4}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
TOTAL_NUMEROS = 10000
BOLETAS_POR_PAGINA = 50
CLIENTES_POR_PAGINA = 50
# Excel/LibreOffice tratan estos caracteres al inicio de una celda como el
# comienzo de una fórmula; un cliente podría usarlos en su nombre para que
# el CSV ejecute algo al abrirlo. Se les antepone un apóstrofo para neutralizarlos.
CSV_FORMULA_PREFIXES = ("=", "+", "-", "@")


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_admin:
            flash("No tienes permiso para acceder a esa sección.", "error")
            return redirect(url_for("main.dashboard"))
        return view(*args, **kwargs)

    return wrapped


def _csv_safe(value):
    text = "" if value is None else str(value)
    if text.startswith(CSV_FORMULA_PREFIXES):
        return "'" + text
    return text


def _ultimo_sorteo_por_premio():
    """Sorteo más reciente registrado para cada uno de los 4 premios (o
    ausente si ese premio todavía no se ha sorteado)."""
    ultimos = {}
    for s in Sorteo.query.order_by(Sorteo.fecha.asc()).all():
        ultimos[s.numero_premio] = s
    return ultimos


def _resultado_premios(boleta, ultimos_sorteos, config):
    """Para cada uno de los 4 premios, determina si la boleta ganó, ganó
    pero no alcanzó a pagarlo, no ganó, o el premio todavía no se sortea
    (en cuyo caso incluye la fecha límite para pagarlo, si está definida)."""
    numeros_boleta = {n.numero for n in boleta.numeros}
    resultados = []
    for premio in (1, 2, 3, 4):
        sorteo = ultimos_sorteos.get(premio)
        pagado = getattr(boleta, f"pagado_premio{premio}")

        if sorteo is None:
            estado = "pendiente"
        elif sorteo.numero in numeros_boleta:
            estado = "ganador" if pagado else "ganador_sin_pago"
        else:
            estado = "no_ganador"

        resultados.append(
            {
                "premio": premio,
                "pagado": pagado,
                "estado": estado,
                "numero_ganador": sorteo.numero if sorteo else None,
                "fecha_limite": config.fecha_premio(premio) if estado == "pendiente" else None,
            }
        )
    return resultados


def _agrupar_clientes(boletas):
    """Agrupa boletas (ya ordenadas por fecha descendente) por cliente.

    Los datos de contacto viven en Cliente (una sola fuente de verdad por
    documento), así que son iguales sin importar cuál de sus boletas se mire.
    """
    clientes = {}
    for b in boletas:
        c = clientes.get(b.cliente_documento)
        if c is None:
            c = {
                "documento": b.cliente.documento,
                "nombre": b.cliente.nombre,
                "telefono": b.cliente.telefono,
                "total_boletas": 0,
                "total_numeros": 0,
                "primera_fecha": b.fecha,
                "ultima_fecha": b.fecha,
            }
            clientes[b.cliente_documento] = c
        c["total_boletas"] += 1
        c["total_numeros"] += len(b.numeros)
        c["primera_fecha"] = min(c["primera_fecha"], b.fecha)
        c["ultima_fecha"] = max(c["ultima_fecha"], b.fecha)
    return clientes


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("5 per minute", methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        vendedor = Vendedor.query.filter_by(username=username).first()

        if vendedor and vendedor.activo and vendedor.check_password(password):
            login_user(vendedor)
            logger.info("Login exitoso: %s", username)
            return redirect(url_for("main.dashboard"))

        logger.warning("Login fallido: %s desde %s", username, request.remote_addr)
        flash("Usuario o contraseña incorrectos, o el usuario está inactivo.", "error")

    return render_template("login.html")


@bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Sesión cerrada.", "success")
    return redirect(url_for("main.login"))


@bp.route("/")
@login_required
def dashboard():
    total_boletas = Boleta.query.filter_by(anulada=False).count()
    numeros_asignados = NumeroAsignado.query.count()
    numeros_libres = TOTAL_NUMEROS - numeros_asignados
    mis_boletas = Boleta.query.filter_by(vendedor_id=current_user.id, anulada=False).count()

    return render_template(
        "dashboard.html",
        total_boletas=total_boletas,
        numeros_asignados=numeros_asignados,
        numeros_libres=numeros_libres,
        mis_boletas=mis_boletas,
        total_numeros=TOTAL_NUMEROS,
    )


@bp.route("/api/numero/<numero>")
@login_required
def api_estado_numero(numero):
    if not NUMERO_RE.match(numero):
        return jsonify({"valido": False, "mensaje": "Debe tener exactamente 4 cifras (0000-9999)."}), 400

    asignado = NumeroAsignado.query.get(numero)
    return jsonify({"valido": True, "libre": asignado is None})


@bp.route("/api/cliente/<documento>")
@login_required
def api_buscar_cliente(documento):
    query = Boleta.query.filter_by(cliente_documento=documento)
    if not current_user.is_admin:
        query = query.filter_by(vendedor_id=current_user.id)

    ultima = query.order_by(Boleta.fecha.desc()).first()
    if not ultima:
        return jsonify({"encontrado": False})

    total = query.count()
    cliente = ultima.cliente
    return jsonify(
        {
            "encontrado": True,
            "nombre_cliente": cliente.nombre,
            "telefono": cliente.telefono,
            "direccion": cliente.direccion or "",
            "email": cliente.email or "",
            "total_boletas": total,
        }
    )


@bp.route("/registrar", methods=["GET", "POST"])
@login_required
def registrar():
    if request.method == "POST":
        nombre_cliente = request.form.get("nombre_cliente", "").strip()
        documento = request.form.get("documento", "").strip()
        telefono = request.form.get("telefono", "").strip()
        direccion = request.form.get("direccion", "").strip()
        email = request.form.get("email", "").strip()
        numeros = [request.form.get(f"numero{i}", "").strip() for i in (1, 2, 3)]

        errores = []
        if not nombre_cliente:
            errores.append("El nombre del cliente es obligatorio.")
        if not documento:
            errores.append("El documento es obligatorio.")
        if not telefono:
            errores.append("El teléfono es obligatorio.")
        if email and not EMAIL_RE.match(email):
            errores.append("El correo electrónico no tiene un formato válido.")
        for n in numeros:
            if not NUMERO_RE.match(n):
                errores.append(f"El número '{n}' no es válido. Debe tener 4 cifras (0000-9999).")
        if len(set(numeros)) != 3 and not errores:
            errores.append("Los 3 números deben ser diferentes entre sí.")

        if not errores:
            # El documento es la llave del cliente: si ya existe (aunque lo haya
            # atendido otro vendedor), se reutiliza el mismo registro en vez de
            # crear datos de contacto duplicados; solo se agrega una boleta nueva.
            cliente = Cliente.query.get(documento)
            if cliente is None:
                cliente = Cliente(
                    documento=documento,
                    nombre=nombre_cliente,
                    telefono=telefono,
                    direccion=direccion or None,
                    email=email or None,
                )
                db.session.add(cliente)
            else:
                cliente.nombre = nombre_cliente
                cliente.telefono = telefono
                cliente.direccion = direccion or None
                cliente.email = email or None

            boleta = Boleta(vendedor_id=current_user.id, cliente_documento=documento)
            db.session.add(boleta)
            try:
                db.session.flush()
                for n in numeros:
                    db.session.add(NumeroAsignado(numero=n, boleta_id=boleta.id))
                db.session.commit()
                logger.info(
                    "Boleta #%s registrada por %s para %s (números %s)",
                    boleta.id, current_user.username, nombre_cliente, ", ".join(numeros),
                )
                flash(
                    f"Boleta registrada con éxito para {nombre_cliente} "
                    f"(números {', '.join(numeros)}).",
                    "success",
                )
                return redirect(url_for("main.registrar"))
            except IntegrityError:
                db.session.rollback()
                errores.append(
                    "Uno de esos números ya fue tomado, o ese documento fue registrado por otro "
                    "vendedor justo ahora. Verifica e inténtalo de nuevo."
                )

        for e in errores:
            flash(e, "error")
        return render_template("registrar.html", form=request.form)

    return render_template("registrar.html", form={})


@bp.route("/numeros")
@login_required
def numeros():
    asignados = {n.numero: n for n in NumeroAsignado.query.all()}
    bloques = [f"{i:04d}" for i in range(0, TOTAL_NUMEROS, 1000)]
    return render_template("numeros.html", asignados=asignados, bloques=bloques)


@bp.route("/boletas")
@login_required
def boletas():
    q = request.args.get("q", "").strip()
    pago = request.args.get("pago", "").strip()
    page = request.args.get("page", 1, type=int)
    query = Boleta.query.join(Cliente)

    if not current_user.is_admin:
        query = query.filter(Boleta.vendedor_id == current_user.id)

    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                Cliente.nombre.ilike(like),
                Cliente.documento.ilike(like),
                Cliente.telefono.ilike(like),
            )
        )

    if pago == "pendiente":
        query = query.filter(
            Boleta.anulada.is_(False),
            or_(
                Boleta.pagado_premio1.is_(False),
                Boleta.pagado_premio2.is_(False),
                Boleta.pagado_premio3.is_(False),
                Boleta.pagado_premio4.is_(False),
            ),
        )
    elif pago == "completo":
        query = query.filter(
            Boleta.anulada.is_(False),
            Boleta.pagado_premio1.is_(True),
            Boleta.pagado_premio2.is_(True),
            Boleta.pagado_premio3.is_(True),
            Boleta.pagado_premio4.is_(True),
        )

    pagina = query.order_by(Boleta.fecha.desc()).paginate(
        page=page, per_page=BOLETAS_POR_PAGINA, error_out=False
    )
    return render_template("boletas.html", boletas=pagina.items, pagina=pagina, q=q, pago=pago)


@bp.route("/clientes")
@login_required
def clientes():
    q = request.args.get("q", "").strip()
    page = request.args.get("page", 1, type=int)

    query = Boleta.query.join(Cliente).filter(Boleta.anulada.is_(False))
    if not current_user.is_admin:
        query = query.filter(Boleta.vendedor_id == current_user.id)
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                Cliente.nombre.ilike(like),
                Cliente.documento.ilike(like),
                Cliente.telefono.ilike(like),
            )
        )

    boletas_encontradas = query.order_by(Boleta.fecha.desc()).all()
    clientes_lista = sorted(
        _agrupar_clientes(boletas_encontradas).values(),
        key=lambda c: c["ultima_fecha"],
        reverse=True,
    )

    total = len(clientes_lista)
    total_paginas = max(1, (total + CLIENTES_POR_PAGINA - 1) // CLIENTES_POR_PAGINA)
    page = max(1, min(page, total_paginas))
    inicio = (page - 1) * CLIENTES_POR_PAGINA

    return render_template(
        "clientes.html",
        clientes=clientes_lista[inicio : inicio + CLIENTES_POR_PAGINA],
        q=q,
        page=page,
        total_paginas=total_paginas,
        total_clientes=total,
    )


@bp.route("/admin/clientes/fusionar", methods=["POST"])
@login_required
@admin_required
def admin_fusionar_clientes():
    documento_conservar = request.form.get("documento_conservar", "").strip()
    documento_fusionar = request.form.get("documento_fusionar", "").strip()

    if not documento_conservar or not documento_fusionar:
        flash("Debes indicar las dos cédulas.", "error")
    elif documento_conservar == documento_fusionar:
        flash("Las dos cédulas deben ser diferentes.", "error")
    else:
        conservar = Cliente.query.get(documento_conservar)
        fusionar = Cliente.query.get(documento_fusionar)
        if not conservar or not fusionar:
            flash("No se encontró alguna de las dos cédulas.", "error")
        else:
            boletas_movidas = Boleta.query.filter_by(cliente_documento=documento_fusionar).update(
                {"cliente_documento": documento_conservar}
            )
            db.session.delete(fusionar)
            db.session.commit()
            logger.info(
                "Cliente %s fusionado dentro de %s por %s (%s boletas movidas)",
                documento_fusionar, documento_conservar, current_user.username, boletas_movidas,
            )
            flash(
                f"Se fusionó la cédula {documento_fusionar} dentro de {documento_conservar} "
                f"({boletas_movidas} boleta(s) movida(s)).",
                "success",
            )

    return redirect(url_for("main.clientes"))


@bp.route("/clientes/<documento>")
@login_required
def cliente_detalle(documento):
    query = Boleta.query.filter_by(cliente_documento=documento, anulada=False)
    if not current_user.is_admin:
        query = query.filter_by(vendedor_id=current_user.id)

    boletas_cliente = query.order_by(Boleta.fecha.desc()).all()
    if not boletas_cliente:
        flash("No se encontró ningún cliente con ese documento.", "error")
        return redirect(url_for("main.clientes"))

    resumen = _agrupar_clientes(boletas_cliente)[documento]
    return render_template("cliente_detalle.html", resumen=resumen, boletas=boletas_cliente)


@bp.route("/boletas/<int:boleta_id>")
@login_required
def boleta_detalle(boleta_id):
    boleta = Boleta.query.get_or_404(boleta_id)
    if not current_user.is_admin and boleta.vendedor_id != current_user.id:
        flash("No tienes permiso para ver esa boleta.", "error")
        return redirect(url_for("main.boletas"))
    return render_template("boleta_detalle.html", boleta=boleta)


@bp.route("/boletas/<int:boleta_id>/editar", methods=["GET", "POST"])
@login_required
def boleta_editar(boleta_id):
    boleta = Boleta.query.get_or_404(boleta_id)
    if not current_user.is_admin and boleta.vendedor_id != current_user.id:
        flash("No tienes permiso para editar esa boleta.", "error")
        return redirect(url_for("main.boletas"))

    if request.method == "POST":
        nombre_cliente = request.form.get("nombre_cliente", "").strip()
        telefono = request.form.get("telefono", "").strip()
        direccion = request.form.get("direccion", "").strip()
        email = request.form.get("email", "").strip()

        errores = []
        if not nombre_cliente:
            errores.append("El nombre del cliente es obligatorio.")
        if not telefono:
            errores.append("El teléfono es obligatorio.")
        if email and not EMAIL_RE.match(email):
            errores.append("El correo electrónico no tiene un formato válido.")

        if not errores:
            boleta.cliente.nombre = nombre_cliente
            boleta.cliente.telefono = telefono
            boleta.cliente.direccion = direccion or None
            boleta.cliente.email = email or None
            db.session.commit()
            logger.info("Datos del cliente %s editados por %s", boleta.cliente_documento, current_user.username)
            flash("Datos actualizados correctamente.", "success")
            return redirect(url_for("main.boleta_detalle", boleta_id=boleta.id))

        for e in errores:
            flash(e, "error")
        return render_template("boleta_editar.html", boleta=boleta, form=request.form)

    return render_template("boleta_editar.html", boleta=boleta, form={})


@bp.route("/boletas/<int:boleta_id>/pago", methods=["POST"])
@login_required
def boleta_pago(boleta_id):
    boleta = Boleta.query.get_or_404(boleta_id)
    if not current_user.is_admin and boleta.vendedor_id != current_user.id:
        flash("No tienes permiso para modificar el pago de esa boleta.", "error")
        return redirect(url_for("main.boletas"))
    if boleta.anulada:
        flash("Esta boleta está anulada; no se puede modificar su pago.", "error")
        return redirect(url_for("main.boleta_detalle", boleta_id=boleta.id))

    for premio in (1, 2, 3, 4):
        nuevo_valor = bool(request.form.get(f"pagado_premio{premio}"))
        valor_anterior = getattr(boleta, f"pagado_premio{premio}")
        if nuevo_valor != valor_anterior:
            db.session.add(
                HistorialPago(
                    boleta_id=boleta.id,
                    numero_premio=premio,
                    marcado=nuevo_valor,
                    vendedor_id=current_user.id,
                )
            )
            setattr(boleta, f"pagado_premio{premio}", nuevo_valor)

    db.session.commit()
    logger.info(
        "Pago actualizado en boleta #%s por %s: %s/4 premios ($%s)",
        boleta.id, current_user.username, boleta.premios_pagados, boleta.monto_pagado,
    )
    flash("Pago actualizado.", "success")
    return redirect(url_for("main.boleta_detalle", boleta_id=boleta.id))


@bp.route("/boletas/<int:boleta_id>/anular", methods=["POST"])
@login_required
def boleta_anular(boleta_id):
    boleta = Boleta.query.get_or_404(boleta_id)
    if not current_user.is_admin and boleta.vendedor_id != current_user.id:
        flash("No tienes permiso para anular esa boleta.", "error")
        return redirect(url_for("main.boletas"))
    if boleta.anulada:
        flash("Esa boleta ya estaba anulada.", "error")
        return redirect(url_for("main.boleta_detalle", boleta_id=boleta.id))

    numeros = sorted(n.numero for n in boleta.numeros)
    for numero_asignado in list(boleta.numeros):
        db.session.delete(numero_asignado)

    boleta.anulada = True
    boleta.fecha_anulacion = datetime.utcnow()
    boleta.anulada_por_id = current_user.id
    boleta.numeros_anulados = ", ".join(numeros)
    db.session.commit()

    logger.info(
        "Boleta #%s anulada por %s (números liberados: %s)",
        boleta.id, current_user.username, ", ".join(numeros),
    )
    flash(f"Boleta #{boleta.id} anulada. Los números {', '.join(numeros)} vuelven a estar libres.", "success")
    return redirect(url_for("main.boleta_detalle", boleta_id=boleta.id))


@bp.route("/admin/vendedores", methods=["GET", "POST"])
@login_required
@admin_required
def admin_vendedores():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        nombre = request.form.get("nombre", "").strip()
        telefono = request.form.get("telefono", "").strip()
        password = request.form.get("password", "")
        es_admin = bool(request.form.get("is_admin"))

        if not username or not nombre or not password:
            flash("Usuario, nombre y contraseña son obligatorios.", "error")
        else:
            v = Vendedor(username=username, nombre=nombre, telefono=telefono or None, is_admin=es_admin)
            v.set_password(password)
            db.session.add(v)
            try:
                db.session.commit()
                logger.info("Vendedor '%s' creado por %s", username, current_user.username)
                flash(f"Vendedor '{username}' creado correctamente.", "success")
            except IntegrityError:
                db.session.rollback()
                flash("Ese nombre de usuario ya existe.", "error")

        return redirect(url_for("main.admin_vendedores"))

    vendedores = Vendedor.query.order_by(Vendedor.fecha_creacion.desc()).all()
    return render_template("admin_vendedores.html", vendedores=vendedores)


@bp.route("/admin/vendedores/<int:vendedor_id>/editar", methods=["GET", "POST"])
@login_required
@admin_required
def admin_editar_vendedor(vendedor_id):
    v = Vendedor.query.get_or_404(vendedor_id)

    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        telefono = request.form.get("telefono", "").strip()

        if not nombre:
            flash("El nombre es obligatorio.", "error")
        else:
            v.nombre = nombre
            v.telefono = telefono or None
            db.session.commit()
            logger.info("Vendedor '%s' editado por %s", v.username, current_user.username)
            flash("Vendedor actualizado correctamente.", "success")
            return redirect(url_for("main.admin_vendedores"))

    return render_template("admin_editar_vendedor.html", vendedor=v)


@bp.route("/admin/vendedores/<int:vendedor_id>/toggle", methods=["POST"])
@login_required
@admin_required
def admin_toggle_vendedor(vendedor_id):
    v = Vendedor.query.get_or_404(vendedor_id)
    if v.id == current_user.id:
        flash("No puedes desactivarte a ti mismo.", "error")
    else:
        v.activo = not v.activo
        db.session.commit()
        logger.info(
            "Vendedor '%s' %s por %s",
            v.username, "activado" if v.activo else "desactivado", current_user.username,
        )
        flash(f"Vendedor '{v.username}' {'activado' if v.activo else 'desactivado'}.", "success")
    return redirect(url_for("main.admin_vendedores"))


@bp.route("/admin/vendedores/<int:vendedor_id>/eliminar", methods=["POST"])
@login_required
@admin_required
def admin_eliminar_vendedor(vendedor_id):
    v = Vendedor.query.get_or_404(vendedor_id)

    if v.id == current_user.id:
        flash("No puedes eliminarte a ti mismo.", "error")
    elif Boleta.query.filter_by(vendedor_id=v.id).count() > 0:
        flash(
            f"No puedes eliminar a '{v.username}': tiene boletas registradas. "
            "Desactívalo en su lugar para conservar el historial de ventas.",
            "error",
        )
    else:
        username = v.username
        db.session.delete(v)
        db.session.commit()
        logger.info("Vendedor '%s' eliminado por %s", username, current_user.username)
        flash(f"Vendedor '{username}' eliminado.", "success")

    return redirect(url_for("main.admin_vendedores"))


@bp.route("/admin/vendedores/<int:vendedor_id>/historial")
@login_required
@admin_required
def admin_vendedor_historial(vendedor_id):
    vendedor = Vendedor.query.get_or_404(vendedor_id)
    page = request.args.get("page", 1, type=int)

    base_query = Boleta.query.filter_by(vendedor_id=vendedor.id, anulada=False)
    pagina = base_query.order_by(Boleta.fecha.desc()).paginate(
        page=page, per_page=BOLETAS_POR_PAGINA, error_out=False
    )
    total_boletas = base_query.count()
    primera = base_query.order_by(Boleta.fecha.asc()).first()
    ultima = base_query.order_by(Boleta.fecha.desc()).first()

    return render_template(
        "vendedor_historial.html",
        vendedor=vendedor,
        boletas=pagina.items,
        pagina=pagina,
        total_boletas=total_boletas,
        total_numeros=total_boletas * 3,
        primera_fecha=primera.fecha if primera else None,
        ultima_fecha=ultima.fecha if ultima else None,
    )


@bp.route("/admin/sorteo", methods=["GET", "POST"])
@login_required
@admin_required
def admin_sorteo():
    if request.method == "POST":
        numero = request.form.get("numero", "").strip()
        numero_premio = request.form.get("numero_premio", "").strip()
        etiqueta = request.form.get("etiqueta", "").strip()

        if not NUMERO_RE.match(numero):
            flash("El número ganador debe tener 4 cifras (0000-9999).", "error")
        elif numero_premio not in ("1", "2", "3", "4"):
            flash("Debes indicar a cuál de los 4 premios corresponde este sorteo.", "error")
        else:
            sorteo = Sorteo(
                numero=numero,
                numero_premio=int(numero_premio),
                etiqueta=etiqueta or None,
                registrado_por_id=current_user.id,
            )
            db.session.add(sorteo)
            db.session.commit()
            logger.info(
                "Sorteo registrado: número %s, premio %s (%s) por %s",
                numero, numero_premio, etiqueta, current_user.username,
            )
            flash(f"Número ganador {numero} registrado para el premio {numero_premio}.", "success")

        return redirect(url_for("main.admin_sorteo"))

    sorteos = Sorteo.query.order_by(Sorteo.fecha.desc()).all()
    resultados = []
    for s in sorteos:
        asignado = NumeroAsignado.query.get(s.numero)
        boleta = asignado.boleta if asignado else None
        pago_al_dia = bool(boleta) and getattr(boleta, f"pagado_premio{s.numero_premio}")
        resultados.append({"sorteo": s, "boleta": boleta, "pago_al_dia": pago_al_dia})

    config = ConfiguracionRifa.obtener()
    return render_template("admin_sorteo.html", resultados=resultados, config=config)


@bp.route("/admin/sorteo/fechas", methods=["POST"])
@login_required
@admin_required
def admin_configurar_fechas_sorteo():
    config = ConfiguracionRifa.obtener()

    for premio in (1, 2, 3, 4):
        fecha_str = request.form.get(f"fecha_premio{premio}", "").strip()
        if fecha_str:
            try:
                setattr(config, f"fecha_premio{premio}", datetime.fromisoformat(fecha_str))
            except ValueError:
                flash(f"La fecha del premio {premio} no tiene un formato válido.", "error")
                return redirect(url_for("main.admin_sorteo"))
        else:
            setattr(config, f"fecha_premio{premio}", None)

    db.session.commit()
    logger.info("Fechas de sorteo actualizadas por %s", current_user.username)
    flash("Fechas de sorteo actualizadas.", "success")
    return redirect(url_for("main.admin_sorteo"))


@bp.route("/pantalla")
def pantalla_selector():
    config = ConfiguracionRifa.obtener()
    return render_template("pantalla_selector.html", config=config)


@bp.route("/pantalla/<int:numero_premio>")
def pantalla_en_vivo(numero_premio):
    if numero_premio not in (1, 2, 3, 4):
        flash("Ese premio no existe.", "error")
        return redirect(url_for("main.pantalla_selector"))

    config = ConfiguracionRifa.obtener()
    return render_template(
        "pantalla.html",
        numero_premio=numero_premio,
        fecha_premio=config.fecha_premio(numero_premio),
    )


@bp.route("/api/ultimo-sorteo")
@limiter.limit("60 per minute")
def api_ultimo_sorteo():
    query = Sorteo.query
    numero_premio = request.args.get("premio", type=int)
    if numero_premio:
        query = query.filter_by(numero_premio=numero_premio)

    sorteo = query.order_by(Sorteo.fecha.desc(), Sorteo.id.desc()).first()
    if sorteo is None:
        return jsonify({"hay_sorteo": False})

    return jsonify(
        {
            "hay_sorteo": True,
            "id": sorteo.id,
            "numero": sorteo.numero,
            "numero_premio": sorteo.numero_premio,
            "etiqueta": sorteo.etiqueta,
            "fecha": sorteo.fecha.isoformat(),
        }
    )


@bp.route("/como-funciona")
def como_funciona():
    return render_template(
        "como_funciona.html",
        precio_total=Boleta.PRECIO_TOTAL,
        precio_premio=Boleta.PRECIO_POR_PREMIO,
        total_numeros=TOTAL_NUMEROS,
    )


@bp.route("/consulta", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def consulta_publica():
    documento = ""
    boletas_encontradas = []
    buscado = False

    if request.method == "POST":
        documento = request.form.get("documento", "").strip()
        buscado = True
        if documento:
            boletas_encontradas = (
                Boleta.query.filter_by(cliente_documento=documento, anulada=False)
                .order_by(Boleta.fecha.desc())
                .all()
            )

    config = ConfiguracionRifa.obtener()
    ultimos_sorteos = _ultimo_sorteo_por_premio()
    resultados_por_boleta = {
        b.id: _resultado_premios(b, ultimos_sorteos, config) for b in boletas_encontradas
    }

    numeros_asignados = NumeroAsignado.query.count()

    return render_template(
        "consulta.html",
        documento=documento,
        boletas=boletas_encontradas,
        resultados_por_boleta=resultados_por_boleta,
        buscado=buscado,
        numeros_asignados=numeros_asignados,
        numeros_libres=TOTAL_NUMEROS - numeros_asignados,
        total_numeros=TOTAL_NUMEROS,
        sorteos_publicos=Sorteo.query.order_by(Sorteo.fecha.desc()).all(),
        config=config,
    )


@bp.route("/admin/exportar.csv")
@login_required
@admin_required
def admin_exportar_csv():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "Boleta", "Cliente", "Documento", "Telefono", "Direccion", "Email", "Numeros",
            "Vendedor", "Fecha", "Premios Pagados (de 4)", "Monto Pagado", "Monto Total", "Anulada",
        ]
    )
    for b in Boleta.query.order_by(Boleta.id).all():
        writer.writerow(
            [
                b.id,
                _csv_safe(b.cliente.nombre),
                _csv_safe(b.cliente.documento),
                _csv_safe(b.cliente.telefono),
                _csv_safe(b.cliente.direccion or ""),
                _csv_safe(b.cliente.email or ""),
                ", ".join(n.numero for n in b.numeros) or _csv_safe(b.numeros_anulados or ""),
                b.vendedor.username,
                b.fecha.strftime("%Y-%m-%d %H:%M"),
                b.premios_pagados,
                b.monto_pagado,
                Boleta.PRECIO_TOTAL,
                "Sí" if b.anulada else "No",
            ]
        )

    logger.info("Exportación CSV solicitada por %s", current_user.username)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=boletas_rifa.csv"},
    )
