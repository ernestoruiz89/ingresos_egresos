frappe.ui.form.on("Movimiento", {
    async onload(frm) {
        await frappe.require(["/assets/ingresos_egresos/js/ie_assets.js", "/assets/ingresos_egresos/js/ie_deferred.js"]);
        if (!ie_movement_locked(frm)) ie_movement_concepts(frm);
    },
    refresh(frm) {
        const locked = ie_movement_locked(frm);
        for (const field of ["sucursal", "fecha_de_registro", "tipo", "clasificacion", "referencia", "descripcion", "moneda", "importe",
            "es_activo", "item_activo", "nombre_activo", "ubicacion_activo", "fecha_uso_activo", "vida_util_meses", "valor_residual",
            "es_diferido", "inicio_diferimiento", "meses_diferimiento"])
            frm.set_df_property(field, "read_only", locked ? 1 : 0);
        frm.set_df_property("tasa_de_cambio", "read_only", locked || frm.doc.moneda === frm.doc.moneda_base ? 1 : 0);
        if (locked) {
            frm.disable_save();
            if (frm.doc.docstatus === 1) frm.page.clear_actions();
        } else frm.enable_save();
        if (!locked && frm.doc.docstatus === 0) frm.page.set_primary_action(__("Guardar"), () => frm.save());
        if (frm.is_new()) return;
        if (frm.doc.asiento_contable) {
            frm.add_custom_button(__("Ver asiento contable"), () => frappe.set_route("Form", "Journal Entry", frm.doc.asiento_contable), __("Contabilidad"));
        }
        if (frm.doc.activo_fijo) frm.add_custom_button(__("Ver activo fijo"), () => frappe.set_route("Form", "Asset", frm.doc.activo_fijo), __("Contabilidad"));
        if (frm.doc.diferimiento) frm.add_custom_button(__("Ver calendario"), () => frappe.set_route("Form", "IE Diferimiento", frm.doc.diferimiento), __("Contabilidad"));
        const automatic_pos = ["Venta", "Devolucion"].includes(frm.doc.origen_pos);
        if (frm.doc.docstatus < 2 && !automatic_pos && frm.doc.estado_contable !== "Contabilizado" &&
            frappe.model.can_create("Journal Entry") && frappe.model.can_submit("Journal Entry")) {
            frm.add_custom_button(__("Contabilizar"), async () => {
                if (frm.is_dirty()) await frm.save();
                await frappe.require("/assets/ingresos_egresos/js/ie_accounting.js");
                await frappe.ie_accounting.show([frm.doc.name], () => frm.reload_doc());
            }, __("Contabilidad"));
        }
        if (automatic_pos) frm.set_intro(__("Este cobro o devolución se contabiliza mediante la factura del POS."), "blue");
        else if (frm.doc.estado_contable === "Contabilizado") frm.set_intro(__("Movimiento contabilizado. Para cambiar sus datos, anule primero el asiento vinculado."), "green");
        else if (frm.doc.estado_contable === "Asiento anulado") frm.set_intro(__("El asiento anterior está anulado. Puede revisar los datos y volver a contabilizar."), "orange");
        else if (!frm.doc.vinculado) frm.set_intro(__("El cierre de movimientos y la contabilización son procesos independientes."), "blue");
        if (!locked && !frm.doc.asiento_contable && !frm.doc.vinculado) {
            frm.add_custom_button(__("Eliminar Registro"), () => frappe.confirm(__("¿Eliminar este movimiento?"), async () => {
                await frappe.call({method: "frappe.client.delete", args: {doctype: "Movimiento", name: frm.doc.name}});
                frappe.set_route("List", "Movimiento");
            }));
        }
    },
    async tipo(frm) {
        if (ie_movement_locked(frm)) return;
        await frm.set_value("clasificacion", "");
        if (frm.doc.tipo !== "Egreso") await frm.set_value("es_activo", 0);
        return ie_movement_concepts(frm);
    },
    async onload_post_render(frm) {
        if (ie_movement_locked(frm)) return;
        frappe.ie_assets.bind(frm, frm.doc);
        const settings = await frappe.ie_currency.settings();
        if (frm.doc.moneda_base !== settings.moneda_base) await frm.set_value("moneda_base", settings.moneda_base);
        if (!frm.doc.moneda) await frm.set_value("moneda", settings.moneda_base);
        frm.set_df_property("tasa_de_cambio", "read_only", frm.doc.moneda === settings.moneda_base ? 1 : 0);
    },
    fecha_de_registro: frm => {if (!ie_movement_locked(frm)) return frappe.ie_currency.fetch_rate(frm);},
    moneda: frm => {if (!ie_movement_locked(frm)) return frappe.ie_currency.fetch_rate(frm);},
    importe: frm => {if (!ie_movement_locked(frm)) return frappe.ie_currency.calculate(frm);},
    tasa_de_cambio: frm => {if (!ie_movement_locked(frm)) return frappe.ie_currency.calculate(frm);},
    item_activo: frm => {if (!ie_movement_locked(frm)) return frappe.ie_assets.details(frm, true);},
    async es_activo(frm) {
        if (ie_movement_locked(frm)) return;
        frappe.ie_assets.requirements(frm);
        if (frm.doc.es_activo && !frm.doc.fecha_uso_activo) await frm.set_value("fecha_uso_activo", frm.doc.fecha_de_registro || frappe.datetime.get_today());
        if (frm.doc.es_activo) await frm.set_value("es_diferido", 0);
    },
    async es_diferido(frm) {
        if (ie_movement_locked(frm) || !frm.doc.es_diferido) return;
        await frm.set_value("es_activo", 0);
        if (!frm.doc.inicio_diferimiento) await frm.set_value("inicio_diferimiento", frm.doc.fecha_de_registro || frappe.datetime.get_today());
    }
});

function ie_movement_locked(frm) {
    return frm.doc.docstatus !== 0 || Boolean(frm.doc.turno_pos) || frm.doc.estado_contable === "Contabilizado";
}

async function ie_movement_concepts(frm) {
    const tipo = frm.doc.tipo;
    if (!tipo) return frm.set_df_property("clasificacion", "options", []);
    const result = await frappe.call({method: "ingresos_egresos.ingresos_y_egresos.doctype.movimiento.movimiento.get_code_name_options", args: {code_name: tipo}});
    if (frm.doc.tipo !== tipo) return;
    const options = result.message || [];
    // Preserve a saved classification even if its concept is later disabled.
    if (frm.doc.clasificacion && !options.includes(frm.doc.clasificacion)) options.push(frm.doc.clasificacion);
    frm.set_df_property("clasificacion", "options", options);
}
