function verificarNumero(input) {
  var estadoEl = document.getElementById('estado-' + input.id);
  if (!estadoEl) return;

  if (input.value.length !== 4) {
    estadoEl.textContent = '';
    estadoEl.className = 'numero-estado';
    return;
  }

  estadoEl.textContent = 'Verificando...';
  estadoEl.className = 'numero-estado estado-verificando';

  fetch('/api/numero/' + input.value)
    .then(function (r) { return r.json(); })
    .then(function (data) {
      if (!data.valido) {
        estadoEl.textContent = data.mensaje;
        estadoEl.className = 'numero-estado estado-invalido';
        return;
      }
      if (data.libre) {
        estadoEl.textContent = 'Libre ✓';
        estadoEl.className = 'numero-estado estado-libre';
      } else {
        estadoEl.textContent = 'Ocupado ✗ (elige otro)';
        estadoEl.className = 'numero-estado estado-ocupado';
      }
    })
    .catch(function () {
      estadoEl.textContent = 'No se pudo verificar. Intenta de nuevo.';
      estadoEl.className = 'numero-estado estado-invalido';
    });
}

function buscarCliente(documentoInput, infoEl) {
  var documento = documentoInput.value.trim();
  if (!documento) {
    infoEl.hidden = true;
    return;
  }

  fetch('/api/cliente/' + encodeURIComponent(documento))
    .then(function (r) { return r.json(); })
    .then(function (data) {
      if (!data.encontrado) {
        infoEl.hidden = true;
        return;
      }
      infoEl.dataset.nombre = data.nombre_cliente;
      infoEl.dataset.telefono = data.telefono;
      infoEl.dataset.direccion = data.direccion;
      infoEl.dataset.email = data.email;

      var texto = infoEl.querySelector('.cliente-info-texto');
      var boletasTxt = data.total_boletas === 1 ? '1 boleta anterior' : data.total_boletas + ' boletas anteriores';
      texto.textContent = 'Cliente ya registrado: ' + data.nombre_cliente + ' — ' + boletasTxt + '.';
      infoEl.hidden = false;
    })
    .catch(function () {
      infoEl.hidden = true;
    });
}

function inicializarBusquedaCliente() {
  var documentoInput = document.getElementById('documento');
  var infoEl = document.getElementById('cliente-info');
  if (!documentoInput || !infoEl) return;

  var timeoutId;
  documentoInput.addEventListener('input', function () {
    clearTimeout(timeoutId);
    timeoutId = setTimeout(function () { buscarCliente(documentoInput, infoEl); }, 400);
  });

  var btnUsar = infoEl.querySelector('.btn-usar-datos');
  if (btnUsar) {
    btnUsar.addEventListener('click', function () {
      document.getElementById('nombre_cliente').value = infoEl.dataset.nombre || '';
      document.getElementById('telefono').value = infoEl.dataset.telefono || '';
      document.getElementById('direccion').value = infoEl.dataset.direccion || '';
      document.getElementById('email').value = infoEl.dataset.email || '';
    });
  }
}

function inicializarMenuMovil() {
  var boton = document.getElementById('menu-toggle');
  var menu = document.getElementById('menu-principal');
  if (!boton || !menu) return;

  function cerrar() {
    menu.classList.remove('abierto');
    boton.classList.remove('abierto');
    boton.setAttribute('aria-expanded', 'false');
    boton.setAttribute('aria-label', 'Abrir menú');
  }

  function alternar() {
    var abierto = menu.classList.toggle('abierto');
    boton.classList.toggle('abierto', abierto);
    boton.setAttribute('aria-expanded', abierto ? 'true' : 'false');
    boton.setAttribute('aria-label', abierto ? 'Cerrar menú' : 'Abrir menú');
  }

  boton.addEventListener('click', function (e) {
    e.stopPropagation();
    alternar();
  });

  menu.querySelectorAll('a').forEach(function (enlace) {
    enlace.addEventListener('click', cerrar);
  });

  document.addEventListener('click', function (e) {
    if (!menu.classList.contains('abierto')) return;
    if (menu.contains(e.target) || boton.contains(e.target)) return;
    cerrar();
  });

  window.addEventListener('resize', function () {
    if (window.innerWidth > 768) cerrar();
  });
}

