"""Read and write scopes shared by material lists, profiles, files and coursework."""
from sqlalchemy import and_, false, or_, select, true

from .university_db import Discipline, MaterialDelegation, Teacher, TeachingAssignment, TeachingMaterial
from .workspace_db import GroupMember, TeachingLoad

MATERIAL_MANAGERS = ('teacher', 'coordinator', 'department', 'staff')
PUBLISHED_ACCESS = ('campus', 'group')


def managed_assignments(user):
    if user.role == 'staff':
        return true()
    if user.role == 'teacher':
        return TeachingAssignment.teacher_id.in_(select(Teacher.id).where(Teacher.user_id == user.id))
    grants = select(MaterialDelegation).where(MaterialDelegation.user_id == user.id)
    if user.role == 'coordinator':
        return TeachingAssignment.discipline_id.in_(grants.with_only_columns(MaterialDelegation.discipline_id)
                                                    .where(MaterialDelegation.discipline_id.is_not(None)))
    if user.role == 'department':
        departments = grants.with_only_columns(MaterialDelegation.department_id).where(MaterialDelegation.department_id.is_not(None))
        return TeachingAssignment.discipline_id.in_(select(Discipline.id).where(Discipline.department_id.in_(departments)))
    return false()


def student_loads(user):
    return select(TeachingLoad).join(GroupMember, GroupMember.group_id == TeachingLoad.group_id).where(
        GroupMember.student_id == user.id)


def visible_materials(user):
    campus = TeachingMaterial.access == 'campus'
    if user.role == 'student':
        assignments = student_loads(user).with_only_columns(TeachingLoad.assignment_id)
        return or_(campus, and_(TeachingMaterial.access == 'group', TeachingMaterial.assignment_id.in_(assignments)))
    return or_(campus, TeachingMaterial.assignment_id.in_(select(TeachingAssignment.id).where(managed_assignments(user))))
