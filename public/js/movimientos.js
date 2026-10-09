// Ejemplo de petición desde el Frontend
async function registrarEntradaVehiculo(placa, tipoVehiculoId, tarifaId) {
    const token = localStorage.getItem('token'); // Recupera el JWT guardado al hacer login

    try {
        const respuesta = await fetch('/api/movimientos/entrada', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`
            },
            body: JSON.stringify({
                placa: placa,
                tipo_vehiculo_id: tipoVehiculoId,
                tarifa_id: tarifaId
            })
        });

        const data = await respuesta.json();

        if (data.success) {
            alert('¡Vehículo ingresado con éxito!');
        } else {
            alert(`Error: ${data.message}`);
        }
    } catch (error) {
        console.error('Error de red:', error);
    }
}