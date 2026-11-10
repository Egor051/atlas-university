/* Exercise the shipped public renderer with canonical clock/date values. */
const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict');
const host={window:{},document:{addEventListener(){}},matchMedia:()=>({matches:false}),setTimeout,clearTimeout,Intl,Date,URLSearchParams};
vm.runInNewContext(fs.readFileSync(process.argv[2],'utf8'),host);
const day='2026-11-10';
const context={state:{page:'calendar',data:{},user:{id:1}},head:()=>'',icon:()=>'',esc:String,empty:()=>'',dateFmt:String,stamp:()=> '10 нояб., 17:00',today:()=>day,monday:()=> '2026-11-09',asDate:x=>new Date(x+'T12:00:00Z'),addDays:(x,n)=>new Date(Date.parse(x+'T12:00:00Z')+n*86400000).toISOString().slice(0,10)};
host.window.ATLASCampus.init(context);
const html=host.window.ATLASCampus.render('calendar',{
 schedule:{week_start:'2026-11-09',days:[{date:day,items:[{id:1,start:'16:00',title:'LESSON_AT_SIXTEEN',room:'Демо',teacher:'Вымышленный преподаватель'}]}]},
 assignments:{items:[]},exams:{items:[]},tasks:{items:[]},registrations:{items:[]},
 bookings:{items:[{id:5,slot_id:5,status:'active',slot:{subject:'CONSULTATION_AT_SEVENTEEN',start_at:day+'T14:00:00Z',room:'Демо'}}]}
});
assert(html.includes('16:00')&&html.includes('10 нояб., 17:00'));
assert(html.indexOf('LESSON_AT_SIXTEEN')<html.indexOf('CONSULTATION_AT_SEVENTEEN'),'A 17:00 localized label sorted before the 16:00 lesson');
console.log(JSON.stringify({scenario:'calendar-canonical-order',passed:true}));
