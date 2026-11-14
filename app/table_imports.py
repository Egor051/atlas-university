"""Role-scoped spreadsheet preview, row validation and atomic import."""
import base64
import binascii
from collections import Counter
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db import Grade, User, campus_today, utc_now
from .learning_db import Attendance
from .main import StrictBody, date_iso, get_db, require_same_origin, require_user
from .references import (GroupBody, LoadBody, MemberBody, RoomBody, group_data, member_data,
                         room_data, write_load, write_member, write_reference)
from .scheduling import ChangeBody, class_data, class_query, create_draft, own_timetable, validate_change, week_bounds
from .table_formats import MAX_UPLOAD, read_table, table_bytes
from .teaching import AttendanceBody, MarkBody, attendance_scope, class_day, save_attendance, save_grade, scoped_class
from .university_db import Teacher, TeachingAssignment
from .workspace import load_payload, load_query, lock_workspace, owned_load, recorded, roster
from .workspace_db import AcademicGroup, Classroom, GroupMember, ScheduledClass, TableImport

Dataset = Literal['schedule','rooms','groups','loads','students','grades','attendance']
Format = Literal['csv','xlsx']
router = APIRouter(prefix='/api/tables')
coordinators = {'scheduler','staff','admin'}
DATA = {
    'schedule': ('Расписание', 'load_id teacher_id room_id day start end kind equipment weeks note', 'load_id teacher_id room_id day start end kind', coordinators|{'teacher'}, {'scheduler'}),
    'rooms': ('Аудитории','id version building code capacity kind equipment accessible available', 'building code capacity kind', coordinators, {'scheduler','admin'}),
    'groups': ('Учебные группы','id version code program capacity accessible', 'code program capacity', coordinators, {'admin'}),
    'loads': ('Учебная нагрузка','id version group_id assignment_id', 'group_id assignment_id', coordinators|{'teacher'}, {'admin'}),
    'students': ('Списки студентов','student_id group_id version', 'student_id group_id', {'admin','teacher'}, {'admin'}),
    'grades': ('Ведомость успеваемости','student_id score version reason', 'student_id score version', {'teacher'}, {'teacher'}),
    'attendance': ('Журнал посещаемости','student_id day status note version class_id', 'student_id day status version', {'teacher'}, {'teacher'}),
}
MODELS = {'rooms':RoomBody, 'groups':GroupBody, 'loads':LoadBody, 'students':MemberBody, 'grades':MarkBody, 'attendance':AttendanceBody}
INTS = {'id','version','load_id','teacher_id','room_id','weeks','capacity','group_id','assignment_id','student_id','score','class_id'}


class Upload(StrictBody):
    format: Format
    content: str = Field(min_length=1, max_length=29400)
    mapping: dict[str,str] = Field(default_factory=dict, max_length=32)


class ConfirmUpload(Upload):
    fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')


def allowed(dataset, user, *, write=False):
    if user.role not in DATA[dataset][4 if write else 3]:
        raise HTTPException(403, 'Этот набор данных недоступен для операции')


def needs_scope(dataset, user):
    return user.role == 'teacher' and dataset in {'students','grades','attendance'}


def scoped_load(db, dataset, scope, user):
    if needs_scope(dataset,user):
        if scope is None:
            raise HTTPException(422, 'Выберите свою дисциплину и группу')
        return owned_load(db, user, scope)
    if scope is not None:
        raise HTTPException(422, 'Для этой таблицы область не указывается')
    return None


def permitted_sets(user):
    return [dict(id=key,title=meta[0],editable=user.role in meta[4],scoped=needs_scope(key,user),
                 columns=meta[1].split(),required=meta[2].split()) for key,meta in DATA.items() if user.role in meta[3]]


def download(format, dataset, rows, *, template=False):
    columns = DATA[dataset][1].split()
    if rows:
        columns += [name for name in rows[0] if name not in columns]
    result, mime = table_bytes(format,columns,rows)
    suffix = '-template' if template else ''
    return Response(result, media_type=mime, headers={'Content-Disposition':f'attachment; filename="atlas-{dataset}{suffix}.{format}"'})


