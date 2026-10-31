const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');

function setup(rateLookup = async () => ({message: {tasa_de_cambio: 36.5}})) {
    const alerts = [];
    const calls = [];
    const frappe = {ie_currency: {}, provide() {}, show_alert: value => alerts.push(value),
        call: async args => {
            calls.push(args);
            if (args.method.endsWith('get_currency_settings')) return {message: {moneda_base: 'NIO'}};
            return rateLookup(args);
        }};
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../public/js/ie_currency.js'), 'utf8'),
        {frappe, flt: value => Number(value) || 0, __: value => value});
    const target = (values = {}) => ({
        doc: {}, // Frappe dialogs carry an empty layout doc unrelated to control values.
        values: {fecha_de_registro: '2026-01-05', importe: 10, ...values},
        fields_dict: Object.fromEntries(['moneda', 'fecha_de_registro', 'importe', 'tasa_de_cambio'].map(key => [key, {df: {}}])),
        get_value(key) { return this.values[key]; },
        async set_value(key, value) {
            const changed = this.values[key] !== value;
            this.values[key] = value;
            if (changed && this.fields_dict[key]?.df.onchange) await this.fields_dict[key].df.onchange();
        },
        set_df_property(key, prop, value) { this.fields_dict[key].df[prop] = value; }
    });
    return {api: frappe.ie_currency, target, alerts, calls};
}

test('base currency always uses one and converts a zero amount', async () => {
    const {api, target} = setup();
    const form = target({moneda: 'NIO', tasa_de_cambio: 999, importe: 0});
    await api.fetch_rate(form);
    assert.equal(form.get_value('tasa_de_cambio'), 1);
    assert.equal(form.get_value('importe_base'), 0);
    assert.equal(form.fields_dict.tasa_de_cambio.df.read_only, 1);
});

test('lookup uses the selected date and direction', async () => {
    const {api, target, calls} = setup();
    const form = target({moneda: 'USD'});
    await api.fetch_rate(form);
    assert.equal(form.get_value('importe_base'), 365);
    assert.equal(calls[1].args.moneda, 'USD');
    assert.equal(calls[1].args.fecha_de_registro, '2026-01-05');
});

test('a manual rate entered during lookup survives the response', async () => {
    let resolve;
    const response = new Promise(done => resolve = done);
    const {api, target} = setup(() => response);
    const form = target({moneda: 'USD'});
    const pending = api.fetch_rate(form);
    await new Promise(setImmediate);
    await form.set_value('tasa_de_cambio', 37);
    resolve({message: {tasa_de_cambio: 36.5}});
    await pending;
    assert.equal(form.get_value('tasa_de_cambio'), 37);
});

test('a late response cannot overwrite a newly selected currency', async () => {
    let resolve;
    const response = new Promise(done => resolve = done);
    const {api, target} = setup(() => response);
    const form = target({moneda: 'USD'});
    const pending = api.fetch_rate(form);
    await new Promise(setImmediate);
    await form.set_value('moneda', 'NIO');
    await api.fetch_rate(form);
    resolve({message: {tasa_de_cambio: 36.5}});
    await pending;
    assert.equal(form.get_value('tasa_de_cambio'), 1);
});

test('missing exchange rate clears the old rate and asks for manual entry', async () => {
    const {api, target, alerts} = setup(async () => ({message: {tasa_de_cambio: null}}));
    const form = target({moneda: 'USD', tasa_de_cambio: 1});
    await api.fetch_rate(form);
    assert.equal(form.get_value('tasa_de_cambio'), 0);
    assert.equal(alerts.length, 1);
});

test('opening an existing movement preserves its historical manual rate', async () => {
    const {api, target, calls} = setup();
    const doc = {moneda: 'USD', tasa_de_cambio: 35.75};
    const dialog = target(doc);
    await api.bind_dialog(dialog, doc);
    assert.equal(dialog.get_value('tasa_de_cambio'), 35.75);
    assert.equal(calls.length, 1);
    await dialog.set_value('importe', 20);
    assert.equal(dialog.get_value('importe_base'), 715);
});

test('new dialog gets base rate one even before its date default settles', async () => {
    const {api, target} = setup();
    const dialog = target({fecha_de_registro: undefined});
    await api.bind_dialog(dialog);
    assert.equal(dialog.get_value('moneda'), 'NIO');
    assert.equal(dialog.get_value('tasa_de_cambio'), 1);
});

test('initial date and currency change events preserve a stored manual rate', async () => {
    const {api, target, calls} = setup();
    const doc = {moneda: 'USD', tasa_de_cambio: 35.75, fecha_de_registro: '2026-01-05'};
    const dialog = target(doc);
    await api.bind_dialog(dialog, doc);
    await dialog.fields_dict.moneda.df.onchange();
    await dialog.fields_dict.fecha_de_registro.df.onchange();
    assert.equal(dialog.get_value('tasa_de_cambio'), 35.75);
    assert.equal(calls.length, 1);
    await dialog.set_value('fecha_de_registro', '2026-01-06');
    assert.equal(calls.length, 2);
});
