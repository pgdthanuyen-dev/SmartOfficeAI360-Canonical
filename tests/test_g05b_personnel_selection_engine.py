import sqlite3
import uuid
import pytest
from tools.qlvb_downloader.assignment_rule_models import RuleRoleType
from tools.qlvb_downloader.personnel_directory_models import OrganizationUnit,PersonnelRecord,PersonnelRoleAssignment,PersonnelDomainAssignment,UnitType,ResponsibilityLevel,PersonnelSelectionDecision,PersonnelSelectionMatch
from tools.qlvb_downloader.personnel_directory_repository import PersonnelDirectoryRepository
from tools.qlvb_downloader.domain_models import Document
from tools.qlvb_downloader.domain_repository import DomainRepository
from tools.qlvb_downloader.personnel_selection_engine import PersonnelSelectionRequest,PersonnelSelectionEngine,PersonnelCandidateEvaluation
from tools.qlvb_downloader.personnel_directory_models import PersonnelSubstitution,SubstitutionStatus

def _engine():
 c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row;c.execute('CREATE TABLE documents (doc_id TEXT PRIMARY KEY,title TEXT)');r=PersonnelDirectoryRepository(c)
 u=OrganizationUnit('t','U',1,'U','Unit',UnitType.PROFESSIONAL);r.create_unit(u)
 p=PersonnelRecord('t','P',1,'Person',primary_unit_id=u.id);r.create_personnel(p)
 return c,r,p
def _availability(c,p,status,start='2026-07-19',end='2026-07-19'):
 c.execute('INSERT INTO personnel_availability VALUES (?,?,?,?,?,?,?,?,?,?,?)',(str(uuid.uuid4()),'t',p.id,status,start,end,'administrative',None,'2026-01-01T00:00:00+00:00','2026-01-01T00:00:00+00:00','2026-01-01T00:00:00+00:00'));c.commit()
def _sub(c,primary,sub,unit,role=RuleRoleType.LEAD_EXECUTOR,tenant='t',effective_from=None,effective_to=None):
 c.execute('INSERT INTO personnel_substitutions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',(str(uuid.uuid4()),tenant,primary.id,sub.id,role.value,unit,'x',effective_from,effective_to,'ACTIVE',None,'2026-01-01T00:00:00+00:00','2026-01-01T00:00:00+00:00'));c.commit()

def test_selects_deterministically_from_directory_only():
 c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row;c.execute('CREATE TABLE documents (doc_id TEXT PRIMARY KEY,title TEXT)');r=PersonnelDirectoryRepository(c)
 u=OrganizationUnit('t','U',1,'U','Unit',UnitType.PROFESSIONAL);r.create_unit(u)
 p=PersonnelRecord('t','P',1,'Person',primary_unit_id=u.id);r.create_personnel(p)
 r.add_role_assignment(PersonnelRoleAssignment('t',p.id,u.id,RuleRoleType.LEAD_EXECUTOR,'LEAD_EXECUTOR',is_primary=True))
 r.add_domain_assignment(PersonnelDomainAssignment('t',p.id,'D',ResponsibilityLevel.PRIMARY))
 q=PersonnelSelectionRequest('t','d','1',None,'R','1',100,'U',[RuleRoleType.LEAD_EXECUTOR],['D'],[],'2026-07-19')
 out=PersonnelSelectionEngine(r).evaluate(q)
 assert out.role_recommendations[0].selected_personnel_id==p.id and out.overall_confidence==100

def test_availability_default_available_and_blocking_statuses():
 c,r,p=_engine();e=PersonnelSelectionEngine(r)
 assert e.resolve_effective_availability(p.id,'t','2026-07-19')['is_available']
 for status in ('LEAVE','TEMPORARILY_UNAVAILABLE','UNAVAILABLE'):
  c,r,p=_engine();_availability(c,p,status);out=PersonnelSelectionEngine(r).resolve_effective_availability(p.id,'t','2026-07-19')
  assert not out['is_available'] and out['warnings']==['AVAILABILITY_BLOCKED']

@pytest.mark.parametrize('statuses',[('AVAILABLE','LEAVE'),('LEAVE','UNAVAILABLE')])
def test_availability_conflicts_are_deterministic(statuses):
 c,r,p=_engine()
 for status in reversed(statuses):_availability(c,p,status)
 out=PersonnelSelectionEngine(r).resolve_effective_availability(p.id,'t','2026-07-19')
 assert out['has_conflict'] and out['warnings']==['AVAILABILITY_CONFLICT'] and not out['is_available']

def test_duplicate_status_and_date_boundaries():
 c,r,p=_engine();_availability(c,p,'LEAVE');_availability(c,p,'LEAVE')
 e=PersonnelSelectionEngine(r);out=e.resolve_effective_availability(p.id,'t','2026-07-19')
 assert not out['has_conflict'] and out['warnings']==['AVAILABILITY_BLOCKED']
 c,r,p=_engine();_availability(c,p,'LEAVE','2026-07-20','2026-07-21');assert PersonnelSelectionEngine(r).resolve_effective_availability(p.id,'t','2026-07-19')['is_available']
 _availability(c,p,'LEAVE','2026-07-19','2026-07-19');assert not PersonnelSelectionEngine(r).resolve_effective_availability(p.id,'t','2026-07-19')['is_available']

def test_direct_substitute_is_capped_and_primary_wins_when_eligible():
 c,r,p=_engine();u=r.get_unit(p.primary_unit_id)
 q=PersonnelSelectionRequest('t','d','1',None,'R','1',100,'U',[RuleRoleType.LEAD_EXECUTOR],['D'],[],'2026-07-19')
 r.add_role_assignment(PersonnelRoleAssignment('t',p.id,u['id'],RuleRoleType.LEAD_EXECUTOR,'LEAD_EXECUTOR',is_primary=True));r.add_domain_assignment(PersonnelDomainAssignment('t',p.id,'D',ResponsibilityLevel.PRIMARY))
 backup=PersonnelRecord('t','B',1,'Backup');r.create_personnel(backup)
 r.add_role_assignment(PersonnelRoleAssignment('t',backup.id,u['id'],RuleRoleType.LEAD_EXECUTOR,'LEAD_EXECUTOR',is_primary=True));r.add_domain_assignment(PersonnelDomainAssignment('t',backup.id,'D',ResponsibilityLevel.PRIMARY))
 r.add_substitution(PersonnelSubstitution('t',p.id,backup.id,RuleRoleType.LEAD_EXECUTOR,unit_id=u['id'],status=SubstitutionStatus.ACTIVE))
 assert PersonnelSelectionEngine(r).evaluate(q).role_recommendations[0].selected_personnel_id==p.id
 _availability(c,p,'LEAVE')
 out=PersonnelSelectionEngine(r).evaluate(q).role_recommendations[0]
 assert out.selected_personnel_id==backup.id and out.decision.value=='SELECTED_WITH_WARNING' and out.confidence==80 and out.warnings==['SUBSTITUTE_USED']

