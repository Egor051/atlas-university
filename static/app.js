/* ATLAS Campus · native client. Personal data comes only from the authenticated API. */
(() => {
  'use strict';
  const $ = (s, root = document) => root.querySelector(s);
  const $$ = (s, root = document) => [...root.querySelectorAll(s)];
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const paths = {
    home:'<rect x="3" y="3" width="7" height="7" rx="2"/><rect x="14" y="3" width="7" height="7" rx="2"/><rect x="3" y="14" width="7" height="7" rx="2"/><rect x="14" y="14" width="7" height="7" rx="2"/>',
    calendar:'<rect x="3" y="5" width="18" height="16" rx="3"/><path d="M16 3v4M8 3v4M3 10h18"/>',
    graduation:'<path d="m2 9 10-5 10 5-10 5L2 9ZM6 11v5c3 3 9 3 12 0v-5M22 9v7"/>',
    file:'<path d="M13 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V10l-7-7Z"/><path d="M13 3v7h7M8 15h8M8 18h5"/>',
    bell:'<path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4"/>',
    user:'<circle cx="12" cy="8" r="4"/><path d="M4 21c0-5 3-7 8-7s8 2 8 7"/>',
    arrow:'<path d="M5 12h14m-7-7 7 7-7 7"/>',
    right:'<path d="m9 18 6-6-6-6"/>', left:'<path d="m15 18-6-6 6-6"/>',
    clock:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    pin:'<path d="M20 10c0 5-8 12-8 12S4 15 4 10a8 8 0 1 1 16 0Z"/><circle cx="12" cy="10" r="2.5"/>',
    check:'<path d="m4 12 5 5L20 6"/>',
    checkCircle:'<circle cx="12" cy="12" r="9"/><path d="m7 12 3 3 7-7"/>',
    alert:'<path d="m10.5 3-9 16a1.5 1.5 0 0 0 1.5 2h18a1.5 1.5 0 0 0 1.5-2l-9-16a1.5 1.5 0 0 0-3 0ZM12 9v5M12 18h.01"/>',
    search:'<circle cx="10.5" cy="10.5" r="6.5"/><path d="m15.5 15.5 5 5"/>',
    close:'<path d="m5 5 14 14M19 5 5 19"/>',
    logout:'<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/>',
    shield:'<path d="m12 2-8 4v6c0 5 4 8 8 10 4-2 8-5 8-10V6l-8-4Z"/><path d="m8 12 3 3 5-6"/>',
    info:'<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 7h.01"/>',
    send:'<path d="m22 2-7 20-4-9-9-4 20-7ZM22 2 11 13"/>',
    sparkles:'<path d="m12 2 2.7 7.3L22 12l-7.3 2.7L12 22l-2.7-7.3L2 12l7.3-2.7L12 2Z"/>',
    plan:'<rect x="4" y="3" width="16" height="18" rx="3"/><path d="m8 8 1 1 2-2M14 8h3m-9 5 1 1 2-2M14 13h3M8 18h9"/>',
    download:'<path d="M12 3v12m-5-5 5 5 5-5M4 16v4h16v-4"/>',
    refresh:'<path d="M3 11a9 9 0 0 1 15-6l3 3M21 3v5h-5M21 13a9 9 0 0 1-15 6l-3-3M3 21v-5h5"/>',
    plus:'<path d="M12 5v14M5 12h14"/>', book:'<path d="M3 5c3-1 6-1 9 1 3-2 6-2 9-1v14c-3-1-6-1-9 1-3-2-6-2-9-1V5ZM12 6v14"/>',
    menu:'<path d="M4 6h16M4 12h16M4 18h16"/>',
    sidebar:'<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16m7-11-3 3 3 3"/>',
    megaphone:'<path d="m5 9 14-5v14L5 14H3V9h2Zm1 5 2 6h3l-2-5M22 9v4"/>',
    certificate:'<rect x="3" y="4" width="18" height="14" rx="2"/><path d="M7 8h6m-6 4h4m3 4v5l2-1 2 1v-5"/><circle cx="16" cy="13" r="3"/>',
    books:'<path d="M3 4h4v16H3zm4 0h4v16H7zm6 2 4-1 4 14-4 1-4-14Z"/>',
    copy:'<rect x="8" y="7" width="12" height="14" rx="2"/><path d="M16 7V5a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h2"/>',
    clipboard:'<rect x="5" y="5" width="14" height="16" rx="2"/><rect x="9" y="3" width="6" height="4" rx="1"/><path d="M9 11h6m-6 4h6"/>',
    wallet:'<path d="M21 8V6a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-2"/><path d="M21 8h-6a4 4 0 0 0 0 8h6Zm-5 4h.01"/>',
    chat:'<path d="M20 15a2 2 0 0 1-2 2H9l-5 4V6a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2ZM8 8h8m-8 4h5"/>',
    users:'<circle cx="9" cy="8" r="3"/><path d="M2 20v-2a5 5 0 0 1 5-5h4a5 5 0 0 1 5 5v2m0-15a3 3 0 0 1 0 6m3 3a4 4 0 0 1 3 4v2"/>',
  };
  const icon = (name, extra = '') => `<svg class="icon ${extra}" viewBox="0 0 24 24" aria-hidden="true">${paths[name] || paths.info}</svg>`;
  const pages = [
    {id:'home',label:'Мой день',icon:'home',hint:'Ближайшая пара и важное'},
    {id:'schedule',label:'Расписание',icon:'calendar',hint:'Неделя, день, аудитории'},
    {id:'grades',label:'Успеваемость и посещаемость',icon:'graduation',hint:'Оценки, баллы, посещения и результаты аттестации'},
    {id:'plan',label:'Мой план',icon:'plan',hint:'Личные отметки выполнения учебных заданий'},
    {id:'requests',label:'Заявки',icon:'file',hint:'Подать обращение и отследить решение'},
    {id:'notifications',label:'Уведомления',icon:'bell',hint:'Новости и изменения'},
    {id:'profile',label:'Профиль',icon:'user',hint:'Моя группа и безопасность'},
    {id:'certificates',label:'Справки',icon:'certificate',hint:'Заказать и получить документ'},
  ];
  const statusNames = {submitted:'Отправлена',review:'На рассмотрении',processing:'В работе',needs_info:'Нужны уточнения',ready:'Готово',rejected:'Отклонена'};
  const campus = window.ATLASCampus;
  const improvements=window.ATLASImprovements;
  const university=window.ATLASUniversity;
  const operations=window.ATLASOperations;
  const extensions=[university,operations,window.ATLASUnits,window.ATLASAnnouncements].filter(Boolean);
  const extensionFor=page=>extensions.find(ext=>ext.has(page));
  const extensionPages=role=>extensions.flatMap(ext=>ext.pages.filter(p=>p.roles.includes(role)));
  const profile=pages.find(p=>p.id==='profile');
  const notifications=pages.find(p=>p.id==='notifications');
  const settings=campus.pages.find(p=>p.id==='settings');
  pages.push(...campus.pages.filter(p=>!p.staff&&p.id!=='campus'));
  const staffPages = [{id:'staff',label:'Учебный офис',icon:'file',hint:'Очередь заявлений и справок'},...campus.pages.filter(p=>p.staff),profile,settings,notifications];
  const section = (id,label,icon,hint,children) => ({id,label,icon,hint,children});
  const account = section('account','Мой кабинет','user','Профиль и настройки',['profile','settings']);
  const planningOffice = section('schedule-work','Организация занятий','calendar','Расписание, согласование и справочники',['timetable-admin','schedule-changes','registry','tables']);
  const sections = {
    student:[
      section('records','Занятия и оценки','graduation','Расписание, оценки, посещаемость и экзамены',['schedule','grades','exams']),
      section('learning','Учебные материалы и задания','book','Дисциплины, учебные материалы, задания и конспекты',['courses','materials','assignments','notes']),
      section('planning','Планирование','plan','Календарь, сроки и личные инструменты',['calendar','plan','tasks']),
      section('administration','Заявки и документы','file','Заявки, справки, финансы и правила',['requests','certificates','finance','knowledge']),
      section('communications','Переписка и консультации','send','Личная переписка, обращения и консультации',['direct','messages','consultations']),
      section('university-life','Университет','pin','Институты, кафедры и подразделения',['university','contacts','union','vuc']),
      section('campus-life','Вне учёбы','sparkles','Кружки и мероприятия',['events']),
      {...account,children:['profile','portfolio','settings']},
    ],
    staff:[
      section('office','Работа со студентами','file','Заявки, справки, объявления и ответы студентам',['staff','staffdesk','staffmessages','announcement-admin']),
      planningOffice,
      section('learning','Материалы','book','Учебные материалы и публикации',['materials','materials-admin']),
      account,
    ],
    teacher:[
      section('academic-work','Учебная работа','graduation','Группы, ведомости, расписание и консультации',['teaching','teach-schedule','teach-consultations','tables']),
      section('learning','Материалы','book','Учебные материалы и публикации',['materials','materials-admin']),
      account,
    ],
    scheduler:[planningOffice,account],
    admin:[planningOffice,account],
    union:[section('union-work','Работа профсоюза','file','Заявления, членство, публикации и отчёты',['union-office']),account],
    vuc:[section('vuc-work','Работа ВУЦ','file','Отбор, учебные группы и публикации',['vuc-office']),account],
  };
  pages.push(...extensionPages('student'));
  staffPages.push(...extensionPages('staff'));
  const menuIcons={exams:'certificate',materials:'copy',tasks:'checkCircle',finance:'wallet',messages:'chat',staffmessages:'chat',teaching:'users',registry:'pin',university:'home','announcement-admin':'megaphone',announcements:'megaphone'};
  const menuFor = role => (role==='student'?pages:role==='staff'?staffPages:
    [profile,settings,notifications,...extensionPages(role)]).map(p=>menuIcons[p.id]?{...p,icon:menuIcons[p.id]}:p);
  const sectionChildren = group => {
    const menu=menuFor(state.user.role);
    return group.children.map(id=>menu.find(p=>p.id===id)).filter(Boolean);
  };
  const startPage = role => ({student:'home',staff:'staff',teacher:'teacher',scheduler:'timetable-admin',admin:'registry',union:'union-office',vuc:'vuc-office'})[role];
  const transitions = {submitted:['review','needs_info','rejected'],review:['processing','needs_info','ready','rejected'],processing:['ready','needs_info','rejected'],needs_info:['review','rejected'],ready:[],rejected:[]};
  const pageTitle = page => menuFor(state.user.role).find(p=>p.id===page)?.label;
  const state = {user:null,sessionEpoch:0,page:'home',routeHref:'/',routeParts:[],routeContext:{},historyEntry:0,data:{},week:null,day:null,scheduleMode:matchMedia('(max-width: 700px)').matches?'day':'week',unread:0,requestFilter:'all',requestView:'mine',serviceQuery:'',planFilter:'active',noticeFilter:'all',staffFilter:'active',staffQuery:'',config:{demo_mode:false},loadingId:0,modalId:0,pending:0,requestOffset:0,noticeOffset:0,staffOffset:0};
  const app = $('#app');
  const drawerMedia=matchMedia('(max-width: 900px)');
  const reducedMotion=matchMedia('(prefers-reduced-motion: reduce)');
  let openNavGroup=null, drawerFocus=null, navScrollTimer;
  let lastFocus, pollTimer, searchTimer, globalSearchTimer;
  let reminderCheckedAt=0, badgePoll;
  let staffSearchId=0;
  const deadlineWrites=new Map();
  const moscowParts = () => Object.fromEntries(new Intl.DateTimeFormat('en-CA',{timeZone:'Europe/Moscow',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(new Date()).map(p => [p.type,p.value]));
  const today = () => {const p=moscowParts();return `${p.year}-${p.month}-${p.day}`;};
  const asDate = value => new Date(`${String(value).slice(0,10)}T12:00:00`);
  const isoDate = d => `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
  const addDays = (value,n) => {const d=asDate(value);d.setDate(d.getDate()+n);return isoDate(d);};
  const monday = value => addDays(value,-((asDate(value).getDay()+6)%7));
  const dateFmt = (value,opts={day:'numeric',month:'long'}) => value ? new Intl.DateTimeFormat('ru-RU',opts).format(asDate(value)) : 'Срок уточняется';
  const stamp = value => {if(!value)return '';const v=/Z$|[+-]\d{2}:\d{2}$/.test(value)?value:value+'Z';return new Intl.DateTimeFormat('ru-RU',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit',timeZone:'Europe/Moscow'}).format(new Date(v));};
  const timestampDate=(value,opts={day:'numeric',month:'short'})=>new Intl.DateTimeFormat('ru-RU',{...opts,timeZone:'Europe/Moscow'}).format(new Date(/Z$|[+-]\d{2}:\d{2}$/.test(value)?value:value+'Z'));
  const dueDays = value => Math.round((asDate(value)-asDate(today()))/86400000);
  const relative = value => {const n=dueDays(value);return n<0?`Просрочено на ${-n} дн.`:n===0?'Сегодня':n===1?'Завтра':`Через ${n} дн.`;};
  const greeting = () => {const h=Number(moscowParts().hour);return h<11?'Доброе утро':h<17?'Добрый день':'Добрый вечер';};
  state.week=monday(today());state.day=today();

  function toast(message) {const el=$('#toast');el.textContent='';const box=document.createElement('div');box.className='toast-message';box.textContent=message;el.append(box);clearTimeout(toast.timer);toast.timer=setTimeout(()=>el.replaceChildren(),5000);}
  async function api(path,options={}) {
    const method=options.method||'GET';
    const epoch=state.sessionEpoch;
    const uid=state.user?.id;
    const controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),18000);
    let response,data;
    try {
      response=await fetch('/api/'+path,{...options,method,credentials:'same-origin',cache:'no-store',signal:controller.signal,headers:{...(options.body?{'Content-Type':'application/json'}:{}),...(method!=='GET'?{'X-Requested-With':'ATLAS'}:{}),...(uid&&!['login','me','config','health','ready'].includes(path.split('?')[0])?{'X-ATLAS-User':String(uid)}:{}),...options.headers}});
      data=options.responseType==='blob'&&response.ok?await response.blob():await response.json();
    }
    catch(error){
      if(epoch!==state.sessionEpoch)throw Object.assign(new Error('Сеанс изменился.'),{stale:true});
      throw new Error(error.name==='AbortError'?'Сервер отвечает слишком долго. Повторите действие.':response?'Сервер вернул неполный ответ. Обновите раздел или повторите действие.':'Не удалось связаться с сервером. Проверьте подключение и повторите.');
    }
    finally{clearTimeout(timeout);}
    if(epoch!==state.sessionEpoch||uid!==state.user?.id)throw Object.assign(new Error('Сеанс изменился.'),{stale:true});
    if(!response.ok){
      if(response.status===409&&data.detail?.code==='account_changed'){improvements.captureRecovery();clearSession({expired:true});showLogin();toast(data.detail.message||'Аккаунт изменился в другой вкладке. Войдите снова.');throw Object.assign(new Error('Аккаунт изменился.'),{stale:true});}
      if(response.status===401 && !options.quietAuth && !['login','logout','me'].includes(path)){improvements.captureRecovery();clearSession({expired:true});showLogin();toast('Сессия завершилась. Войдите снова: ваш ввод можно восстановить для этого же аккаунта.');}
      const error=new Error(typeof data.detail==='string'?data.detail:data.detail?.message?data.detail.message:response.status===422?'Проверьте заполненные поля. Не используйте лишние или слишком длинные значения.':'Не удалось выполнить действие.');error.status=response.status;error.fields=data.errors||[];error.details=data.detail;throw error;
    }
    if(options.responseType==='blob')return {blob:data,disposition:response.headers.get('Content-Disposition')||''};
    return data;
  }
  async function downloadFile(link){
    const path=link.getAttribute('href').slice('/api/'.length);link.setAttribute('aria-busy','true');
    try{const {blob,disposition}=await api(path,{responseType:'blob'});const encoded=disposition.match(/filename\*=UTF-8''([^;]+)/i);const plain=disposition.match(/filename="?([^";]+)"?/i);let filename=plain?.[1]||link.getAttribute('download')||path.split('?')[0].split('/').at(-1)||'atlas-download';if(encoded){try{filename=decodeURIComponent(encoded[1]);}catch{/* The server's plain filename remains usable. */}}const url=URL.createObjectURL(blob),anchor=document.createElement('a');anchor.href=url;anchor.download=filename;anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
    catch(error){if(!error.stale)toast(error.message);}
    finally{link.removeAttribute('aria-busy');}
  }
  let identityCheck=null;
  const tabIdentity=crypto.randomUUID();
  const identityChannel=typeof BroadcastChannel==='function'?new BroadcastChannel('atlas-session'):null;
  function announceIdentity(){const message={tab:tabIdentity,at:Date.now(),nonce:crypto.randomUUID()};identityChannel?.postMessage(message);try{localStorage.setItem('atlas-session-change',JSON.stringify(message));}catch{/* The server owner fence also protects browsers with blocked storage. */}}
  async function revalidateIdentity(){if(identityCheck||!state.user)return identityCheck;const uid=state.user.id,epoch=state.sessionEpoch;identityCheck=(async()=>{try{const user=await api('me',{quietAuth:true});if(epoch===state.sessionEpoch&&uid===state.user?.id&&user.id!==uid){improvements.captureRecovery();clearSession({expired:true});showLogin();toast('Аккаунт изменился в другой вкладке. Войдите снова, чтобы продолжить.');}}catch(error){if(!error.stale&&error.status===401&&epoch===state.sessionEpoch){improvements.captureRecovery();clearSession({expired:true});showLogin();}}finally{identityCheck=null;}})();return identityCheck;}
  identityChannel?.addEventListener('message',event=>{if(event.data?.tab!==tabIdentity)revalidateIdentity();});
  window.addEventListener('storage',event=>{if(event.key==='atlas-session-change')revalidateIdentity();});
  window.addEventListener('focus',revalidateIdentity);
  async function load(page) {
    const extension=extensionFor(page);
    if(extension)return extension.load(page,state.routeParts,state.routeContext);
    if(campus.has(page))return campus.load(page);
    if(page==='home'){
      const [dashboard,announcements]=await Promise.all([api('dashboard'),window.ATLASAnnouncements.homeFeed()]);
      return {...dashboard,announcements};
    }
    if(page==='schedule')return api('schedule?week='+state.week);
    if(page==='grades')return api('learning/progress');
    if(page==='plan')return api('deadlines');
    if(['requests','certificates'].includes(page)){
      const kind=page==='certificates'?'certificate':'request';
      const [result,types]=await Promise.all([
        api(`requests?paginated=true&limit=30&offset=${state.requestOffset}&filter=${state.requestFilter}&kind=${kind}`),
        api('requests/types?kind='+kind)
      ]);
      return {...result,types,kind};
    }
    if(page==='notifications')return api(`notifications?paginated=true&limit=30&offset=${state.noticeOffset}&filter=${state.noticeFilter}`);
    if(page==='staff')return api(`staff/requests?paginated=true&limit=30&offset=${state.staffOffset}&filter=${state.staffFilter}&kind=${state.staffKind||'request'}&q=${encodeURIComponent(state.staffQuery)}`);
    return state.user;
  }
  const contextPages=new Set(['schedule','calendar','courses','assignments','grades','exams','tasks','events','consultations','messages','staffmessages','notes','portfolio']);
  const pagePath=page=>page==='notes'?'/app/learning/notes':'/app/'+page;
  function cleanContext(page, context){
    if(!contextPages.has(page))return {};
    const result={};
    const id=Number(context.id);
    if(Number.isSafeInteger(id)&&id>0)result.id=id;
    if(/^\d{4}-\d{2}-\d{2}$/.test(context.date||'')&&Math.abs(dueDays(context.date))<=360&&isoDate(asDate(context.date))===context.date)result.date=context.date;
    if(context.subject?.trim())result.subject=context.subject.trim().slice(0,130);
    if(context.kind?.trim())result.kind=context.kind.trim().slice(0,40);
    return result;
  }
  function routeFromUrl(url=location){
    const [prefix,initial,...rest]=url.pathname.split('/').filter(Boolean);
    const query=new URLSearchParams(url.search);
    if(prefix!=='app')return {};
    const legacyStudentSections={learning:['library','flashcards','quizzes'],planning:['notes','focus'],records:['attendance']};
    if(state.user.role==='student'&&rest.length===1&&Object.hasOwn(legacyStudentSections,initial)&&legacyStudentSections[initial].includes(rest[0])){
      return {page:rest[0],parts:[],context:Object.fromEntries(query)};
    }
    const group=sections[state.user.role].find(item=>item.id===initial||(initial==='university'&&item.id==='university-life'&&item.children.includes(rest[0])));
    const nested=group?.children.includes(rest[0]);
    const page=nested?rest[0]:initial;
    const parts=nested?rest.slice(1):rest;
    return {page:!parts.length||extensionFor(page)?.validParts(page,parts)?page:null,parts,context:Object.fromEntries(query)};
  }
  function replaceRouteContext(){
    if(!Object.keys(state.routeContext).length)return;
    state.routeContext={};state.routeHref=state.routeHref.split('?')[0];
    history.replaceState({atlasEntry:state.historyEntry},'',state.routeHref);
  }
  async function route(page,{replace=false,fromHistory=false,parts=[],context={}}={}){
    if(state.pending){toast('Дождитесь завершения отправки.');return;}
    if(!state.user||!closeModal())return;
    const role=state.user.role;
    const legacy={campus:'home','work-contact':'notifications','work-notices':'notifications',attendance:'grades'};
    if(role==='student'&&['library','quizzes','flashcards','focus'].includes(page)){
      page=page==='focus'?'tasks':'materials';
      context={};
    }
    const oldSection=sections[role].find(item=>item.id===page);
    page=legacy[page]|| (oldSection?sectionChildren(oldSection)[0]?.id:page);
    const valid=menuFor(role).some(item=>item.id===page);
    const target=valid?page:startPage(role);
    const extension=extensionFor(target);
    const detail=valid&&extension?.validParts(target,parts)?parts:[];
    const next=valid?(extension?extension.cleanQuery(target,context,detail):cleanContext(target,context)):{};
    const query=new URLSearchParams(next).toString();
    const href=pagePath(target)+(detail.length?'/'+detail.join('/'):'')+(query?'?'+query:'');
    const previous=state.routeContext, previousPage=state.page;
    if(Object.keys(previous).length&&contextPages.has(previousPage))campus.resetRouteContext(previousPage);
    if(target!==previousPage&&['requests','certificates'].includes(target)){
      state.requestView='mine';state.requestFilter='all';state.requestOffset=0;state.serviceQuery='';
    }
    state.page=target;state.routeParts=detail;state.routeContext=next;
    if(query&&!extension){
      if(target==='schedule'&&next.date){state.day=next.date;state.week=monday(next.date);state.scheduleMode='day';}
      campus.prepareRoute(target,next);
    }else if(target==='schedule'&&previousPage==='schedule'&&previous.date){state.day=today();state.week=monday(state.day);}
    if(fromHistory||replace||state.routeHref===href){
      state.historyEntry=history.state?.atlasEntry??0;
      history.replaceState({atlasEntry:state.historyEntry},'',href);
    }else{
      state.historyEntry++;
      history.pushState({atlasEntry:state.historyEntry},'',href);
    }
    state.routeHref=href;
    renderShell();
    const epoch=state.sessionEpoch;
    const loading=updatePage();const loadId=state.loadingId;
    window.scrollTo({top:0,behavior:'instant'});
    await loading;
    if(!query||extension||epoch!==state.sessionEpoch||loadId!==state.loadingId||$('.error-state'))return;
    if(target==='schedule'){
      const row=next.id?$(`[data-lesson-id="${next.id}"]`):null;
      if(row){row.classList.add('search-match');row.tabIndex=-1;row.scrollIntoView({block:'center',behavior:'instant'});row.focus({preventScroll:true});}
    }else if(target!=='grades')await campus.openContext(target,next);
  }
  function goToUrl(url,options={}){
    const {page,parts,context}=routeFromUrl(url);
    return route(page,{...options,parts,context});
  }
  function enterRoute(){return goToUrl(location,{replace:true});}
  const navigateContext = (page,context) => route(page,{context});
  const logo = () => `<div class="logo"><img class="logo-mark" src="${esc($('link[rel="icon"]').getAttribute('href'))}" alt="" width="40" height="40" /><span class="logo-copy"><span class="logo-word">АТЛАС<span class="logo-period">.</span></span><span class="logo-sub">ЦИФРОВОЙ КАМПУС</span></span></div>`;
  const avatar = (u,extra='') => `<span aria-hidden="true" class="avatar ${['purple','orange','blue'].includes(u.accent)?u.accent:'purple'} ${extra}">${esc(u.initials)}</span>`;
  const badge = r => `<span class="request-status ${Object.hasOwn(statusNames,r.status)?r.status:'submitted'}"><span class="status-dot"></span>${esc(statusNames[r.status]||r.status)}</span>`;
  function currentSection(){
    return sections[state.user.role].find(group=>group.id===state.page||group.children.includes(state.page));
  }
  function routeLink(page,label,cls=''){
    return `<a class="${cls}" href="${pagePath(page)}" data-route="${page}">${esc(label)}</a>`;
  }
  function breadcrumbs(data){
    const role=state.user.role, root=startPage(role), group=currentSection();
    const crumbs=[['Кабинет','/app/'+root]];
    if(state.page!==root){
      if(group)crumbs.push([group.label]);
      crumbs.push([pageTitle(state.page),pagePath(state.page)]);
    }
    if(state.routeParts.length){
      for(const parent of data?.parents||[])crumbs.push([parent.title,parent.href]);
      crumbs.push([data?.title||'Запись',state.routeHref]);
    }
    return `<nav class="breadcrumbs" aria-label="Путь к разделу"><ol>${crumbs.map(([label,href],index)=>`<li>${index?icon('right'):''}${index===crumbs.length-1?`<strong aria-current="page">${esc(label)}</strong>`:href?`<a href="${esc(href)}" data-app-link>${esc(label)}</a>`:`<span>${esc(label)}</span>`}</li>`).join('')}</ol></nav>`;
  }
  function siblingNav(){
    const group=currentSection();
    const children=group?sectionChildren(group):[];
    if(children.length<2)return '';
    return `<nav class="section-nav" aria-label="${esc(group.label)} — разделы">${children.map(p=>p.id===state.page?`<span aria-current="page">${esc(p.label)}</span>`:routeLink(p.id,p.label)).join('')}</nav>`;
  }
  function navItem(p,{mobile=false}={}){
    const active=state.page===p.id;
    const attributes=`class="nav-item ${active?'active':''}" data-route="${p.id}" title="${esc(p.label)}" ${active?'aria-current="page"':''}`;
    const label=`${icon(p.icon)}<span class="nav-text">${esc(p.label)}</span>${p.id==='notifications'?`<span class="nav-badge" ${state.unread?'':'hidden'}>${state.unread}</span>`:''}${p.id==='direct'?university.unreadBadge():''}`;
    return mobile?`<button type="button" ${attributes}>${label}</button>`:`<a href="${pagePath(p.id)}" ${attributes}>${label}</a>`;
  }
  function navMarkup(menu){
    const role=state.user.role, active=currentSection();
    const groups=sections[role].map(group=>{
      const children=sectionChildren(group);
      if(children.length===1)return navItem(children[0]);
      const expanded=group.id===openNavGroup;
      return `<div class="nav-group${expanded?' is-open':''}" data-nav-group="${group.id}">
        <button type="button" class="nav-item nav-group-toggle ${active===group?'has-current':''}" title="${esc(group.label)}" aria-label="${esc(group.label)}" aria-expanded="${expanded}" aria-controls="nav-${group.id}" data-action="nav-group" data-id="${group.id}">
          ${icon(group.icon)}<span class="nav-text">${esc(group.label)}</span>${icon('right','nav-chevron')}
        </button>
        <div class="nav-group-panel" id="nav-${group.id}" ${expanded?'':'inert'}><div class="nav-group-links">${children.map(p=>navItem(p)).join('')}</div></div>
      </div>`;
    }).join('');
    const pinned=[...(role==='student'?['home']:role==='teacher'?['teacher']:[]),'announcements','notifications',...(role==='student'?[]:['direct','university'])];
    return pinned.map(id=>menu.find(p=>p.id===id)).filter(Boolean).map(p=>navItem(p)).join('')+groups;
  }
  const conceptNotice=()=>`<div class="concept-bar" role="note">${icon('info')}<span>Конкурсный концепт · все данные вымышлены · неофициальный сервис</span></div>`;
  const sidebarKey=()=>`atlas.sidebar.${state.user.id}`;
  function savedSidebar(){
    try{return localStorage.getItem(sidebarKey())==='collapsed';}catch{return false;}
  }
  function toggleSidebar(button){
    const collapsed=$('.shell').classList.toggle('sidebar-collapsed');
    const label=collapsed?'Развернуть боковое меню':'Свернуть боковое меню';
    button.setAttribute('aria-expanded',String(!collapsed));button.setAttribute('aria-label',label);button.title=label;
    try{localStorage.setItem(sidebarKey(),collapsed?'collapsed':'expanded');}catch{/* Continue without persisting this device's choice. */}
  }
  function setDrawer(open,{restoreFocus=true,trigger=null}={}){
    const shell=$('.shell'),sidebar=$('.sidebar',shell||document);
    if(!sidebar)return;
    open=open&&drawerMedia.matches;
    if(open&&!shell.classList.contains('drawer-open'))drawerFocus=trigger||document.activeElement;
    shell.classList.toggle('drawer-open',open);document.body.classList.toggle('nav-drawer-open',open);
    sidebar.inert=drawerMedia.matches&&!open;
    if(open){sidebar.setAttribute('role','dialog');sidebar.setAttribute('aria-modal','true');}
    else{sidebar.removeAttribute('role');sidebar.removeAttribute('aria-modal');}
    $('.main',shell).inert=open;$('.bottom-nav',shell).inert=open;$('.skip-link').inert=open;
    $('[data-action="drawer-open"]',shell).setAttribute('aria-expanded',String(open));
    if(open){$('[data-action="drawer-close"]',sidebar).focus({preventScroll:true});scrollNavGroup();}
    else{if(restoreFocus&&drawerFocus?.isConnected&&drawerMedia.matches)drawerFocus.focus({preventScroll:true});drawerFocus=null;}
  }
  drawerMedia.addEventListener('change',()=>setDrawer(false));
  function scrollNavGroup(){
    const nav=$('.nav-stack'),group=$('.nav-group.is-open',nav||document);
    if(!nav||!group)return;
    const viewport=nav.getBoundingClientRect(),bounds=group.getBoundingClientRect();
    const delta=bounds.top<viewport.top?bounds.top-viewport.top:Math.min(bounds.bottom-viewport.bottom,bounds.top-viewport.top);
    if(bounds.top<viewport.top||bounds.bottom>viewport.bottom)nav.scrollBy({top:delta,behavior:reducedMotion.matches?'instant':'smooth'});
  }
  function toggleNavGroup(id){
    openNavGroup=openNavGroup===id?null:id;
    for(const group of $$('.nav-group')){
      const expanded=group.dataset.navGroup===openNavGroup;
      group.classList.toggle('is-open',expanded);
      $('.nav-group-toggle',group).setAttribute('aria-expanded',String(expanded));
      $('.nav-group-panel',group).inert=!expanded;
    }
    clearTimeout(navScrollTimer);
    if(openNavGroup)navScrollTimer=setTimeout(scrollNavGroup,reducedMotion.matches?0:190);
  }
  function renderShell(){
    if(!state.user)return showLogin();
    openNavGroup=currentSection()?.id||null;
    const u=state.user, student=u.role==='student', menu=menuFor(u.role);
    const shortcut=(id,label)=>({...menu.find(p=>p.id===id),label});
    document.title=`${pageTitle(state.page)} — АТЛАС`;
    const mobile=student?[shortcut('home','Главная'),pages[1],shortcut('grades','Оценки'),shortcut('requests','Заявки')]
      :u.role==='staff'?[shortcut('staff','Заявки'),shortcut('staffdesk','Работа'),shortcut('staffmessages','Вопросы'),shortcut('direct','Личные')]
      :u.role==='teacher'?[shortcut('teacher','Кабинет'),shortcut('teaching','Группы'),shortcut('teach-schedule','Занятия'),shortcut('direct','Личные')]
      :['union','vuc'].includes(u.role)?[shortcut(startPage(u.role),'Кабинет'),notifications,profile]
      :[shortcut('timetable-admin','Занятия'),shortcut('schedule-changes','Проекты'),shortcut('registry','Данные'),shortcut('tables','Таблицы')];
    const notice=`<button class="circle-button" data-route="notifications" aria-label="Уведомления"><span class="dot" data-unread-dot ${state.unread?'':'hidden'}></span>${icon('bell')}</button>`;
    const directShortcut=['staff','teacher'].includes(u.role)?`<button class="circle-button header-direct" data-route="direct" aria-label="Личные сообщения">${icon('send')}${university.unreadBadge(true)}</button>`:'';
    const collapsed=savedSidebar(),collapseLabel=collapsed?'Развернуть боковое меню':'Свернуть боковое меню';
    app.innerHTML=`<div class="shell${collapsed?' sidebar-collapsed':''}">
      <div class="drawer-shade" data-action="drawer-close" aria-hidden="true"></div>
      <aside class="sidebar" id="atlas-sidebar" aria-label="Личный кабинет">
        <div class="side-heading">
          <button class="brand-button" data-route="${startPage(u.role)}" title="На главную">${logo()}</button>
          <button type="button" class="icon-button sidebar-toggle" data-action="sidebar-toggle" aria-label="${collapseLabel}" aria-expanded="${!collapsed}" aria-controls="side-nav" title="${collapseLabel}">${icon('sidebar')}</button>
          <button type="button" class="icon-button drawer-close" data-action="drawer-close" aria-label="Закрыть меню">${icon('close')}</button>
        </div>
        <nav class="nav-stack" id="side-nav" aria-label="Основная навигация">${navMarkup(menu)}</nav>
        <div class="side-user"><button class="side-person" data-route="profile" title="${esc(u.full_name)}">${avatar(u)}<span class="sr-only">Профиль</span><span class="side-person-copy"><b>${esc(u.full_name)}</b> <span>${esc(u.group)}</span></span></button><button class="icon-button" data-action="logout" aria-label="Выйти из кабинета" title="Выйти из кабинета">${icon('logout')}</button></div>
      </aside>
      <main class="main">
        <header class="topbar">
          <button class="brand-button topbar-brand" data-route="${startPage(u.role)}" title="На главную">${logo()}</button>
          ${breadcrumbs()}
          <div class="top-actions"><span class="today-label">${dateFmt(today(),{day:'numeric',month:'long'})}</span><button class="search-trigger" data-action="search">${icon('search')}<span>Поиск по кабинету</span><kbd aria-hidden="true">Ctrl K</kbd></button><button type="button" class="circle-button" id="refresh-current" data-action="retry" title="Обновить данные раздела" aria-label="Обновить данные раздела">${icon('refresh')}</button>${notice}${directShortcut}<button class="avatar-button" data-route="profile" aria-label="Мой профиль, ${esc(u.initials)}">${avatar(u)}</button></div>
        </header>
        ${siblingNav()}
        ${conceptNotice()}
        <div class="content" id="page-content" tabindex="-1"></div>
        <footer class="app-footer"><span>Время занятий — МСК (UTC+3)</span></footer>
      </main><nav class="bottom-nav" aria-label="Мобильная навигация">${mobile.map(p=>navItem(p,{mobile:true})).join('')}<button type="button" class="nav-item" data-action="drawer-open" aria-expanded="false" aria-controls="atlas-sidebar" aria-label="Открыть меню">${icon('menu')}<span>Меню</span></button></nav>
    </div><div id="modal-root"></div>`;
    improvements.shell();
    setDrawer(false,{restoreFocus:false});
    if(!drawerMedia.matches)scrollNavGroup();
  }
  function loading(){return `<div class="loading-state" role="status" aria-label="Загрузка раздела"><div class="skeleton skeleton-heading"></div><div class="skeleton skeleton-sub"></div><div class="skeleton-grid"><div class="skeleton skeleton-card"></div><div class="skeleton skeleton-card"></div><div class="skeleton skeleton-card"></div></div><span class="sr-only">Загружаем данные…</span></div>`;}
  async function updatePage({quiet=false}={}) {
    const page=state.page;const requestId=++state.loadingId;const target=$('#page-content');if(!target||!state.user)return;
    target.dataset.loadId=requestId;
    if(!quiet){target.innerHTML=loading();target.setAttribute('aria-busy','true');}
    try {let d=await load(page);if(requestId!==state.loadingId||page!==state.page||!state.user)return;
      if(['requests','notifications','staff'].includes(page)&&d.offset>0&&d.offset>=d.total){const field={requests:'requestOffset',notifications:'noticeOffset',staff:'staffOffset'}[page];state[field]=Math.max(0,Math.floor((d.total-1)/d.limit)*d.limit);d=await load(page);if(requestId!==state.loadingId||page!==state.page||!state.user)return;}
      state.data[page]=d;if(page==='home')state.unread=d.unread_count;if(page==='notifications')state.unread=d.unread_count;
      drawPage();updateBadges();
      if(!quiet)$('#page-title')?.focus({preventScroll:true});
    }catch(error){if(error.stale||requestId!==state.loadingId||!state.user)return;target.innerHTML=`<section class="card error-state" role="alert">${icon('alert')}<h1 id="page-title" tabindex="-1">Не удалось загрузить раздел</h1><p>${esc(error.message)}</p><button class="primary-button" data-action="retry">${icon('refresh')} Попробовать ещё раз</button></section>`;}
    finally{if(target.dataset.loadId===String(requestId))target.removeAttribute('aria-busy');}
  }
  async function refreshCurrent(trigger){
    const control=$('#refresh-current');
    if(!control||control.disabled||state.pending||!navigator.onLine)return;
    const focused=document.activeElement===trigger;
    control.disabled=true;control.setAttribute('aria-busy','true');
    if(trigger!==control)trigger.disabled=true;
    try{await updatePage({quiet:trigger===control});}
    finally{
      control.removeAttribute('aria-busy');control.disabled=!navigator.onLine;
      if(control.isConnected&&focused&&document.activeElement===document.body)control.focus();
    }
  }
  function updateBadges(){
    for(const dot of $$('[data-unread-dot]')){
      dot.hidden=!state.unread;
      dot.parentElement.setAttribute('aria-label',state.unread?`Уведомления, непрочитанных: ${state.unread}`:'Уведомления');
    }
    for(const badge of $$('.nav-badge')){
      badge.hidden=!state.unread;
      badge.textContent=state.unread>99?'99+':state.unread;
    }
  }
  function head(kicker,title,description,actions=''){return `<div class="title-row"><div><h1 class="page-title" id="page-title" tabindex="-1">${title}</h1>${description?`<p class="page-subtitle">${description}</p>`:''}</div>${actions?`<div class="page-actions">${actions}</div>`:''}</div>`;}
  function disclosure(title,content,extra=''){return `<details class="card disclosure ${extra}"><summary>${title}${icon('right')}</summary><div class="disclosure-body">${content}</div></details>`;}
  function cardHead(title,link='',label='Открыть'){return `<div class="card-titlebar"><h2 class="card-title">${title}</h2>${link?`<button class="mini-link" data-route="${link}">${label} ${icon('arrow')}</button>`:''}</div>`;}
  function empty(name,title,description,action=''){return `<div class="empty-state"><span class="empty-icon">${icon(name)}</span><h3>${esc(title)}</h3><p>${esc(description)}</p>${action}</div>`;}
  function lessonRows(items){return items.length?`<div class="schedule-list">${items.map(l=>`<article data-lesson-id="${Number(l.id)}" class="lesson-row"><div class="lesson-time"><b>${esc(l.start)}</b><span>${esc(l.end)}</span></div><span class="lesson-line ${esc(l.color)}"></span><div class="lesson-details"><h3>${esc(l.title)}</h3><p>${esc(l.kind)} <span>·</span> ${esc(l.teacher)}</p><div class="lesson-location">${icon('pin')} ${esc(l.room)}${l.changed?'<span class="status-tag changed">Изменение</span>':''}</div>${l.changed?`<div class="change-note">${esc(l.note)}${l.original_room||l.original_start?`<small class="change-comparison">Было: ${esc(l.original_start)} · ${esc(l.original_room)} → Стало: ${esc(l.start)} · ${esc(l.room)}</small>`:''}</div>`:''}</div></article>`).join('')}</div>`:'<p class="compact-empty">В этот день занятий нет.</p>';}
  function dueItems(items,interactive=false){if(!items.length)return empty('checkCircle','Всё под контролем','Незавершённых заданий пока нет.');return `<div class="deadline-list">${items.map(d=>`<div class="deadline-item ${d.is_done?'done':''}">${interactive?`<input type="checkbox" class="task-checkbox" data-deadline="${d.id}" ${(deadlineWrites.get(Number(d.id))?.done??d.is_done)?'checked':''} ${deadlineWrites.has(Number(d.id))?'disabled':''} aria-label="Выполнено: ${esc(d.title)}" />`:`<div class="deadline-cal ${dueDays(d.due_date)<=2?'urgent':''}"><b>${asDate(d.due_date).getDate()}</b><span>${dateFmt(d.due_date,{month:'short'})}</span></div>`}<div class="deadline-info"><button class="deadline-open" data-route="assignments" data-record-id="${Number(d.id)}"><b>${esc(d.title)}</b></button><p>${esc(d.subject)}</p>${interactive?`<small>${dateFmt(d.due_date)} · ${d.is_done?'Выполнено':relative(d.due_date)}</small>`:''}</div>${!interactive?`<span class="due-label ${dueDays(d.due_date)<=2?'urgent':''}">${relative(d.due_date)}</span>`:''}</div>`).join('')}</div>`;}
  function dashboard(d){
    const next=d.next_lesson;const risks=d.grades.items.filter(x=>['blocked','failed','retake'].includes(x.assessment_status?.code));const firstName=d.profile.full_name.split(' ')[0];
    const deadlines=`<section class="card card-pad">${cardHead('Ближайшие сроки','assignments','Все задания')}${dueItems(d.deadlines.slice(0,2))}</section>`;
    const todayLessons=d.today.length?`<section class="card card-pad">${cardHead('Занятия сегодня','schedule','Расписание')}${lessonRows(d.today)}</section>`:'';
    const notices=d.notifications.slice(0,2).map(n=>{
      const excerpt=n.body.length>160?n.body.slice(0,160).trimEnd()+'…':n.body;
      return `<button class="notice-preview" data-action="open-notice" data-id="${Number(n.id)}"><span class="notice-icon">${icon(n.category==='request'?'file':'bell')}</span><span><b>${esc(n.title)}</b><small>${esc(excerpt)}</small></span>${!n.is_read?'<span class="notice-dot" aria-label="Не прочитано"></span>':''}</button>`;
    }).join('');
    const notifications=`<section class="card card-pad">${cardHead('Уведомления','notifications',state.unread?`Новые: ${state.unread}`:'Все')}${notices||'<p class="compact-empty">Уведомлений пока нет.</p>'}</section>`;
    const shortcuts=`<details class="card disclosure home-links"><summary>Ещё в кабинете ${icon('right')}</summary><div class="disclosure-body home-link-list"><button data-route="courses">${icon('book')} Учебные материалы ${icon('right')}</button><button data-route="calendar">${icon('calendar')} Общий календарь ${icon('right')}</button><button data-route="consultations">${icon('user')} Запись на консультацию ${icon('right')}</button></div></details>`;
    return head('',`${greeting()}, ${esc(firstName)}`,`${dateFmt(today(),{weekday:'long',day:'numeric',month:'long'})} · ${esc(d.profile.group)}`)+
      `<div class="home-actions"><button class="outline-button" data-route="assignments">${icon('send')} Сдать работу</button><button class="outline-button" data-action="new-request" data-type="study">${icon('file')} Заказать справку</button><button class="outline-button" data-route="messages">${icon('user')} Написать в деканат</button></div>
      <div class="home-overview"><section class="next-class"><div class="next-class-label">${icon('calendar')}<span>${next?'Ближайшее занятие':'Ближайших занятий нет'}</span>${next?`<time>${next.date===today()?'Сегодня':dateFmt(next.date,{weekday:'short',day:'numeric',month:'short'})}</time>`:''}</div><h2>${next?esc(next.title):'Сегодня можно отдохнуть'}</h2><p>${next?`<strong>${esc(next.start)}–${esc(next.end)}</strong> · ${esc(next.room)}${next.teacher?` · ${esc(next.teacher)}`:''}`:'Расписание появится здесь после публикации.'}</p>${next?.changed?`<p class="change-note">${esc(next.note)}</p>`:''}<button class="mini-link" data-route="schedule" data-date="${esc(next?.date||today())}" data-record-id="${Number(next?.id||0)}">Открыть расписание ${icon('arrow')}</button></section>
      <div class="stats home-stats"><button class="stat" data-route="grades"><span class="stat-label">Средний балл</span><span class="stat-value">${d.grades.items.some(row=>row.score!=null)?d.grades.average:'—'}</span><span class="stat-sub">Учебные результаты ${icon('right')}</span></button><button class="stat" data-route="assignments"><span class="stat-label">Скоро сдавать</span><span class="stat-value">${d.deadlines.length}</span><span class="stat-sub">К заданиям ${icon('right')}</span></button><button class="stat" data-route="requests"><span class="stat-label">Заявки в работе</span><span class="stat-value">${d.open_requests}</span><span class="stat-sub">Узнать статус ${icon('right')}</span></button></div></div>
      ${risks.length?`<div class="home-attention">${icon('alert')}<span><b>${esc(risks[0].subject)} · ${esc(risks[0].assessment_status.label)}</b></span><button class="mini-link" data-route="exams" data-subject="${esc(risks[0].subject)}">К аттестации ${icon('arrow')}</button></div>`:''}
      ${window.ATLASAnnouncements.timeline(d.announcements)}
      <div class="home-sections"><div class="home-widget-column">${deadlines}${notifications}</div><div class="home-widget-column">${todayLessons}${shortcuts}</div></div>`;
  }
  function schedulePage(d){
    const weekdays=['Пн','Вт','Ср','Чт','Пт','Сб','Вс'];const count=d.days.reduce((n,x)=>n+x.items.length,0);const changes=d.days.flatMap(x=>x.items).filter(x=>x.changed);
    if(!d.days.some(x=>x.date===state.day))state.day=d.week_start;
    const visibleDays=state.scheduleMode==='day'?d.days.filter(x=>x.date===state.day):d.days;const visibleCount=visibleDays.reduce((n,x)=>n+x.items.length,0);
    return head('Время для учёбы','Расписание','Пары, аудитории и преподаватели. Время — московское.',`<a class="outline-button" href="/api/schedule/export?week=${encodeURIComponent(d.week_start)}" download>${icon('download')} Скачать расписание</a>`)+
      `<div class="schedule-toolbar"><div class="week-switch"><button class="square-btn" data-action="prev-week" aria-label="Предыдущая неделя">${icon('left')}</button><h2>${dateFmt(d.week_start,{day:'numeric',month:'short'})} — ${dateFmt(addDays(d.week_start,6),{day:'numeric',month:'short'})}</h2><button class="square-btn" data-action="next-week" aria-label="Следующая неделя">${icon('right')}</button></div><div class="toolbar-actions"><button class="outline-button" data-action="this-week">Сегодня</button><div class="segmented" aria-label="Вид расписания"><button data-view="day" aria-pressed="${state.scheduleMode==='day'}">День</button><button data-view="week" aria-pressed="${state.scheduleMode==='week'}">Неделя</button></div></div></div>
      ${changes.length?`<div class="change-banner">${icon('alert')}<span><b>На этой неделе есть изменения: ${changes.length}</b><span>Обновлённые пары отмечены жёлтым. Время указано по Москве.</span><button class="mini-link" data-route="schedule" data-date="${esc(d.days.find(day=>day.items.some(x=>x.changed)).date)}" data-record-id="${Number(changes[0].id)}">Показать изменение</button></span></div>`:''}
      ${state.scheduleMode==='day'?`<div class="day-picker" aria-label="Выбрать день">${d.days.map((day,i)=>`<button class="day-pick ${state.day===day.date?'selected':''}" data-day="${day.date}" aria-pressed="${state.day===day.date}"><span>${weekdays[i]}</span><b>${asDate(day.date).getDate()}</b><span class="day-count">${day.items.length?String(day.items.length):'—'}</span></button>`).join('')}</div>`:''}
      <div class="schedule-info"><span>${visibleCount} занятий · ${state.scheduleMode==='day'?'Выбранный день':'Неделя'} · МСК (UTC+3)</span><span>Регулярное расписание с учётом переносов</span></div>
      ${state.scheduleMode==='day'?`<section class="card card-pad day-view">${cardHead(dateFmt(state.day,{weekday:'long',day:'numeric',month:'long'}))}${lessonRows(visibleDays[0].items)}</section>`:`<div class="week-grid">${visibleDays.map((day,i)=>`<section class="day-column"><div class="day-head ${day.date===today()?'today':''}"><div><span>${weekdays[i]}</span><b>${asDate(day.date).getDate()}</b></div><span>${day.date===today()?'Сегодня':day.items.length+' зан.'}</span></div><div class="day-lessons">${day.items.length?day.items.map(l=>`<article class="day-lesson ${esc(l.color)} ${l.changed?'lesson-changed':''}"><div class="day-lesson-time">${esc(l.start)}–${esc(l.end)}</div><h3>${esc(l.title)}</h3><span class="lesson-kind">${esc(l.kind)}</span><p>${esc(l.teacher)}</p><div class="lesson-location">${icon('pin')} ${esc(l.room)}</div>${l.changed?`<div class="change-note">${icon('alert')} ${esc(l.note)}${l.original_room||l.original_start?`<small class="change-comparison">Было: ${esc(l.original_start)} · ${esc(l.original_room)} → Стало: ${esc(l.start)} · ${esc(l.room)}</small>`:''}</div>`:''}</article>`).join(''):'<div class="week-empty">Свободный день<span>Время для себя</span></div>'}</div></section>`).join('')}</div>`}`;
  }
  function filterButtons(items,current,attribute){return `<div class="filter-tabs" aria-label="Фильтр списка">${items.map(([id,label,count])=>`<button ${attribute}="${id}" aria-pressed="${current===id}">${esc(label)}${count!==undefined?`<span>${count}</span>`:''}</button>`).join('')}</div>`;}
  function pagination(data,kind){return data.total>data.limit?`<nav class="pagination" aria-label="Страницы списка"><span>${data.offset+1}–${Math.min(data.offset+data.items.length,data.total)} из ${data.total}</span><div><button class="square-btn" data-pager="${kind}" data-offset="${Math.max(0,data.offset-data.limit)}" aria-label="Предыдущая страница" ${data.offset?'':'disabled'}>${icon('left')}</button><button class="square-btn" data-pager="${kind}" data-offset="${data.offset+data.limit}" aria-label="Следующая страница" ${data.has_more?'':'disabled'}>${icon('right')}</button></div></nav>`:'';}
  function planPage(items){
    const done=items.filter(x=>x.is_done).length;const active=items.filter(x=>!x.is_done);const urgent=active.filter(x=>dueDays(x.due_date)<=3);const visible=state.planFilter==='all'?items:items.filter(x=>state.planFilter==='done'?x.is_done:!x.is_done);
    return head('','Мой план','Личные отметки выполнения заданий. Для отправки работы откройте «Сдать работу».',`<button class="primary-button" data-route="assignments">${icon('send')} Сдать работу</button>`)+
      `<div class="plan-summary"><span>${icon('checkCircle')} Выполнено <b>${done} из ${items.length}</b></span><progress max="${Math.max(items.length,1)}" value="${done}" aria-label="Прогресс выполнения заданий"></progress><span>${urgent.length?`${urgent.length} со сроком в ближайшие 3 дня`:'Ближайших срочных дел нет'}</span><button class="mini-link" data-route="tasks">Личные задачи ${icon('arrow')}</button></div><section class="card card-pad">${cardHead('Учебные задания')}${filterButtons([['active','Предстоят',active.length],['done','Выполнены',done],['all','Все',items.length]],state.planFilter,'data-plan-filter')}${visible.length?dueItems(visible,true):empty('checkCircle',state.planFilter==='done'?'Выполненных заданий пока нет':'Все задания отмечены',state.planFilter==='done'?'Поставьте отметку у выполненного задания.':'Посмотрите отправленные работы или добавьте собственную задачу.')}<p class="list-footnote">Отметка сохраняется в вашем плане и не заменяет сдачу работы.</p></section>`;
  }
  function requestRow(r,staff=false){return `<button class="request-row ${r.status==='ready'?'request-is-ready':''}" data-action="request-details" data-id="${r.id}"><span class="file-glyph ${r.status==='ready'?'ready':''}">${icon(r.status==='ready'?'checkCircle':'file')}</span><span class="request-row-main"><b>${esc(r.type)}</b><small>№ ${r.id} · ${timestampDate(r.created_at,{day:'numeric',month:'short'})}${staff?` · ${esc(r.student_name)} · ${esc(r.group)}`:''}</small>${r.staff_message?`<span class="request-preview">${esc(r.staff_message.slice(0,110))}</span>`:''}</span><span class="request-row-end">${badge(r)}<small>${r.status==='ready'?'Открыть результат':r.status==='rejected'?'Посмотреть причину':`Ориентир: ${dateFmt(r.due_at,{day:'numeric',month:'short'})}`}</small></span>${icon('right')}</button>`;}
  function certificateCard(service){
    const basis=service.source_url?`<p class="hint"><a href="${esc(service.source_url)}" target="_blank" rel="noopener noreferrer">${esc(service.basis)}</a></p>`:'';
    return `<article class="card card-pad certificate-service">
      <h2>${esc(service.name)}</h2><p>${esc(service.description)}</p>
      <p class="service-eta">${esc(service.department)} · ${esc(service.eta)}</p>${basis}
      ${service.eligibility?`<p>${esc(service.eligibility)}</p>`:''}
      ${service.required_data?`<p><strong>Что потребуется.</strong> ${esc(service.required_data)}</p>`:''}
      ${service.available===false?`<p role="status">${esc(service.unavailable_reason)}</p>`:
        `<button class="outline-button" data-action="new-request" data-type="${esc(service.id)}">${icon('plus')} Заказать справку</button>`}
    </article>`;
  }
  function requestsPage(d){
    const certificates=d.kind==='certificate', counts=d.counts;
    const query=normalise(state.serviceQuery), mine=certificates?'Мои справки':'Мои заявки';
    const choose=certificates?'Виды справок':'Каталог заявок';
    const types=query?d.types.filter(t=>normalise([t.name,t.description,t.basis,t.department].filter(Boolean).join(' ')).includes(query)):
      certificates?d.types:campus.catalogTypes(d.types);
    const tabs=filterButtons([['mine',mine,counts.all],['services',choose]],state.requestView,'data-request-view');
    const filters=[['all','Все',counts.all],['active','В работе',counts.active],
      ['ready',certificates?'Готовые документы':'Готовы',counts.ready],['rejected','Отклонены',counts.rejected]];
    const list=`<section class="card card-pad">${cardHead(mine)}${filterButtons(filters,state.requestFilter,'data-request-filter')}
      <div class="request-list">${d.items.length?d.items.map(r=>requestRow(r)).join(''):
        empty('file',counts.all?'Записей по этому фильтру нет':certificates?'Вы ещё не заказывали справки':'Вы ещё не подавали заявки',
          counts.all?'Выберите другой статус.':'В каталоге указаны сроки и необходимые сведения.',
          `<button class="outline-button" data-request-view="services">${choose} ${icon('arrow')}</button>`)}</div>${pagination(d,'requests')}</section>`;
    const cards=certificates?types.map(certificateCard).join(''):types.map((t,i)=>`
      <button class="service-card" data-action="new-request" data-type="${esc(t.id)}">
        <span class="catalog-icon tone-${i%4}">${icon('send')}</span><span class="service-card-copy"><h2>${esc(t.name)}</h2>
        <span class="service-eta">${esc(t.department)} · ${esc(t.eta)}</span><p>${esc(t.description)}</p></span>${icon('right')}
      </button>`).join('');
    const catalog=`<label class="search-field service-search">${icon('search')}<input id="service-search" value="${esc(state.serviceQuery)}"
      maxlength="100" placeholder="${certificates?'Название справки':'Название услуги'}" aria-label="${certificates?'Поиск по справкам':'Поиск по услугам'}" /></label>
      ${certificates?'':campus.catalogFilter()}<p class="result-count" role="status">Найдено: ${types.length}</p>
      <div class="service-catalog">${cards||empty('search','Услуга не найдена','Попробуйте другое название.')}</div>`;
    const departmentLinks=certificates?'':disclosure('Куда направить обращение',`
      <p>Учебный офис принимает заявления по учёбе и сопровождению. У профсоюза и Военного учебного центра свои очереди.</p>
      <div class="campus-button-row"><button class="outline-button" data-route="union">Студенческий профсоюз</button>
      <button class="outline-button" data-route="vuc">Военный учебный центр</button></div>`);
    return head('',certificates?'Справки':'Заявки',certificates?'Закажите справку, проверьте статус и получите готовый документ.':
      'Подайте обращение и отслеживайте решение учебного офиса.',
      `<button class="primary-button" data-action="new-request">${icon('plus')} ${certificates?'Заказать справку':'Новая заявка'}</button>`)+
      tabs+(state.requestView==='mine'?list:catalog)+departmentLinks;
  }
  function notificationsPage(data){
    const visible=data.items;const counts=data.counts;const unread=counts.unread;
    const sources={request:['Заявки и справки','file'],schedule:['Расписание','calendar'],deadline:['Сроки заданий','clock'],
      direct:['Личные сообщения','send'],announcement:['Объявления','bell'],academic:['Учебная работа','book'],
      material:['Учебные материалы','book'],service:['Сервисы кампуса','pin'],union:['Профсоюз','heart'],vuc:['ВУЦ','shield']};
    const filters=[['all','Все',counts.all],['unread','Непрочитанные',unread],
      ...Object.entries(sources).filter(([key])=>counts[key]||key===state.noticeFilter).map(([key,[label]])=>[key,label,counts[key]])];
    const articles=visible.map(n=>{
      const [source,symbol]=sources[n.category]||['Кампус','bell'];
      return `<article class="notification-full ${n.is_read?'read':''}">
        <span class="notice-icon ${n.category==='deadline'?'orange':''}">${icon(symbol)}</span>
        <div class="notice-content"><div class="notice-title"><h2>${esc(n.title)}</h2>${!n.is_read?'<span class="notice-dot" role="img" aria-label="Не прочитано"></span>':''}</div>
        <p>${esc(n.body)}</p><div class="notice-bottom"><span>${source}</span><time datetime="${esc(n.created_at)}">${stamp(n.created_at)} МСК</time>
        <button class="mini-link" data-action="open-notice" data-id="${n.id}">Открыть ${icon('arrow')}</button>
        ${!n.is_read?`<button class="quiet-button" data-action="read-notification" data-id="${n.id}">Прочитано ${icon('check')}</button>`:''}</div></div></article>`;
    }).join('');
    return head('','Уведомления','',`<button class="outline-button" data-action="read-all" ${unread?'':'disabled'}>${icon('check')} Прочитать все</button>`)+
      `<section class="card card-pad notification-page">${filterButtons(filters,state.noticeFilter,'data-notice-filter')}${articles||empty('bell','Уведомлений нет','Уведомлений по этому фильтру нет.')}${pagination(data,'notifications')}</section>`;
  }
  function profilePage(u){
    const student=u.role==='student';
    const fields=student?[['Факультет',u.faculty],['Направление',u.program],['Курс',u.course],['Группа',u.group],['Учебный номер',u.student_number]]
      :[['Подразделение',u.faculty],['Роль',u.group],['Направление работы',u.program]];
    return head('','Мой профиль','Личные сведения и доступ к кабинету.',`<button class="outline-button" data-route="settings">${icon('shield')} Настройки</button>`)+`<section class="card card-pad profile-summary"><div class="profile-identity">${avatar(u)}<div><h2>${esc(u.full_name)}</h2><p>${esc(student?u.group+' · '+u.course+' курс':u.group)}</p></div></div><dl class="profile-data">${fields.map(([k,v])=>`<div><dt>${esc(k)}</dt><dd>${esc(v||'—')}</dd></div>`).join('')}</dl></section>`+disclosure('Доступ и безопасность',`<div class="security-list"><div>${icon('shield')}<span><b>Данные разделены по аккаунтам</b><p>${student?'Другие студенты не могут открыть ваши оценки, заявки и заметки.':'Кабинет использует полномочия вашей роли. Личную переписку видят только участники.'}</p></span></div></div>`)+`<button class="danger-button" data-action="logout">${icon('logout')} Выйти из кабинета</button>`;
  }
  function staffPage(data){
    const counts=data.counts;const visible=data.items;
    return head('','Учебный офис','Разберите обращения и заказы справок.')+
      filterButtons([['request','Заявки'],['certificate','Справки'],['all','Вся очередь']],state.staffKind||'request','data-staff-kind')+
      `<div class="grade-summary"><div class="card summary-metric"><span class="summary-icon">${icon('file')}</span><div><b>${counts.active}</b><p>Ожидают решения</p></div></div><div class="card summary-metric"><span class="summary-icon orange">${icon('clock')}</span><div><b>${counts.overdue}</b><p>Срок требует внимания</p></div></div><div class="card summary-metric"><span class="summary-icon teal">${icon('checkCircle')}</span><div><b>${counts.ready}</b><p>Результат готов</p></div></div></div><section class="card card-pad">${cardHead('Очередь обращений')}<div class="staff-tools"><label class="search-field">${icon('search')}<input id="staff-search" maxlength="100" value="${esc(state.staffQuery)}" placeholder="Номер, студент, группа…" aria-label="Поиск по очереди" autocomplete="off" /></label>${filterButtons([['active','В работе',counts.active],['all','Все',counts.all],['submitted','Новые',counts.submitted],['ready','Готовые',counts.ready],['overdue','Просрочены',counts.overdue]],state.staffFilter,'data-staff-filter')}</div><div id="staff-results" class="request-list">${visible.length?visible.map(r=>requestRow(r,true)).join(''):empty('checkCircle','Обращений не найдено','По этому фильтру обращений нет. Попробуйте другой фильтр или запрос.')}${pagination(data,'staff')}</div></section>`;
  }
  function drawPage(){
    const target=$('#page-content'), page=state.page, data=state.data[page];if(!target||!data)return;
    const renders={home:dashboard,schedule:schedulePage,grades:window.ATLASAcademics.render,plan:planPage,requests:requestsPage,certificates:requestsPage,notifications:notificationsPage,profile:profilePage,staff:staffPage};
    const extension=extensionFor(page);
    if(extension){
      target.innerHTML=extension.render(page,data);
      if(state.routeParts.length){
        $('.breadcrumbs').outerHTML=breadcrumbs(data);
        document.title=`${data.title||pageTitle(page)} — АТЛАС`;
      }
      extension.afterRender?.(page,data);
    }else{
      target.innerHTML=campus.has(page)?campus.render(page,data):renders[page](data);
      campus.afterRender(page);
      if(page==='grades')window.ATLASAcademics.bind(target,data,state.routeContext);
    }
    target.removeAttribute('aria-busy');
  }

  function modal(content,{wide=false,label='Диалог'}={}) {
    if(state.pending){toast('Дождитесь завершения отправки.');return;}
    const root=$('#modal-root');if(!root)return;const wasOpen=!!$('.modal',root);if(!wasOpen)lastFocus=document.activeElement;
    state.modalId++;root.innerHTML=`<div class="modal-layer" data-action="close-backdrop"><section class="modal ${wide?'modal-wide':''}" role="dialog" aria-modal="true" aria-label="${esc(label)}">${content}</section></div>`;
    $('.shell')?.setAttribute('inert','');$('.skip-link')?.setAttribute('inert','');document.body.classList.add('modal-open');
    // The dialog already exists in the DOM. Focus now so a deferred frame
    // cannot steal focus from a user's first Tab or click inside the dialog.
    ($('[autofocus]',root)||$('.close-btn',root)||$('button',root))?.focus({preventScroll:true});
    queueMicrotask(()=>improvements.bindForms());
  }
  function modalHead(title,subtitle){return `<div class="modal-head"><div><h2>${esc(title)}</h2>${subtitle?`<p>${esc(subtitle)}</p>`:''}</div><button class="close-btn" data-action="close-modal" aria-label="Закрыть диалог">${icon('close')}</button></div>`;}
  function closeModal({force=false}={}){
    if(state.pending){toast('Дождитесь завершения отправки.');return false;}
    const form=$('.modal form[data-dirty="true"]');
    if(form&&!force){
      let warning=$('.unsaved-warning',form);
      if(!warning){warning=document.createElement('div');warning.className='unsaved-warning';warning.setAttribute('role','alert');warning.innerHTML='<b>Есть несохранённые изменения</b><p>Продолжите редактирование или закройте форму без сохранения.</p><div><button type="button" class="primary-button" data-action="continue-edit">Продолжить</button><button type="button" class="outline-button" data-action="discard-modal">Не сохранять</button></div>';form.append(warning);}
      $('[data-action="continue-edit"]',warning).focus();return false;
    }
    state.modalId++;clearTimeout(globalSearchTimer);$('#modal-root')?.replaceChildren();$('.shell')?.removeAttribute('inert');$('.skip-link')?.removeAttribute('inert');document.body.classList.remove('modal-open');if(lastFocus?.isConnected)lastFocus.focus({preventScroll:true});lastFocus=null;return true;
  }
  const draftKey=(kind='request')=>`atlas.draft.${state.user?.id}${kind==='certificate'?'.certificate':''}`;
  const draftMemory=new Map();
  let draftStorageAvailable=true;
  const removeDraft=kind=>{const key=draftKey(kind);draftMemory.set(key,{});try{sessionStorage.removeItem(key);}catch{/* Saving on the server does not depend on browser storage. */}};
  const requestKey=()=>typeof crypto.randomUUID==='function'?crypto.randomUUID():[...crypto.getRandomValues(new Uint8Array(24))].map(x=>x.toString(16).padStart(2,'0')).join('');
  function readDraft(kind){
    const key=draftKey(kind);
    if(draftMemory.has(key))return draftMemory.get(key);
    let value={};
    try{
      const legacy=JSON.parse(sessionStorage.getItem(draftKey()))||{};
      if(['study','transcript','scholarship','tax','military'].includes(legacy.type)&&!sessionStorage.getItem(draftKey('certificate'))){
        sessionStorage.setItem(draftKey('certificate'),JSON.stringify(legacy));
        sessionStorage.removeItem(draftKey());
      }
      value=JSON.parse(sessionStorage.getItem(key))||{};
    }catch{draftStorageAvailable=false;}
    draftMemory.set(key,value);
    return value;
  }
  function saveDraft(value,kind){const key=draftKey(kind);draftMemory.set(key,value);try{sessionStorage.setItem(key,JSON.stringify(value));draftStorageAvailable=true;}catch{draftStorageAvailable=false;}}
  function updateDraftNote(form){const note=$('.draft-note',form);if(note)note.innerHTML=`${icon('checkCircle')} ${draftStorageAvailable?'Черновик остаётся в этой вкладке до отправки или выхода.':'Черновик в памяти вкладки. Перезагрузка удалит его.'}`;}
  function storeDraft(form){
    const kind=form.dataset.requestKind;
    saveDraft({...readDraft(kind),type:form.elements.type.value,comment:form.elements.comment.value,details:Object.fromEntries($$('[data-service-field]',form).map(x=>[x.name,x.value]))},kind);
    updateDraftNote(form);
  }
  async function newRequestModal(type, preferredKind){
    if(state.user?.role!=='student'||state.pending)return;
    const epoch=state.sessionEpoch,uid=state.user.id,modalId=state.modalId,routeHref=state.routeHref;
    const current=()=>state.sessionEpoch===epoch&&state.user?.id===uid&&state.modalId===modalId&&state.routeHref===routeHref&&!state.pending;
    let catalog;
    try{catalog=await api('requests/types');}catch(error){if(!error.stale)toast(error.message);return;}
    if(!current())return;
    const explicit=catalog.find(t=>t.id===type);
    if(explicit?.available===false){toast(explicit.unavailable_reason);return;}
    const kind=explicit?.kind||preferredKind||(state.page==='certificates'?'certificate':'request');
    const types=catalog.filter(t=>t.kind===kind&&t.available!==false);
    if(kind==='request'&&!state.data.gradeOptions){
      try{const grades=await api('grades');if(!current())return;state.data.gradeOptions=grades.items;}
      catch(error){if(!error.stale)toast(error.message);return;}
    }
    const draft=readDraft(kind),chosen=explicit?.id||types.find(t=>t.id===draft.type)?.id||types[0]?.id;
    const comment=explicit&&draft.type!==explicit.id?'':draft.comment||'';
    const label=kind==='certificate'?'Заказать справку':'Новая заявка';
    modal(modalHead(label,'Учебный офис')+`<form id="request-form" data-request-kind="${kind}" data-explicit-type="${esc(explicit?.id||'')}">
      <div class="field"><label for="doc-type">${kind==='certificate'?'Вид справки':'Вид обращения'}</label>
      <select id="doc-type" name="type" required autofocus>${types.map(t=>`<option value="${esc(t.id)}" ${t.id===chosen?'selected':''}>${esc(t.name)}</option>`).join('')}</select></div>
      <div class="selected-service" id="selected-service"></div><div id="service-details" class="service-detail-fields"></div>
      <div class="field"><label for="doc-comment" id="comment-label">Комментарий</label>
      <textarea id="doc-comment" name="comment" maxlength="1200" rows="4" aria-describedby="comment-hint">${esc(comment)}</textarea>
      <div class="field-meta"><span id="comment-hint">Не вводите персональные данные.</span><span id="comment-count">${comment.length} / 1200</span></div></div>
      <div class="draft-note"></div><div id="request-error" class="inline-error" role="alert" hidden></div>
      <div class="modal-actions"><button class="muted-button" type="button" data-action="close-modal">Сохранить на потом</button>
      <button class="primary-button" type="submit">${icon('send')} ${kind==='certificate'?'Отправить заказ':'Отправить заявку'}</button></div></form>`,{label});
    const form=$('#request-form');form._types=types;updateRequestType(form);updateDraftNote(form);form.addEventListener('input',()=>{storeDraft(form);$('#comment-count').textContent=`${form.elements.comment.value.length} / 1200`;});form.addEventListener('change',()=>{updateRequestType(form);storeDraft(form);});
  }
  function renderServiceFields(form,service){
    const type=service.id;
    const holder=$('#service-details',form);if(!holder||holder.dataset.type===type)return;holder.dataset.type=type;
    const stored=readDraft(form.dataset.requestKind),draft=stored.type===type?stored.details||{}:{};
    const input=(name,label,value,extra='')=>`<div class="field"><label for="service-${name}">${label}</label><input id="service-${name}" name="${name}" data-service-field value="${esc(draft[name]??value)}" ${extra}></div>`;
    if(type==='study')holder.innerHTML=input('purpose','Для чего нужна справка','По месту требования','maxlength="120" required')+`<div class="field"><label for="service-copies">Количество экземпляров</label><select id="service-copies" name="copies" data-service-field>${['1','2','3'].map(x=>`<option ${draft.copies===x?'selected':''}>${x}</option>`).join('')}</select></div>`;
    else if(type==='transcript')holder.innerHTML=input('period','Учебный период','Текущий семестр','maxlength="80" required')+`<div class="field"><label for="service-format">Формат результата</label><select id="service-format" name="format" data-service-field><option>HTML</option><option>PDF через печать</option></select></div>`;
    else if(type==='retake')holder.innerHTML=`<div class="field"><label for="service-subject">Дисциплина</label><select id="service-subject" name="subject" data-service-field required>${(state.data.gradeOptions||[]).map(x=>`<option value="${esc(x.subject)}" ${draft.subject===x.subject?'selected':''}>${esc(x.subject)}</option>`).join('')}</select></div>`+input('preferred_date','Желаемая дата (будет согласована сотрудником)',addDays(today(),7),`type="date" min="${today()}" max="${addDays(today(),180)}" required`);
    else if(service.destinations)holder.innerHTML=`<div class="field"><label for="service-commissioner">Военный комиссариат</label>
      <select id="service-commissioner" name="commissioner" data-service-field required><option value="">Выберите комиссариат</option>
      ${Object.entries(service.destinations).map(([id,name])=>`<option value="${esc(id)}" ${draft.commissioner===id?'selected':''}>${esc(name)}</option>`).join('')}</select></div>`;
    else holder.innerHTML='';
  }
  function updateRequestType(form){
    const service=form._types.find(x=>x.id===form.elements.type.value);if(!service)return;
    $('#selected-service',form).innerHTML=`${icon('clock')}<span><b>${esc(service.department)} · ${esc(service.eta)}</b>
      <small>${esc(service.required_data||service.description)}</small></span>`;
    renderServiceFields(form,service);
    const required=Boolean(service.id==='statement'||service.requires_comment);
    form.elements.comment.required=required;form.elements.comment.minLength=required?10:0;
    $('#comment-label',form).textContent=required?'Ваш вопрос или заявление':'Комментарий (необязательно)';
  }
  function beginFormOperation(form){
    const epoch=state.sessionEpoch,uid=state.user?.id,modalId=state.modalId;let released=false;
    state.pending++;const controls=$$('input,select,textarea,button',form);controls.forEach(x=>x.disabled=true);
    return {current:()=>epoch===state.sessionEpoch&&uid===state.user?.id&&modalId===state.modalId&&form.isConnected,
      release(){if(released)return;released=true;if(epoch===state.sessionEpoch&&uid===state.user?.id)state.pending=Math.max(0,state.pending-1);},
      finish(focus){this.release();if(form._atlasDraft)form._atlasDraft.submitting=false;if(this.current()){controls.forEach(x=>x.disabled=false);if(focus?.isConnected&&!focus.disabled)focus.focus();}}};
  }
  async function submitRequest(form){
    if(state.pending)return;const operation=beginFormOperation(form),button=$('button[type="submit"]',form),error=$('#request-error',form);let validationFocus;button.textContent='Подготавливаем…';error.hidden=true;
    try{
      await improvements.prepareFormSubmission(form);if(!operation.current())return;
      storeDraft(form);const body={type:form.elements.type.value,comment:form.elements.comment.value.trim(),details:Object.fromEntries($$('[data-service-field]',form).map(x=>[x.name,x.value]))};
      if((body.type==='statement'||form._types.find(t=>t.id===body.type)?.requires_comment)&&body.comment.length<10)throw new Error('Опишите вопрос хотя бы в 10 символах.');
      const key=await improvements.formSubmission(form,body);if(!operation.current())return;
      saveDraft({...body,key,fingerprint:JSON.stringify(body)},form.dataset.requestKind);button.textContent='Отправляем…';
      const result=await api('requests',{method:'POST',headers:{'Idempotency-Key':key},body:JSON.stringify(body)});if(!operation.current())return;
      removeDraft(form.dataset.requestKind);try{await improvements.clearFormDraft(form);}catch(e){if(!e.stale)toast('Заявка сохранена. Очистить черновик пока не удалось.');}if(!operation.current())return;
      operation.release();await requestDetails(result.id);if(['requests','certificates'].includes(state.page)){state.requestFilter='all';state.requestView='mine';state.requestOffset=0;updatePage({quiet:true});}refreshUnread();toast(`Заявка № ${result.id} сохранена. Можно следить за статусом.`);
    }catch(e){if(!e.stale&&operation.current()){error.hidden=false;error.textContent=e.message;validationFocus=improvements.showFieldErrors(e,form);button.innerHTML=`${icon('send')} Повторить отправку`;}}
    finally{operation.finish(validationFocus);}
  }
  function requestHistoryPager(r){const total=r.history_total??r.history?.length??0,limit=r.history_limit||100,offset=r.history_offset||0;return total>limit?`<nav class="pagination" aria-label="Страницы истории заявки"><span role="status">${offset+1}–${Math.min(total,offset+(r.history||[]).length)} из ${total}</span><div><button type="button" class="outline-button" data-action="request-history" data-id="${Number(r.id)}" data-offset="${Math.max(0,offset-limit)}" ${offset?'':'disabled'}>Ранее</button><button type="button" class="outline-button" data-action="request-history" data-id="${Number(r.id)}" data-offset="${offset+limit}" ${r.history_has_more?'':'disabled'}>Позже</button></div></nav>`:'';}
  function requestHistoryMarkup(r){return `<section class="detail-block" data-request-history data-id="${Number(r.id)}"><ol class="request-history">${(r.history||[]).map(event=>`<li><span class="history-mark">${icon('check')}</span><div><b>${esc(statusNames[event.status]||event.status)}</b><time>${stamp(event.created_at)} МСК · ${esc(event.actor_name||'Система')}</time>${event.message?`<p class="user-text">${esc(event.message)}</p>`:''}</div></li>`).join('')}</ol>${requestHistoryPager(r)}</section>`;}
  async function loadRequestHistory(id,offset,button){const epoch=state.sessionEpoch,uid=state.user?.id,modalId=state.modalId,section=$('[data-request-history]');if(!section)return;const revision=Number(section.dataset.revision||0)+1;section.dataset.revision=String(revision);section.setAttribute('aria-busy','true');button.disabled=true;try{const r=await api(`${state.user.role==='staff'?'staff/':''}requests/${Number(id)}?history_limit=100&history_offset=${Number(offset)}`);if(epoch!==state.sessionEpoch||uid!==state.user?.id||modalId!==state.modalId||!section.isConnected||Number(section.dataset.revision)!==revision)return;const holder=document.createElement('div');holder.innerHTML=requestHistoryMarkup(r);section.replaceWith(holder.firstElementChild);$('[data-request-history] .pagination button:not(:disabled)')?.focus({preventScroll:true});}catch(e){if(!e.stale){toast(e.message);if(button.isConnected)button.disabled=false;}}finally{section.removeAttribute('aria-busy');}}
  function requestDetailFields(fields){
    return fields.length?`<dl class="service-details-summary">${fields.map(({label,value})=>
      `<div><dt>${esc(label)}</dt><dd>${esc(value)}</dd></div>`).join('')}</dl>`:'';
  }
  async function requestDetails(id){
    if(!Number.isSafeInteger(Number(id)))return;
    const staff=state.user?.role==='staff';modal(modalHead(`Заявка № ${id}`,'Загружаем историю и результат…')+loading(),{wide:true,label:`Заявка № ${id}`});const modalId=state.modalId;
    try{const r=await api(`${staff?'staff/':''}requests/${Number(id)}`);if(modalId!==state.modalId)return;
      const terminal=['ready','rejected'].includes(r.status);const steps=['submitted','review','processing','ready'];const index=steps.indexOf(r.status);
      const labels={purpose:'Назначение',copies:'Экземпляры',period:'Учебный период',format:'Формат',
        subject:'Дисциплина',preferred_date:'Желаемая дата',commissioner:'Военный комиссариат'};
      const details=Object.entries(r.details||{}).map(([key,value])=>({label:labels[key]||key,value}));
      const result=!staff&&r.document_url?`<div class="document-result"><div><b>Результат готов</b>
        <p>${r.kind==='certificate'?'Подготовленный документ без подписи и печати.':'В результате сохранён ответ учебного офиса.'}</p></div>
        ${r.kind==='certificate'?`<a class="outline-button" href="${esc(r.document_url)}?preview=true" data-document-preview target="_blank" rel="noopener noreferrer">Открыть</a>`:''}
        <a class="primary-button" href="${esc(r.document_url)}" download>${icon('download')} Скачать</a></div>`:'';
      const summary=`<div class="detail-summary"><span class="file-glyph">${icon('file')}</span><div><h3>${esc(r.type)}</h3>
        <p>${staff?`${esc(r.student_name||'')} · ${esc(r.group||'')}<br>`:''}Создана ${stamp(r.created_at)} МСК · ${esc(r.department)}</p></div>${badge(r)}</div>
        <div class="request-track" aria-label="Этапы заявки">${steps.map((s,i)=>`<div class="track-step ${r.status!=='rejected'&&i<=index?'complete':''} ${s===r.status?'current':''}"><span>${i<index?icon('check'):i+1}</span><b>${statusNames[s]}</b></div>`).join('')}</div>
        ${!terminal?`<div class="detail-eta">${icon('clock')}<span>Ориентир готовности: <b>${dateFmt(r.due_at,{day:'numeric',month:'long',year:'numeric'})}</b></span></div>`:''}
        ${requestDetailFields(details)}
        ${r.comment?`<div class="detail-block"><h3>Комментарий студента</h3><p class="user-text">${esc(r.comment)}</p></div>`:''}
        ${r.staff_message?`<div class="staff-answer ${r.status==='rejected'?'answer-rejected':''}"><span>${icon(r.status==='rejected'?'info':'checkCircle')}</span>
        <div><h3>${r.status==='rejected'?'Причина отклонения':'Ответ учебного офиса'}</h3><p class="user-text">${esc(r.staff_message)}</p></div></div>`:''}${result}`;
      const enrollment=Array.isArray(r.certificate_enrollment)?
        disclosure('Сведения для приложения № 4',r.certificate_enrollment.length?requestDetailFields(r.certificate_enrollment):
          '<p>В реестре нет подтверждённых сведений для подготовки справки.</p>'):'';
      const history=requestHistoryMarkup(r);
      const staffForm=staff&&!terminal?`<form id="staff-form" data-id="${Number(r.id)}" data-version="${Number(r.version)}">
        <h3>Решение учебного офиса</h3><div class="field"><label for="staff-status">Следующий этап</label>
        <select id="staff-status" name="status" required><option value="">Выберите действие</option>
        ${(transitions[r.status]||[]).filter(s=>s!=='ready'||r.certificate_enrollment?.length!==0).map(s=>`<option value="${s}">${statusNames[s]}</option>`).join('')}</select></div>
        ${r.certificate_enrollment?.length?`<label class="certificate-confirmation"><input name="confirmed_enrollment" type="checkbox">
          <span>Сверены сведения об обучении для приложения № 4. Отметьте для подготовки справки.</span></label>`:''}
        <div class="field"><label for="staff-message">Ответ студенту</label>
        <textarea id="staff-message" name="message" maxlength="1600" rows="3" aria-describedby="staff-hint"></textarea>
        <span class="hint" id="staff-hint">При запросе уточнений, подготовке результата или отклонении нужен ответ от 10 символов.</span></div>
        <div class="inline-error" id="staff-error" role="alert" hidden></div><div class="modal-actions">
        <button class="primary-button" type="submit">${icon('check')} Сохранить и уведомить</button></div></form>`:'';
      modal(modalHead(`Заявка № ${r.id}`,'Каждый этап и ответ — в вашей истории')+summary+enrollment+staffForm+(!staff&&!terminal?`<details class="card disclosure"><summary>Уточнить сведения или попросить отозвать</summary><div class="disclosure-body"><p>Сообщение сохранится в истории. Статус меняет сотрудник; просьба об отзыве требует его решения.</p><form id="request-followup" data-id="${Number(r.id)}" data-version="${Number(r.version)}"><div class="field"><label for="followup-kind">Что изменилось</label><select name="kind" id="followup-kind"><option value="clarification">Уточнение сведений</option><option value="withdrawal">Просьба отозвать заявку</option></select></div><div class="field"><label for="followup-message">Сообщение сотруднику</label><textarea id="followup-message" name="message" minlength="10" maxlength="1200" required></textarea></div><div id="followup-error" class="inline-error" role="alert" hidden></div><button type="submit" class="primary-button">Отправить уточнение</button></form></div></details>`:'')+disclosure('История заявки',history),{wide:true,label:`Заявка № ${r.id}`});
    }catch(error){if(modalId!==state.modalId)return;modal(modalHead('Не удалось открыть заявку','')+`<div class="inline-error" role="alert">${esc(error.message)}</div><button class="primary-button" data-action="request-details" data-id="${id}">Повторить</button>`,{label:'Ошибка загрузки заявки'});}
  }
  async function submitFollowup(form){
    if(state.pending)return;const operation=beginFormOperation(form),error=$('#followup-error',form);let validationFocus;error.hidden=true;
    try{await improvements.prepareFormSubmission(form);if(!operation.current())return;const body={kind:form.elements.kind.value,message:form.elements.message.value.trim(),expected_version:Number(form.dataset.version)};
      const key=await improvements.formSubmission(form,body);if(!operation.current())return;
      await api(`requests/${Number(form.dataset.id)}/followup`,{method:'POST',headers:{'Idempotency-Key':key},body:JSON.stringify(body)});
      if(!operation.current())return;try{await improvements.clearFormDraft(form);}catch(e){if(!e.stale)toast('Уточнение сохранено. Очистить черновик пока не удалось.');}if(!operation.current())return;
      operation.release();await requestDetails(Number(form.dataset.id));toast('Уточнение сохранено в истории. Сотрудник рассмотрит его.');
    }catch(e){if(!e.stale&&operation.current()){error.hidden=false;error.textContent=e.message;validationFocus=improvements.showFieldErrors(e,form);}}
    finally{operation.finish(validationFocus);}
  }
  async function submitStaff(form){
    if(state.pending)return;const id=Number(form.dataset.id);const body={status:form.elements.status.value,message:form.elements.message.value.trim(),expected_version:Number(form.dataset.version)};
    const error=$('#staff-error',form);error.hidden=true;
    if(['needs_info','ready','rejected'].includes(body.status)&&body.message.length<10){error.hidden=false;error.textContent='Напишите понятный ответ студенту (не менее 10 символов).';form.elements.message.focus();return;}
    const confirmation=form.elements.confirmed_enrollment;
    if(body.status==='ready'&&confirmation){
      if(!confirmation.checked){error.hidden=false;error.textContent='Подтвердите сверку сведений для приложения № 4.';confirmation.focus();return;}
      body.confirmed_enrollment=true;
    }
    const operation=beginFormOperation(form);
    let validationFocus;
    try{
      await api(`staff/requests/${id}/status`,{method:'POST',body:JSON.stringify(body)});
      if(!operation.current())return;
      operation.release();await requestDetails(id);updatePage({quiet:true});
      toast(`Заявка № ${id}: ${statusNames[body.status]}. Студент получил уведомление.`);
    }catch(e){
      if(e.stale||!operation.current())return;
      error.hidden=false;error.textContent=e.message;validationFocus=improvements.showFieldErrors(e,form);
      if(e.status===409)error.insertAdjacentHTML('beforeend',` <button class="mini-link" type="button" data-action="request-details" data-id="${id}">Обновить заявку</button>`);
    }finally{operation.finish(validationFocus);}
  }
  const searchWords={home:'главная сегодня пары',schedule:'пары когда аудитория неделя преподаватель',grades:'оценки оценка успеваемость результаты баллы посещения пропуски журнал',plan:'план сроки дедлайны отметки',requests:'обращение заявление подать статус',certificates:'справка справку документ заказать военный комиссариат',notifications:'новости объявления уведомления прочитать',courses:'учебный план материалы лекции дисциплины предметы',assignments:'задания сдать работа работы лабораторная отправить пересдать',exams:'экзамен сессия зачёт допуск калькулятор',tasks:'дела задачи список',notes:'заметки конспекты запись',consultations:'консультация консультации записаться преподаватель',messages:'деканат вопрос написать помощь переписка ответ',events:'события мероприятия кружки участие',finance:'деньги стипендия оплата долг',contacts:'телефон адрес кабинет контакты корпуса',knowledge:'помощь правила как вопросы',portfolio:'портфолио проекты достижения',profile:'профиль имя группа курс факультет',settings:'настройки сеансы выход безопасность'};
  const normalise=value=>String(value).toLocaleLowerCase('ru').replaceAll('ё','е').trim();
  const matchesPage=(p,q)=>normalise(q).split(/\s+/).every(word=>normalise(`${p.label} ${p.hint} ${searchWords[p.id]||''}`).includes(word));
  function searchModal(){
    if($('.modal form[data-dirty="true"]')&&!closeModal())return;
    const options=menuFor(state.user.role);const student=state.user.role==='student';
    modal(modalHead('Поиск по кабинету',student?'Найдите раздел, задание, заявку или личную заметку.':'Найдите нужный раздел учебного офиса.')+`<label class="search-field search-large">${icon('search')}<input id="search-input" maxlength="100" aria-label="Поиск по кабинету" placeholder="Например, оценки, справка или конспект" autofocus autocomplete="off" /></label><div class="search-results" id="search-results"></div>`,{label:'Поиск по кабинету'});
    const modalId=state.modalId;const epoch=state.sessionEpoch;let revision=0;
    const draw=async q=>{
      const current=++revision;clearTimeout(globalSearchTimer);
      const shortcuts=student?['schedule','grades','assignments','requests','certificates','direct']
        :state.user.role==='staff'?['staff','staffmessages','staffdesk','schedule-changes','direct']
        :state.user.role==='teacher'?['teacher','teaching','teach-schedule','direct','materials-admin']
        :['union','vuc'].includes(state.user.role)?[state.user.role+'-office','notifications','profile']
        :['timetable-admin','schedule-changes','registry','tables'];
      const choices=q?options.filter(p=>matchesPage(p,q)):options.filter(p=>shortcuts.includes(p.id));
      $('#search-results').innerHTML=`<p class="search-group-label">${q?'Разделы':'Часто нужно'}</p>`+(choices.length?choices.map(p=>`<button class="search-result" data-route="${esc(p.id)}">${icon(p.icon)}<span><b>${esc(p.label)}</b><small>${esc(p.hint)}</small></span>${icon('right')}</button>`).join(''):'<p class="search-empty">Раздел не найден. Попробуйте «оценки», «справка» или «конспекты».</p>')+(student&&q.length>=2?'<div id="search-personal" aria-live="polite"><p class="search-group-label" role="status">Ищем в ваших данных…</p></div>':'');
      if(!student||q.length<2)return;
      globalSearchTimer=setTimeout(async()=>{
        try{const result=await api('campus/search?q='+encodeURIComponent(q));if(current!==revision||modalId!==state.modalId||epoch!==state.sessionEpoch)return;
          const target=$('#search-personal');if(!target)return;target.innerHTML='<p class="search-group-label">Мои данные</p>'+((result.items||[]).length?result.items.map(x=>`<button class="search-result" data-search-target="${esc(x.target)}" data-search-id="${Number(x.id)}">${icon('file')}<span><b>${esc(x.title)}</b><small>${esc(x.category)} · ${esc(x.snippet)}</small></span>${icon('right')}</button>`).join(''):'<p class="search-empty">В ваших данных совпадений нет.</p>');
        }catch(error){if(!error.stale&&current===revision&&modalId===state.modalId&&epoch===state.sessionEpoch){const target=$('#search-personal');if(target){target.replaceChildren();const message=document.createElement('p');message.className='search-empty';message.setAttribute('role','alert');message.textContent=error.message;target.append(message);}}}
      },240);
    };
    draw('');$('#search-input').addEventListener('input',e=>draw(e.target.value.trim()));
  }
  function clearSession({expired=false}={}){deadlineWrites.clear();improvements.reset(expired);campus.reset();extensions.forEach(ext=>ext.reset?.());clearInterval(pollTimer);state.sessionEpoch++;state.loadingId++;state.modalId++;state.pending=0;removeDraft();removeDraft('certificate');draftMemory.clear();draftStorageAvailable=true;state.user=null;state.data={};state.unread=0;state.staffQuery='';state.requestOffset=state.noticeOffset=state.staffOffset=0;state.requestFilter=state.noticeFilter='all';state.requestView='mine';state.serviceQuery='';state.staffFilter='active';state.staffKind='request';state.planFilter='active';$('.skip-link')?.removeAttribute('inert');document.body.classList.remove('modal-open');}
  const demoAccounts=[
    {login:'alina.demo',password:'AtlasDemo!2026-A',full_name:'Алина Ветрова',initials:'АВ',accent:'purple',description:'2 курс · ИТ-24-03 · занятия и справки'},
    {login:'mark.demo',password:'AtlasDemo!2026-M',full_name:'Марк Северин',initials:'МС',accent:'orange',description:'3 курс · ПИ-23-02 · материалы и задания'},
    {login:'dean.demo',password:'AtlasStaff!2026-D',full_name:'Кира Миронова',initials:'КМ',accent:'blue',description:'Учебный офис · обработка заявок'},
    {login:'orlov.demo',password:'AtlasTeach!2026-M',full_name:'Михаил Орлов',initials:'МО',accent:'purple',description:'Преподаватель · материалы и переписка'},
    {login:'schedule.demo',password:'AtlasRooms!2026-S',full_name:'София Берестова',initials:'СБ',accent:'blue',description:'Диспетчер · расписание и аудитории'},
    {login:'registry.demo',password:'AtlasRegistry!2026-R',full_name:'Роман Ильин',initials:'РИ',accent:'blue',description:'Администратор · справочники и утверждение'},
    {login:'union.demo',password:'AtlasUnion!2026-U',full_name:'Полина Савельева',initials:'ПС',accent:'blue',description:'Профсоюз · членство и обращения'},
    {login:'vuc.demo',password:'AtlasCenter!2026-V',full_name:'Артём Неверов',initials:'АН',accent:'blue',description:'ВУЦ · учебный офис'},
    {login:'ryabinina.demo',password:'AtlasTeach!2026-E',full_name:'Елена Рябинина',initials:'ЕР',accent:'purple',description:'Преподаватель · базы данных'},
    {login:'lastochkina.demo',password:'AtlasTeach!2026-N',full_name:'Нина Ласточкина',initials:'НЛ',accent:'purple',description:'Преподаватель · проектирование интерфейсов'},
    {login:'zorin.demo',password:'AtlasTeach!2026-Z',full_name:'Даниил Зорин',initials:'ДЗ',accent:'purple',description:'Преподаватель · анализ данных'},
  ];
  function showLogin(){
    document.body.classList.remove('nav-drawer-open');
    document.title='Вход в кампус — АТЛАС';
    app.innerHTML=`<main class="login-page" id="page-content">
      ${conceptNotice()}
      <div class="login-root">
        <section class="login-art">
          ${logo()}
          <div class="login-copy">
            <h2>Твой кампус.<br>В твоём <em>ритме.</em></h2>
            <p>Расписание, заявки, справки и связь с учебным офисом.</p>
            <div class="login-illustration" aria-hidden="true">
              <div class="illustration-grid"></div>
              <div class="login-ticket"><span>МОЙ ДЕНЬ / АТЛАС</span><div><b>${dateFmt(today(),{day:'numeric'})}</b><span>${dateFmt(today(),{month:'long'})}<small>${dateFmt(today(),{weekday:'long'})}</small></span></div></div>
              <div class="illustration-bubble">${icon('checkCircle')} Справка готова<small>Можно скачать в кабинете</small></div>
              <span class="illustration-star">✳</span>
            </div>
          </div>
        </section>
        <section class="login-panel">
          <div class="login-mobile-brand">${logo()}</div>
          <div class="login-form-wrap">
            <h1>Вход в кабинет</h1>
            <form id="login-form">
              <div class="field"><label for="login-name">Логин</label><input id="login-name" name="login" required autocomplete="username" autocapitalize="none" spellcheck="false" maxlength="100" placeholder="Ваш логин" /></div>
              <div class="login-actions">
                <div class="field"><label for="login-password">Пароль</label><div class="password-wrap"><input id="login-password" name="password" type="password" required autocomplete="current-password" enterkeyhint="go" maxlength="200" placeholder="Введите пароль" /><button class="password-toggle" type="button" data-action="password" aria-controls="login-password" aria-pressed="false">Показать</button></div></div>
                <div class="inline-error" id="login-error" role="alert" hidden></div>
                <button class="primary-button login-submit" type="submit">Войти в кабинет ${icon('arrow')}</button>
              </div>
            </form>
            ${state.config.demo_mode?'<button class="outline-button demo-trigger" type="button" data-action="demo-picker" aria-haspopup="dialog">Выбрать аккаунт</button>':''}
          </div>
        </section>
      </div>
    </main>${state.config.demo_mode?demoDialog():''}`;
  }
  function revealLoginField(){
    const field=document.activeElement;
    if(field?.form?.id!=='login-form'||field.tagName!=='INPUT'||!document.documentElement.hasAttribute('data-atlas-keyboard'))return;
    window.ATLASViewport?.reveal(field.closest('.login-actions')||field,field);
  }
  document.addEventListener('atlas:viewport',revealLoginField);

  function demoDialog(){
    const groups=[['Студенты',[0,1]],['Преподаватели',[3,8,9,10]],['Сотрудники',[2,4,5,6,7]]];
    return `<dialog class="demo-dialog" id="demo-dialog" aria-labelledby="demo-title">
      <header class="modal-head"><div><h2 id="demo-title">Выбрать аккаунт</h2><p>Выберите аккаунт для входа в кабинет.</p></div><button type="button" class="close-btn" data-action="demo-close" aria-label="Закрыть выбор аккаунта" autofocus>${icon('close')}</button></header>
      <div class="inline-error" id="demo-error" role="alert" hidden></div>
      <div class="demo-list">${groups.map(([role,indices])=>`<section aria-label="${role}"><h3>${role}</h3>${indices.map(i=>{const u=demoAccounts[i];return `<button type="button" class="demo-user" data-demo="${i}">${avatar(u)}<span><b>${esc(u.full_name)}</b><small>${esc(u.description)}</small></span>${icon('arrow')}</button>`;}).join('')}</section>`).join('')}</div>
    </dialog>`;
  }
  async function submitLogin(form,demo=null,demoButton=null){
    if(form.dataset.pending)return;
    form.dataset.pending='true';
    const controls=[$('button[type="submit"]',form),...$$('[data-demo], [data-action="demo-picker"]')];
    const pending=demoButton||controls[0],originalLabel=pending.innerHTML;
    pending.textContent='Входим…';
    controls.forEach(button=>button.disabled=true);
    $$('#login-error, #demo-error').forEach(error=>error.hidden=true);
    try{
      const credentials=demo||{login:form.elements.login.value,password:form.elements.password.value};
      const {user}=await api('login',{method:'POST',body:JSON.stringify({login:credentials.login,password:credentials.password})});
      state.sessionEpoch++;state.user=user;announceIdentity();await campus.prepare();if(!state.user)return;
      await enterRoute();startPolling();await improvements.resumeRecovery();toast(`С возвращением, ${user.full_name.split(' ')[0]}!`);
    }catch(e){
      const error=$('#demo-dialog[open] #demo-error')||$('#login-error');
      if(error){error.hidden=false;error.textContent=e.message;}
      controls.forEach(button=>button.disabled=false);
      pending.innerHTML=originalLabel;
      delete form.dataset.pending;
      if(error?.id==='login-error')requestAnimationFrame(revealLoginField);
    }
  }
  async function refreshUnread(){
    if(!state.user||document.hidden)return;
    const epoch=state.sessionEpoch;
    try{
      const data=await api('notifications/unread',{quietAuth:true});
      if(state.sessionEpoch===epoch){state.unread=data.unread_count;updateBadges();}
    }catch{/* Explicit requests show errors. */}
  }
  function pollBadges(){
    if(!state.user||document.hidden||badgePoll)return;
    const epoch=state.sessionEpoch;
    const poll=(async()=>{
      if(['student','teacher','staff'].includes(state.user.role))university.pollUnread();
      if(state.user.role==='student'&&Date.now()-reminderCheckedAt>=900000){
        reminderCheckedAt=Date.now();
        try{
          await api('notifications/deadline-reminders',{method:'POST',quietAuth:true});
          if(epoch===state.sessionEpoch)sessionStorage.setItem(`atlas:reminders:${state.user.id}`,String(reminderCheckedAt));
        }catch{/* The current page still throttles reminders if storage or the network is unavailable. */}
      }
      if(epoch!==state.sessionEpoch)return;
      await refreshUnread();
      if(epoch===state.sessionEpoch&&state.page==='notifications'&&state.data.notifications&&
         state.unread!==state.data.notifications.unread_count&&!state.pending&&!$('.modal')&&
         !document.activeElement?.closest('.notification-page, [data-action="read-all"]'))await updatePage({quiet:true});
    })().finally(()=>{if(badgePoll===poll)badgePoll=null;});
    badgePoll=poll;
  }
  function startPolling(){
    clearInterval(pollTimer);
    badgePoll=null;
    reminderCheckedAt=0;
    try{reminderCheckedAt=Number(sessionStorage.getItem(`atlas:reminders:${state.user.id}`))||0;}catch{/* Storage can be disabled. */}
    pollBadges();
    pollTimer=setInterval(pollBadges,20000);
  }
  async function markRead(id){await api(`notifications/${Number(id)}/read`,{method:'POST'});const data=state.data.notifications;if(data){const item=data.items.find(n=>n.id===Number(id));if(item&&!item.is_read){item.is_read=true;data.counts.unread=Math.max(0,data.counts.unread-1);data.unread_count=data.counts.unread;}}await refreshUnread();}
  async function openNotice(id){
    try{
      const epoch=state.sessionEpoch;const modalId=state.modalId;const loadId=state.loadingId;const page=state.page;
      const current=()=>epoch===state.sessionEpoch&&modalId===state.modalId&&loadId===state.loadingId&&page===state.page;
      const n=await api('notifications/'+Number(id));if(!current())return;
      await markRead(id);if(!current())return;
      if(n.request_id){
        const office=state.user.role==='staff';
        const destination=office?'staff':n.target==='/app/certificates'?'certificates':'requests';
        if(office){state.staffKind=n.target==='/app/staff?kind=certificate'?'certificate':'request';state.staffOffset=0;state.staffQuery='';}
        const loading=route(destination);const nextModalId=state.modalId;const nextLoadId=state.loadingId;
        await loading;
        if(epoch===state.sessionEpoch&&state.page===destination&&nextModalId===state.modalId&&nextLoadId===state.loadingId)await requestDetails(Number(n.request_id));
        return;
      }
      const aliases={'/app/support':'/app/messages','/app/campus':'/app/events'};
      const href=aliases[n.target]||n.target||({schedule:'/app/schedule',deadline:'/app/plan',request:'/app/requests'}[n.category]);
      if(/^\/app\/[a-z][a-z0-9-]*(?:\/[a-z0-9-]+)*(?:\?[^#]*)?$/.test(href||'')){
        const url=new URL(href,location.origin), destination=routeFromUrl(url).page;
        if(destination!=='notifications'&&menuFor(state.user.role).some(item=>item.id===destination)){
          await goToUrl(url);return;
        }
      }
      modal(modalHead(n.title,stamp(n.created_at)+' МСК')+`<p class="user-text campus-body">${esc(n.body)}</p><div class="modal-actions"><button class="primary-button" data-action="close-modal">Прочитано</button></div>`,{label:'Уведомление'});
      if(state.page==='notifications')updatePage({quiet:true});
    }catch(error){if(!error.stale)toast(error.message);}
  }
  async function openSearchResult(page,id){
    if(state.pending||!Number.isSafeInteger(id)||id<1||!pages.some(p=>p.id===page))return;
    const epoch=state.sessionEpoch;campus.clearFilters(page);
    if(['requests','certificates'].includes(page)){state.requestView='mine';state.requestFilter='all';state.requestOffset=0;}
    if(page==='notifications'){state.noticeFilter='all';state.noticeOffset=0;}
    if(page==='plan')state.planFilter='all';
    const loading=route(page);const modalId=state.modalId;const loadId=state.loadingId;await loading;if(epoch!==state.sessionEpoch||page!==state.page||modalId!==state.modalId||loadId!==state.loadingId)return;
    if(['requests','certificates'].includes(page)){await requestDetails(id);return;}
    if(page==='notifications'){await openNotice(id);return;}
    if(['notes','portfolio'].includes(page)){campus.openResult(page,id);return;}
    const row=page==='grades'?$(`[data-record-id="${id}"]`):page==='plan'?$(`[data-deadline="${id}"]`)?.closest('.deadline-item'):null;
    if(row){row.classList.add('search-match');row.tabIndex=-1;row.scrollIntoView({block:'center',behavior:'instant'});row.focus({preventScroll:true});}
  }
  document.addEventListener('submit',e=>{const form=e.target;if(!['login-form','request-form','staff-form','request-followup'].includes(form.id))return;e.preventDefault();if(form.id==='login-form')submitLogin(form);if(form.id==='request-form')submitRequest(form);if(form.id==='staff-form')submitStaff(form);if(form.id==='request-followup')submitFollowup(form);});
  document.addEventListener('click',async e=>{
    const preview=e.target.closest('[data-document-preview]');
    if(preview){
      const url=new URL(preview.href);
      url.searchParams.set('theme',window.ATLASTheme.mode);
      preview.href=url.href;
    }
    const download=e.target.closest('a[download][href^="/api/"]');if(download){e.preventDefault();if(download.getAttribute('aria-busy')!=='true')await downloadFile(download);return;}
    const result=e.target.closest('[data-search-target]');if(result){await openSearchResult(result.dataset.searchTarget,Number(result.dataset.searchId));return;}
    const to=e.target.closest('[data-route], a[data-app-link]');
    if(to){
      if(to.tagName==='A'&&(e.button!==0||e.ctrlKey||e.metaKey||e.altKey||e.shiftKey))return;
      e.preventDefault();
      if(to.hasAttribute('data-app-link')){
        const url=new URL(to.href);
        if(url.origin===location.origin&&url.pathname.startsWith('/app/'))await goToUrl(url);
        return;
      }
      if(to.dataset.recordId||to.dataset.date||to.dataset.subject)await navigateContext(to.dataset.route,{id:to.dataset.recordId,date:to.dataset.date,subject:to.dataset.subject,kind:to.dataset.kind});
      else await route(to.dataset.route);
      return;
    }
    const demo=e.target.closest('#demo-dialog[open] [data-demo]');if(demo&&state.config.demo_mode){const u=demoAccounts[Number(demo.dataset.demo)];if(u)await submitLogin($('#login-form'),u,demo);return;}
    const view=e.target.closest('[data-view]');if(view){state.scheduleMode=view.dataset.view;drawPage();$(`[data-view="${state.scheduleMode}"]`)?.focus({preventScroll:true});return;}
    const day=e.target.closest('[data-day]');if(day){state.day=day.dataset.day;drawPage();$(`[data-day="${state.day}"]`)?.focus({preventScroll:true});return;}
    const pager=e.target.closest('[data-pager]');if(pager){const kind=pager.dataset.pager;state[{requests:'requestOffset',notifications:'noticeOffset',staff:'staffOffset'}[kind]]=Number(pager.dataset.offset);await updatePage();return;}
    for(const [attr,field] of [['data-plan-filter','planFilter'],['data-request-filter','requestFilter'],['data-notice-filter','noticeFilter'],['data-staff-filter','staffFilter']]){const filter=e.target.closest(`[${attr}]`);if(filter){const value=filter.getAttribute(attr);state[field]=value;if(field==='planFilter')drawPage();else{state[{requestFilter:'requestOffset',noticeFilter:'noticeOffset',staffFilter:'staffOffset'}[field]]=0;staffSearchId++;await updatePage({quiet:true});}$(`[${attr}="${value}"]`)?.focus({preventScroll:true});return;}}
    const staffKind=e.target.closest('[data-staff-kind]');
    if(staffKind){
      state.staffKind=staffKind.dataset.staffKind;state.staffOffset=0;staffSearchId++;
      await updatePage({quiet:true});$(`[data-staff-kind="${state.staffKind}"]`)?.focus({preventScroll:true});
      return;
    }
    const requestView=e.target.closest('[data-request-view]');if(requestView){state.requestView=requestView.dataset.requestView;drawPage();$(`[data-request-view="${state.requestView}"]`)?.focus({preventScroll:true});return;}
    const el=e.target.closest('[data-action]');if(!el)return;const action=el.dataset.action;
    if(action==='sidebar-toggle'){toggleSidebar(el);return;}
    if(action==='nav-group'){toggleNavGroup(el.dataset.id);return;}
    if(action==='drawer-open'||action==='drawer-close'){setDrawer(action==='drawer-open',{trigger:el});return;}
    if(action==='demo-picker'){
      const picker=$('#demo-dialog');
      if(picker&&!picker.open){picker.addEventListener('close',()=>{if(el.isConnected&&!el.disabled)el.focus();},{once:true});picker.showModal();}
      return;
    }
    if(action==='demo-close'){$('#demo-dialog')?.close();return;}
    if(action==='close-backdrop'&&e.target!==el)return;
    if(action==='close-modal'||action==='close-backdrop'){closeModal();return;}
    if(action==='discard-modal'){closeModal({force:true});return;}
    if(action==='continue-edit'){const form=el.closest('form');el.closest('.unsaved-warning').remove();$('input,textarea,select',form)?.focus();return;}
    if(action==='password'){const input=$('#login-password');input.type=input.type==='password'?'text':'password';el.textContent=input.type==='password'?'Показать':'Скрыть';el.setAttribute('aria-pressed',input.type==='text');return;}
    if(action==='new-request'){await newRequestModal(el.dataset.type);return;}
    if(action==='request-details'){await requestDetails(Number(el.dataset.id));return;}
    if(action==='request-history'){await loadRequestHistory(Number(el.dataset.id),Number(el.dataset.offset),el);return;}
    if(action==='search'){searchModal();return;}
    if(action==='retry'){await refreshCurrent(el);return;}
    if(action==='this-week'){state.week=monday(today());state.day=today();await updatePage();return;}
    if(action==='prev-week'||action==='next-week'){const week=addDays(state.week,action==='prev-week'?-7:7);if(Math.abs(dueDays(week))>360){toast('Расписание доступно в пределах года.');return;}state.week=week;state.day=week;await updatePage();return;}
    if(action==='logout'){el.disabled=true;try{await api('logout',{method:'POST'});clearSession();announceIdentity();history.replaceState({},'','/');showLogin();toast('Вы вышли из кабинета.');}catch(error){el.disabled=false;toast('Не удалось завершить сессию. '+error.message);}return;}
    if(action==='read-all'){el.disabled=true;try{await api('notifications/read-all',{method:'POST'});await refreshUnread();await updatePage({quiet:true});toast('Все уведомления прочитаны.');}catch(error){el.disabled=false;toast(error.message);}return;}
    if(action==='read-notification'){el.disabled=true;try{await markRead(el.dataset.id);await updatePage({quiet:true});$('.filter-tabs button[aria-pressed="true"]')?.focus({preventScroll:true});}catch(error){if(!error.stale){el.disabled=false;toast(error.message);}}return;}
    if(action==='open-notice'){await openNotice(el.dataset.id);}
  });
  document.addEventListener('change',async e=>{
    const input=e.target.closest('[data-deadline]');if(!input)return;const id=Number(input.dataset.deadline),done=input.checked;
    if(deadlineWrites.has(id)){input.checked=deadlineWrites.get(id).done;return;}
    const epoch=state.sessionEpoch,uid=state.user?.id,write={done};deadlineWrites.set(id,write);input.disabled=true;
    try{await api(`deadlines/${id}/toggle`,{method:'POST',body:JSON.stringify({is_done:done})});if(epoch!==state.sessionEpoch||uid!==state.user?.id||deadlineWrites.get(id)!==write)return;
      const task=state.data.plan?.find(x=>x.id===id);if(task)task.is_done=done;
      const work=state.data.assignments?.items?.find(x=>(x.deadline_id||x.id)===id);if(work)work.is_done=done;
      toast(done?'Готово! Ещё одно дело позади.':'Задание снова в плане.');
    }catch(error){if(!error.stale){input.checked=!done;toast(error.message);}}
    finally{if(deadlineWrites.get(id)===write)deadlineWrites.delete(id);if(epoch===state.sessionEpoch&&uid===state.user?.id){if(input.isConnected)input.disabled=false;if(state.page==='plan'){drawPage();($(`[data-deadline="${id}"]`)||$('.filter-tabs button[aria-pressed="true"]'))?.focus();}}}
  });
  document.addEventListener('input',e=>{if(e.target.id==='staff-search'){state.staffQuery=e.target.value;state.staffOffset=0;state.loadingId++;clearTimeout(searchTimer);const requestId=++staffSearchId;const epoch=state.sessionEpoch;searchTimer=setTimeout(async()=>{const results=$('#staff-results');results?.setAttribute('aria-busy','true');try{const data=await load('staff');if(requestId!==staffSearchId||state.page!=='staff'||epoch!==state.sessionEpoch)return;state.data.staff=data;const holder=document.createElement('div');holder.innerHTML=staffPage(data);$('#staff-results')?.replaceWith($('#staff-results',holder));}catch(error){if(!error.stale)toast(error.message);}finally{results?.removeAttribute('aria-busy');}},300);}});
  document.addEventListener('keydown',e=>{
    if(e.key==='Escape'){
      if($('#demo-dialog[open]'))return;
      if($('.modal'))closeModal();
      else if($('.shell.drawer-open'))setDrawer(false);
      return;
    }
    if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='k'&&state.user){e.preventDefault();if(state.pending){toast('Дождитесь завершения отправки.');return;}setDrawer(false);searchModal();return;}
    const dialog=$('.modal');if(e.key==='Tab'&&dialog){const controls=$$('a[href],button:not(:disabled),input:not(:disabled),textarea:not(:disabled),select:not(:disabled),summary,[tabindex="0"]',dialog).filter(x=>x.getClientRects().length&&getComputedStyle(x).visibility!=='hidden'&&!x.closest('details:not([open]) > :not(summary)'));if(!controls.length){e.preventDefault();return;}const first=controls[0],last=controls.at(-1);if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}}
  });
  let restoringHistory=false;
  window.addEventListener('popstate',event=>{
    if(restoringHistory){restoringHistory=false;return;}
    if(!state.user)return;
    if(location.pathname+location.search===state.routeHref)return;
    if(state.pending||!closeModal()){
      if(state.pending)toast('Дождитесь завершения отправки.');
      const index=event.state?.atlasEntry;
      if(Number.isInteger(index)&&index!==state.historyEntry){
        restoringHistory=true;history.go(state.historyEntry-index);
      }else history.replaceState({atlasEntry:state.historyEntry},'',state.routeHref);
      return;
    }
    goToUrl(location,{fromHistory:true});
  });
  document.addEventListener('visibilitychange',()=>{if(!document.hidden){revalidateIdentity();pollBadges();}});
  document.addEventListener('input',e=>{
    const form=e.target.closest('.modal form[data-c-form]');if(form&&form.dataset.cForm!=='personal-search')form.dataset.dirty='true';
    if(e.target.id==='service-search'){const value=e.target.value;const pos=e.target.selectionStart;state.serviceQuery=value;drawPage();const input=$('#service-search');input.focus({preventScroll:true});input.setSelectionRange(pos,pos);}
  });
  document.addEventListener('change',e=>{const form=e.target.closest('.modal form[data-c-form]');if(form)form.dataset.dirty='true';});
  window.addEventListener('beforeunload',e=>{if($('.modal form[data-dirty="true"]')){e.preventDefault();e.returnValue='';}});
  window.addEventListener('online',()=>toast('Подключение восстановлено. Можно обновить раздел.'));
  window.addEventListener('offline',()=>toast('Нет сети. Показаны уже загруженные данные; для сохранения нужен сервер.'));
  async function boot(){try{state.config=await api('config');}catch{/* Fail closed: do not advertise demo credentials if config is unavailable. */}try{state.user=await api('me');await campus.prepare();if(!state.user)return;await enterRoute();startPolling();}catch{showLogin();}}
  const context={state,api,deadlinePending:id=>deadlineWrites.has(Number(id)),$,$$,esc,icon,head,cardHead,disclosure,matchesPage,empty,modal,modalHead,closeModal,toast,route,navigateContext,drawPage,updatePage,today,dateFmt,stamp,relative,addDays,asDate,monday,refreshUnread,newRequestModal,replaceRouteContext,clearFormDraft:improvements.clearFormDraft,restoreFormDraft:improvements.restoreFormDraft,prepareFormSubmission:improvements.prepareFormSubmission,formSubmission:improvements.formSubmission,showFieldErrors:improvements.showFieldErrors};
  improvements.init(context);campus.init(context);window.ATLASAcademics.init(context);extensions.forEach(ext=>ext.init(context));
  boot();
})();
