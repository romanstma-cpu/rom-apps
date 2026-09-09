import { useEffect, useState } from 'react';
import type { TraderConfig } from '@shared/types';
import { Card } from './common';
import { useApp } from '../state/AppStateProvider';
import { useToast } from '../state/ToastProvider';

const pick = (c: TraderConfig) => ({position: String(c.hardMaxPositionUsd), exposure: String(Math.round(c.maxTotalExposureFraction * 100)), reserve: String(Math.round(c.minCashReserveFraction * 100)), daily: String(Math.abs(c.stopLossOnDay || 0))});
export function RiskLimits({config, onDirty}: {config: TraderConfig; onDirty: (dirty: boolean) => void}) {
  const {refresh}=useApp();const toast=useToast();
  const [base,setBase]=useState(()=>pick(config));
  const [draft,setDraft]=useState(()=>pick(config));
  const [saving,setSaving]=useState(false);
  const incoming=pick(config);
  const dirty=JSON.stringify(draft)!==JSON.stringify(base);
  const conflict=dirty && JSON.stringify(incoming)!==JSON.stringify(base);
  useEffect(()=>{onDirty(dirty);},[dirty,onDirty]);
  useEffect(()=>{
    if(!dirty&&!saving&&JSON.stringify(incoming)!==JSON.stringify(base)){setBase(incoming);setDraft(incoming);}
  },[config,dirty,saving]);
  const values={position:Number(draft.position),exposure:Number(draft.exposure),reserve:Number(draft.reserve),daily:Number(draft.daily)};
  const valid=Object.values(draft).every(v=>v.trim()!=='') && Object.values(values).every(Number.isFinite) && values.position>=1 && values.exposure>=1 && values.exposure<=100 && values.reserve>=0 && values.reserve<=100 && values.exposure+values.reserve<=100 && values.daily>=0;
  const save=async()=>{
    if(!valid||conflict||saving)return;
    setSaving(true);
    try{await window.rom.config.update({hardMaxPositionUsd:values.position,maxTotalExposureFraction:values.exposure/100,minCashReserveFraction:values.reserve/100,stopLossOnDay:-values.daily});await refresh.state();setBase(draft);toast.success('Risk limits saved');}
    catch(e){toast.error(e instanceof Error?e.message:'Could not save limits');}
    finally{setSaving(false);}
  };
  const reset=()=>{setBase(incoming);setDraft(incoming);};
  return <Card className="mb-6">
    <h3 className="mb-2 font-semibold">Set your risk limits</h3><p className="mb-5 text-sm text-rom-muted">Edit comfortably. Nothing changes until you save.</p>
    <fieldset disabled={saving} className="grid gap-5 sm:grid-cols-2 xl:grid-cols-4">
      {([{key:'position',label:'Maximum per position ($)',help:'Most you can commit to one position.',min:1},{key:'exposure',label:'Portfolio exposure (%)',help:'Maximum share committed across positions.',min:1,max:100},{key:'reserve',label:'Keep as cash (%)',help:'Balance reserved for flexibility.',min:0,max:100},{key:'daily',label:'Daily loss stop ($)',help:'Pauses new main-strategy entries. 0 turns this limit off.',min:0}] as const).map(field=><label key={field.key} className="block text-xs font-medium text-rom-muted">{field.label}<input className="rom-input mt-2" type="number" min={field.min} max={'max' in field?field.max:undefined} step="any" value={draft[field.key]} onChange={e=>setDraft({...draft,[field.key]:e.target.value})}/><span className="mt-2 block text-[11px] font-normal leading-5 text-rom-dim">{field.help}</span></label>)}
    </fieldset>
    {conflict&&<p role="alert" className="mt-4 text-xs text-rom-warn">Settings changed elsewhere while you were editing. Discard your draft to load the current values before saving.</p>}
    {!valid&&<p role="alert" className="mt-4 text-xs text-rom-warn">Enter valid limits. Exposure plus cash reserve cannot exceed 100%.</p>}
    <div className="mt-5 flex flex-wrap items-center gap-3 border-t border-rom-border pt-5"><button className="rom-btn-primary" disabled={!dirty||!valid||conflict||saving} onClick={()=>void save()}>{saving?'Saving…':'Save limits'}</button><button className="rom-btn-default" disabled={!dirty||saving} onClick={reset}>Discard changes</button><span role="status" className="text-xs text-rom-dim">{dirty?'Unsaved changes':'Your saved limits are active'}</span></div>
    <p className="mt-4 text-[11px] leading-5 text-rom-dim">These controls apply to the main strategy. Daily loss stops do not guarantee a maximum loss; gaps, existing positions and separate engines can produce further losses.</p>
  </Card>;
}