def test_substitution_chain_and_cycle_are_guarded():
 c,r,a=_engine();u=r.get_unit(a.primary_unit_id);q=PersonnelSelectionRequest('t','d','1',None,'R','1',100,'U',[RuleRoleType.LEAD_EXECUTOR],['D'],[],'2026-07-19')
 b=PersonnelRecord('t','B',1,'B');d=PersonnelRecord('t','C',1,'C');r.create_personnel(b);r.create_personnel(d)
 for p in (a,b,d): r.add_role_assignment(PersonnelRoleAssignment('t',p.id,u['id'],RuleRoleType.LEAD_EXECUTOR,'R',is_primary=True));r.add_domain_assignment(PersonnelDomainAssignment('t',p.id,'D',ResponsibilityLevel.PRIMARY))
 _availability(c,a,'LEAVE');_availability(c,b,'LEAVE');_sub(c,a,b,u['id']);_sub(c,b,d,u['id'])
 out=PersonnelSelectionEngine(r).evaluate(q).role_recommendations[0];assert out.selected_personnel_id is None and 'SUBSTITUTION_CHAIN_UNSUPPORTED' in out.warnings
 c,r,a=_engine();u=r.get_unit(a.primary_unit_id);b=PersonnelRecord('t','B',1,'B');r.create_personnel(b)
 for p in (a,b):r.add_role_assignment(PersonnelRoleAssignment('t',p.id,u['id'],RuleRoleType.LEAD_EXECUTOR,'R',is_primary=True));r.add_domain_assignment(PersonnelDomainAssignment('t',p.id,'D',ResponsibilityLevel.PRIMARY))
 _availability(c,a,'LEAVE');_sub(c,a,b,u['id']);_sub(c,b,a,u['id'])
 out=PersonnelSelectionEngine(r).evaluate(q).role_recommendations[0];assert out.selected_personnel_id is None and 'SUBSTITUTION_CYCLE_DETECTED' in out.warnings

def test_multiple_direct_substitutes_conflict_or_choose_deterministically():
 c,r,a=_engine();u=r.get_unit(a.primary_unit_id);q=PersonnelSelectionRequest('t','d','1',None,'R','1',100,'U',[RuleRoleType.LEAD_EXECUTOR],['D'],[],'2026-07-19')
 b=PersonnelRecord('t','B',1,'B');d=PersonnelRecord('t','C',1,'C');r.create_personnel(b);r.create_personnel(d)
 for p in (a,b,d):r.add_role_assignment(PersonnelRoleAssignment('t',p.id,u['id'],RuleRoleType.LEAD_EXECUTOR,'R',is_primary=True));r.add_domain_assignment(PersonnelDomainAssignment('t',p.id,'D',ResponsibilityLevel.PRIMARY))
 _availability(c,a,'LEAVE');_sub(c,a,b,u['id']);_sub(c,a,d,u['id']);out=PersonnelSelectionEngine(r).evaluate(q).role_recommendations[0]
 assert out.decision.value=='CONFLICT' and out.selected_personnel_id is None and len(out.alternative_candidates)==2 and {'PERSONNEL_CONFLICT','MULTIPLE_TOP_PERSONNEL'}.issubset(out.warnings)
 c,r,a=_engine();u=r.get_unit(a.primary_unit_id);b=PersonnelRecord('t','B',1,'B');d=PersonnelRecord('t','C',1,'C');r.create_personnel(b);r.create_personnel(d)
 for p,primary,level in ((a,True,ResponsibilityLevel.PRIMARY),(b,True,ResponsibilityLevel.PRIMARY),(d,False,ResponsibilityLevel.SUPPORT)):
  r.add_role_assignment(PersonnelRoleAssignment('t',p.id,u['id'],RuleRoleType.LEAD_EXECUTOR,'R',is_primary=primary));r.add_domain_assignment(PersonnelDomainAssignment('t',p.id,'D',level))
 _availability(c,a,'LEAVE');_sub(c,a,d,u['id']);_sub(c,a,b,u['id']);out=PersonnelSelectionEngine(r).evaluate(q).role_recommendations[0]
 assert out.selected_personnel_id==b.id and out.confidence==80 and out.alternative_candidates[0].personnel_id==d.id

def _sub_candidate(key,score):
 return PersonnelCandidateEvaluation(key,key,key,'u',RuleRoleType.LEAD_EXECUTOR,score,PersonnelSelectionDecision.SELECTED_WITH_WARNING,True,warnings=['SUBSTITUTE_USED'])
def test_two_point_three_point_and_above_boundary_conflicts():
 e=PersonnelSelectionEngine(_engine()[1])
 for scores in ((80,78),(80,77)):
  out=e.select_for_role(RuleRoleType.LEAD_EXECUTOR,[_sub_candidate('B',scores[0]),_sub_candidate('C',scores[1])],0)
  assert out.decision==PersonnelSelectionDecision.CONFLICT and out.selected_personnel_id is None
 out=e.select_for_role(RuleRoleType.LEAD_EXECUTOR,[_sub_candidate('B',80),_sub_candidate('C',76.99)],0)
 assert out.selected_personnel_id=='B' and out.alternative_candidates[0].personnel_id=='C'

def test_ineligible_high_score_substitutes_do_not_conflict_with_valid_lower():
 c,r,a=_engine();u=r.get_unit(a.primary_unit_id);q=PersonnelSelectionRequest('t','d','1',None,'R','1',100,'U',[RuleRoleType.LEAD_EXECUTOR],['D'],[],'2026-07-19')
 valid=PersonnelRecord('t','C',1,'C');bad=PersonnelRecord('t','B',1,'B');r.create_personnel(valid);r.create_personnel(bad)
 for p in (a,valid,bad):r.add_role_assignment(PersonnelRoleAssignment('t',p.id,u['id'],RuleRoleType.LEAD_EXECUTOR,'R',is_primary=True))
 r.add_domain_assignment(PersonnelDomainAssignment('t',valid.id,'D',ResponsibilityLevel.SUPPORT));_availability(c,a,'LEAVE');_sub(c,a,valid,u['id']);_sub(c,a,bad,u['id'])
 out=PersonnelSelectionEngine(r).evaluate(q).role_recommendations[0]
 assert out.selected_personnel_id==valid.id and out.decision==PersonnelSelectionDecision.NEEDS_CLASSIFICATION or out.selected_personnel_id==valid.id

def test_persist_false_true_append_only_and_fingerprint():
 c,r,p=_engine();u=r.get_unit(p.primary_unit_id);r.add_role_assignment(PersonnelRoleAssignment('t',p.id,u['id'],RuleRoleType.LEAD_EXECUTOR,'R',is_primary=True));r.add_domain_assignment(PersonnelDomainAssignment('t',p.id,'D',ResponsibilityLevel.PRIMARY))
 doc=Document(tenant_id='t',source_system='fake',source_document_id='persist');DomainRepository(c).save_document(doc)
 q=PersonnelSelectionRequest('t',doc.id,'1',None,'R','1',90,'U',[RuleRoleType.LEAD_EXECUTOR],['D'],[],'2026-07-19')
 assert not r.list_selection_matches_for_document(doc.id,'1')
 PersonnelSelectionEngine(r).evaluate(q,False);assert not r.list_selection_matches_for_document(doc.id,'1')
 PersonnelSelectionEngine(r).evaluate(q,True);first=r.list_selection_matches_for_document(doc.id,'1');assert len(first)==1
 PersonnelSelectionEngine(r).evaluate(q,True);second=r.list_selection_matches_for_document(doc.id,'1');assert len(second)==2 and second[0]['input_fingerprint']==second[1]['input_fingerprint'] and second[0]['id']!=second[1]['id']

