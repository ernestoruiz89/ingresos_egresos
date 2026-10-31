frappe.provide("frappe.ie_deferred");
Object.assign(frappe.ie_deferred, {
    fields(doc = {}, read_only = false) {
        return [
            {fieldtype: "Section Break"},
            {fieldtype: "Check", fieldname: "es_diferido", label: __("Distribuir entre meses"), default: doc.es_diferido || 0, read_only,
                description: __("El cobro o pago afecta caja completo; el ingreso o gasto se reconoce mensualmente.")},
            {fieldtype: "Section Break", label: __("Diferimiento mensual"), depends_on: "es_diferido"},
            {fieldtype: "Date", fieldname: "inicio_diferimiento", label: __("Inicio del servicio"), default: doc.inicio_diferimiento, read_only},
            {fieldtype: "Column Break"},
            {fieldtype: "Int", fieldname: "meses_diferimiento", label: __("Número de meses"), default: doc.meses_diferimiento || 12, read_only,
                description: __("Cuotas al cierre de cada mes; la última ajusta el redondeo.")}
        ];
    },
    bind(dialog) {
        const refresh = async () => {
            const active = Boolean(dialog.get_value("es_diferido"));
            for (const field of ["inicio_diferimiento", "meses_diferimiento"]) dialog.set_df_property(field, "reqd", active ? 1 : 0);
            if (active) {
                if (dialog.fields_dict.es_activo) await dialog.set_value("es_activo", 0);
                if (!dialog.get_value("inicio_diferimiento")) await dialog.set_value("inicio_diferimiento", dialog.get_value("fecha_de_registro") || frappe.datetime.get_today());
            }
        };
        dialog.fields_dict.es_diferido.df.onchange = refresh;
        if (dialog.fields_dict.es_activo) {
            const original = dialog.fields_dict.es_activo.df.onchange;
            dialog.fields_dict.es_activo.df.onchange = async () => {
                await original?.();
                if (dialog.get_value("es_activo")) await dialog.set_value("es_diferido", 0);
            };
        }
        return refresh();
    }
});
