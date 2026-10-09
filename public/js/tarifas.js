// Variable global para almacenar las tarifas activas
// Relacionado con: función loadTarifas() y listener de cambio de tipo
let tarifasActivas = [];

document.addEventListener('DOMContentLoaded', () => {
    // Guard de rol: solo admin
    if (localStorage.getItem('userRole') !== 'admin') { window.location.href = '/admin/dashboard'; return; }
    const nameEl = document.getElementById('userName');
    if (nameEl) {
        const showUserName = false;
        if (showUserName) {
            nameEl.textContent = localStorage.getItem('userName') || 'Usuario';
        } else {
            nameEl.textContent = '';
            const parent = nameEl.closest('.nav-item, li');
            if (parent) parent.style.display = 'none';
        }
    }
    document.querySelector('.sidebar-toggle').addEventListener('click',()=>document.querySelector('.sidebar').classList.toggle('show'));
    document.getElementById('btnLogout').addEventListener('click',()=>{localStorage.clear(); location.href='/';});

    // Cargar tipos de vehículos dinámicamente
    // Relacionado con: src/routes/tipos-vehiculos.js GET /api/tipos-vehiculos/activos
    cargarTiposVehiculos();
    loadTarifas();

    // Habilitar/deshabilitar campos según modo
    const modo = document.getElementById('modo_cobro');
    const fToggle = () => {
        const m = modo.value;
        const enMin = m === 'minuto' || m === 'mixto';
        const enHora = m === 'hora' || m === 'mixto';
        const enDia = m === 'dia' || m === 'mixto';
        document.getElementById('valor_minuto').disabled = !enMin;
        document.getElementById('valor_hora').disabled = !enHora;
        document.getElementById('valor_dia_completo').disabled = !enDia;
        const escalas = m === 'mixto';
        document.getElementById('paso_minutos_a_horas').disabled = !escalas;
        document.getElementById('paso_horas_a_dias').disabled = !escalas;
        document.getElementById('redondeo_horas').disabled = !escalas;
        document.getElementById('redondeo_dias').disabled = !escalas;
    };
    modo.addEventListener('change', fToggle);
    fToggle();

    // Función para cargar tipos de vehículos
    // Relacionado con: src/routes/tipos-vehiculos.js GET /api/tipos-vehiculos/activos
    async function cargarTiposVehiculos() {
        try {
            const res = await fetch('/api/tipos-vehiculos/activos', {
                headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
            });
            const j = await res.json();
            if (res.ok && j.success) {
                const select = document.getElementById('tipo_vehiculo');
                select.innerHTML = '<option value="">Seleccione un tipo</option>';
                j.data.forEach(tipo => {
                    const option = document.createElement('option');
                    option.value = tipo.id_tipo;
                    option.textContent = tipo.nombre;
                    select.appendChild(option);
                });
                
                // Después de cargar los tipos, agregar el listener para cargar tarifas automáticamente
                // Esto asegura que el listener se agregue después de que el select esté poblado
                if (!select.hasAttribute('data-listener-agregado')) {
                    select.addEventListener('change', async function() {
                        const idTipo = this.value;
                        if (!idTipo) {
                            // Si no hay tipo seleccionado, limpiar el formulario
                            limpiarFormulario();
                            return;
                        }

                        // Buscar la tarifa activa para este tipo
                        const tarifa = tarifasActivas.find(t => t.id_tipo == idTipo);
                        
                        if (tarifa) {
                            // Si existe una tarifa activa, rellenar el formulario
                            rellenarFormulario(tarifa);
                            showToast('Info', `Tarifa activa cargada para ${tarifa.tipo_nombre || 'este tipo'}`, 'info');
                        } else {
                            // Si no existe, limpiar el formulario para crear una nueva
                            limpiarFormulario();
                        }
                    });
                    select.setAttribute('data-listener-agregado', 'true');
                }
            }
        } catch (err) {
            console.error('Error cargando tipos:', err);
        }
    }

    document.getElementById('tarifaForm').addEventListener('submit', async (e)=>{
        e.preventDefault();
        const body = {
            id_tipo: document.getElementById('tipo_vehiculo').value,
            modo_cobro: document.getElementById('modo_cobro').value,
            valor_minuto: parseFloat(document.getElementById('valor_minuto').value||0),
            valor_hora: parseFloat(document.getElementById('valor_hora').value||0),
            valor_dia_completo: parseFloat(document.getElementById('valor_dia_completo').value||0),
            paso_minutos_a_horas: parseInt(document.getElementById('paso_minutos_a_horas').value||0, 10),
            paso_horas_a_dias: parseInt(document.getElementById('paso_horas_a_dias').value||0, 10),
            redondeo_horas: document.getElementById('redondeo_horas').value,
            redondeo_dias: document.getElementById('redondeo_dias').value
        };
        try{
            const res = await fetch('/api/tarifas', {
                method: 'PUT',
                headers: { 'Content-Type':'application/json', 'Authorization':`Bearer ${localStorage.getItem('token')}` },
                body: JSON.stringify(body)
            });
            const j = await res.json();
            if(!res.ok) throw new Error(j.message||'No se pudo guardar');
            showToast('Éxito','Tarifa guardada','success');
            // Recargar tarifas para actualizar la lista y la variable global
            await loadTarifas();
            // Si el tipo seleccionado es el mismo, recargar sus datos en el formulario
            const idTipoSeleccionado = document.getElementById('tipo_vehiculo').value;
            if (idTipoSeleccionado) {
                const tarifaActualizada = tarifasActivas.find(t => t.id_tipo == idTipoSeleccionado);
                if (tarifaActualizada) {
                    rellenarFormulario(tarifaActualizada);
                }
            }
        }catch(err){
            showToast('Error', err.message, 'error');
        }
    });
});