def test_transaction_rolls_back_fk_and_validation_failures():
 c,r,p=_engine();u=r.get_unit(p.primary_unit_id);doc=Document(tenant_id='t',source_system='fake',source_document_id='tx');DomainRepository(c).save_document(doc)
 def match(person=p.id,unit=u['id'],score=80,fingerprint='a'*64):return PersonnelSelectionMatch('t',doc.id,'1',RuleRoleType.LEAD_EXECUTOR,score,PersonnelSelectionDecision.SELECTED_WITH_WARNING,fingerprint,unit_id=unit,personnel_id=person)
 r.append_selection_matches([match(),PersonnelSelectionMatch('t',doc.id,'1',RuleRoleType.MONITOR,80,PersonnelSelectionDecision.SELECTED_WITH_WARNING,'a'*64,unit_id=u['id'],personnel_id=p.id)]);old=r.list_selection_matches_for_document(doc.id,'1')
 with pytest.raises(Exception):r.append_selection_matches([match(),match(person='missing'),match()])
 assert r.list_selection_matches_for_document(doc.id,'1')==old
 for bad in (match(score=-.01),match(score=100.01),match(fingerprint='x'*64)):
  with pytest.raises(Exception):r.append_selection_matches([match(),bad])
  assert r.list_selection_matches_for_document(doc.id,'1')==old
 r.append_selection_matches([match()]);assert len(r.list_selection_matches_for_document(doc.id,'1'))==3

def test_three_row_unit_fk_tenant_enum_and_injected_transaction(monkeypatch):
 c,r,p=_engine();u=r.get_unit(p.primary_unit_id);doc=Document(tenant_id='t',source_system='fake',source_document_id='r2');DomainRepository(c).save_document(doc)
 def m(person=p.id,unit=u['id'],role=RuleRoleType.LEAD_EXECUTOR,decision=PersonnelSelectionDecision.SELECTED):return PersonnelSelectionMatch('t',doc.id,'1',role,80,decision,'a'*64,unit_id=unit,personnel_id=person)
 r.append_selection_matches([m(role=RuleRoleType.LEAD_EXECUTOR),m(role=RuleRoleType.MONITOR),m(role=RuleRoleType.LEADER)]);assert len(r.list_selection_matches_for_document(doc.id,'1'))==3
 before=list(r.list_selection_matches_for_document(doc.id,'1'))
 with pytest.raises(Exception):r.append_selection_matches([m(role=RuleRoleType.LEAD_EXECUTOR),m(unit='missing',role=RuleRoleType.MONITOR),m(role=RuleRoleType.LEADER)])
 assert r.list_selection_matches_for_document(doc.id,'1')==before
 foreign_unit=OrganizationUnit('other','X',1,'X','X',UnitType.OTHER);r.create_unit(foreign_unit)
 with pytest.raises(Exception):r.append_selection_matches([m(unit=foreign_unit.id)])
 for role,decision in (('UNKNOWN_ROLE',PersonnelSelectionDecision.SELECTED),('',PersonnelSelectionDecision.SELECTED),(RuleRoleType.LEAD_EXECUTOR,'AUTO_APPROVED')):
  with pytest.raises(Exception):r.append_selection_matches([m(role=role,decision=decision)])
 original=r.append_selection_match;calls={'n':0}
 def fail_second(match,commit=True):
  calls['n']+=1
  if calls['n']==2:raise RuntimeError('injected failure')
  return original(match,commit=commit)
 monkeypatch.setattr(r,'append_selection_match',fail_second)
 with pytest.raises(RuntimeError):r.append_selection_matches([m(role=RuleRoleType.LEAD_EXECUTOR),m(role=RuleRoleType.MONITOR),m(role=RuleRoleType.LEADER)])
 assert r.list_selection_matches_for_document(doc.id,'1')==before
 monkeypatch.setattr(r,'append_selection_match',original);r.append_selection_matches([m()]);assert len(r.list_selection_matches_for_document(doc.id,'1'))==4

def test_fingerprint_canonicalization_and_persistence_bounds():
 c,r,p=_engine();e=PersonnelSelectionEngine(r)
 a=PersonnelSelectionRequest('t','d','1',None,'R','1',80,'U',[RuleRoleType.MONITOR,RuleRoleType.LEAD_EXECUTOR],['D','D'],[],'2026-07-19')
 b=PersonnelSelectionRequest('t','d','1',None,'R','1',80,'U',[RuleRoleType.LEAD_EXECUTOR,RuleRoleType.MONITOR],['D'],[],'2026-07-19')
 assert e._fingerprint(a)==e._fingerprint(b) and e._fingerprint(a)!=e._fingerprint(PersonnelSelectionRequest('t','d','2',None,'R','1',80,'U',a.required_roles,a.domain_codes,[],'2026-07-19'))
 u=r.get_unit(p.primary_unit_id);doc=Document(tenant_id='t',source_system='fake',source_document_id='bounds');DomainRepository(c).save_document(doc)
 good=PersonnelSelectionMatch('t',doc.id,'1',RuleRoleType.LEAD_EXECUTOR,80,PersonnelSelectionDecision.SELECTED,'a'*64,unit_id=u['id'],personnel_id=p.id,explanation='x'*2000)
 r.append_selection_matches([good])
 with pytest.raises(Exception):r.append_selection_matches([PersonnelSelectionMatch('t',doc.id,'1',RuleRoleType.LEAD_EXECUTOR,80,PersonnelSelectionDecision.SELECTED,'a'*64,unit_id=u['id'],personnel_id=p.id,explanation='x'*2001)])

def test_warning_bound_and_sensitive_persistence_rejected():
 c,r,p=_engine();u=r.get_unit(p.primary_unit_id);doc=Document(tenant_id='t',source_system='fake',source_document_id='security');DomainRepository(c).save_document(doc)
 def m(explanation=None,warnings='["DOMAIN_NOT_MATCHED"]'):return PersonnelSelectionMatch('t',doc.id,'1',RuleRoleType.LEAD_EXECUTOR,80,PersonnelSelectionDecision.SELECTED,'a'*64,unit_id=u['id'],personnel_id=p.id,explanation=explanation,warnings_json=warnings)
 r.append_selection_matches([m()])
 for bad in (m(explanation='Authorization: Bearer fake'),m(explanation='https://tenant.sharepoint.example/file'),m(warnings='["free text"]'),m(warnings='["DOMAIN_NOT_MATCHED"]'*17)):
  with pytest.raises(Exception):r.append_selection_matches([m(),bad])
 assert len(r.list_selection_matches_for_document(doc.id,'1'))==1

