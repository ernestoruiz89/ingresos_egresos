const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function setup({missing = [], gate = Promise.resolve()} = {}) {
    const buttons = new Map(), dialogs = [], messages = [], requested = [];
    const jquery = selector => ({
        find: query => jquery(query), append() {return this;}, html() {return this;},
        on(event, callback) {buttons.set(selector + ':' + event, callback); return this;},
        prop() {return this;}
    });
    const page = {add_field(df) {return {get_value: () => df.fieldname === 'sucursal' ? 'Sucursal QA' : df.default};}};
    const frappe = {pages: {'dashboard-movimientos': {}}, boot: {assets_json: {}},
        provide(name) {this[name.split('.')[1]] ||= {};}, msgprint: message => messages.push(message),
        datetime: {get_today: () => '2026-10-31'},
        ui: {make_app_page: () => page, Dialog: class {
            constructor(options) {
                this.options = options; this.values = {}; this.fields_dict = {}; this.doc = {};
                for (const df of options.fields) {
                    assert.ok(df, 'a dialog field must not be undefined');
                    if (df.fieldname) {
                        this.values[df.fieldname] = df.default;
                        this.fields_dict[df.fieldname] = {df, $wrapper: jquery(df.fieldname)};
                    }
                }
                dialogs.push(this);
            }
            get_value(name) {return this.values[name];}
            async set_value(name, value) {this.values[name] = value;}
            set_df_property(name, key, value) {this.fields_dict[name].df[key] = value;}
            show() {this.display = true; sandbox.cur_dialog = this;}
            hide() {this.display = false;}
        }},
        call: async args => {
            if (args.method.endsWith('get_code_name_options')) args.callback({message: ['Otros']});
            return {message: args.method.endsWith('get_currency_settings') ? {moneda_base: 'NIO'} : {}};
        }
    };
    const sandbox = {frappe, $: jquery, __: value => value, flt: value => Number(value) || 0,
        cur_dialog: null, localStorage: {getItem: () => null, setItem() {}}};
    vm.createContext(sandbox);
    frappe.require = async items => {
        await gate;
        for (const item of items) {
            requested.push(item);
            // Reproduce Frappe's resolved-on-error behavior and an unavailable bundle manifest.
            if (item.includes('.bundle.') || missing.includes(path.basename(item))) continue;
            assert.ok(item.startsWith('/assets/ingresos_egresos/js/'));
            vm.runInContext(fs.readFileSync(path.join(__dirname, '../public/js', path.basename(item)), 'utf8'), sandbox);
        }
    };
    vm.runInContext(fs.readFileSync(path.join(__dirname,
        '../ingresos_y_egresos/page/dashboard_movimientos/dashboard_movimientos.js'), 'utf8'), sandbox);
    return {load: () => frappe.pages['dashboard-movimientos'].on_page_load({}), buttons, dialogs, messages, requested};
}

test('entry and expense dialogs open without any compiled app bundles or manifest', async () => {
    const app = setup(); await app.load();
    for (const [button, title] of [['entrada', 'Ingreso'], ['salida', 'Egreso']]) {
        app.buttons.get('#btn-registrar-' + button + ':click')();
        await new Promise(setImmediate);
        const dialog = app.dialogs.at(-1);
        assert.equal(dialog.options.title, 'Registrar ' + title);
        assert.equal(dialog.display, true);
        assert.ok(dialog.fields_dict.es_diferido);
        assert.equal(dialog.values.moneda, 'NIO');
        assert.equal(dialog.values.tasa_de_cambio, 1);
        if (title === 'Egreso') assert.ok(dialog.fields_dict.es_activo);
        dialog.hide();
    }
    assert.equal(app.messages.length, 0);
    assert.ok(app.requested.every(item => !item.includes('.bundle.')));
});

test('quick actions are not enabled before their helper scripts finish loading', async () => {
    let release;
    const gate = new Promise(resolve => {release = resolve;});
    const app = setup({gate}); const pending = app.load();
    assert.equal(app.buttons.has('#btn-registrar-entrada:click'), false);
    release(); await pending;
    app.buttons.get('#btn-registrar-entrada:click')();
    await new Promise(setImmediate);
    assert.equal(app.dialogs[0].display, true);
});

test('a failed helper load produces an actionable message instead of an undefined fields error', async () => {
    for (const script of ['ie_currency.js', 'ie_assets.js', 'ie_deferred.js']) {
        const app = setup({missing: [script]});
        await app.load();
        assert.equal(app.dialogs.length, 0);
        assert.equal(app.buttons.has('#btn-registrar-entrada:click'), false);
        assert.equal(app.messages.length, 1);
        assert.match(app.messages[0].message, /recargue la página/);
    }
});