@router.get('')
def datasets(user=Depends(require_user)):
    return {'items': permitted_sets(user), 'max_bytes': MAX_UPLOAD}


@router.get('/{dataset}/template')
def template(dataset: Dataset, format: Format='xlsx', user=Depends(require_user)):
    allowed(dataset,user,write=True)
    return download(format,dataset,[],template=True)


def export_rows(dataset, db, user, load, day, class_id=None):
    if dataset == 'schedule':
        if user.role == 'teacher':
            return [{**row,'weeks':1} for row in own_timetable(day,user,db)['items']]
        _, start, end = week_bounds(day)
        return [{**class_data(row),'weeks':1} for row in db.scalars(class_query().where(
            ScheduledClass.starts_at>=start,ScheduledClass.starts_at<end).order_by(ScheduledClass.starts_at))]
    if dataset == 'rooms':
        return [room_data(row) for row in db.scalars(select(Classroom).order_by(Classroom.code))]
    if dataset == 'groups':
        return [group_data(row) for row in db.scalars(select(AcademicGroup).order_by(AcademicGroup.code))]
    if dataset == 'loads':
        query = load_query().order_by(TeachingAssignment.id).join(TeachingAssignment)
        if user.role == 'teacher':
            query = query.join(Teacher).where(Teacher.user_id==user.id)
        return [load_payload(row) for row in db.scalars(query)]
    if dataset == 'students' and user.role == 'admin':
        return [member_data(student,row) for student,row in db.execute(select(User,GroupMember).outerjoin(GroupMember)
                    .where(User.role=='student').order_by(User.full_name))]
    people = {row.id:row for row in roster(db,load.group_id)}
    if dataset == 'students':
        return [dict(student_id=row.id,group_id=load.group_id,name=row.full_name,number=row.student_number,
                     group=load.group.code) for row in people.values()]
    if dataset == 'grades':
        marks = {}
        for row in db.scalars(select(Grade).where(Grade.student_id.in_(people), Grade.subject==load.discipline.title).order_by(Grade.id)):
            marks.setdefault(row.student_id,row)
        return [dict(student_id=uid,name=person.full_name,score=marks[uid].current if uid in marks else None,
                     version=marks[uid].version if uid in marks else 0) for uid,person in people.items()]
    day = class_day(scoped_class(db, load, class_id)) if class_id else day or campus_today()
    present = {}
    for row in db.scalars(select(Attendance).where(Attendance.student_id.in_(people),Attendance.subject==load.discipline.title,
                                                  attendance_scope(day, class_id)).order_by(Attendance.id)):
        present.setdefault(row.student_id,row)
    return [dict(student_id=uid,name=person.full_name,day=day.isoformat(),class_id=class_id,status=present[uid].status if uid in present else '',
                 note=present[uid].note if uid in present else '',version=present[uid].version if uid in present else 0)
            for uid,person in people.items()]


@router.get('/{dataset}/export')
def export(dataset: Dataset, format: Format='xlsx', scope: int|None=Query(None,ge=1,le=2147483647), day: date|None=None,
           class_id: int | None = Query(None, ge=1, le=2147483647),
           user=Depends(require_user), db: Session=Depends(get_db)):
    allowed(dataset,user)
    load = scoped_load(db,dataset,scope,user)
    return download(format,dataset,export_rows(dataset,db,user,load,day,class_id))


def decimal_number(value):
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise ValueError('Нужно числовое значение') from None
    if not number.is_finite() or number.copy_abs()>2147483647:
        raise ValueError('Число вне допустимого диапазона')
    return number


