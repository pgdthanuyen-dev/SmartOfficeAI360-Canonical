from __future__ import annotations

import hashlib, json
from dataclasses import dataclass, field
from datetime import date

from .assignment_rule_models import RuleRoleType
from .personnel_directory_models import PersonnelSelectionDecision, ResponsibilityLevel
from .personnel_directory_repository import PersonnelDirectoryRepository

PERSONNEL_SELECTION_ENGINE_VERSION = "g05b.selection.1"
PERSONNEL_CONFLICT_DELTA = 3.0

@dataclass
class PersonnelSelectionRequest:
    tenant_id: str; document_id: str; document_revision: str; assignment_rule_match_id: str | None
    assignment_rule_code: str; assignment_rule_version: str; rule_confidence: float; lead_unit_source_key: str
    required_roles: list[RuleRoleType]; domain_codes: list[str]; subdomain_codes: list[str]; reference_date: str
    requested_co_executor_count: int = 0; input_context_fingerprint: str | None = None

@dataclass
class PersonnelCandidateEvaluation:
    personnel_id: str; source_person_key: str; display_name: str; unit_id: str; role_type: RuleRoleType; score: float
    decision: PersonnelSelectionDecision; is_substitute: bool=False; matched_domain_codes: list[str]=field(default_factory=list)
    matched_role_codes: list[str]=field(default_factory=list); warnings: list[str]=field(default_factory=list); explanation: str=""; role_priority: int=0; domain_priority: int=0

@dataclass
class PersonnelRoleRecommendation:
    role_type: RuleRoleType; decision: PersonnelSelectionDecision; selected_personnel_id: str|None=None
    selected_source_person_key: str|None=None; selected_display_name: str|None=None; selected_personnel_ids: list[str]=field(default_factory=list)
    alternative_candidates: list[PersonnelCandidateEvaluation]=field(default_factory=list); confidence: float=0; warnings:list[str]=field(default_factory=list); explanation:str=""

@dataclass
class PersonnelSelectionRecommendation:
    document_id:str; document_revision:str; assignment_rule_match_id:str|None; unit_id:str|None; unit_source_key:str
    role_recommendations:list[PersonnelRoleRecommendation]; unresolved_roles:list[RuleRoleType]; conflicting_roles:list[RuleRoleType]
    overall_confidence:float; warnings:list[str]; explanation:str; input_fingerprint:str; engine_version:str=PERSONNEL_SELECTION_ENGINE_VERSION; evaluated_at:str=""