def test_availability_blocked_diagnostic_persists_without_selection():
 c,r,p=_engine();u=r.get_unit(p.primary_unit_id);r.add_role_assignment(PersonnelRoleAssignment('t',p.id,u['id'],RuleRoleType.LEAD_EXECUTOR,'R',is_primary=True));r.add_domain_assignment(PersonnelDomainAssignment('t',p.id,'D',ResponsibilityLevel.PRIMARY));_availability(c,p,'LEAVE')
 doc=Document(tenant_id='t',source_system='fake',source_document_id='diag');DomainRepository(c).save_document(doc);q=PersonnelSelectionRequest('t',doc.id,'1',None,'R','1',90,'U',[RuleRoleType.LEAD_EXECUTOR],['D'],[],'2026-07-19')
 out=PersonnelSelectionEngine(r).evaluate(q,True);rows=r.list_selection_matches_for_document(doc.id,'1')
 assert out.role_recommendations[0].selected_personnel_id is None and len(rows)==1 and rows[0]['decision']=='NEEDS_CLASSIFICATION' and rows[0]['warnings_json']=='["AVAILABILITY_BLOCKED"]'

def test_availability_conflict_diagnostic_persists_once():
 c,r,p=_engine();u=r.get_unit(p.primary_unit_id);r.add_role_assignment(PersonnelRoleAssignment('t',p.id,u['id'],RuleRoleType.LEAD_EXECUTOR,'R',is_primary=True));r.add_domain_assignment(PersonnelDomainAssignment('t',p.id,'D',ResponsibilityLevel.PRIMARY));_availability(c,p,'AVAILABLE');_availability(c,p,'LEAVE')
 doc=Document(tenant_id='t',source_system='fake',source_document_id='diag2');DomainRepository(c).save_document(doc);q=PersonnelSelectionRequest('t',doc.id,'1',None,'R','1',90,'U',[RuleRoleType.LEAD_EXECUTOR],['D'],[],'2026-07-19')
 PersonnelSelectionEngine(r).evaluate(q,True);rows=r.list_selection_matches_for_document(doc.id,'1');assert len(rows)==1 and rows[0]['warnings_json']=='["AVAILABILITY_CONFLICT"]'

def test_required_role_completeness_and_co_executor_zero_policy():
 c,r,p=_engine();u=r.get_unit(p.primary_unit_id);r.add_role_assignment(PersonnelRoleAssignment('t',p.id,u['id'],RuleRoleType.LEADER,'L',is_primary=True));q=PersonnelSelectionRequest('t','d','1',None,'R','1',90,'U',[RuleRoleType.CO_EXECUTOR,RuleRoleType.LEADER,RuleRoleType.LEAD_EXECUTOR,RuleRoleType.LEADER],['D'],[],'2026-07-19',0)
 out=PersonnelSelectionEngine(r).evaluate(q);assert [x.role_type for x in out.role_recommendations]==[RuleRoleType.LEADER,RuleRoleType.LEAD_EXECUTOR,RuleRoleType.CO_EXECUTOR] and set(out.unresolved_roles)=={RuleRoleType.LEAD_EXECUTOR,RuleRoleType.CO_EXECUTOR} and out.overall_confidence==75

def test_co_executor_direct_substitute_is_capped_without_conflict():
 c,r,a=_engine();u=r.get_unit(a.primary_unit_id);b=PersonnelRecord('t','B',1,'B');d=PersonnelRecord('t','C',1,'C');r.create_personnel(b);r.create_personnel(d)
 for p in (a,b,d):r.add_role_assignment(PersonnelRoleAssignment('t',p.id,u['id'],RuleRoleType.CO_EXECUTOR,'C',is_primary=True));r.add_domain_assignment(PersonnelDomainAssignment('t',p.id,'D',ResponsibilityLevel.PRIMARY))
 _availability(c,a,'LEAVE');_sub(c,a,b,u['id'],RuleRoleType.CO_EXECUTOR);_sub(c,a,d,u['id'],RuleRoleType.CO_EXECUTOR)
 q=PersonnelSelectionRequest('t','d','1',None,'R','1',100,'U',[RuleRoleType.CO_EXECUTOR],['D'],[],'2026-07-19',2)
 out=PersonnelSelectionEngine(r).evaluate(q).role_recommendations[0]
 assert out.decision==PersonnelSelectionDecision.SELECTED_WITH_WARNING and len(out.selected_personnel_ids)==2 and out.confidence==80 and out.decision!=PersonnelSelectionDecision.CONFLICT

def test_co_executor_shortfall_remains_unresolved_after_partial_selection():
 c,r,a=_engine();u=r.get_unit(a.primary_unit_id);r.add_role_assignment(PersonnelRoleAssignment('t',a.id,u['id'],RuleRoleType.CO_EXECUTOR,'C',is_primary=True));r.add_domain_assignment(PersonnelDomainAssignment('t',a.id,'D',ResponsibilityLevel.PRIMARY))
 q=PersonnelSelectionRequest('t','d','1',None,'R','1',100,'U',[RuleRoleType.CO_EXECUTOR],['D'],[],'2026-07-19',2);out=PersonnelSelectionEngine(r).evaluate(q);rec=out.role_recommendations[0]
 assert rec.selected_personnel_ids==[a.id] and {'CO_EXECUTOR_COUNT_SHORTFALL','REQUIRED_ROLE_UNRESOLVED'}.issubset(rec.warnings) and RuleRoleType.CO_EXECUTOR in out.unresolved_roles

def _co_executor_case(primary_status='ACTIVE', primary_available=True):
 c,r,a=_engine();u=r.get_unit(a.primary_unit_id);b=PersonnelRecord('t','B',1,'B');r.create_personnel(b)
 for p in (a,b):r.add_role_assignment(PersonnelRoleAssignment('t',p.id,u['id'],RuleRoleType.CO_EXECUTOR,'C',is_primary=True));r.add_domain_assignment(PersonnelDomainAssignment('t',p.id,'D',ResponsibilityLevel.PRIMARY))
 if primary_status != 'ACTIVE':c.execute('UPDATE personnel_records SET status=? WHERE id=?',(primary_status,a.id));c.commit()
 if not primary_available:_availability(c,a,'LEAVE')
 _sub(c,a,b,u['id'],RuleRoleType.CO_EXECUTOR)
 return c,r,a,b,u,PersonnelSelectionRequest('t','d','1',None,'R','1',100,'U',[RuleRoleType.CO_EXECUTOR],['D'],[],'2026-07-19',1)

def _co_executor_chain_case(backup_available=False):
 c,r,a=_engine();u=r.get_unit(a.primary_unit_id);b=PersonnelRecord('t','B',1,'B');d=PersonnelRecord('t','C',1,'C');r.create_personnel(b);r.create_personnel(d)
 for p in (a,b,d):r.add_role_assignment(PersonnelRoleAssignment('t',p.id,u['id'],RuleRoleType.CO_EXECUTOR,'C',is_primary=True));r.add_domain_assignment(PersonnelDomainAssignment('t',p.id,'D',ResponsibilityLevel.PRIMARY))
 _availability(c,a,'LEAVE')
 if not backup_available:_availability(c,b,'LEAVE')
 _sub(c,a,b,u['id'],RuleRoleType.CO_EXECUTOR);_sub(c,b,d,u['id'],RuleRoleType.CO_EXECUTOR)
 return c,r,a,b,d,u,PersonnelSelectionRequest('t','d','1',None,'R','1',100,'U',[RuleRoleType.CO_EXECUTOR],['D'],[],'2026-07-19',1)