function formatearTiempoRestante(diff) {
  var dias = Math.floor(diff / 86400000);
  var horas = Math.floor((diff / 3600000) % 24);
  var minutos = Math.floor((diff / 60000) % 60);

  var partes = [];
  if (dias > 0) partes.push(dias + (dias === 1 ? ' día' : ' días'));
  partes.push(horas + 'h');
  partes.push(minutos + 'm');
  return partes.join(' ');
}

function inicializarCuentasRegresivas() {
  var elementos = document.querySelectorAll('.cuenta-regresiva[data-fecha]');
  if (!elementos.length) return;

  function actualizarTodas() {
    elementos.forEach(function (el) {
      var fecha = new Date(el.dataset.fecha);
      var tipo = el.dataset.tipo || 'sorteo';
      var diff = fecha - new Date();

      if (diff <= 0) {
        el.textContent = tipo === 'plazo'
          ? 'Ya venció el plazo para pagar este premio'
          : '¡El sorteo ya se realizó o está por comenzar!';
        return;
      }

      var restante = formatearTiempoRestante(diff);
      el.textContent = tipo === 'plazo'
        ? 'Faltan ' + restante + ' para pagar este premio'
        : 'Faltan ' + restante;
    });
  }

  actualizarTodas();
  setInterval(actualizarTodas, 60000);
}

function inicializarPantallaEnVivo() {
  var contenedor = document.getElementById('pantalla-live');
  if (!contenedor) return;

  var estadoEl = document.getElementById('pantalla-estado');
  var cuentaEl = document.getElementById('pantalla-cuenta');
  var premioEl = document.getElementById('pantalla-premio');
  var numeroEl = document.getElementById('pantalla-numero');
  var etiquetaEl = document.getElementById('pantalla-etiqueta');

  var diasEl = document.getElementById('cuenta-dias');
  var horasEl = document.getElementById('cuenta-horas');
  var minEl = document.getElementById('cuenta-min');
  var segEl = document.getElementById('cuenta-seg');

  var numeroPremio = contenedor.dataset.numeroPremio;
  var fechaStr = contenedor.dataset.fechaPremio;
  var fechaPremio = fechaStr ? new Date(fechaStr) : null;
  var revelado = false;

  function dosDigitos(n) {
    return n < 10 ? '0' + n : '' + n;
  }

  function actualizarCuenta() {
    if (revelado || !fechaPremio) return;
    var diff = fechaPremio - new Date();

    if (diff <= 0) {
      estadoEl.textContent = 'Esperando el resultado del Premio ' + numeroPremio + '...';
      diasEl.textContent = horasEl.textContent = minEl.textContent = segEl.textContent = '00';
      return;
    }

    var dias = Math.floor(diff / 86400000);
    var horas = Math.floor((diff / 3600000) % 24);
    var minutos = Math.floor((diff / 60000) % 60);
    var segundos = Math.floor((diff / 1000) % 60);

    diasEl.textContent = dosDigitos(dias);
    horasEl.textContent = dosDigitos(horas);
    minEl.textContent = dosDigitos(minutos);
    segEl.textContent = dosDigitos(segundos);
  }

  function revelarGanador(data) {
    revelado = true;
    cuentaEl.hidden = true;
    premioEl.hidden = false;
    numeroEl.hidden = false;
    estadoEl.textContent = '¡Número ganador del Premio ' + numeroPremio + '!';
    premioEl.textContent = data.etiqueta || ('Premio ' + numeroPremio);
    etiquetaEl.textContent = new Date(data.fecha).toLocaleString('es-CO');
    numeroEl.textContent = data.numero;
    numeroEl.classList.add('revelando');
  }

  function consultarResultado() {
    fetch('/api/ultimo-sorteo?premio=' + numeroPremio)
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.hay_sorteo && !revelado) {
          revelarGanador(data);
        }
      })
      .catch(function () {});
  }

  if (fechaPremio) {
    actualizarCuenta();
    setInterval(actualizarCuenta, 1000);
  } else {
    estadoEl.textContent = 'Esperando el resultado del Premio ' + numeroPremio + '...';
    cuentaEl.hidden = true;
  }

  consultarResultado();
  setInterval(consultarResultado, 5000);
}