class PersonnelSelectionEngine:
    def __init__(self, repository: PersonnelDirectoryRepository): self.repository=repository
    def evaluate(self, request: PersonnelSelectionRequest, persist_matches: bool=False) -> PersonnelSelectionRecommendation:
        date.fromisoformat(request.reference_date)
        if not 0<=request.rule_confidence<=100 or not 0<=request.requested_co_executor_count<=10: raise ValueError("invalid selection request")
        fp=self._fingerprint(request); units=[u for u in self.repository.list_active_units(request.tenant_id,request.reference_date) if u['source_unit_key']==request.lead_unit_source_key]
        if len(units)!=1:
            warning='UNIT_NOT_FOUND' if not units else 'UNIT_VERSION_CONFLICT'
            roles=[PersonnelRoleRecommendation(r,PersonnelSelectionDecision.NEEDS_CLASSIFICATION,warnings=[warning]) for r in request.required_roles]
            return PersonnelSelectionRecommendation(request.document_id,request.document_revision,request.assignment_rule_match_id,None,request.lead_unit_source_key,roles,list(request.required_roles),[],0,[warning],warning,fp)
        unit=units[0]; recs=[]; unresolved=[]; conflicts=[]; self.all_evaluations=[]; selected_ids=set()
        role_order={RuleRoleType.LEADER:0,RuleRoleType.MONITOR:1,RuleRoleType.LEAD_EXECUTOR:2,RuleRoleType.CO_EXECUTOR:3}
        roles=sorted(set(request.required_roles),key=lambda role:role_order[role])
        for role in roles:
            candidates=self.collect_candidates(request,unit,role)
            if not candidates: candidates=self.resolve_substitute(request,unit,role)
            if role==RuleRoleType.CO_EXECUTOR: candidates=[candidate for candidate in candidates if candidate.personnel_id not in selected_ids]
            rec=self.select_for_role(role,candidates,request.requested_co_executor_count)
            if not candidates and getattr(self, 'substitution_warnings', []):
                rec.decision=PersonnelSelectionDecision.NEEDS_CLASSIFICATION
                rec.warnings=list(dict.fromkeys(
                    self.substitution_warnings
                    + (['CO_EXECUTOR_COUNT_SHORTFALL'] if role == RuleRoleType.CO_EXECUTOR and request.requested_co_executor_count else [])
                    + ['REQUIRED_ROLE_UNRESOLVED']
                ))
            recs.append(rec)
            if rec.decision in (PersonnelSelectionDecision.NO_ELIGIBLE_PERSON,PersonnelSelectionDecision.NEEDS_CLASSIFICATION,PersonnelSelectionDecision.CONFLICT) or 'REQUIRED_ROLE_UNRESOLVED' in rec.warnings:
                unresolved.append(role)
                if 'REQUIRED_ROLE_UNRESOLVED' not in rec.warnings: rec.warnings.append('REQUIRED_ROLE_UNRESOLVED')
            if rec.decision==PersonnelSelectionDecision.CONFLICT: conflicts.append(role)
            selected_ids.update(rec.selected_personnel_ids)
        if persist_matches: self.persist_selection_matches(request,unit,self.all_evaluations)
        chosen=[r.confidence for r in recs if r.selected_personnel_ids or r.selected_personnel_id]
        overall=min([request.rule_confidence,100,*chosen]) if chosen else 0
        warnings=['REQUIRED_ROLE_UNRESOLVED'] if unresolved else []
        return PersonnelSelectionRecommendation(request.document_id,request.document_revision,request.assignment_rule_match_id,unit['id'],unit['source_unit_key'],recs,sorted(set(unresolved),key=lambda role:role_order[role]),sorted(set(conflicts),key=lambda role:role_order[role]),overall,warnings,'personnel proposal only',fp)
    def collect_candidates(self, req, unit, role):
        substitute_ids={row['substitute_personnel_id'] for row in self.repository.conn.execute("SELECT substitute_personnel_id FROM personnel_substitutions WHERE tenant_id=? AND role_type=? AND status='ACTIVE' AND (unit_id IS NULL OR unit_id=?) AND (effective_from IS NULL OR effective_from<=?) AND (effective_to IS NULL OR effective_to>=?)",(req.tenant_id,role.value,unit['id'],req.reference_date,req.reference_date)).fetchall()}
        raw=[]
        for person in self.repository.list_active_personnel(req.tenant_id,req.reference_date):
            if person['id'] in substitute_ids: continue
            if person['primary_unit_id']!=unit['id']: continue
            for ra in self.repository.list_role_assignments(personnel_id=person['id'],role_type=role.value,as_of_date=req.reference_date):
                if ra['unit_id']!=unit['id']: continue
                availability=self.resolve_effective_availability(person['id'], req.tenant_id, req.reference_date)
                if not availability['is_available']:
                    warning=availability['warnings'][0]
                    raw.append(PersonnelCandidateEvaluation(person['id'],person['source_person_key'],person['full_name'],unit['id'],role,0,PersonnelSelectionDecision.NEEDS_CLASSIFICATION,False,[],[ra['role_code']],[warning],'Personnel is unavailable on the reference date.'))
                    continue
                domains=self.repository.list_domain_assignments(personnel_id=person['id'],as_of_date=req.reference_date)
                matched=[d for d in domains if d['domain_code'] in req.domain_codes or (d['subdomain_code'] and d['subdomain_code'] in req.subdomain_codes)]
                if role in (RuleRoleType.LEAD_EXECUTOR,RuleRoleType.CO_EXECUTOR) and not matched: continue
                level=max([{'PRIMARY':25,'SECONDARY':15,'SUPPORT':8}[d['responsibility_level']] for d in matched],default=0)
                domain_priority=max([d['priority'] for d in matched if {'PRIMARY':25,'SECONDARY':15,'SUPPORT':8}[d['responsibility_level']]==level],default=0)
                score=min(100,30+25+(10 if ra['is_primary'] else 0)+level+10)
                warn=[] if matched else ['DOMAIN_NOT_MATCHED']
                evaluation=PersonnelCandidateEvaluation(person['id'],person['source_person_key'],person['full_name'],unit['id'],role,score,PersonnelSelectionDecision.SELECTED if score>=90 else PersonnelSelectionDecision.SELECTED_WITH_WARNING,False,[d['domain_code'] for d in matched],[ra['role_code']],warn,f'unit +30; role +25; domain +{level}; availability +10',ra['priority'],domain_priority)
                raw.append(evaluation)
        canonical=self._canonicalize_evaluations(raw)
        self._record_evaluations(canonical)
        return self.rank_candidates([candidate for candidate in canonical if candidate.score > 0 and candidate.decision != PersonnelSelectionDecision.NEEDS_CLASSIFICATION])
    def rank_candidates(self,candidates): return sorted(self._canonicalize_evaluations(candidates),key=lambda c:(-c.score,c.source_person_key,c.personnel_id))
    def select_for_role(self,role,candidates,count):
        if not candidates:return PersonnelRoleRecommendation(role,PersonnelSelectionDecision.NO_ELIGIBLE_PERSON,warnings=['NO_ELIGIBLE_PERSON'])
        if role==RuleRoleType.CO_EXECUTOR:
            if count == 0:return PersonnelRoleRecommendation(role,PersonnelSelectionDecision.NEEDS_CLASSIFICATION,warnings=['REQUIRED_ROLE_UNRESOLVED'])
            chosen=[]; selected=set()
            for candidate in candidates:
                if candidate.score>=75 and candidate.personnel_id not in selected:
                    chosen.append(candidate); selected.add(candidate.personnel_id)
                if len(chosen)==count: break
            if not chosen:return PersonnelRoleRecommendation(role,PersonnelSelectionDecision.NO_ELIGIBLE_PERSON,warnings=['NO_ELIGIBLE_PERSON'])
            warnings=list(dict.fromkeys(warning for candidate in chosen for warning in candidate.warnings))
            if len(chosen)<count:warnings=list(dict.fromkeys(warnings+['CO_EXECUTOR_COUNT_SHORTFALL','REQUIRED_ROLE_UNRESOLVED']))
            alternatives=[candidate for candidate in candidates if candidate.personnel_id not in selected]
            return PersonnelRoleRecommendation(role,PersonnelSelectionDecision.SELECTED_WITH_WARNING if warnings or chosen[0].score<90 else PersonnelSelectionDecision.SELECTED,selected_personnel_ids=[c.personnel_id for c in chosen],alternative_candidates=alternatives,confidence=min([c.score for c in chosen],default=0),warnings=warnings)
        if len(candidates)>1 and candidates[0].personnel_id != candidates[1].personnel_id and candidates[0].score-candidates[1].score<=PERSONNEL_CONFLICT_DELTA:return PersonnelRoleRecommendation(role,PersonnelSelectionDecision.CONFLICT,alternative_candidates=candidates[:2],warnings=['PERSONNEL_CONFLICT','MULTIPLE_TOP_PERSONNEL'])
        c=candidates[0]; d=PersonnelSelectionDecision.SELECTED if c.score>=90 and not c.warnings else PersonnelSelectionDecision.SELECTED_WITH_WARNING if c.score>=75 else PersonnelSelectionDecision.NEEDS_CLASSIFICATION
        return PersonnelRoleRecommendation(role,d,c.personnel_id,c.source_person_key,c.display_name,[c.personnel_id],candidates[1:],c.score,c.warnings,c.explanation)
    def resolve_substitute(self,req,unit,role):
        rows=self.repository.conn.execute("SELECT * FROM personnel_substitutions WHERE tenant_id=? AND role_type=? AND status='ACTIVE' AND (unit_id IS NULL OR unit_id=?) AND (effective_from IS NULL OR effective_from<=?) AND (effective_to IS NULL OR effective_to>=?) ORDER BY primary_personnel_id,substitute_personnel_id,id",(req.tenant_id,role.value,unit['id'],req.reference_date,req.reference_date)).fetchall()
        graph={}
        for row in rows: graph.setdefault(row['primary_personnel_id'],set()).add(row['substitute_personnel_id'])
        incoming={row['substitute_personnel_id'] for row in rows}; result=[]; seen=set(); self.substitution_warnings=[]
        roots=[row for row in rows if row['primary_personnel_id'] not in incoming]
        if not roots and rows:
            self.substitution_warnings=['SUBSTITUTION_CYCLE_DETECTED']; return []
        for row in roots:
            primary=self.repository.get_personnel(row['primary_personnel_id'])
            if not primary or primary['tenant_id']!=req.tenant_id: continue
            primary_roles=[x for x in self.repository.list_role_assignments(personnel_id=primary['id'],role_type=role.value,as_of_date=req.reference_date) if x['unit_id']==unit['id'] and x['is_primary']]
            if not primary_roles: continue
            if self._graph_reaches(graph,row['substitute_personnel_id'],primary['id']):
                self.substitution_warnings.append('SUBSTITUTION_CYCLE_DETECTED'); continue
            person, personnel_warning=self.resolve_effective_personnel_record(req.tenant_id,row['substitute_personnel_id'],req.reference_date)
            if personnel_warning:
                raw=self.repository.get_personnel(row['substitute_personnel_id'])
                if raw:
                    self._record_evaluations([PersonnelCandidateEvaluation(raw['id'],raw['source_person_key'],raw['full_name'],unit['id'],role,0,PersonnelSelectionDecision.NEEDS_CLASSIFICATION,False,[],[],[personnel_warning],'Substitute personnel record is not effective on the reference date.')])
                if graph.get(row['substitute_personnel_id']): self.substitution_warnings.append('SUBSTITUTION_CHAIN_UNSUPPORTED')
                continue
            if self._availability(person['id'],req.reference_date)!='AVAILABLE':
                if graph.get(row['substitute_personnel_id']): self.substitution_warnings.append('SUBSTITUTION_CHAIN_UNSUPPORTED')
                continue
            for ra in self.repository.list_role_assignments(personnel_id=person['id'],role_type=role.value,as_of_date=req.reference_date):
                if ra['unit_id']!=unit['id'] or person['id'] in seen: continue
                domains=self.repository.list_domain_assignments(personnel_id=person['id'],as_of_date=req.reference_date); matched=[d for d in domains if d['domain_code'] in req.domain_codes or (d['subdomain_code'] and d['subdomain_code'] in req.subdomain_codes)]
                if role in (RuleRoleType.LEAD_EXECUTOR,RuleRoleType.CO_EXECUTOR) and not matched:
                    if graph.get(row['substitute_personnel_id']): self.substitution_warnings.append('SUBSTITUTION_CHAIN_UNSUPPORTED')
                    continue
                level=max([{'PRIMARY':25,'SECONDARY':15,'SUPPORT':8}[d['responsibility_level']] for d in matched],default=0);domain_priority=max([d['priority'] for d in matched if {'PRIMARY':25,'SECONDARY':15,'SUPPORT':8}[d['responsibility_level']]==level],default=0);seen.add(person['id']); score=min(80,30+25+(10 if ra['is_primary'] else 0)+level+10)
                evaluation=PersonnelCandidateEvaluation(person['id'],person['source_person_key'],person['full_name'],unit['id'],role,score,PersonnelSelectionDecision.SELECTED_WITH_WARNING,True,[d['domain_code'] for d in matched],[ra['role_code']],['SUBSTITUTE_USED'],'Direct effective substitute; confidence capped at 80.',ra['priority'],domain_priority)
                result.append(evaluation)
        canonical=self._canonicalize_evaluations(result)
        self._record_evaluations(canonical)
        return self.rank_candidates(canonical)
    def _graph_reaches(self, graph, start, target):
        pending=[start]; seen=set()
        while pending:
            node=pending.pop()
            if node==target:return True
            if node not in seen:
                seen.add(node); pending.extend(sorted(graph.get(node,())))
        return False
    def resolve_effective_availability(self, personnel_id, tenant_id, reference_date):
        person = self.repository.get_personnel(personnel_id)
        if not person or person['tenant_id'] != tenant_id:
            return {'status': 'UNAVAILABLE', 'is_available': False, 'has_conflict': False, 'active_statuses': [], 'warnings': ['AVAILABILITY_BLOCKED']}
        statuses = sorted({row['availability_status'] for row in self.repository.list_availability(personnel_id) if row['unavailable_from'] <= reference_date and (row['unavailable_to'] is None or row['unavailable_to'] >= reference_date)})
        if not statuses or statuses == ['AVAILABLE']:
            return {'status': 'AVAILABLE', 'is_available': True, 'has_conflict': False, 'active_statuses': statuses or ['AVAILABLE'], 'warnings': []}
        if len(statuses) > 1:
            return {'status': 'AVAILABILITY_CONFLICT', 'is_available': False, 'has_conflict': True, 'active_statuses': statuses, 'warnings': ['AVAILABILITY_CONFLICT']}
        return {'status': statuses[0], 'is_available': False, 'has_conflict': False, 'active_statuses': statuses, 'warnings': ['AVAILABILITY_BLOCKED']}
    def _availability(self,personnel_id,as_of):
        person=self.repository.get_personnel(personnel_id)
        return self.resolve_effective_availability(personnel_id,person['tenant_id'],as_of)['status'] if person else 'UNAVAILABLE'
    def resolve_effective_personnel_record(self,tenant_id,personnel_id,reference_date):
        raw=self.repository.get_personnel(personnel_id)
        if not raw or raw['tenant_id']!=tenant_id:return None,'PERSONNEL_DIRECTORY_INCOMPLETE'
        effective=[person for person in self.repository.list_active_personnel(tenant_id,reference_date) if person['source_person_key']==raw['source_person_key']]
        if len(effective)==1:return effective[0],None
        return None,'PERSONNEL_OUTSIDE_EFFECTIVE_DATE' if not effective else 'PERSONNEL_DIRECTORY_INCOMPLETE'
    def _record_evaluations(self,evaluations):
        self.all_evaluations=self._canonicalize_evaluations([*self.all_evaluations,*evaluations])
    def _canonicalize_evaluations(self,evaluations):
        grouped={}
        for evaluation in evaluations: grouped.setdefault((evaluation.personnel_id,evaluation.role_type),[]).append(evaluation)
        canonical=[]
        for _,group in grouped.items():
            direct=[candidate for candidate in group if not candidate.is_substitute and candidate.score>0 and candidate.decision!=PersonnelSelectionDecision.NEEDS_CLASSIFICATION]
            candidates=direct or [candidate for candidate in group if candidate.is_substitute] or group
            best=sorted(candidates,key=lambda candidate:(-candidate.score,-candidate.role_priority,-candidate.domain_priority,candidate.source_person_key,candidate.personnel_id,candidate.explanation))[0]
            canonical.append(PersonnelCandidateEvaluation(best.personnel_id,best.source_person_key,best.display_name,best.unit_id,best.role_type,best.score,best.decision,bool(not direct and best.is_substitute),sorted({domain for candidate in candidates for domain in candidate.matched_domain_codes}),sorted({role_code for candidate in candidates for role_code in candidate.matched_role_codes}),sorted({warning for candidate in candidates for warning in candidate.warnings}),best.explanation,best.role_priority,best.domain_priority))
        return sorted(canonical,key=lambda candidate:(-candidate.score,candidate.source_person_key,candidate.personnel_id,candidate.role_type.value))
    def persist_selection_matches(self,req,unit,candidates):
        from .personnel_directory_models import PersonnelSelectionMatch
        self.repository.append_selection_matches([PersonnelSelectionMatch(req.tenant_id,req.document_id,req.document_revision,c.role_type,c.score,c.decision,self._fingerprint(req),assignment_rule_match_id=req.assignment_rule_match_id,unit_id=unit['id'],personnel_id=c.personnel_id,explanation=c.explanation,warnings_json=json.dumps(c.warnings,sort_keys=True,separators=(',',':'))) for c in candidates])
    def _fingerprint(self,r):
        data={'v':PERSONNEL_SELECTION_ENGINE_VERSION,'tenant':r.tenant_id,'document':r.document_id,'revision':r.document_revision,'match':r.assignment_rule_match_id,'unit':r.lead_unit_source_key,'roles':sorted({x.value for x in r.required_roles}),'domains':sorted(set(r.domain_codes)),'subdomains':sorted(set(r.subdomain_codes)),'date':r.reference_date}
        return hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def evaluate_personnel_selection(request:PersonnelSelectionRequest, repository:PersonnelDirectoryRepository, persist_matches:bool=False): return PersonnelSelectionEngine(repository).evaluate(request,persist_matches)
