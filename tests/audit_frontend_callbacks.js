/* Deterministic queue tests: every promise and helper lives in the same realm. */
const fs=require('fs'),vm=require('vm'),{createHash}=require('crypto');
const scenario=process.argv[2];
const source=`
globalThis.window={addEventListener(){}};globalThis.document={addEventListener(){}};
let serial=0;const crypto={randomUUID:()=> 'key-'+(++serial),subtle:{digest:async(_,bytes)=>Uint8Array.from(hash(Array.from(bytes))).buffer}};
`+fs.readFileSync(process.argv[3],'utf8')+`
const helper=window.ATLASImprovements;
const form=value=>({id:'',dataset:{cForm:'note'},elements:[{name:'body',type:'textarea',value}],isConnected:true,querySelector:()=>({textContent:''})});
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve}};
const check=(value,message)=>{if(!value)throw Error(message)};
async function run(){
 const state={user:{id:1},sessionEpoch:1,modalId:1},calls=[];let values={};
 let api=async(path,options={})=>{calls.push(options.method||'GET');if(options.method==='PUT')values=JSON.parse(options.body).values;if(options.method==='DELETE')values={};return {values};};
 helper.init({state,api:(...args)=>api(...args)});
 if(scenario==='strict-persistence'){
  api=async(path,options={})=>{calls.push(options.method||'GET');if(options.method==='PUT')throw Error('offline');return {values:{}}};let rejected=false;try{await helper.formSubmission(form('not sent'),{body:'not sent'})}catch(e){rejected=!e.stale}check(rejected&&calls.join(',')==='GET,PUT','Failed durable PUT must block the primary identity');
 }else if(scenario==='failed-initial-read'){
  const old={fingerprint:Array.from(hash(Array.from(new TextEncoder().encode(JSON.stringify({body:'same answer'}))))).map(x=>x.toString(16).padStart(2,'0')).join(''),key:'old-durable-key'};
  let broken=true;api=async(path,options={})=>{calls.push(options.method||'GET');if(!options.method){if(broken)throw Error('offline');return {values:{body:'same answer',_submission:JSON.stringify(old)}}}return {values:{}}};const f=form('same answer');f.dataset.draftEdited='true';let rejected=false;try{await helper.formSubmission(f,{body:'same answer'})}catch{rejected=true}check(rejected&&!calls.includes('PUT'),'Unread remote identity was overwritten');broken=false;const key=await helper.formSubmission(f,{body:'same answer'});check(key===old.key,'Retry after a failed read lost the existing durable key');
 }else if(scenario==='edited-before-restore'){
  const gate=deferred(),body={body:'same answer'},fingerprint=Array.from(hash(Array.from(new TextEncoder().encode(JSON.stringify(body))))).map(x=>x.toString(16).padStart(2,'0')).join('');api=async(path,options={})=>{if(!options.method){await gate.promise;return {values:{body:'old visible text',_submission:JSON.stringify({fingerprint,key:'already-committed-key'})}}}return {values:{}}};const f=form('');const restoring=helper.restoreFormDraft(f);f.dataset.draftEdited='true';f.elements[0].value=body.body;const preparing=helper.prepareFormSubmission(f);gate.resolve();await restoring;await preparing;check(f.elements[0].value===body.body,'Late restore replaced edited fields');const key=await helper.formSubmission(f,body);check(key==='already-committed-key','Edited fields discarded the durable matching remote key');
 }else if(scenario==='late-owner'){
  const gate=deferred(),started=deferred();crypto.subtle.digest=async()=>{started.resolve();await gate.promise;return new Uint8Array(32).buffer};const sending=helper.formSubmission(form('A text'),{body:'A text'});await started.promise;state.user={id:2};state.sessionEpoch++;helper.reset(false);gate.resolve();let rejected=false;try{await sending}catch(e){rejected=e.stale}check(rejected&&!calls.includes('PUT'),'Old identity reached a new owner');
 }else if(scenario==='restore-before-submit'){
  const gate=deferred();api=async(path,options={})=>{if(!options.method){await gate.promise;return {values:{body:'restored text'}}}return {values:{}}};const f=form('published text');helper.restoreFormDraft(f);let prepared=false;const preparing=helper.prepareFormSubmission(f).then(()=>prepared=true);await Promise.resolve();check(!prepared,'Preparation raced restore');gate.resolve();await preparing;check(f.elements[0].value==='restored text','Restoration did not precede body capture');const key=await helper.formSubmission(f,{body:f.elements[0].value});check(key===f._submission.key,'Submission key changed after save');
 }else if(scenario==='delete-serialized'){
  const gate=deferred(),started=deferred();const old=form('old');await helper.saveFormDraft(old);api=async(path,options={})=>{calls.push(options.method||'GET');if(options.method==='DELETE'){started.resolve();await gate.promise;values={};}if(options.method==='PUT')values=JSON.parse(options.body).values;return {values};};const clearing=helper.clearFormDraft(old);await started.promise;const edited=form('fresh');edited.dataset.draftEdited='true';const fresh=helper.saveFormDraft(edited);await Promise.resolve();check(calls.filter(x=>x!=='GET').at(-1)==='DELETE','New PUT overtook pending DELETE');gate.resolve();await clearing;await fresh;check(values.body==='fresh','Cleanup erased the new draft');
 }else if(scenario==='closed-during-hash'){
  const gate=deferred(),started=deferred(),f=form('closed');crypto.subtle.digest=async()=>{started.resolve();await gate.promise;return new Uint8Array(32).buffer};const sending=helper.formSubmission(f,{body:'closed'});await started.promise;f.isConnected=false;gate.resolve();let rejected=false;try{await sending}catch(e){rejected=e.stale}check(rejected&&!calls.includes('PUT'),'Detached form persisted a new submission identity');
 }else if(scenario==='logout-queued'){
  const gate=deferred(),started=deferred();api=async(path,options={})=>{if(!options.method)return {values:{}};calls.push({uid:state.user.id,method:options.method});started.resolve();await gate.promise;return {}};const old=form('old');const first=helper.saveFormDraft(old);await started.promise;old.elements[0].value='queued';const second=helper.saveFormDraft(old);helper.reset(false);state.sessionEpoch+=2;gate.resolve();await first;await second;check(calls.length===1,'Queued old job survived logout');
 }else if(scenario==='durable-replay'){
  const first=form('same answer'),body={body:'same answer'};const key=await helper.formSubmission(first,body);const reopened=form('');await helper.restoreFormDraft(reopened);await helper.prepareFormSubmission(reopened);const replay=await helper.formSubmission(reopened,body);check(key===replay,'Reload changed durable submission identity');
 }else throw Error('Unknown scenario');
 console.log(JSON.stringify({scenario,passed:true}));
}
run().catch(e=>{console.error(e);process.exitCode=1});
`;
vm.runInNewContext(source,{scenario,console,process,TextEncoder,setTimeout,clearTimeout,hash:bytes=>Array.from(createHash('sha256').update(Buffer.from(bytes)).digest())});
