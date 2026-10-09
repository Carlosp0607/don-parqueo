// Configuración e Impresión Bluetooth ESC/POS
async function imprimirTicketBluetooth(datosTicket) {
    const texto = `
================================
         PARKSYSTEM POS         
================================
  Ticket N°: ${datosTicket.id || 'N/A'}
  Placa: ${datosTicket.placa}
  Tipo: ${datosTicket.tipo_vehiculo || 'General'}
--------------------------------
  Entrada: ${datosTicket.fecha_ingreso}
  ${datosTicket.fecha_salida ? `Salida:  ${datosTicket.fecha_salida}` : ''}
  ${datosTicket.total_pagar !== undefined ? `TOTAL:   $${datosTicket.total_pagar}` : ''}
================================
    ¡Gracias por su visita!
\n\n\n`;

    // 1. Intentar impresión por Web Bluetooth API
    if (navigator.bluetooth) {
        try {
            const device = await navigator.bluetooth.requestDevice({
                acceptAllDevices: true,
                optionalServices: ['000018f0-0000-1000-8000-00805f9b34fb', '49535343-fe7d-4ae5-8fa9-9fafd205e455']
            });

            const server = await device.gatt.connect();
            // Intenta obtener el servicio POS más común
            const services = await server.getPrimaryServices();
            if (services.length > 0) {
                const characteristics = await services[0].getCharacteristics();
                if (characteristics.length > 0) {
                    const encoder = new TextEncoder();
                    await characteristics[0].writeValue(encoder.encode(texto));
                    alert('¡Ticket impreso correctamente!');
                    return;
                }
            }
        } catch (error) {
            console.warn('Bluetooth cancelado o no disponible, usando impresión de sistema:', error);
        }
    }

    // 2. Fallback: Si no aparea por Bluetooth o se cancela, abre el diálogo de impresión clásico
    const ventanaImpresion = window.open('', '', 'width=300,height=400');
    ventanaImpresion.document.write(`<pre style="font-family: monospace; font-size: 14px;">${texto}</pre>`);
    ventanaImpresion.document.close();
    ventanaImpresion.print();
    ventanaImpresion.close();
}