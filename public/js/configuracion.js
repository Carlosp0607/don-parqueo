// Configuración de empresa (admin)
// Relacionado con: public/admin/configuracion.html y API /api/empresa

document.addEventListener('DOMContentLoaded', () => {
    const token = localStorage.getItem('token');
    const role = localStorage.getItem('userRole');
    if (!token) { window.location.href = '/'; return; }
    if (role !== 'admin') { window.location.href = '/admin/dashboard'; return; }

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
    document.getElementById('btnLogout').addEventListener('click',()=>{ localStorage.clear(); location.href='/'; });

    // Cargar datos
    cargarEmpresa();
    cargarConfig();
    cargarQR();

    // Guardar
    document.getElementById('btnSaveEmpresa').addEventListener('click', guardarEmpresa);
    document.getElementById('btnSaveConfig').addEventListener('click', guardarConfig);

    // Logo: vista previa y subida
    const fileInput = document.getElementById('e_logo_file');
    const preview = document.getElementById('e_logo_preview');
    const uploadBtn = document.getElementById('btnUploadLogo');
    if (fileInput) {
        fileInput.addEventListener('change', () => {
            const f = fileInput.files && fileInput.files[0];
            if (!f) { preview.src=''; preview.classList.add('d-none'); return; }
            // Validar tamaño (<= 2MB) y tipo (PNG/JPG/GIF)
            const max = 2 * 1024 * 1024;
            const okType = ['image/png','image/jpeg','image/jpg','image/gif'].includes(f.type);
            if (!okType) { setAlert('alertEmpresa','danger','Tipo de archivo no permitido. Usa PNG/JPG.'); fileInput.value=''; return; }
            if (f.size > max) { setAlert('alertEmpresa','danger','El archivo excede 2MB.'); fileInput.value=''; return; }
            const reader = new FileReader();
            reader.onload = e => { preview.src = e.target.result; preview.classList.remove('d-none'); };
            reader.readAsDataURL(f);
        });
    }
    if (uploadBtn) {
        uploadBtn.addEventListener('click', subirLogo);
    }

    // QR de pago
    const btnSubirQR = document.getElementById('btnSubirQR');
    if (btnSubirQR) btnSubirQR.addEventListener('click', subirQR);

    const btnQuitarQR = document.getElementById('btnQuitarQR');
    if (btnQuitarQR) btnQuitarQR.addEventListener('click', quitarQR);
});

async function cargarEmpresa(){
    try{
        const r = await fetch('/api/empresa/me',{ headers:{ 'Authorization':`Bearer ${localStorage.getItem('token')}` }});
        const j = await r.json();
        if(!r.ok) throw new Error(j.message||'Error cargando empresa');
        const e = j.data;
        document.getElementById('e_nombre').value = e.nombre || '';
        document.getElementById('e_nit').value = e.nit || '';
        document.getElementById('e_direccion').value = e.direccion || '';
        document.getElementById('e_telefono').value = e.telefono || '';
        document.getElementById('e_email').value = e.email || '';
        const preview = document.getElementById('e_logo_preview');
        if (preview) {
            // Intentar cargar desde endpoint BLOB; si 404, ocultar
            fetch('/api/empresa/logo', { headers:{'Authorization':`Bearer ${localStorage.getItem('token')}`} })
                .then(r=> r.ok ? r.blob() : Promise.reject())
                .then(b=>{ preview.src = URL.createObjectURL(b); preview.classList.remove('d-none'); })
                .catch(()=> preview.classList.add('d-none'));
        }
    }catch(err){ setAlert('alertEmpresa', 'danger', err.message); }
}

// Función para cargar configuración de empresa
// Relacionado con: src/routes/empresa.js GET /api/empresa/config
// Nota: Las capacidades ya no se cargan aquí, se gestionan desde Tipos de Vehículos
async function cargarConfig(){
    try{
        const r = await fetch('/api/empresa/config',{ headers:{ 'Authorization':`Bearer ${localStorage.getItem('token')}` }});
        const j = await r.json();
        if(!r.ok) throw new Error(j.message||'Error cargando configuración');
        const c = j.data;
        // Las capacidades ya no se cargan, se gestionan desde tipos-vehiculos.html
        document.getElementById('c_apertura').value = (c.horario_apertura||'').toString().substring(0,5);
        document.getElementById('c_cierre').value = (c.horario_cierre||'').toString().substring(0,5);
        document.getElementById('c_iva').value = c.iva_porcentaje ?? 0;
        document.getElementById('c_moneda').value = c.moneda || 'COP';
        document.getElementById('c_tz').value = c.zona_horaria || 'America/Bogota';
        const chk = document.getElementById('c_24h');
        if (chk) {
            chk.checked = !!c.operacion_24h;
            toggleHorasPor24h();
            chk.addEventListener('change', toggleHorasPor24h);
        }
    }catch(err){ setAlert('alertConfig', 'danger', err.message); }
}