// Función para cargar tarifas activas y mostrarlas en la lista
// Relacionado con: src/routes/tarifas.js GET /api/tarifas/current
async function loadTarifas(){
    try{
        const res = await fetch('/api/tarifas/current', { headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }});
        const j = await res.json();
        if(!res.ok) throw new Error(j.message||'Error cargando tarifas');
        
        // Guardar las tarifas activas en la variable global para uso posterior
        tarifasActivas = j.data || [];
        
        const ul = document.getElementById('listaTarifas');
        ul.innerHTML = j.data.map(t => `
            <li class="list-group-item d-flex flex-column">
                <div class="d-flex justify-content-between align-items-center">
                    <strong class="text-capitalize">${t.tipo_nombre || t.tipo_codigo || 'N/A'}</strong>
                    <span class="badge bg-primary">${t.modo_cobro}</span>
                </div>
                <small>Min: ${t.valor_minuto} | Hora: ${t.valor_hora} | Día: ${t.valor_dia_completo}</small>
                <small>Escalas → min→hr: ${t.paso_minutos_a_horas} min, hr→día: ${t.paso_horas_a_dias} h</small>
            </li>
        `).join('');
    }catch(err){
        showToast('Error', err.message, 'error');
    }
}

// Función para rellenar el formulario con los datos de una tarifa
// Relacionado con: campos del formulario en public/admin/tarifas.html
function rellenarFormulario(tarifa) {
    document.getElementById('modo_cobro').value = tarifa.modo_cobro || 'mixto';
    document.getElementById('valor_minuto').value = tarifa.valor_minuto || 0;
    document.getElementById('valor_hora').value = tarifa.valor_hora || 0;
    document.getElementById('valor_dia_completo').value = tarifa.valor_dia_completo || 0;
    document.getElementById('paso_minutos_a_horas').value = tarifa.paso_minutos_a_horas || 0;
    document.getElementById('paso_horas_a_dias').value = tarifa.paso_horas_a_dias || 0;
    document.getElementById('redondeo_horas').value = tarifa.redondeo_horas || 'arriba';
    document.getElementById('redondeo_dias').value = tarifa.redondeo_dias || 'arriba';
    
    // Disparar el evento change del modo para habilitar/deshabilitar campos correctamente
    const modo = document.getElementById('modo_cobro');
    const event = new Event('change');
    modo.dispatchEvent(event);
}

// Función para limpiar el formulario
// Relacionado con: campos del formulario en public/admin/tarifas.html
function limpiarFormulario() {
    document.getElementById('modo_cobro').value = 'mixto';
    document.getElementById('valor_minuto').value = '';
    document.getElementById('valor_hora').value = '';
    document.getElementById('valor_dia_completo').value = '';
    document.getElementById('paso_minutos_a_horas').value = '0';
    document.getElementById('paso_horas_a_dias').value = '0';
    document.getElementById('redondeo_horas').value = 'arriba';
    document.getElementById('redondeo_dias').value = 'arriba';
    
    // Disparar el evento change del modo para habilitar/deshabilitar campos correctamente
    const modo = document.getElementById('modo_cobro');
    const event = new Event('change');
    modo.dispatchEvent(event);
}

function showToast(title, message, type) {
    const container = document.getElementById('toastContainer');
    const id = 't_' + Date.now();
    const typeClass = type==='success' ? 'toast-success' : type==='warning' ? 'toast-warning' : type==='info' ? 'toast-info' : 'toast-error';
    const el = document.createElement('div');
    el.className = `toast align-items-center toast-custom ${typeClass}`;
    el.id = id;
    el.role = 'alert';
    el.ariaLive = 'assertive';
    el.ariaAtomic = 'true';
    el.innerHTML = `
      <div class="toast-header">
        <strong class="me-auto">${title}</strong>
        <button type="button" class="btn-close" data-bs-dismiss="toast" aria-label="Close"></button>
      </div>
      <div class="toast-body">${message}</div>
    `;
    container.appendChild(el);
    const toast = new bootstrap.Toast(el, { delay: 3500 });
    toast.show();
    el.addEventListener('hidden.bs.toast', () => el.remove());
}


