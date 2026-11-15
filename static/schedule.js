/* Calendar views use the same day and event data. */
(() => {
  'use strict';
  const modes = {day:'День',week:'Неделя',month:'Месяц'};
  const kinds = {
    lecture:['Л','Лекция'],practice:['П','Практическое занятие'],lab:['ЛР','Лабораторная работа'],
    consultation:['К','Консультация'],credit:['З','Зачёт'],exam:['Э','Экзамен'],retake:['ПС','Пересдача'],
    organization:['О','Организационное мероприятие'],other:['У','Учебное мероприятие'],
    campus:['М','Мероприятие кампуса'],vuc:['В','Занятие ВУЦ'],deadline:['С','Срок сдачи'],
  };
  const weekdays = ['Пн','Вт','Ср','Чт','Пт','Сб','Вс'];
  let c;
  const esc = x => c.esc(x);
  const icon = x => c.icon(x);
  const type = x => Object.hasOwn(kinds,x) ? x : 'other';
  const countActive = day => day.items.filter(item => item.status === 'active').length;
  const dateLabel = d => c.dateFmt(d, {day:'numeric',month:'short',year:'numeric'});
  const longDate = d => c.dateFmt(d, {weekday:'long',day:'numeric',month:'long'});
  const countLabel = (n, words) => n+' '+words[new Intl.PluralRules('ru').select(n)];
  const kindLabel = (code, text) => `<span class="schedule-kind schedule-type-${type(code)}">${esc(text)}</span>`;
  const todayAttribute = day => day.date === c.today() ? 'aria-current="date"' : '';
  const href = (date, id, details=false) => '/app/schedule?'+new URLSearchParams({date,...(id?{id,...(details?{change:'1'}:{})}:{})});

  function changeDetails(item){
    const {change} = item;
    if(!change) return '';
    const earlier = change.previous;
    function values(x){
      const clock = x.start+'–'+x.end;
      const status = x.status === 'cancelled' ? 'Отменено' : '';
      return esc([x.title,x.kind,dateLabel(x.day),clock,x.room,x.teacher,status].filter(Boolean).join(' · '));
    }
    const current = {...item,day:item.date};
    return `<div class="schedule-event-change"><span class="schedule-change-label">${esc(change.label)}</span>
      <span>${esc(change.summary)}</span>
      ${earlier||item.note||item.calendar_exception?`<details class="schedule-event-details"><summary>Подробности</summary>
        ${earlier?`<dl><div><dt>Было</dt><dd>${values(earlier)}</dd></div>
        <div><dt>Стало</dt><dd>${values(current)}</dd></div></dl>`:''}
        ${item.note?`<p>${esc(item.note)}</p>`:''}
        ${item.calendar_exception?`<p>Основание исключения · ${esc(item.calendar_exception)}</p>`:''}
      </details>`:''}</div>`;
  }

  function card(item){
    const audience = item.individual ? 'Индивидуально' : [item.group,item.subgroup].filter(Boolean).join(' · ');
    const room = item.format === 'online' && !/^онлайн|дистанц/i.test(item.room) ? 'Онлайн · '+item.room : item.room;
    const end = item.end_date === item.date ? item.end : c.dateFmt(item.end_date,{day:'numeric',month:'short'})+' '+item.end;
    return `<article data-lesson-id="${Number(item.id)}" data-schedule-key="${esc(item.uid)}" class="schedule-event schedule-type-${type(item.type)}
      ${item.is_lesson?'schedule-class':'schedule-special'} ${item.changed?'schedule-changed':''} ${item.status==='cancelled'?'schedule-cancelled':''}">
      <div class="schedule-event-line"><span class="schedule-event-time">${esc(item.start)}–${esc(end)}</span>${kindLabel(item.type,item.kind)}</div>
      <h3>${esc(item.title)}</h3>
      ${item.subject&&item.subject!==item.title?`<p>${esc(item.subject)}</p>`:''}
      ${item.teacher?`<p>${esc(item.teacher)}</p>`:''}
      ${room?`<p class="schedule-place">${icon('pin')} ${esc(room)}</p>`:''}
      ${audience?`<p class="schedule-audience">${esc(audience)}</p>`:''}
      ${changeDetails(item)}
      ${!item.changed&&item.calendar_exception?`<p class="schedule-audience">Исключение из календаря · ${esc(item.calendar_exception)}</p>`:''}
    </article>`;
  }

  function marker(item){
    const label = item.type === 'deadline' && item.done ? 'Срок сдачи · выполнено' : item.kind;
    return `<div class="schedule-marker schedule-type-${type(item.type)}">
      ${kindLabel(item.type,label)}<span class="schedule-marker-title">${esc(item.title)}</span>
      ${item.time?`<span>${esc(item.time)}</span>`:item.type==='deadline'?'':'<span>Время не опубликовано</span>'}
    </div>`;
  }

  function reason(day){
    if(day.items.some(item=>item.is_lesson&&item.status==='active') && day.reason.code==='teaching') return '';
    return `<p class="schedule-reason"><strong>${esc(day.reason.label)}</strong>
      ${day.reason.detail?`<span>${esc(day.reason.detail)}</span>`:''}</p>`;
  }

  function dayContents(day){
    const moves = day.moves.map(item=>`<a class="schedule-marker schedule-move" href="${esc(href(item.date,item.id))}" data-app-link>
      <span class="schedule-change-label">${item.status==='cancelled'?'Отменено после переноса':'Перенесено'}</span>
      <span class="schedule-marker-title">${esc(item.title)}</span><span>${esc(dateLabel(item.date))} ${icon('arrow')}</span></a>`).join('');
    return reason(day)+day.items.map(card).join('')+moves+day.markers.map(marker).join('');
  }

  function dayPanel(day, index, single=false){
    const current = day.date===c.today();
    return `<section class="schedule-day ${single?'day-view':''} ${current?'schedule-today':''}" aria-labelledby="day-${esc(day.date)}">
      <header class="schedule-day-header"><h2 id="day-${esc(day.date)}"><time datetime="${esc(day.date)}" ${todayAttribute(day)}>
      ${single?esc(longDate(day.date)):`<span>${weekdays[index]}</span> <b>${c.asDate(day.date).getDate()}</b>`}</time></h2>
      ${current?'<span class="schedule-today-label">Сегодня</span>':''}</header>
      <div class="schedule-day-items">${dayContents(day)}</div></section>`;
  }

  function monthDay(day, anchor){
    const entries = [...day.items,...day.markers];
    const labels = [...new Set(entries.map(item=>item.kind))];
    const extra = entries.length + day.moves.length;
    const reasonLabel = day.reason.code==='teaching' && day.items.some(item=>item.is_lesson&&item.status==='active') ? '' : day.reason.label;
    const label = [longDate(day.date),labels.join(', '),reasonLabel,day.reason.detail,day.moves.length?'Есть переносы':''].filter(Boolean).join(' · ');
    return `<button type="button" data-day="${esc(day.date)}" class="schedule-month-day
      ${day.date.slice(0,7)!==anchor.slice(0,7)?'schedule-spillover':''} ${day.date===c.today()?'schedule-today':''}"
      ${todayAttribute(day)} aria-description="${esc(label)}">
      <strong>${c.asDate(day.date).getDate()}</strong>
      ${entries.slice(0,2).map(item=>`<span class="schedule-month-item schedule-type-${type(item.type)}" aria-hidden="true"><b>${kinds[type(item.type)][0]}</b>
      <span>${esc(item.title)}</span></span>`).join('')}
      ${extra>2?`<span class="schedule-month-extra">+${extra-2}</span>`:''}
      ${day.moves.length?'<span class="schedule-month-extra" aria-hidden="true">Перенос</span>':''}
      ${!extra?`<span class="schedule-month-reason">${esc(day.reason.label)}</span>`:''}</button>`;
  }

  function banner(data){
    const changes = data.changes;
    if(!changes.length) return '';
    const period = data.view==='month'?'В этом месяце':'На этой неделе';
    const show = ({date,id})=>esc(href(date,id,true));
    return `<aside class="change-banner schedule-banner" aria-label="Изменения расписания">${icon('alert')}
      <div><b>${period} есть изменения · ${changes.length}</b>
      ${changes.length===1?`<a class="mini-link" href="${show(changes[0])}" data-app-link>Показать изменение</a>`:
      `<details><summary>Показать изменения</summary><ul>${changes.map(change=>`<li><a href="${show(change)}" data-app-link>
        ${esc(c.dateFmt(change.date))} · ${esc(change.title)}</a></li>`).join('')}</ul></details>`}</div>
      <button class="square-btn schedule-dismiss" type="button" data-schedule-dismiss aria-label="Скрыть уведомление об изменениях">${icon('close')}</button>
    </aside>`;
  }

  function render(data){
    const mode = c.state.scheduleMode;
    const anchor = data.date;
    const day = data.days.find(x=>x.date===anchor);
    const month = mode==='month', single = mode==='day';
    const [first,last] = [data.days[0].date,data.days.at(-1).date];
    const title = month ? c.dateFmt(anchor,{month:'long',year:'numeric'}) :
      c.dateFmt(first,{day:'numeric',month:'short',...(first.slice(0,4)!==last.slice(0,4)?{year:'numeric'}:{})})+' — '+dateLabel(last);
    const nav = month?'месяц':'неделя';
    const visible = data.days.filter(x=>single?x.date===anchor:!month||x.date.slice(0,7)===anchor.slice(0,7));
    const entries = visible.flatMap(x=>x.items).filter(x=>x.status==='active');
    const ordinary = entries.filter(x=>x.is_lesson).length;
    const total = countLabel(ordinary,{one:'занятие',few:'занятия',many:'занятий',other:'занятий'})+
      (entries.length>ordinary?' · '+countLabel(entries.length-ordinary,{one:'событие',few:'события',many:'событий',other:'событий'}):'');
    const exportHref = '/api/schedule/export?'+new URLSearchParams({week:anchor,view:data.view});
    return c.head('','Расписание','Время указано по Москве.',`<a class="outline-button" href="${esc(exportHref)}" download>
      ${icon('download')} Скачать расписание</a>`)+
      `<div class="schedule-toolbar"><div class="week-switch">
      <button class="square-btn" type="button" data-schedule-step="-1" aria-label="${month?'Предыдущий':'Предыдущая'} ${nav}">${icon('left')}</button>
      <h2>${esc(title)}</h2><button class="square-btn" type="button" data-schedule-step="1" aria-label="${month?'Следующий':'Следующая'} ${nav}">${icon('right')}</button>
      </div><div class="toolbar-actions"><button class="outline-button" type="button" data-schedule-today>Сегодня</button>
      <div class="segmented" aria-label="Вид расписания">${Object.entries(modes).map(([value,label])=>
      `<button type="button" data-view="${value}" aria-pressed="${value===mode}">${label}</button>`).join('')}</div></div></div>
      <div class="schedule-meta"><form data-schedule-date><label for="schedule-date">К дате</label>
      <input id="schedule-date" name="date" type="date" value="${esc(anchor)}" min="2000-01-01" max="2099-12-31" required>
      <button class="outline-button" type="submit">Открыть</button></form>
      <details class="schedule-legend"><summary>Условные обозначения</summary><div>${Object.entries(kinds).map(([value,[abbr,label]])=>
      kindLabel(value,abbr+' · '+label)).join('')}</div></details></div>
      ${banner(data)}
      ${single?`<div class="day-picker" aria-label="Выбрать день">${data.days.map((x,i)=>`<button type="button" class="day-pick
        ${x.date===anchor?'selected':''}" data-day="${esc(x.date)}" aria-pressed="${x.date===anchor}" ${todayAttribute(x)}
        aria-description="${esc(longDate(x.date))} · ${countActive(x)?countActive(x):esc(x.reason.label)}">
        <span>${weekdays[i]}</span><b>${c.asDate(x.date).getDate()}</b><span class="day-count">${countActive(x)||'—'}</span></button>`).join('')}</div>`:''}
      <p class="schedule-info">${total}</p>
      ${single?dayPanel(day,0,true):month?`<div class="schedule-month" aria-label="Дни месяца">
        ${weekdays.map(d=>`<span class="schedule-month-weekday">${d}</span>`).join('')}
        ${data.days.map(x=>monthDay(x,anchor)).join('')}</div>`:
        `<div class="week-grid schedule-week">${data.days.map((x,i)=>dayPanel(x,i)).join('')}</div>`}`;
  }

  function go(date, view){
    if(!/^20\d\d-\d\d-\d\d$/.test(date)){
      c.toast('Укажите дату в пределах 2000–2099 годов.');
      return;
    }
    return c.route('schedule',{context:{date,view}});
  }

  async function dismiss(button){
    const data = c.state.data.schedule;
    button.disabled = true;
    try {
      const keys = data.changes.map(entry=>entry.key);
      let result;
      for(let i=0;i<keys.length;i+=300){
        result = await c.api('schedule/dismiss',{method:'POST',body:JSON.stringify({date:data.date,view:data.view,keys:keys.slice(i,i+300)})});
      }
      if(c.state.data.schedule!==data || c.state.page!=='schedule')return;
      data.changes = result.changes;
      c.drawPage();
      c.$('#page-title')?.focus({preventScroll:true});
    } catch(error){
      if(!error.stale)c.toast(error.message);
    } finally {
      button.disabled = false;
    }
  }

  function bind(context){
    c = context;
    document.addEventListener('click', e=>{
      const button=e.target.closest('#page-content button');
      if(!button||c.state.page!=='schedule'||!c.state.data.schedule)return;
      const {date} = c.state.data.schedule;
      const mode = c.state.scheduleMode;
      if(button.dataset.view){
        const view=button.dataset.view;
        if(view!==mode)go(date,view)?.then(()=>c.$(`[data-view="${view}"]`)?.focus({preventScroll:true}));
      } else if(button.dataset.day) {
        const selected=button.dataset.day;
        if(selected!==date||mode!=='day')go(selected,'day')?.then(()=>c.$(`[data-day="${selected}"]`)?.focus({preventScroll:true}));
      } else if(button.hasAttribute('data-schedule-today')) {
        go(c.today(),mode);
      } else if(button.dataset.scheduleStep){
        const offset=Number(button.dataset.scheduleStep);
        if(mode==='month'){
          const next=c.asDate(date);
          next.setDate(1);
          next.setMonth(next.getMonth()+offset);
          go(c.isoDate(next),mode);
        }else go(c.addDays(date,7*offset),mode);
      } else if(button.hasAttribute('data-schedule-dismiss')) {
        dismiss(button);
      }
    });
    document.addEventListener('submit', e=>{
      if(!e.target.hasAttribute('data-schedule-date'))return;
      e.preventDefault();
      go(e.target.elements.date.value,c.state.scheduleMode);
    });
  }

  window.ATLASSchedule = {render,bind};
})();