// ---------------------------------------------------------------------------
// QR de pago
//
// Es la foto del QR fijo que el parqueadero ya tiene pegado en la caseta. Se
// sube una vez y el operador la muestra al cobrar. NO es una pasarela: el
// sistema no cobra ni verifica nada, el operador confirma en su celular.
// ---------------------------------------------------------------------------
async function cargarQR(){
    const img = document.getElementById('qr_preview');
    const vacio = document.getElementById('qr_vacio');
    const btnQuitar = document.getElementById('btnQuitarQR');
    if (!img) return;

    try{
        const r = await fetch('/api/empresa/qr-pago', {
            headers:{ 'Authorization':`Bearer ${localStorage.getItem('token')}` }
        });
        if (!r.ok) throw new Error('sin qr');
        const b = await r.blob();
        img.src = URL.createObjectURL(b);
        img.classList.remove('d-none');
        if (vacio) vacio.classList.add('d-none');
        if (btnQuitar) btnQuitar.classList.remove('d-none');
    }catch(e){
        // 404 es lo normal cuando todavia no han subido ninguno.
        img.classList.add('d-none');
        if (vacio) vacio.classList.remove('d-none');
        if (btnQuitar) btnQuitar.classList.add('d-none');
    }
}

async function subirQR(){
    const input = document.getElementById('qr_file');
    const file = input && input.files[0];
    if (!file) { setAlert('alertQR','warning','Escoge primero la imagen del QR.'); return; }

    const max = 2 * 1024 * 1024;
    const okType = ['image/png','image/jpeg','image/jpg','image/gif'].includes(file.type);
    if (!okType) { setAlert('alertQR','danger','Tipo de archivo no permitido. Usa PNG o JPG.'); return; }
    if (file.size > max) { setAlert('alertQR','danger','La imagen excede 2MB.'); return; }

    const btn = document.getElementById('btnSubirQR');
    const prev = btn.innerHTML; btn.disabled = true; btn.innerHTML = spinner('Subiendo...');
    try{
        const form = new FormData();
        form.append('qr', file);
        const r = await fetch('/api/empresa/qr-pago', {
            method:'POST',
            headers:{ 'Authorization': `Bearer ${localStorage.getItem('token')}` },
            body: form
        });
        const j = await r.json();
        if (!r.ok) throw new Error(j.message||'Error al subir el QR');

        setAlert('alertQR','success','QR guardado. Ya aparece al cobrar.');
        input.value = '';
        const btnQuitar = document.getElementById('btnQuitarQR');
        if (btnQuitar) btnQuitar.classList.remove('d-none');
        const vacio = document.getElementById('qr_vacio');
        if (vacio) vacio.classList.add('d-none');
    }catch(err){ setAlert('alertQR','danger', err.message); }
    finally{ btn.disabled=false; btn.innerHTML = prev; }
}

async function quitarQR(){
    if (!confirm('¿Quitar el QR? Dejará de aparecer al cobrar.')) return;

    const btn = document.getElementById('btnQuitarQR');
    const prev = btn.innerHTML; btn.disabled = true; btn.innerHTML = spinner('Quitando...');
    try{
        const r = await fetch('/api/empresa/qr-pago', {
            method:'DELETE',
            headers:{ 'Authorization': `Bearer ${localStorage.getItem('token')}` }
        });
        const j = await r.json();
        if (!r.ok) throw new Error(j.message||'Error al quitar el QR');

        const img = document.getElementById('qr_preview');
        const vacio = document.getElementById('qr_vacio');
        if (img) { img.src = ''; img.classList.add('d-none'); }
        if (vacio) vacio.classList.remove('d-none');
        btn.classList.add('d-none');
        setAlert('alertQR','success','QR eliminado.');
    }catch(err){ setAlert('alertQR','danger', err.message); }
    finally{ btn.disabled=false; btn.innerHTML = prev; }
}

