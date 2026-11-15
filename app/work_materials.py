"""References between assignments and their shared discipline materials."""
from fastapi import HTTPException
from sqlalchemy import and_, or_, select

from .material_policy import visible_materials
from .university_db import TeachingAssignment, TeachingMaterial
from .workspace_db import GroupWork, TeachingLoad, WorkMaterial


def eligible_materials(load):
    return (TeachingAssignment.discipline_id == load.discipline_id,
            or_(TeachingMaterial.access == 'campus',
                and_(TeachingMaterial.access == 'group', TeachingMaterial.assignment_id == load.assignment_id)))


def set_work_materials(db, load, work_id, ids):
    links = {row.material_id: row for row in db.scalars(select(WorkMaterial).where(WorkMaterial.work_id == work_id))}
    added = set(ids) - links.keys()
    if added:
        allowed = set(db.scalars(select(TeachingMaterial.id).join(TeachingAssignment)
                                 .where(TeachingMaterial.id.in_(added), *eligible_materials(load))))
        if added != allowed:
            raise HTTPException(404, 'Выберите доступные материалы этой дисциплины')
    for material_id in links.keys() - set(ids):
        db.delete(links[material_id])
    db.add_all(WorkMaterial(work_id=work_id, material_id=material_id) for material_id in sorted(added))


def student_work_materials(db, work_id, student):
    rows = db.execute(select(TeachingMaterial.id, TeachingMaterial.title).join(WorkMaterial)
                      .join(GroupWork, GroupWork.id == WorkMaterial.work_id)
                      .join(TeachingLoad, TeachingLoad.id == GroupWork.load_id)
                      .join(TeachingAssignment, TeachingAssignment.id == TeachingMaterial.assignment_id)
                      .where(WorkMaterial.work_id == work_id, visible_materials(student), *eligible_materials(TeachingLoad))
                      .order_by(TeachingMaterial.title, TeachingMaterial.id))
    return [dict(id=key, title=title, href=f'/app/courses/materials/{key}') for key, title in rows]