def test_co_executor_inactive_primary_uses_direct_substitute_and_active_primary_does_not():
 c,r,a,b,u,q=_co_executor_case('INACTIVE');engine=PersonnelSelectionEngine(r);out=engine.evaluate(q);rec=out.role_recommendations[0]
 assert rec.selected_personnel_ids==[b.id] and rec.decision==PersonnelSelectionDecision.SELECTED_WITH_WARNING and rec.confidence==80 and rec.warnings==['SUBSTITUTE_USED']
 assert [x for x in engine.all_evaluations if x.personnel_id==b.id][0].is_substitute
 c,r,a,b,u,q=_co_executor_case();out=PersonnelSelectionEngine(r).evaluate(q);rec=out.role_recommendations[0]
 assert rec.selected_personnel_ids==[a.id] and 'SUBSTITUTE_USED' not in rec.warnings and b.id not in rec.selected_personnel_ids

def test_co_executor_chain_blocks_next_person_and_retains_shortfall_unresolved():
 c,r,a,b,d,u,q=_co_executor_chain_case();out=PersonnelSelectionEngine(r).evaluate(q);rec=out.role_recommendations[0]
 assert not rec.selected_personnel_ids and {'SUBSTITUTION_CHAIN_UNSUPPORTED','CO_EXECUTOR_COUNT_SHORTFALL','REQUIRED_ROLE_UNRESOLVED'}.issubset(rec.warnings)
 assert RuleRoleType.CO_EXECUTOR in out.unresolved_roles and b.id not in rec.selected_personnel_ids and d.id not in rec.selected_personnel_ids

def test_co_executor_chain_uses_valid_direct_substitute_without_chain_warning():
 c,r,a,b,d,u,q=_co_executor_chain_case(backup_available=True);out=PersonnelSelectionEngine(r).evaluate(q);rec=out.role_recommendations[0]
 assert rec.selected_personnel_ids==[b.id] and rec.decision==PersonnelSelectionDecision.SELECTED_WITH_WARNING and 'SUBSTITUTION_CHAIN_UNSUPPORTED' not in rec.warnings and d.id not in rec.selected_personnel_ids

@pytest.mark.parametrize('edges',[('self',[('a','a')]),('two',[('a','b'),('b','a')]),('three',[('a','b'),('b','c'),('c','a')])])
def test_co_executor_cycle_guard_is_deterministic(edges):
 _,pairs=edges;c,r,a=_engine();u=r.get_unit(a.primary_unit_id);b=PersonnelRecord('t','B',1,'B');d=PersonnelRecord('t','C',1,'C');r.create_personnel(b);r.create_personnel(d);people={'a':a,'b':b,'c':d}
 cycle_people={person for edge in pairs for person in edge}
 for key in cycle_people:
  p=people[key];r.add_role_assignment(PersonnelRoleAssignment('t',p.id,u['id'],RuleRoleType.CO_EXECUTOR,'C',is_primary=True));r.add_domain_assignment(PersonnelDomainAssignment('t',p.id,'D',ResponsibilityLevel.PRIMARY))
 _availability(c,a,'LEAVE')
 for primary,substitute in pairs:_sub(c,people[primary],people[substitute],u['id'],RuleRoleType.CO_EXECUTOR)
 q=PersonnelSelectionRequest('t','d','1',None,'R','1',100,'U',[RuleRoleType.CO_EXECUTOR],['D'],[],'2026-07-19',1);first=PersonnelSelectionEngine(r).evaluate(q);second=PersonnelSelectionEngine(r).evaluate(q);rec=first.role_recommendations[0]
 assert not rec.selected_personnel_ids and {'SUBSTITUTION_CYCLE_DETECTED','CO_EXECUTOR_COUNT_SHORTFALL','REQUIRED_ROLE_UNRESOLVED'}.issubset(rec.warnings) and RuleRoleType.CO_EXECUTOR in first.unresolved_roles and first==second

@pytest.mark.parametrize('kind',[('tenant',RuleRoleType.CO_EXECUTOR,'other',None),('role',RuleRoleType.LEAD_EXECUTOR,'t',None),('expired',RuleRoleType.CO_EXECUTOR,'t','2026-07-18')])
def test_irrelevant_co_executor_cycles_are_ignored(kind):
 _,role,tenant,effective_to=kind;c,r,a,b,u,q=_co_executor_case(primary_available=False)
 _sub(c,a,b,u['id'],role,tenant=tenant,effective_to=effective_to);_sub(c,b,a,u['id'],role,tenant=tenant,effective_to=effective_to)
 rec=PersonnelSelectionEngine(r).evaluate(q).role_recommendations[0]
 assert rec.selected_personnel_ids==[b.id] and 'SUBSTITUTION_CYCLE_DETECTED' not in rec.warnings

def test_co_executor_substitute_persistence_is_append_only_and_matches_nonpersistent_result():
 c,r,a,b,u,q=_co_executor_case(primary_available=False);doc=Document(tenant_id='t',source_system='fake',source_document_id='co-sub');DomainRepository(c).save_document(doc);q.document_id=doc.id
 nonpersistent=PersonnelSelectionEngine(r).evaluate(q,False);assert not r.list_selection_matches_for_document(doc.id,'1')
 persistent=PersonnelSelectionEngine(r).evaluate(q,True);rows=r.list_selection_matches_for_document(doc.id,'1');assert persistent==nonpersistent
 substitute_rows=[row for row in rows if row['personnel_id']==b.id and row['role_type']=='CO_EXECUTOR'];assert len(substitute_rows)==1
 row=substitute_rows[0];assert row['unit_id']==u['id'] and row['score']==80 and row['decision']=='SELECTED_WITH_WARNING' and row['warnings_json']=='["SUBSTITUTE_USED"]' and len(row['input_fingerprint'])==64
 assert not [item for item in rows if item['personnel_id']==a.id and item['decision'] in ('SELECTED','SELECTED_WITH_WARNING')]
 PersonnelSelectionEngine(r).evaluate(q,True);after=r.list_selection_matches_for_document(doc.id,'1');assert len([item for item in after if item['personnel_id']==b.id and item['role_type']=='CO_EXECUTOR'])==2 and row in after and len({x['id'] for x in after})==len(after)

@pytest.mark.parametrize('case',[('chain',False),('cycle',True)])
def test_co_executor_chain_and_cycle_never_persist_an_unselected_person_as_selected(case):
 kind,is_cycle=case
 if is_cycle:
  c,r,a,b,u,q=_co_executor_case(primary_available=False);_sub(c,b,a,u['id'],RuleRoleType.CO_EXECUTOR);people={a.id,b.id}
 else:
  c,r,a,b,d,u,q=_co_executor_chain_case();people={b.id,d.id}
 doc=Document(tenant_id='t',source_system='fake',source_document_id='co-'+kind);DomainRepository(c).save_document(doc);q.document_id=doc.id
 PersonnelSelectionEngine(r).evaluate(q,True);rows=r.list_selection_matches_for_document(doc.id,'1')
 assert not [row for row in rows if row['personnel_id'] in people and row['decision'] in ('SELECTED','SELECTED_WITH_WARNING')]