async function guardarEmpresa(){
    const payload = {
        nombre: document.getElementById('e_nombre').value.trim(),
        nit: document.getElementById('e_nit').value.trim(),
        direccion: document.getElementById('e_direccion').value.trim(),
        telefono: document.getElementById('e_telefono').value.trim(),
        email: document.getElementById('e_email').value.trim()
    };
    const btn = document.getElementById('btnSaveEmpresa');
    const prev = btn.innerHTML; btn.disabled = true; btn.innerHTML = spinner('Guardando...');
    try{
        const r = await fetch('/api/empresa',{
            method:'PUT', headers:{'Content-Type':'application/json','Authorization':`Bearer ${localStorage.getItem('token')}`}, body: JSON.stringify(payload)
        });
        const j = await r.json();
        if(!r.ok) throw new Error(j.message||'Error al guardar');
        setAlert('alertEmpresa', 'success', 'Datos de empresa actualizados.');
    }catch(err){ setAlert('alertEmpresa','danger', err.message); }
    finally{ btn.disabled=false; btn.innerHTML = prev; }
}

// Función para guardar configuración de empresa
// Relacionado con: src/routes/empresa.js PUT /api/empresa/config
// Nota: Las capacidades ya no se envían aquí, se gestionan desde tipos-vehiculos.html
async function guardarConfig(){
    const payload = {
        // Las capacidades ya no se envían, se gestionan desde el panel de Tipos de Vehículos
        horario_apertura: document.getElementById('c_apertura').value,
        horario_cierre: document.getElementById('c_cierre').value,
        iva_porcentaje: Number(document.getElementById('c_iva').value||0),
        moneda: document.getElementById('c_moneda').value.trim()||'COP',
        zona_horaria: document.getElementById('c_tz').value.trim()||'America/Bogota',
        operacion_24h: document.getElementById('c_24h').checked
    };
    const btn = document.getElementById('btnSaveConfig');
    const prev = btn.innerHTML; btn.disabled = true; btn.innerHTML = spinner('Guardando...');
    try{
        const r = await fetch('/api/empresa/config',{
            method:'PUT', headers:{'Content-Type':'application/json','Authorization':`Bearer ${localStorage.getItem('token')}`}, body: JSON.stringify(payload)
        });
        const j = await r.json();
        if(!r.ok) throw new Error(j.message||'Error al guardar');
        setAlert('alertConfig', 'success', 'Configuración actualizada.');
    }catch(err){ setAlert('alertConfig','danger', err.message); }
    finally{ btn.disabled=false; btn.innerHTML = prev; }
}

function toggleHorasPor24h(){
    const on = document.getElementById('c_24h').checked;
    document.getElementById('c_apertura').disabled = on;
    document.getElementById('c_cierre').disabled = on;
}

function setAlert(id, type, msg){
    const el = document.getElementById(id);
    if (!el) return;
    el.className = `alert alert-${type} py-2 small`;
    el.textContent = msg;
}

function spinner(text){
    return `<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> ${text}`;
}

// Sube el logo y lo guarda como BLOB en la empresa.
//
// FIX: aqui se usaba la variable "preview", que solo existe dentro del
// DOMContentLoaded. Al ejecutarse lanzaba ReferenceError DESPUES de que el
// logo ya se habia guardado, asi que el admin veia un error rojo y volvia a
// subirlo pensando que habia fallado.
async function subirLogo(){
    const input = document.getElementById('e_logo_file');
    const file = input && input.files[0];
    if (!file) { setAlert('alertEmpresa','warning','Selecciona un archivo de logo.'); return; }
    const btn = document.getElementById('btnUploadLogo');
    const prev = btn.innerHTML; btn.disabled = true; btn.innerHTML = spinner('Subiendo...');
    try{
        const form = new FormData();
        form.append('logo', file);
        const r = await fetch('/api/empresa/logo', { method:'POST', headers:{ 'Authorization': `Bearer ${localStorage.getItem('token')}` }, body: form });
        const j = await r.json();
        if (!r.ok) throw new Error(j.message||'Error al subir logo');

        const img = document.getElementById('e_logo_preview');
        if (img) { img.src = j.url; img.classList.remove('d-none'); }
        setAlert('alertEmpresa','success','Logo subido y guardado.');
    }catch(err){ setAlert('alertEmpresa','danger', err.message); }
    finally{ btn.disabled=false; btn.innerHTML = prev; }
}
