// Script para gestión de tipos de vehículos
// Relacionado con: public/admin/tipos-vehiculos.html (página HTML) y src/routes/tipos-vehiculos.js (API backend)

document.addEventListener('DOMContentLoaded', function() {
    // Verificar autenticación
    const token = localStorage.getItem('token');
    if (!token) {
        window.location.href = '/';
        return;
    }

    // Verificar rol admin
    if (localStorage.getItem('userRole') !== 'admin') {
        window.location.href = '/admin/dashboard';
        return;
    }

    // Inicializar DataTable
    // Relacionado con: DataTables Bootstrap 5 para mostrar la tabla de tipos
    const table = $('#tiposTable').DataTable({
        language: {
            url: '//cdn.datatables.net/plug-ins/1.13.7/i18n/es-ES.json'
        },
        order: [[6, 'desc']], // Ordenar por fecha de creación descendente
        columns: [
            { data: 'nombre' },
            { 
                data: 'codigo',
                render: function(data) {
                    return `<code>${data}</code>`;
                }
            },
            { 
                data: 'capacidad_total',
                render: function(data) {
                    return data || 0;
                }
            },
            { 
                data: 'total_vehiculos',
                render: function(data) {
                    return data || 0;
                }
            },
            { 
                data: 'tiene_tarifa_activa',
                render: function(data) {
                    return data > 0 
                        ? '<span class="badge bg-success">Sí</span>'
                        : '<span class="badge bg-warning">No</span>';
                }
            },
            { 
                data: 'activo',
                render: function(data) {
                    return data 
                        ? '<span class="badge bg-success">Activo</span>'
                        : '<span class="badge bg-secondary">Inactivo</span>';
                }
            },
            { 
                data: 'fecha_creacion',
                render: function(data) {
                    return new Date(data).toLocaleString('es-CO');
                }
            },
            {
                data: null,
                render: function(data, type, row) {
                    return `
                        <button class="btn btn-sm btn-info me-1" onclick="editarTipo(${row.id_tipo})" title="Editar">
                            <i class="fas fa-edit"></i>
                        </button>
                        <button class="btn btn-sm btn-danger" onclick="eliminarTipo(${row.id_tipo})" title="Eliminar">
                            <i class="fas fa-trash"></i>
                        </button>
                    `;
                }
            }
        ]
    });

    // Cargar datos iniciales
    cargarTipos();

    // Event Listeners
    document.getElementById('btnGuardar').addEventListener('click', guardarTipo);
    document.getElementById('btnLogout').addEventListener('click', cerrarSesion);
    document.getElementById('logoutDropdown').addEventListener('click', cerrarSesion);

    // Mostrar nombre del usuario
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
    
    // Ocultar menús admin para operadores
    if (localStorage.getItem('userRole') !== 'admin') {
        document.querySelectorAll('.admin-only').forEach(el => el.classList.add('d-none'));
    }

    // Toggle Sidebar
    document.querySelector('.sidebar-toggle').addEventListener('click', function() {
        document.querySelector('.sidebar').classList.toggle('show');
    });

    // Función para cargar tipos de vehículos desde la API
    // Relacionado con: src/routes/tipos-vehiculos.js GET /api/tipos-vehiculos
    async function cargarTipos() {
        try {
            const response = await fetch('/api/tipos-vehiculos', {
                headers: {
                    'Authorization': `Bearer ${localStorage.getItem('token')}`
                }
            });

            if (!response.ok) {
                throw new Error('Error al cargar los tipos de vehículos');
            }

            const result = await response.json();
            if (result.success) {
                $('#tiposTable').DataTable().clear().rows.add(result.data).draw();
            } else {
                throw new Error(result.message || 'Error al cargar los tipos');
            }

        } catch (error) {
            mostrarError('Error al cargar los tipos de vehículos: ' + error.message);
            console.error(error);
        }
    }

    // Función para guardar tipo de vehículo (crear o actualizar)
    // Relacionado con: src/routes/tipos-vehiculos.js POST /api/tipos-vehiculos y PUT /api/tipos-vehiculos/:id
    async function guardarTipo() {
        const tipoId = document.getElementById('tipoId').value;
        const tipo = {
            nombre: document.getElementById('nombre').value.trim(),
            codigo: document.getElementById('codigo').value.trim(),
            capacidad_total: document.getElementById('capacidad').value ? parseInt(document.getElementById('capacidad').value) : null,
            activo: document.getElementById('activo').checked
        };

        // Validación básica
        if (!tipo.nombre || !tipo.codigo) {
            mostrarError('El nombre y el código son obligatorios');
            return;
        }

        try {
            const url = tipoId 
                ? `/api/tipos-vehiculos/${tipoId}`
                : '/api/tipos-vehiculos';
            
            const response = await fetch(url, {
                method: tipoId ? 'PUT' : 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${localStorage.getItem('token')}`
                },
                body: JSON.stringify(tipo)
            });

            const result = await response.json();

            if (!response.ok) {
                throw new Error(result.message || 'Error al guardar el tipo de vehículo');
            }

            // Cerrar modal y recargar datos
            const modal = bootstrap.Modal.getInstance(document.getElementById('tipoModal'));
            modal.hide();
            cargarTipos();
            mostrarExito(tipoId ? 'Tipo de vehículo actualizado exitosamente' : 'Tipo de vehículo registrado exitosamente');

        } catch (error) {
            mostrarError(error.message);
            console.error(error);
        }
    }

    // Función para editar tipo de vehículo
    // Relacionado con: src/routes/tipos-vehiculos.js GET /api/tipos-vehiculos/:id
    async function editarTipo(id) {
        try {
            const response = await fetch(`/api/tipos-vehiculos/${id}`, {
                headers: {
                    'Authorization': `Bearer ${localStorage.getItem('token')}`
                }
            });

            if (!response.ok) {
                throw new Error('Error al cargar los datos del tipo de vehículo');
            }

            const result = await response.json();
            if (!result.success) {
                throw new Error(result.message || 'Error al cargar los datos');
            }

            const tipo = result.data;
            
            // Llenar el formulario
            document.getElementById('tipoId').value = tipo.id_tipo;
            document.getElementById('nombre').value = tipo.nombre;
            document.getElementById('codigo').value = tipo.codigo;
            document.getElementById('capacidad').value = tipo.capacidad_total || '';
            document.getElementById('activo').checked = tipo.activo;

            // Actualizar título del modal
            document.getElementById('modalTitle').textContent = 'Editar Tipo de Vehículo';
            
            // Abrir modal
            const modal = new bootstrap.Modal(document.getElementById('tipoModal'));
            modal.show();

        } catch (error) {
            mostrarError(error.message);
            console.error(error);
        }
    }

    // Función para eliminar tipo de vehículo
    // Relacionado con: src/routes/tipos-vehiculos.js DELETE /api/tipos-vehiculos/:id
    async function eliminarTipo(id) {
        if (!confirm('¿Está seguro de eliminar este tipo de vehículo?\n\nNota: No se puede eliminar si tiene vehículos asociados o tarifas activas.')) {
            return;
        }

        try {
            const response = await fetch(`/api/tipos-vehiculos/${id}`, {
                method: 'DELETE',
                headers: {
                    'Authorization': `Bearer ${localStorage.getItem('token')}`
                }
            });

            const result = await response.json();

            if (!response.ok) {
                throw new Error(result.message || 'Error al eliminar el tipo de vehículo');
            }

            cargarTipos();
            mostrarExito('Tipo de vehículo eliminado exitosamente');

        } catch (error) {
            mostrarError(error.message);
            console.error(error);
        }
    }

    // Función para nuevo tipo (limpiar formulario)
    function nuevoTipo() {
        document.getElementById('tipoForm').reset();
        document.getElementById('tipoId').value = '';
        document.getElementById('activo').checked = true;
        document.getElementById('modalTitle').textContent = 'Nuevo Tipo de Vehículo';
    }

    // Función para mostrar mensajes de éxito
    function mostrarExito(mensaje) {
        // Crear toast de Bootstrap
        const toastContainer = document.getElementById('toastContainer') || crearToastContainer();
        const toastId = 'toast_' + Date.now();
        const toast = document.createElement('div');
        toast.id = toastId;
        toast.className = 'toast align-items-center text-white bg-success border-0';
        toast.setAttribute('role', 'alert');
        toast.setAttribute('aria-live', 'assertive');
        toast.setAttribute('aria-atomic', 'true');
        toast.innerHTML = `
            <div class="d-flex">
                <div class="toast-body">${mensaje}</div>
                <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
            </div>
        `;
        toastContainer.appendChild(toast);
        const bsToast = new bootstrap.Toast(toast);
        bsToast.show();
        toast.addEventListener('hidden.bs.toast', () => toast.remove());
    }

    // Función para mostrar mensajes de error
    function mostrarError(mensaje) {
        // Crear toast de Bootstrap
        const toastContainer = document.getElementById('toastContainer') || crearToastContainer();
        const toastId = 'toast_' + Date.now();
        const toast = document.createElement('div');
        toast.id = toastId;
        toast.className = 'toast align-items-center text-white bg-danger border-0';
        toast.setAttribute('role', 'alert');
        toast.setAttribute('aria-live', 'assertive');
        toast.setAttribute('aria-atomic', 'true');
        toast.innerHTML = `
            <div class="d-flex">
                <div class="toast-body">${mensaje}</div>
                <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
            </div>
        `;
        toastContainer.appendChild(toast);
        const bsToast = new bootstrap.Toast(toast);
        bsToast.show();
        toast.addEventListener('hidden.bs.toast', () => toast.remove());
    }

    // Crear contenedor de toasts si no existe
    function crearToastContainer() {
        const container = document.createElement('div');
        container.id = 'toastContainer';
        container.className = 'position-fixed top-0 end-0 p-3';
        container.style.zIndex = '1100';
        document.body.appendChild(container);
        return container;
    }

    // Función para cerrar sesión
    // Relacionado con: public/js/login.js para limpiar localStorage
    function cerrarSesion() {
        localStorage.clear();
        window.location.href = '/';
    }

    // Exportar funciones globales para uso en onclick
    window.editarTipo = editarTipo;
    window.eliminarTipo = eliminarTipo;
    window.nuevoTipo = nuevoTipo;
});