function confirmarPersonalizado(mensaje, tipo) {
  return new Promise(function (resolve) {
    var overlay = document.getElementById('modal-confirmacion');
    var caja = document.getElementById('modal-box');
    var mensajeEl = document.getElementById('modal-mensaje');
    var iconoEl = document.getElementById('modal-icono');
    var btnAceptar = document.getElementById('modal-aceptar');
    var btnCancelar = document.getElementById('modal-cancelar');

    if (!overlay) {
      resolve(window.confirm(mensaje));
      return;
    }

    var esPeligro = tipo === 'peligro';
    mensajeEl.textContent = mensaje;
    iconoEl.textContent = esPeligro ? '⚠️' : '❓';
    caja.classList.toggle('modal-peligro', esPeligro);
    btnAceptar.className = 'btn ' + (esPeligro ? 'btn-danger' : 'btn-primary');

    overlay.hidden = false;
    document.body.classList.add('modal-abierto');
    btnAceptar.focus();

    function cerrar(resultado) {
      overlay.hidden = true;
      document.body.classList.remove('modal-abierto');
      btnAceptar.removeEventListener('click', alAceptar);
      btnCancelar.removeEventListener('click', alCancelar);
      overlay.removeEventListener('click', alHacerClicFuera);
      document.removeEventListener('keydown', alPresionarTecla);
      resolve(resultado);
    }
    function alAceptar() { cerrar(true); }
    function alCancelar() { cerrar(false); }
    function alHacerClicFuera(e) { if (e.target === overlay) cerrar(false); }
    function alPresionarTecla(e) { if (e.key === 'Escape') cerrar(false); }

    btnAceptar.addEventListener('click', alAceptar);
    btnCancelar.addEventListener('click', alCancelar);
    overlay.addEventListener('click', alHacerClicFuera);
    document.addEventListener('keydown', alPresionarTecla);
  });
}

function inicializarConfirmaciones() {
  document.querySelectorAll('form[data-confirmar]').forEach(function (form) {
    form.addEventListener('submit', function (e) {
      if (form.dataset.confirmado === 'si') return;
      e.preventDefault();
      confirmarPersonalizado(form.dataset.confirmar, form.dataset.confirmarTipo).then(function (aceptado) {
        if (!aceptado) return;
        form.dataset.confirmado = 'si';
        if (form.requestSubmit) {
          form.requestSubmit();
        } else {
          form.submit();
        }
      });
    });
  });
}

function inicializarBannerInstalar() {
  var banner = document.getElementById('instalar-banner');
  if (!banner) return;

  var CLAVE_DESCARTADO = 'rifa-banner-instalar-oculto';
  var yaDescartado = localStorage.getItem(CLAVE_DESCARTADO) === 'si';
  var enStandalone = window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;
  var esMovil = window.matchMedia('(max-width: 820px)').matches;

  if (yaDescartado || enStandalone || !esMovil) return;

  var esIOS = /iphone|ipad|ipod/i.test(navigator.userAgent);
  var textoEl = document.getElementById('instalar-banner-texto');
  textoEl.textContent = esIOS
    ? 'Consejo: toca el botón compartir de Safari y elige "Agregar a pantalla de inicio" para usar la app sin la barra del navegador.'
    : 'Consejo: abre el menú del navegador y elige "Agregar a pantalla de inicio" (o "Instalar app") para usar la app sin la barra del navegador.';

  banner.hidden = false;

  document.getElementById('instalar-banner-cerrar').addEventListener('click', function () {
    banner.hidden = true;
    localStorage.setItem(CLAVE_DESCARTADO, 'si');
  });
}

inicializarMenuMovil();
inicializarConfirmaciones();
inicializarBannerInstalar();