def cell_value(name,value,format,date1904):
    value = value.strip()
    if name in INTS:
        number = decimal_number(value)
        if number!=int(number):
            raise ValueError('Нужно целое число')
        return int(number)
    if name in {'accessible','available'}:
        if value.casefold() in {'true','1','да'}:
            return True
        if value.casefold() in {'false','0','нет'}:
            return False
        raise ValueError('Укажите «да» или «нет»')
    if name=='day':
        if format=='xlsx' and value.replace('.','',1).isdigit():
            number = decimal_number(value)
            if number != int(number) or not 0<=number<=200000:
                raise ValueError('Укажите календарную дату')
            return (date(1904,1,1) if date1904 else date(1899,12,30)) + timedelta(days=int(number))
        if '.' in value:
            return datetime.strptime(value,'%d.%m.%Y').date()
        return date.fromisoformat(value)
    if name in {'start','end'}:
        if format=='xlsx' and value.replace('.','',1).isdigit():
            number=decimal_number(value)
            if not 0<=number<1:
                raise ValueError('Укажите время без даты')
            minutes=int(round(number*1440))
            return f'{minutes//60:02d}:{minutes%60:02d}'
        return value.removesuffix(':00') if len(value)==8 else value
    return value


def parse_upload(dataset,body):
    try:
        headers,rows,date1904 = read_table(body.format,base64.b64decode(body.content,validate=True))
    except (ValueError,binascii.Error) as error:
        raise HTTPException(422,str(error)) from None
    columns, required = DATA[dataset][1].split(), DATA[dataset][2].split()
    if any(key not in columns or (value and value not in headers) for key,value in body.mapping.items()):
        raise HTTPException(422,'Сопоставьте столбцы из загруженного файла')
    source={header.casefold():header for header in headers}
    mapping={key:body.mapping.get(key,source.get(key.casefold(),'')) for key in columns}
    missing=[key for key in required if not mapping[key]]
    selected=[value for value in mapping.values() if value]
    if len(set(selected))!=len(selected):
        raise HTTPException(422,'Используйте каждый столбец для одного поля')
    errors, parsed=[],[]
    if missing:
        return headers,mapping,missing,parsed,errors
    for number,row in rows:
        try:
            values={}
            for key,header in mapping.items():
                raw=row.get(header,'')
                if key=='score' and not raw.strip():
                    values[key]=None
                elif raw.strip() or key in required:
                    try:
                        values[key]=cell_value(key,raw,body.format,date1904)
                    except (ValueError,OverflowError) as error:
                        raise ValueError(f'{key} — {error}') from None
            if dataset=='schedule':
                note=values.pop('note','')
                record=ChangeBody(action='create',slot=values,note=note)
            else:
                record=MODELS[dataset](**values)
            parsed.append((number,record))
        except ValidationError as error:
            issue=error.errors(include_input=False,include_url=False)[0]
            errors.append(dict(row=number,message=f"{'.'.join(map(str,issue['loc'])) or 'Строка'} — {issue['msg']}"))
        except ValueError as error:
            errors.append(dict(row=number,message=str(error)))
    return headers,mapping,missing,parsed,errors


def check_rows(db, user, dataset, load, parsed):
    errors, seen, queued = [], set(), []
    capacities, member_changes = {}, []
    for number,body in parsed:
        try:
            if dataset=='schedule':
                key=(body.slot.load_id,body.slot.day,body.slot.start)
                _, intervals=validate_change(db,body,queued)
                queued.extend(intervals)
            elif dataset in {'rooms','groups'}:
                key=('id',body.id) if body.id else ('code',body.code.casefold())
                code_key=('resulting-code',body.code.casefold())
                if code_key in seen:
                    raise HTTPException(409,'Код повторяется в файле')
                write_reference(db,user,dataset,body,apply=False)
                seen.add(code_key)
            elif dataset=='loads':
                discipline=write_load(db,user,body,apply=False)
                key=(body.group_id,discipline)
            elif dataset=='students':
                key=body.student_id
                old,limit=write_member(db,user,body,apply=False,capacity_check=False)
                capacities[body.group_id]=limit
                member_changes.append((number,old,body.group_id))
            elif dataset=='grades':
                key=body.student_id
                save_grade(db,user,load,body,apply=False)
            else:
                key=(body.student_id,body.class_id or body.day)
                save_attendance(db,user,load,body,apply=False)
            if key in seen:
                raise HTTPException(409,'Запись повторяется в файле')
            seen.add(key)
        except HTTPException as error:
            errors.append(dict(row=number,message=error.detail))
    if member_changes and not errors:
        counts=Counter(dict(db.execute(select(GroupMember.group_id,func.count()).group_by(GroupMember.group_id)).all()))
        for _,old,new in member_changes:
            counts[old]-=1
            counts[new]+=1
        errors.extend(dict(row=number,message='По итогам импорта в группе не хватает мест')
                      for number,old,new in member_changes if old!=new and counts[new]>capacities[new])
    return errors


