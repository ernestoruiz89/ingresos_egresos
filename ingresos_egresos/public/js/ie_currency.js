frappe.provide("frappe.ie_currency");

Object.assign(frappe.ie_currency, {
    settings() {
        if (!this._settings) {
            this._settings = frappe.call({method: "ingresos_egresos.currency.get_currency_settings"})
                .then(r => r.message).catch(error => { this._settings = null; throw error; });
        }
        return this._settings;
    },
    fields(doc = {}, read_only = false) {
        return [
            {fieldname: "moneda", label: __("Moneda"), fieldtype: "Link", options: "Currency", reqd: 1, default: doc.moneda, read_only},
            {fieldname: "tasa_de_cambio", label: __("Tasa de Cambio"), fieldtype: "Float", precision: 9, reqd: 1,
                default: doc.tasa_de_cambio, read_only, description: __("Unidades de moneda base por 1 unidad de esta moneda.")},
            {fieldname: "moneda_base", label: __("Moneda Base"), fieldtype: "Link", options: "Currency", read_only: 1, default: doc.moneda_base},
            {fieldname: "importe_base", label: __("Importe Base"), fieldtype: "Float", precision: frappe.boot?.sysdefaults?.currency_precision || 2, read_only: 1, default: doc.importe_base}
        ];
    },
    value(target, field) { return typeof target.get_value === "function" ? target.get_value(field) : target.doc[field]; },
    calculate(target) {
        return target.set_value("importe_base", flt(this.value(target, "importe")) * flt(this.value(target, "tasa_de_cambio")));
    },
    async fetch_rate(target) {
        const seq = target._ie_rate_seq = (target._ie_rate_seq || 0) + 1;
        const moneda = this.value(target, "moneda");
        const fecha = this.value(target, "fecha_de_registro");
        await target.set_value("tasa_de_cambio", 0);
        if (!moneda) return;
        const settings = await this.settings();
        if (seq !== target._ie_rate_seq) return;
        await target.set_value("moneda_base", settings.moneda_base);
        const is_base = moneda === settings.moneda_base;
        if (target.set_df_property) target.set_df_property("tasa_de_cambio", "read_only", is_base ? 1 : 0);
        if (is_base) {
            await target.set_value("tasa_de_cambio", 1);
            this.calculate(target);
            return;
        }
        if (!fecha) return;
        const response = await frappe.call({method: "ingresos_egresos.currency.get_rate", args: {moneda, fecha_de_registro: fecha}});
        // A late response must not overwrite a manual rate or a changed currency/date.
        if (seq !== target._ie_rate_seq || flt(this.value(target, "tasa_de_cambio")) !== 0) return;
        if (response.message.tasa_de_cambio) {
            await target.set_value("tasa_de_cambio", response.message.tasa_de_cambio);
            this.calculate(target);
        } else {
            frappe.show_alert({message: __("No hay una tasa disponible. Introduzca la tasa de cambio manualmente."), indicator: "orange"});
        }
    },
    async bind_dialog(dialog, doc = {}, read_only = false) {
        const pair = () => [this.value(dialog, "moneda"), this.value(dialog, "fecha_de_registro")].join("|");
        let previous_pair = doc.moneda ? [doc.moneda, doc.fecha_de_registro || this.value(dialog, "fecha_de_registro")].join("|") : null;
        for (const name of ["moneda", "fecha_de_registro", "importe", "tasa_de_cambio"]) {
            const field = dialog.fields_dict[name];
            field.df.onchange = () => {
                if (read_only) return;
                if (["moneda", "fecha_de_registro"].includes(name)) {
                    if (!this.value(dialog, "moneda") || !this.value(dialog, "fecha_de_registro")) return;
                    const current_pair = pair();
                    // Dialog defaults also emit change events; opening a record must keep its saved rate.
                    if (current_pair === previous_pair) return;
                    previous_pair = current_pair;
                    return this.fetch_rate(dialog);
                }
                return this.calculate(dialog);
            };
        }
        const settings = await this.settings();
        await dialog.set_value("moneda_base", settings.moneda_base);
        if (!doc.moneda) {
            await dialog.set_value("moneda", settings.moneda_base);
            await this.fetch_rate(dialog);
        } else if (!read_only) dialog.set_df_property("tasa_de_cambio", "read_only", doc.moneda === settings.moneda_base ? 1 : 0);
    }
});
