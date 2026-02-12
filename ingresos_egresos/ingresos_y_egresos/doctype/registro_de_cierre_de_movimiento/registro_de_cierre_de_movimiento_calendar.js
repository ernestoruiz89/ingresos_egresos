frappe.views.calendar["Registro de Cierre de Movimiento"] = {
	field_map: {
		"start": "fecha_inicio",
		"end": "fecha_final",
		"id": "name",
		"title": "title",
		"allDay": "allDay"
	},
	get_events_method: "ingresos_egresos.ingresos_y_egresos.doctype.registro_de_cierre_de_movimiento.registro_de_cierre_de_movimiento.get_events",
	get_style: function(data) {
        if (data.color) {
            return {
                "backgroundColor": data.color,
                "color": "#fff"
            };
        }
        return {
            "backgroundColor": "#007bff",
            "color": "#fff"
        };
    },
	// Si deseas sobreescribir el texto (título) que se muestra en la tarjeta del calendario,
	// para incluir total_ingreso / total_egreso, puedes usar get_title.
	get_title: function(data) {
	// Combinas el 'name' con los totales
	return `${data.sucursal} | Ingresos: ${data.total_ingresos} / Egresos: ${data.total_egresos}`;
	}
};