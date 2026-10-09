const db = require('../config/db'); // Tu conexión a MariaDB

// 1. REGISTRAR ENTRADA DE VEHÍCULO
exports.registrarEntrada = async (req, res) => {
    const { placa, tipo_vehiculo_id, tarifa_id, observaciones } = req.body;
    const usuario_id = req.usuario.id; // Obtenido del token JWT

    if (!placa || !tipo_vehiculo_id) {
        return res.status(400).json({ success: false, message: 'Placa y tipo de vehículo son requeridos' });
    }

    try {
        // Verificar si el vehículo ya está parqueado (estado 'ACTIVO')
        const [existe] = await db.query(
            'SELECT id FROM movimientos WHERE placa = ? AND estado = "ACTIVO"',
            [placa.toUpperCase()]
        );

        if (existe.length > 0) {
            return res.status(400).json({ success: false, message: 'El vehículo ya se encuentra dentro del parqueadero' });
        }

        // Registrar ingreso
        const sql = `
            INSERT INTO movimientos (placa, tipo_vehiculo_id, tarifa_id, usuario_ingreso_id, fecha_ingreso, estado)
            VALUES (?, ?, ?, ?, NOW(), 'ACTIVO')
        `;
        const [resultado] = await db.query(sql, [placa.toUpperCase(), tipo_vehiculo_id, tarifa_id, usuario_id]);

        return res.json({
            success: true,
            message: 'Entrada registrada con éxito',
            movimiento_id: resultado.insertId
        });
    } catch (error) {
        console.error('Error al registrar entrada:', error);
        return res.status(500).json({ success: false, message: 'Error interno del servidor' });
    }
};

// 2. CALCULAR Y REGISTRAR SALIDA (COBRO)
exports.registrarSalida = async (req, res) => {
    const { placa } = req.body;
    const usuario_id = req.usuario.id;

    try {
        // Obtener el movimiento activo y la tarifa asociada
        const [movimientos] = await db.query(`
            SELECT m.id, m.fecha_ingreso, t.valor_hora, t.valor_fraccion, t.minutos_gracia
            FROM movimientos m
            JOIN tarifas t ON m.tarifa_id = t.id
            WHERE m.placa = ? AND m.estado = 'ACTIVO'
        `, [placa.toUpperCase()]);

        if (movimientos.length === 0) {
            return res.status(404).json({ success: false, message: 'No se encontró un vehículo activo con esa placa' });
        }

        const mov = movimientos[0];
        const fechaIngreso = new Date(mov.fecha_ingreso);
        const fechaSalida = new Date();

        // Calcular minutos transcurridos
        const diferenciaMs = fechaSalida - fechaIngreso;
        const minutosTotales = Math.ceil(diferenciaMs / (1000 * 60));

        let totalPagar = 0;

        // Validar minutos de gracia
        if (minutosTotales > (mov.minutos_gracia || 0)) {
            const horas = Math.floor(minutosTotales / 60);
            const minutosRestantes = minutosTotales % 60;

            totalPagar = horas * mov.valor_hora;

            // Si hay minutos sobrantes, se cobra fracción o hora completa
            if (minutosRestantes > 0) {
                totalPagar += mov.valor_fraccion || mov.valor_hora;
            }
        }

        // Actualizar el registro en la base de datos
        const updateSql = `
            UPDATE movimientos 
            SET fecha_salida = NOW(), 
                total_pagar = ?, 
                usuario_salida_id = ?, 
                estado = 'FINALIZADO'
            WHERE id = ?
        `;
        await db.query(updateSql, [totalPagar, usuario_id, mov.id]);

        return res.json({
            success: true,
            message: 'Salida procesada correctamente',
            datos: {
                placa: placa.toUpperCase(),
                minutos_totales: minutosTotales,
                total_pagar: totalPagar,
                fecha_ingreso: fechaIngreso,
                fecha_salida: fechaSalida
            }
        });
    } catch (error) {
        console.error('Error al registrar salida:', error);
        return res.status(500).json({ success: false, message: 'Error al procesar la liquidación' });
    }
};