def _temporal_substitute(role=RuleRoleType.LEAD_EXECUTOR,effective_from=None,effective_to=None):
 c,r,a=_engine();u=r.get_unit(a.primary_unit_id);b=PersonnelRecord('t','B',1,'B',effective_from=effective_from,effective_to=effective_to);r.create_personnel(b)
 for p in (a,b):r.add_role_assignment(PersonnelRoleAssignment('t',p.id,u['id'],role,role.value,is_primary=True));r.add_domain_assignment(PersonnelDomainAssignment('t',p.id,'D',ResponsibilityLevel.PRIMARY))
 _availability(c,a,'LEAVE');r.add_substitution(PersonnelSubstitution('t',a.id,b.id,role,unit_id=u['id'],status=SubstitutionStatus.ACTIVE))
 return c,r,a,b,u,PersonnelSelectionRequest('t','d','1',None,'R','1',100,'U',[role],['D'],[],'2026-07-19',1 if role==RuleRoleType.CO_EXECUTOR else 0)

def test_duplicate_role_and_domain_evidence_produces_one_canonical_candidate_without_self_conflict():
 c,r,p=_engine();u=r.get_unit(p.primary_unit_id)
 for code,priority in (('LEAD-A',1),('LEAD-B',5)):r.add_role_assignment(PersonnelRoleAssignment('t',p.id,u['id'],RuleRoleType.LEAD_EXECUTOR,code,is_primary=True,priority=priority))
 for domain,priority in (('D1',2),('D2',7)):r.add_domain_assignment(PersonnelDomainAssignment('t',p.id,domain,ResponsibilityLevel.PRIMARY,priority=priority))
 q=PersonnelSelectionRequest('t','d','1',None,'R','1',100,'U',[RuleRoleType.LEAD_EXECUTOR],['D1','D2'],[],'2026-07-19');engine=PersonnelSelectionEngine(r);rec=engine.evaluate(q).role_recommendations[0]
 evaluations=[item for item in engine.all_evaluations if item.personnel_id==p.id and item.role_type==RuleRoleType.LEAD_EXECUTOR]
 assert rec.selected_personnel_id==p.id and rec.decision!=PersonnelSelectionDecision.CONFLICT and len(evaluations)==1 and evaluations[0].score==100 and evaluations[0].role_priority==5 and evaluations[0].domain_priority==7 and evaluations[0].matched_role_codes==['LEAD-A','LEAD-B'] and evaluations[0].matched_domain_codes==['D1','D2']

def test_co_executor_identity_dedupe_applies_before_count_alternatives_and_persistence():
 c,r,p=_engine();u=r.get_unit(p.primary_unit_id);qperson=PersonnelRecord('t','Q',1,'Q',primary_unit_id=u['id']);rperson=PersonnelRecord('t','R',1,'R',primary_unit_id=u['id']);r.create_personnel(qperson);r.create_personnel(rperson)
 for code in ('CO-A','CO-B'):r.add_role_assignment(PersonnelRoleAssignment('t',p.id,u['id'],RuleRoleType.CO_EXECUTOR,code,is_primary=True))
 for person,code in ((qperson,'CO-Q'),(rperson,'CO-R')):r.add_role_assignment(PersonnelRoleAssignment('t',person.id,u['id'],RuleRoleType.CO_EXECUTOR,code,is_primary=True))
 for person in (p,qperson,rperson):r.add_domain_assignment(PersonnelDomainAssignment('t',person.id,'D',ResponsibilityLevel.PRIMARY))
 doc=Document(tenant_id='t',source_system='fake',source_document_id='identity');DomainRepository(c).save_document(doc);q=PersonnelSelectionRequest('t',doc.id,'1',None,'R','1',100,'U',[RuleRoleType.CO_EXECUTOR],['D'],[],'2026-07-19',2);engine=PersonnelSelectionEngine(r);rec=engine.evaluate(q,True).role_recommendations[0];rows=r.list_selection_matches_for_document(doc.id,'1')
 assert rec.selected_personnel_ids==[p.id,qperson.id] and len(rec.selected_personnel_ids)==len(set(rec.selected_personnel_ids)) and [item.personnel_id for item in rec.alternative_candidates]==[rperson.id]
 assert len([item for item in engine.all_evaluations if item.role_type==RuleRoleType.CO_EXECUTOR and item.personnel_id==p.id])==1 and len([row for row in rows if row['personnel_id']==p.id and row['role_type']=='CO_EXECUTOR'])==1

def test_canonicalization_prefers_direct_candidate_and_is_independent_of_source_order():
 c,r,p=_engine();e=PersonnelSelectionEngine(r);direct=PersonnelCandidateEvaluation(p.id,'P','P','u',RuleRoleType.LEAD_EXECUTOR,100,PersonnelSelectionDecision.SELECTED,False,['D'],['DIRECT'],[],'direct');substitute=PersonnelCandidateEvaluation(p.id,'P','P','u',RuleRoleType.LEAD_EXECUTOR,80,PersonnelSelectionDecision.SELECTED_WITH_WARNING,True,['D'],['SUB'],['SUBSTITUTE_USED'],'substitute')
 first=e._canonicalize_evaluations([substitute,direct]);second=e._canonicalize_evaluations([direct,substitute])
 assert first==second and len(first)==1 and not first[0].is_substitute and first[0].score==100 and first[0].warnings==[]

def test_multiple_substitution_rows_for_one_person_yield_one_substitute_candidate():
 c,r,a=_engine();u=r.get_unit(a.primary_unit_id);cprimary=PersonnelRecord('t','C',1,'C',primary_unit_id=u['id']);b=PersonnelRecord('t','B',1,'B');r.create_personnel(cprimary);r.create_personnel(b)
 for person in (a,cprimary,b):r.add_role_assignment(PersonnelRoleAssignment('t',person.id,u['id'],RuleRoleType.LEAD_EXECUTOR,'LEAD',is_primary=True));r.add_domain_assignment(PersonnelDomainAssignment('t',person.id,'D',ResponsibilityLevel.PRIMARY))
 _availability(c,a,'LEAVE');_availability(c,cprimary,'LEAVE');_sub(c,a,b,u['id']);_sub(c,cprimary,b,u['id'])
 q=PersonnelSelectionRequest('t','d','1',None,'R','1',100,'U',[RuleRoleType.LEAD_EXECUTOR],['D'],[],'2026-07-19');engine=PersonnelSelectionEngine(r);rec=engine.evaluate(q).role_recommendations[0]
 evaluations=[item for item in engine.all_evaluations if item.personnel_id==b.id and item.role_type==RuleRoleType.LEAD_EXECUTOR]
 assert rec.selected_personnel_id==b.id and len(evaluations)==1 and evaluations[0].is_substitute and evaluations[0].score==80 and evaluations[0].warnings==['SUBSTITUTE_USED']

