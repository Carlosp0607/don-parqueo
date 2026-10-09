/* ============================================================
   public/js/menu.js
   Menu lateral unico de Don Parqueo.
   Reescribe el sidebar de la pagina donde se cargue.
   Para cambiar el menu del sistema entero, se edita SOLO este archivo.

   Tambien maneja el cierre de sesion, la expiracion del token y el
   modo demostracion (rol invitado).

   Uso: agregar antes de </body> en cada pagina del panel:
     <script src="../js/menu.js"></script>
   ============================================================ */
(function () {
  'use strict';

  var ITEMS = [
    { href: 'dashboard.html',     icono: 'fa-house',           texto: 'Inicio' },
    { href: 'vehiculos.html',     icono: 'fa-car',             texto: 'Vehículos' },
    { href: 'mensualidades.html', icono: 'fa-calendar-check',  texto: 'Planes' },
    { href: 'tarifas.html',       icono: 'fa-money-bill-wave', texto: 'Tarifas',       admin: true },
    { href: 'reportes.html',      icono: 'fa-chart-bar',       texto: 'Reportes',      admin: true },
    { href: 'usuarios.html',      icono: 'fa-users',           texto: 'Usuarios',      admin: true },
    { href: 'configuracion.html', icono: 'fa-gear',            texto: 'Configuración', admin: true }
  ];

  // Paginas retiradas del menu que redirigen a su reemplazo.
  var REDIRECCIONES = {
    'operacion.html': 'vehiculos.html',
    'ingreso-salida.html': 'vehiculos.html',
    'tipos-vehiculos.html': 'tarifas.html'
  };

  var RUTA_LOGOUT = '/api/auth/logout';

  // Claves de sesion. Las preferencias del equipo (ps_ultimo_nit,
  // savedUsername, savedEmpresa) NO se borran: se conservan para que el
  // operador no tenga que volver a escribir el NIT cada vez.
  var CLAVES_SESION = [
    'token', 'ps_token', 'usuario', 'user', 'userRole', 'userName',
    'empresaId', 'empresaNit', 'gfLoginDay', 'gfDismissedDay'
  ];

  function limpiarSesion() {
    CLAVES_SESION.forEach(function (k) {
      try { localStorage.removeItem(k); } catch (e) {}
    });
  }

  // ---------------------------------------------------------------------
  // Rol actual
  // ---------------------------------------------------------------------
  function rolActual() {
    try {
      var rol = String(localStorage.getItem('userRole') || '').toLowerCase();
      if (rol) return rol;

      var raw = localStorage.getItem('usuario') || localStorage.getItem('user');
      var user = raw ? JSON.parse(raw) : null;
      return user ? String(user.rol || user.role || '').toLowerCase() : '';
    } catch (e) {
      return '';
    }
  }

  function esInvitado() {
    return rolActual() === 'invitado';
  }

  // ---------------------------------------------------------------------
  // Sesion vencida
  //
  // Si el token muere mientras el operador esta trabajando, cualquier llamada
  // a la API responde 401. Antes cada pagina mandaba al login SIN limpiar el
  // localStorage, y el login veia el token guardado y devolvia al panel: la
  // pantalla se recargaba sola para siempre y el operador quedaba trabado.
  //
  // Aqui se limpia primero y se redirige despues, una sola vez. El login ya
  // no encuentra token, asi que muestra el formulario y el ciclo se corta.
  // ---------------------------------------------------------------------
  var yaRedirigiendo = false;

  function sesionVencida() {
    if (yaRedirigiendo) return;
    yaRedirigiendo = true;
    limpiarSesion();
    window.location.replace('/?expirada=1');
  }

  // Aviso flotante para el modo demostracion. No usa Bootstrap toast para no
  // depender de que la pagina lo tenga inicializado.
  var avisoVisible = false;

  function avisarSoloLectura() {
    if (avisoVisible) return;
    avisoVisible = true;

    var caja = document.createElement('div');
    caja.textContent = 'Modo demostración: solo lectura. Esta acción no se guarda.';
    caja.style.cssText =
      'position:fixed;left:50%;bottom:24px;transform:translateX(-50%);' +
      'background:#212529;color:#fff;padding:12px 20px;border-radius:6px;' +
      'font-size:.9rem;z-index:9999;box-shadow:0 4px 14px rgba(0,0,0,.3);' +
      'max-width:90vw;text-align:center;';
    document.body.appendChild(caja);

    setTimeout(function () {
      if (caja.parentNode) caja.parentNode.removeChild(caja);
      avisoVisible = false;
    }, 3000);
  }

  // Envuelve fetch para detectar el 401 en TODA la aplicacion sin tener que
  // tocar cada pagina. Solo actua sobre llamadas a /api/: si el propio login
  // responde 401 (usuario o clave mala) no se toca, porque ahi el mensaje de
  // error lo maneja el formulario.
  //
  // FIX modo demostracion: el 403 del invitado NO es sesion vencida. Es el
  // bloqueo de escritura de src/middleware/auth.js. Si se tratara como
  // vencimiento, el invitado saldria al login apenas tocara cualquier boton.
  function interceptarFetch() {
    if (window.__fetchInterceptado) return;
    window.__fetchInterceptado = true;

    var fetchOriginal = window.fetch;
    window.fetch = function () {
      var args = arguments;
      var url = '';
      try {
        url = typeof args[0] === 'string' ? args[0] : (args[0] && args[0].url) || '';
      } catch (e) {}

      return fetchOriginal.apply(this, args).then(function (res) {
        var esApi = url.indexOf('/api/') !== -1;
        var esLogin = url.indexOf('/api/auth/login') !== -1;

        if (!esApi || esLogin) return res;

        if (res.status === 403 && esInvitado()) {
          avisarSoloLectura();
          return res;
        }

        if (res.status === 401 || res.status === 403) {
          sesionVencida();
        }
        return res;
      });
    };
  }

  function paginaActual() {
    return (window.location.pathname.split('/').pop() || 'dashboard.html').toLowerCase();
  }

  function htmlSidebar() {
    var actual = paginaActual();
    var destino = REDIRECCIONES[actual] || actual;

    var li = ITEMS.map(function (it) {
      var activa = (it.href.toLowerCase() === destino) ? ' active' : '';
      var clase  = it.admin ? 'nav-item admin-only' : 'nav-item';
      return '<li class="' + clase + '">' +
               '<a href="' + it.href + '" class="nav-link' + activa + '">' +
                 '<i class="fas ' + it.icono + '"></i><span>' + it.texto + '</span>' +
               '</a>' +
             '</li>';
    }).join('');

    return '' +
      '<div class="sidebar-header">' +
        '<div class="logo-container">' +
          '<div class="logo-circle"><span class="logo-text">PS</span></div>' +
        '</div>' +
        '<h5 class="mt-3 text-white">Don Parqueo</h5>' +
      '</div>' +
      '<nav class="sidebar-nav"><ul class="nav flex-column">' + li + '</ul></nav>' +
      '<div class="sidebar-footer">' +
        '<a href="#" class="nav-link" id="btnLogout">' +
          '<i class="fas fa-sign-out-alt"></i><span>Cerrar Sesión</span>' +
        '</a>' +
      '</div>';
  }

  function salir() {
    // Se marca antes de llamar al servidor: el logout devuelve la cookie
    // borrada y no queremos que el interceptor lo lea como sesion vencida.
    yaRedirigiendo = true;

    var headers = { 'Content-Type': 'application/json' };
    var tok = localStorage.getItem('token') || localStorage.getItem('ps_token');
    if (tok) headers['Authorization'] = 'Bearer ' + tok;

    fetch(RUTA_LOGOUT, {
      method: 'POST',
      headers: headers,
      credentials: 'include',
      body: '{}'
    })
    .catch(function () { /* la cookie igual se descarta al salir */ })
    .then(function () {
      limpiarSesion();
      window.location.href = '/';
    });
  }

  // ---------------------------------------------------------------------
  // Modo demostracion
  //
  // Banner fijo arriba y ocultado de los controles de escritura. El bloqueo
  // real vive en el backend (src/middleware/auth.js); esto es solo para que
  // el invitado no vea botones que le van a devolver un error.
  //
  // Los botones se detectan por su texto porque las vistas no traen marcas.
  // Si mas adelante se les agrega data-accion="escritura", ese selector tiene
  // prioridad y esta busqueda por texto deja de hacer falta.
  // ---------------------------------------------------------------------
  var VERBOS_ESCRITURA = [
    'registrar', 'nuevo', 'nueva', 'agregar', 'añadir', 'crear',
    'editar', 'eliminar', 'borrar', 'guardar', 'actualizar',
    'abrir turno', 'cerrar turno', 'ingreso', 'salida', 'subir'
  ];

  function montarBanner() {
    if (document.getElementById('bannerDemo')) return;

    var banner = document.createElement('div');
    banner.id = 'bannerDemo';
    banner.textContent = 'MODO DEMOSTRACIÓN — Datos de prueba. Solo lectura.';
    banner.style.cssText =
      'position:sticky;top:0;z-index:1050;background:#b8530a;color:#fff;' +
      'text-align:center;padding:8px 12px;font-size:.78rem;' +
      'letter-spacing:.08em;text-transform:uppercase;font-weight:500;';
    document.body.insertBefore(banner, document.body.firstChild);
  }

  function esControlDeEscritura(el) {
    if (el.closest('.sidebar')) return false;
    if (el.id === 'btnLogout') return false;

    if (el.dataset && el.dataset.accion === 'escritura') return true;

    var texto = (el.textContent || '').trim().toLowerCase();
    if (!texto) return false;

    return VERBOS_ESCRITURA.some(function (v) {
      return texto.indexOf(v) !== -1;
    });
  }

  function ocultarEscritura(raiz) {
    var candidatos = (raiz || document).querySelectorAll(
      'button, a.btn, input[type="submit"], [data-accion="escritura"]'
    );

    Array.prototype.forEach.call(candidatos, function (el) {
      if (el.dataset && el.dataset.demoOculto) return;
      if (!esControlDeEscritura(el)) return;
      el.dataset.demoOculto = '1';
      el.style.display = 'none';
    });
  }

  function activarModoDemo() {
    montarBanner();
    ocultarEscritura(document);

    // Muchas vistas pintan las tablas despues de traer los datos. Sin esto,
    // los botones de cada fila aparecerian cuando llega la respuesta.
    try {
      var obs = new MutationObserver(function (cambios) {
        cambios.forEach(function (c) {
          Array.prototype.forEach.call(c.addedNodes, function (n) {
            if (n.nodeType === 1) ocultarEscritura(n);
          });
        });
      });
      obs.observe(document.body, { childList: true, subtree: true });
    } catch (e) { /* navegador sin MutationObserver */ }
  }

  function montar() {
    interceptarFetch();

    // Si la pagina fue retirada del menu, se manda a su reemplazo.
    var destino = REDIRECCIONES[paginaActual()];
    if (destino) { window.location.replace(destino); return; }

    var side = document.querySelector('.sidebar');
    if (!side) {
      side = document.createElement('div');
      side.className = 'sidebar';
      document.body.insertBefore(side, document.body.firstChild);
    }
    side.innerHTML = htmlSidebar();

    var toggle = document.querySelector('.sidebar-toggle');
    if (toggle && !toggle.dataset.menuJs) {
      toggle.dataset.menuJs = '1';
      toggle.addEventListener('click', function () {
        side.classList.toggle('active');
        var main = document.querySelector('.main-content');
        if (main) main.classList.toggle('active');
      });
    }

    var btn = document.getElementById('btnLogout');
    if (btn) btn.addEventListener('click', function (e) { e.preventDefault(); salir(); });

    // Enlace heredado que algunas paginas todavia traen oculto.
    var viejo = document.getElementById('logoutDropdown');
    if (viejo) viejo.addEventListener('click', function (e) { e.preventDefault(); salir(); });

    var span = document.getElementById('userName');
    if (span) {
      try {
        var u = JSON.parse(localStorage.getItem('usuario') || localStorage.getItem('user') || 'null');
        var n = u && (u.nombre || u.usuario || u.username || u.nombre_usuario);
        if (n) span.textContent = n;
        else {
          var simple = localStorage.getItem('userName');
          if (simple) span.textContent = simple;
        }
      } catch (e) {}
    }

    // Oculta las opciones de admin si el rol es operador.
    // El invitado SI las ve: el demo debe mostrar reportes y tarifas.
    try {
      if (rolActual() === 'operador') {
        side.querySelectorAll('.admin-only').forEach(function (el) {
          el.style.display = 'none';
        });
      }
    } catch (e) {}

    if (esInvitado()) activarModoDemo();
  }

  // El interceptor se instala de una, sin esperar al DOM: si una pagina hace
  // su primera llamada a la API antes de que el menu se monte, igual queda
  // protegida.
  interceptarFetch();

  // Disponible por si alguna pagina necesita cerrar sesion por su cuenta.
  window.psLimpiarSesion = limpiarSesion;
  window.psSesionVencida = sesionVencida;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', montar);
  } else {
    montar();
  }
})();