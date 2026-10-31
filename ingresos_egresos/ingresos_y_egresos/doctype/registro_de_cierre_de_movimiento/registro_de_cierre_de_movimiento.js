frappe.ui.form.on("Registro de Cierre de Movimiento", {
    setup(frm) { frm.ignore_doctypes_on_cancel_all = ["Movimiento"]; },
    async onload(frm) {
        if (!frm.is_new()) return;
        const settings = await frappe.ie_currency.settings();
        await frm.set_value("moneda_base", settings.moneda_base);
        if (!frm.doc.moneda) await frm.set_value("moneda", settings.moneda_base);
        frm.trigger("suggest_dates");
    },
    sucursal(frm) { frm.trigger("suggest_dates"); },
    moneda(frm) { frm.trigger("suggest_dates"); },
    async suggest_dates(frm) {
        if (!frm.is_new() || !frm.doc.sucursal || !frm.doc.moneda) return;
        const seq = frm._closure_seq = (frm._closure_seq || 0) + 1;
        const r = await frappe.call({
            method: "ingresos_egresos.ingresos_y_egresos.doctype.registro_de_cierre_de_movimiento.registro_de_cierre_de_movimiento.get_closure_defaults",
            args: {sucursal: frm.doc.sucursal, moneda: frm.doc.moneda}
        });
        if (seq !== frm._closure_seq) return;
        frm.set_value("fecha_inicio", r.message.fecha_inicio);
        frm.set_df_property("fecha_inicio", "read_only", r.message.hay_cierre ? 1 : 0);
    },
    actualizar_movimientos(frm) {
        if (frm.doc.docstatus !== 0) return;
        return frm.save();
    }
});