@pytest.mark.parametrize('effective_from,effective_to,selected',[("2026-07-18",None,True),("2026-07-19",None,True),("2026-07-20",None,False),(None,"2026-07-20",True),(None,"2026-07-19",True),(None,"2026-07-18",False),(None,None,True)])
def test_substitute_personnel_effective_date_boundaries_are_inclusive(effective_from,effective_to,selected):
 c,r,a,b,u,q=_temporal_substitute(effective_from=effective_from,effective_to=effective_to);engine=PersonnelSelectionEngine(r);out=engine.evaluate(q);rec=out.role_recommendations[0]
 assert (rec.selected_personnel_id==b.id)==selected
 if not selected:
  diagnostics=[item for item in engine.all_evaluations if item.personnel_id==b.id];assert diagnostics and diagnostics[0].warnings==['PERSONNEL_OUTSIDE_EFFECTIVE_DATE'] and 'SUBSTITUTE_USED' not in diagnostics[0].warnings and RuleRoleType.LEAD_EXECUTOR in out.unresolved_roles

def test_substitute_version_gap_and_overlap_are_not_auto_selected():
 c,r,a,b,u,q=_temporal_substitute(effective_to='2026-07-18');future=PersonnelRecord('t','B',2,'B future',effective_from='2026-07-20');r.create_personnel(future);out=PersonnelSelectionEngine(r).evaluate(q);assert out.role_recommendations[0].selected_personnel_id is None
 c,r,a,b,u,q=_temporal_substitute();overlap=PersonnelRecord('t','B',2,'B overlap');r._insert_personnel(overlap);c.commit();engine=PersonnelSelectionEngine(r);out=engine.evaluate(q);diagnostics=[item for item in engine.all_evaluations if item.personnel_id==b.id]
 assert out.role_recommendations[0].selected_personnel_id is None and diagnostics and diagnostics[0].warnings==['PERSONNEL_DIRECTORY_INCOMPLETE']

@pytest.mark.parametrize('role',[RuleRoleType.LEADER,RuleRoleType.MONITOR,RuleRoleType.LEAD_EXECUTOR,RuleRoleType.CO_EXECUTOR])
def test_all_roles_reject_future_dated_substitute_personnel(role):
 c,r,a,b,u,q=_temporal_substitute(role,effective_from='2026-07-20');out=PersonnelSelectionEngine(r).evaluate(q);rec=out.role_recommendations[0]
 assert b.id not in rec.selected_personnel_ids and rec.selected_personnel_id is None and RuleRoleType(role) in out.unresolved_roles

def test_temporally_ineligible_substitute_is_not_persisted_as_selected():
 c,r,a,b,u,q=_temporal_substitute(effective_from='2026-07-20');doc=Document(tenant_id='t',source_system='fake',source_document_id='future-sub');DomainRepository(c).save_document(doc);q.document_id=doc.id
 PersonnelSelectionEngine(r).evaluate(q,True);rows=r.list_selection_matches_for_document(doc.id,'1')
 assert not [row for row in rows if row['personnel_id']==b.id and row['decision'] in ('SELECTED','SELECTED_WITH_WARNING')] and [row for row in rows if row['personnel_id']==b.id and row['warnings_json']=='["PERSONNEL_OUTSIDE_EFFECTIVE_DATE"]']

def _direct_and_substitute_identity(substitution_first=False):
 c,r,a=_engine();u=r.get_unit(a.primary_unit_id);b=PersonnelRecord('t','B',1,'B direct',primary_unit_id=u['id']);r.create_personnel(b)
 r.add_role_assignment(PersonnelRoleAssignment('t',a.id,u['id'],RuleRoleType.LEAD_EXECUTOR,'LEAD',is_primary=True));r.add_domain_assignment(PersonnelDomainAssignment('t',a.id,'D',ResponsibilityLevel.PRIMARY));_availability(c,a,'LEAVE')
 if substitution_first:_sub(c,a,b,u['id'])
 for code in ('DIRECT-A','DIRECT-B'):r.add_role_assignment(PersonnelRoleAssignment('t',b.id,u['id'],RuleRoleType.LEAD_EXECUTOR,code,is_primary=True))
 for domain in ('D','D2'):r.add_domain_assignment(PersonnelDomainAssignment('t',b.id,domain,ResponsibilityLevel.PRIMARY))
 if not substitution_first:_sub(c,a,b,u['id'])
 q=PersonnelSelectionRequest('t','d','1',None,'R','1',100,'U',[RuleRoleType.LEAD_EXECUTOR],['D','D2'],[],'2026-07-19')
 return c,r,a,b,u,q

@pytest.mark.parametrize('substitution_first',[False,True])
def test_direct_candidate_precedes_same_identity_substitute_independent_of_insert_order(substitution_first):
 c,r,a,b,u,q=_direct_and_substitute_identity(substitution_first);engine=PersonnelSelectionEngine(r);rec=engine.evaluate(q).role_recommendations[0];evaluations=[item for item in engine.all_evaluations if item.personnel_id==b.id]
 assert rec.selected_personnel_id==b.id and rec.confidence==100 and rec.warnings==[] and len(evaluations)==1 and not evaluations[0].is_substitute and evaluations[0].score==100 and evaluations[0].warnings==[] and evaluations[0].matched_role_codes==['DIRECT-A','DIRECT-B'] and evaluations[0].matched_domain_codes==['D','D2']

def test_direct_precedence_persists_one_uncapped_non_substitute_row():
 c,r,a,b,u,q=_direct_and_substitute_identity(True);doc=Document(tenant_id='t',source_system='fake',source_document_id='direct-precedence');DomainRepository(c).save_document(doc);q.document_id=doc.id
 PersonnelSelectionEngine(r).evaluate(q,True);rows=[row for row in r.list_selection_matches_for_document(doc.id,'1') if row['personnel_id']==b.id]
 assert len(rows)==1 and rows[0]['score']==100 and rows[0]['decision']=='SELECTED' and rows[0]['warnings_json']=='[]'

def test_ineligible_direct_path_retains_substitute_only_cap_and_warning():
 c,r,a=_engine();u=r.get_unit(a.primary_unit_id);b=PersonnelRecord('t','B',1,'B substitute only');r.create_personnel(b)
 for person in (a,b):r.add_role_assignment(PersonnelRoleAssignment('t',person.id,u['id'],RuleRoleType.LEAD_EXECUTOR,'LEAD',is_primary=True));r.add_domain_assignment(PersonnelDomainAssignment('t',person.id,'D',ResponsibilityLevel.PRIMARY))
 _availability(c,a,'LEAVE');_sub(c,a,b,u['id']);q=PersonnelSelectionRequest('t','d','1',None,'R','1',100,'U',[RuleRoleType.LEAD_EXECUTOR],['D'],[],'2026-07-19');engine=PersonnelSelectionEngine(r);rec=engine.evaluate(q).role_recommendations[0];evaluation=[item for item in engine.all_evaluations if item.personnel_id==b.id][0]
 assert rec.selected_personnel_id==b.id and rec.confidence==80 and rec.warnings==['SUBSTITUTE_USED'] and evaluation.is_substitute and evaluation.score==80

