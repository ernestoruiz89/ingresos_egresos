frappe.provide("frappe.ie_assets");
Object.assign(frappe.ie_assets, {
    fields(tipo, doc = {}, read_only = false) {
        if (tipo !== "Egreso") return [];
        return [
            {fieldtype: "Section Break"},
            {fieldtype: "Check", fieldname: "es_activo", label: __("Es activo fijo"), default: doc.es_activo || 0, read_only},
            {fieldtype: "Section Break", label: __("Activo fijo"), depends_on: "es_activo"},
            {fieldtype: "Link", fieldname: "item_activo", label: __("Artículo de activo fijo"), options: "Item", default: doc.item_activo,
                read_only, get_query: () => ({filters: {is_fixed_asset: 1, is_stock_item: 0, disabled: 0}})},
            {fieldtype: "Data", fieldname: "nombre_activo", label: __("Nombre del activo"), default: doc.nombre_activo, read_only},
            {fieldtype: "Link", fieldname: "categoria_activo", label: __("Categoría"), options: "Asset Category", default: doc.categoria_activo, read_only: 1},
            {fieldtype: "Column Break"},
            {fieldtype: "Link", fieldname: "ubicacion_activo", label: __("Ubicación"), options: "Location", default: doc.ubicacion_activo, read_only},
            {fieldtype: "Date", fieldname: "fecha_uso_activo", label: __("Disponible para uso desde"), default: doc.fecha_uso_activo, read_only},
            {fieldtype: "Int", fieldname: "vida_util_meses", label: __("Vida útil en meses"), description: __("Depreciación lineal mensual."), default: doc.vida_util_meses, read_only},
            {fieldtype: "Currency", fieldname: "valor_residual", label: __("Valor residual"), options: "moneda", default: doc.valor_residual || 0, read_only}
        ];
    },
    value(target, name) {return typeof target.get_value === "function" ? target.get_value(name) : target.doc[name];},
    async details(target, changed = false) {
        const item = this.value(target, "item_activo");
        if (!item) return;
        const before = {nombre: this.value(target, "nombre_activo"), vida: this.value(target, "vida_util_meses")};
        const sequence = target._asset_sequence = (target._asset_sequence || 0) + 1;
        const options = (await frappe.call({method: "ingresos_egresos.asset_integration.get_options", args: {item_activo: item}})).message;
        if (sequence !== target._asset_sequence) return;
        await target.set_value("categoria_activo", options.categoria_activo);
        if (!this.value(target, "nombre_activo") || changed && this.value(target, "nombre_activo") === before.nombre)
            await target.set_value("nombre_activo", options.nombre_activo);
        if (!this.value(target, "vida_util_meses") || changed && this.value(target, "vida_util_meses") === before.vida)
            await target.set_value("vida_util_meses", options.vida_util_meses);
        target._asset_depreciable = options.depreciable;
        this.requirements(target);
    },
    requirements(target) {
        const active = Boolean(this.value(target, "es_activo"));
        for (const name of ["item_activo", "ubicacion_activo", "fecha_uso_activo"])
            if (target.fields_dict[name]) target.set_df_property(name, "reqd", active ? 1 : 0);
        if (target.fields_dict.vida_util_meses) {
            target.set_df_property("vida_util_meses", "reqd", active && target._asset_depreciable !== false ? 1 : 0);
            target.set_df_property("vida_util_meses", "hidden", target._asset_depreciable === false ? 1 : 0);
        }
    },
    bind(target, doc = {}) {
        if (!target.fields_dict.es_activo) return;
        const item = target.fields_dict.item_activo;
        const enabled = target.fields_dict.es_activo;
        if (target.doc?.doctype !== "Movimiento") {
            item.df.onchange = () => this.details(target, true);
            enabled.df.onchange = async () => {
                this.requirements(target);
                if (this.value(target, "es_activo") && !this.value(target, "fecha_uso_activo"))
                    await target.set_value("fecha_uso_activo", this.value(target, "fecha_de_registro") || frappe.datetime.get_today());
            };
        }
        this.requirements(target);
        if (doc.es_activo && doc.item_activo) this.details(target, false);
    }
});
