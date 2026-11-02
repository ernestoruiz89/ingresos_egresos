frappe.provide("frappe.ie_currency");

Object.assign(frappe.ie_currency, {
    settings(sucursal = null, refresh = false) {
        if (!(this._settings instanceof Map)) this._settings = new Map();
        const key = sucursal || "";
        if (refresh || !this._settings.has(key)) {
            const request = frappe.call({method: "ingresos_egresos.currency.get_currency_settings", args: {sucursal}})
                .then(r => r.message).catch(error => {if (this._settings.get(key) === request) this._settings.delete(key);throw error;});
            this._settings.set(key,request);
        }
        return this._settings.get(key);
    },
    multi(settings = {}) {return settings.permitir_multimoneda == null || Boolean(Number(settings.permitir_multimoneda));},
    async apply_policy(target, doc = {}, read_only = false, refresh = true) {
        const sequence = target._ie_policy_seq = (target._ie_policy_seq || 0) + 1;
        const settings = await this.settings(this.value(target,"sucursal"),refresh);
        if (sequence !== target._ie_policy_seq) return;
        target._ie_currency_settings = settings;
        const multi = this.multi(settings), saved = Boolean(doc.name) && !doc.__islocal;
        const old_currency = this.value(target,"moneda");
        const historical = !multi && saved && doc.moneda && doc.moneda !== settings.moneda_empresa;
        target._ie_currency_historical = Boolean(historical);
        target.set_df_property("moneda","read_only",read_only || !multi ? 1 : 0);
        target._ie_currency_applying = true;
        try {
            if (!read_only && !historical) {
                const currency = multi ? old_currency || settings.moneda_base : settings.moneda_empresa;
                if (currency) await target.set_value("moneda",currency);
                else if (!multi) {
                    await target.set_value("moneda","");
                    frappe.show_alert({message:__("Configure la compañía de la sucursal o la compañía predeterminada de ERPNext."),indicator:"orange"});
                }
            }
            if (target.fields_dict.moneda_base) await target.set_value("moneda_base",settings.moneda_base);
        } finally {target._ie_currency_applying=false;}
        if (target.fields_dict.tasa_de_cambio) {
            target.set_df_property("tasa_de_cambio","read_only",read_only || historical || this.value(target,"moneda") === settings.moneda_base ? 1 : 0);
            if (!read_only && !historical && (old_currency !== this.value(target,"moneda") || !flt(this.value(target,"tasa_de_cambio")))) await this.fetch_rate(target);
        }
        if (historical) for (const field of ["importe","tasa_de_cambio","fecha_de_registro"])
            if (target.fields_dict[field]) target.set_df_property(field,"read_only",1);
        return settings;
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
        const settings = target._ie_currency_settings || await this.settings(this.value(target,"sucursal"));
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
                if (read_only || dialog._ie_currency_applying || dialog._ie_currency_historical) return;
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
        await this.apply_policy(dialog,doc,read_only);
        previous_pair = pair();
    }
});