def test_direct_precedence_is_not_global_between_different_personnel_identities():
 c,r,a=_engine();u=r.get_unit(a.primary_unit_id);direct=PersonnelRecord('t','C',1,'Direct',primary_unit_id=u['id']);substitute=PersonnelRecord('t','B',1,'Substitute');r.create_personnel(direct);r.create_personnel(substitute)
 for person,primary in ((a,True),(substitute,True),(direct,False)):r.add_role_assignment(PersonnelRoleAssignment('t',person.id,u['id'],RuleRoleType.MONITOR,'MONITOR',is_primary=primary))
 r.add_domain_assignment(PersonnelDomainAssignment('t',substitute.id,'D',ResponsibilityLevel.PRIMARY))
 _availability(c,a,'LEAVE');_sub(c,a,substitute,u['id'],RuleRoleType.MONITOR);q=PersonnelSelectionRequest('t','d','1',None,'R','1',100,'U',[RuleRoleType.MONITOR],['D'],[],'2026-07-19');rec=PersonnelSelectionEngine(r).evaluate(q).role_recommendations[0]
 assert rec.selected_personnel_id==substitute.id and rec.confidence==80 and rec.warnings==['SUBSTITUTE_USED'] and [item.personnel_id for item in rec.alternative_candidates]==[direct.id]

def test_co_executor_same_identity_direct_and_substitute_is_selected_once():
 c,r,a=_engine();u=r.get_unit(a.primary_unit_id);b=PersonnelRecord('t','B',1,'B direct',primary_unit_id=u['id']);d=PersonnelRecord('t','C',1,'C direct',primary_unit_id=u['id']);r.create_personnel(b);r.create_personnel(d)
 for person in (a,b,d):r.add_role_assignment(PersonnelRoleAssignment('t',person.id,u['id'],RuleRoleType.CO_EXECUTOR,'CO',is_primary=True));r.add_domain_assignment(PersonnelDomainAssignment('t',person.id,'D',ResponsibilityLevel.PRIMARY))
 _availability(c,a,'LEAVE');_sub(c,a,b,u['id'],RuleRoleType.CO_EXECUTOR);q=PersonnelSelectionRequest('t','d','1',None,'R','1',100,'U',[RuleRoleType.CO_EXECUTOR],['D'],[],'2026-07-19',2);engine=PersonnelSelectionEngine(r);rec=engine.evaluate(q).role_recommendations[0]
 evaluations=[item for item in engine.all_evaluations if item.personnel_id==b.id and item.role_type==RuleRoleType.CO_EXECUTOR]
 assert rec.selected_personnel_ids==[b.id,d.id] and len(set(rec.selected_personnel_ids))==2 and len(evaluations)==1 and not evaluations[0].is_substitute and evaluations[0].warnings==[]

def _ordered_direct_substitute_snapshot(substitution_before_current=False,reverse_roles=False,reverse_domains=False,reverse_substitutions=False,current_before_old=False):
 c,r,a=_engine();u=r.get_unit(a.primary_unit_id);backup_primary=PersonnelRecord('t','C',1,'Backup primary')
 r.create_personnel(backup_primary);old=PersonnelRecord('t','B',1,'B old',effective_to='2026-07-18');current=PersonnelRecord('t','B',2,'B direct',primary_unit_id=u['id'],effective_from='2026-07-19')
 if current_before_old:r.create_personnel(current);r.create_personnel(old)
 else:r.create_personnel(old)
 for person in (a,backup_primary):r.add_role_assignment(PersonnelRoleAssignment('t',person.id,u['id'],RuleRoleType.LEAD_EXECUTOR,'LEAD',is_primary=True))
 _availability(c,a,'LEAVE');_availability(c,backup_primary,'LEAVE')
 substitutions=[(a,old),(backup_primary,old)]
 if reverse_substitutions:substitutions.reverse()
 if substitution_before_current:
  for primary,substitute in substitutions:_sub(c,primary,substitute,u['id'])
 if not current_before_old:r.create_personnel(current)
 roles=[('DIRECT-A',1),('DIRECT-B',5)]
 domains=[('D1',2),('D2',7)]
 if reverse_roles:roles.reverse()
 if reverse_domains:domains.reverse()
 for code,priority in roles:r.add_role_assignment(PersonnelRoleAssignment('t',current.id,u['id'],RuleRoleType.LEAD_EXECUTOR,code,is_primary=True,priority=priority))
 for domain,priority in domains:r.add_domain_assignment(PersonnelDomainAssignment('t',current.id,domain,ResponsibilityLevel.PRIMARY,priority=priority))
 if not substitution_before_current:
  for primary,substitute in substitutions:_sub(c,primary,substitute,u['id'])
 doc=Document(tenant_id='t',source_system='fake',source_document_id='ordered-direct-substitute',id='ordered-direct-substitute');DomainRepository(c).save_document(doc);q=PersonnelSelectionRequest('t',doc.id,'1',None,'R','1',100,'U',[RuleRoleType.LEAD_EXECUTOR],['D1','D2'],[],'2026-07-19');engine=PersonnelSelectionEngine(r);out=engine.evaluate(q,True);rec=out.role_recommendations[0]
 source=lambda personnel_id:r.get_personnel(personnel_id)['source_person_key'] if personnel_id else None
 recommendation=(rec.selected_source_person_key,[source(personnel_id) for personnel_id in rec.selected_personnel_ids],rec.decision.value,rec.confidence,rec.warnings,rec.explanation,[(candidate.source_person_key,candidate.score,candidate.is_substitute,candidate.warnings,candidate.explanation) for candidate in rec.alternative_candidates],[role.value for role in out.unresolved_roles],[role.value for role in out.conflicting_roles])
 evaluations=sorted((item.source_person_key,item.role_type.value,item.score,item.decision.value,item.is_substitute,item.warnings,item.explanation,item.matched_role_codes,item.matched_domain_codes) for item in engine.all_evaluations)
 matches=sorted((source(row['personnel_id']),row['role_type'],row['decision'],row['score'],row['warnings_json'],row['explanation'],row['input_fingerprint']) for row in r.list_selection_matches_for_document(doc.id,'1'))
 return recommendation,evaluations,matches

def test_direct_substitute_recommendation_and_persistence_are_insert_order_independent():
 snapshots=[_ordered_direct_substitute_snapshot(**variant) for variant in (
  {},{'substitution_before_current':True},{'reverse_roles':True},{'reverse_domains':True},{'reverse_substitutions':True},{'current_before_old':True},{'substitution_before_current':True,'reverse_roles':True,'reverse_domains':True,'reverse_substitutions':True,'current_before_old':True})]
 assert all(snapshot==snapshots[0] for snapshot in snapshots)
 recommendation,evaluations,matches=snapshots[0]
 assert recommendation[0]=='B' and recommendation[2]=='SELECTED' and recommendation[3]==100 and recommendation[4]==[] and recommendation[6]==[] and recommendation[7]==[] and recommendation[8]==[]
 assert [item for item in evaluations if item[0]=='B']==[('B','LEAD_EXECUTOR',100,'SELECTED',False,[],'unit +30; role +25; domain +25; availability +10',['DIRECT-A','DIRECT-B'],['D1','D2'])]
 assert len({match[-1] for match in matches})==1
 assert [item for item in matches if item[0]=='B']==[('B','LEAD_EXECUTOR','SELECTED',100.0,'[]','unit +30; role +25; domain +25; availability +10',matches[0][-1])]
