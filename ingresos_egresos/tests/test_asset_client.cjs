const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');

function setup(lookup = async () => ({message:{categoria_activo:'Equipo',nombre_activo:'Equipo estándar',vida_util_meses:60,depreciable:true}})) {
    const frappe={ie_assets:{},provide(){},call:lookup};
    vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../public/js/ie_assets.bundle.js'),'utf8'),{frappe,__:v=>v});
    const target={values:{es_activo:1,item_activo:'A'},fields_dict:Object.fromEntries(['es_activo','item_activo','ubicacion_activo','fecha_uso_activo','vida_util_meses'].map(name=>[name,{df:{}}])),
        get_value(key){return this.values[key];},async set_value(key,value){this.values[key]=value;},
        set_df_property(key,property,value){this.fields_dict[key].df[property]=value;}};
    return {api:frappe.ie_assets,target};
}

test('saved useful life and individual asset name survive reopening',async()=>{
    const {api,target}=setup();target.values.nombre_activo='Refrigerador sucursal';target.values.vida_util_meses=24;
    await api.details(target,false);
    assert.equal(target.values.nombre_activo,'Refrigerador sucursal');assert.equal(target.values.vida_util_meses,24);
});

test('typing details while the item lookup runs preserves the user input',async()=>{
    let done;const response=new Promise(resolve=>done=resolve);
    const {api,target}=setup(()=>response);const pending=api.details(target,true);
    await target.set_value('nombre_activo','Caja nueva');await target.set_value('vida_util_meses',36);
    done({message:{categoria_activo:'Equipo',nombre_activo:'Nombre sugerido',vida_util_meses:60,depreciable:true}});
    await pending;assert.equal(target.values.nombre_activo,'Caja nueva');assert.equal(target.values.vida_util_meses,36);
});

test('a late item response cannot change the newly selected category',async()=>{
    let done;const first=new Promise(resolve=>done=resolve);
    const {api,target}=setup(args=>args.args.item_activo==='A'?first:Promise.resolve({message:{categoria_activo:'B',nombre_activo:'B',vida_util_meses:12,depreciable:true}}));
    const pending=api.details(target,true);target.values.item_activo='B';await api.details(target,true);
    done({message:{categoria_activo:'A',nombre_activo:'A',vida_util_meses:60,depreciable:true}});await pending;
    assert.equal(target.values.categoria_activo,'B');assert.equal(target.values.vida_util_meses,12);
});

test('ordinary expenses and non-depreciable assets do not require depreciation inputs',()=>{
    const {api,target}=setup();target.values.es_activo=0;api.requirements(target);
    assert.equal(target.fields_dict.item_activo.df.reqd,0);
    target.values.es_activo=1;target._asset_depreciable=false;api.requirements(target);
    assert.equal(target.fields_dict.item_activo.df.reqd,1);assert.equal(target.fields_dict.vida_util_meses.df.reqd,0);
});