def fingerprint(dataset, scope, parsed):
    canonical=json.dumps([dataset,scope,[row.model_dump(mode='json') for _,row in parsed]],sort_keys=True,ensure_ascii=False)
    return sha256(canonical.encode()).hexdigest()


def existing_import(db,user,digest):
    return db.scalar(select(TableImport).where(TableImport.actor_id==user.id,TableImport.fingerprint==digest))


def import_result(row,replayed=False):
    return dict(id=row.id,dataset=row.dataset,count=row.count,created_at=date_iso(row.created_at),replayed=replayed)


@router.post('/{dataset}/preview',dependencies=[Depends(require_same_origin)])
def preview(dataset: Dataset,body: Upload,scope: int|None=Query(None,ge=1,le=2147483647),user=Depends(require_user),db: Session=Depends(get_db)):
    allowed(dataset,user,write=True)
    load=scoped_load(db,dataset,scope,user)
    headers,mapping,missing,parsed,errors=parse_upload(dataset,body)
    digest=fingerprint(dataset,scope,parsed) if parsed and not missing and not errors else None
    prior=existing_import(db,user,digest) if digest else None
    if not prior and not missing:
        errors+=check_rows(db,user,dataset,load,parsed)
    return dict(headers=headers,mapping=mapping,missing=missing,errors=sorted(errors,key=lambda row:row['row']),
                rows=[dict(row=number,values=row.model_dump(mode='json')) for number,row in parsed[:8]],count=len(parsed),
                fingerprint=digest if not errors and not prior else None,prior=import_result(prior,True) if prior else None)


@router.post('/{dataset}/apply',dependencies=[Depends(require_same_origin)])
def apply_import(dataset: Dataset,body: ConfirmUpload,scope: int|None=Query(None,ge=1,le=2147483647),user=Depends(require_user),db: Session=Depends(get_db)):
    allowed(dataset,user,write=True)
    lock_workspace(db,user.id)
    load=scoped_load(db,dataset,scope,user)
    _,_,missing,parsed,errors=parse_upload(dataset,body)
    digest=fingerprint(dataset,scope,parsed)
    if missing or errors or not parsed or digest!=body.fingerprint:
        raise HTTPException(422,{'message':'Выполните предварительный просмотр текущего файла', 'rows':errors})
    prior=existing_import(db,user,digest)
    if prior:
        return import_result(prior,True)
    errors=check_rows(db,user,dataset,load,parsed)
    if errors:
        raise HTTPException(409,{'message':'Данные изменились. Проверьте строки и повторите просмотр.', 'rows':errors})
    for _,row in parsed:
        if dataset=='schedule':
            create_draft(db,user,row,checked=True)
        elif dataset in {'rooms','groups'}:
            write_reference(db,user,dataset,row)
        elif dataset=='loads':
            write_load(db,user,row)
        elif dataset=='students':
            write_member(db,user,row,capacity_check=False)
        elif dataset=='grades':
            save_grade(db,user,load,row)
        else:
            save_attendance(db,user,load,row)
    receipt=TableImport(actor_id=user.id,dataset=dataset,scope=scope or 0,fingerprint=digest,count=len(parsed),created_at=utc_now())
    db.add(receipt)
    db.flush()
    recorded(db,user,'imports',receipt.id,'imported',after={'dataset':dataset,'scope':scope,'count':len(parsed),'fingerprint':digest})
    db.commit()
    return import_result(receipt)


@router.get('/history')
def history(user=Depends(require_user),db: Session=Depends(get_db)):
    rows=db.scalars(select(TableImport).where(TableImport.actor_id==user.id).order_by(TableImport.id.desc()).limit(50))
    return {'items':[import_result(row) for row in rows]}
