import json
import inspect
import traceback
from pathlib import Path
import pytest
import requests
from tools.qlvb_downloader.planner_draft_handoff_v1_envelope import build_planner_draft_handoff_envelope_v1
from tools.qlvb_downloader.planner_draft_handoff_v1_models import PlannerDraftHandoffProjectionV1
from tools.qlvb_downloader.planner_draft_handoff_v1_sender import *
from tests.support.planner_fake_receiver import PlannerFakeReceiver

def envelope(version=1, tenant='tenant-a', doc='doc-a'):
 p=PlannerDraftHandoffProjectionV1('v1',tenant,tenant,'SMARTOFFICE_AI360',doc,'draft',version,None,'Title',None,None,None,'Summary','Action',({'action':'Action','citations':[{'page':1}],'provenance':{'id':'p'}},),'unit',None,('coord',),'reason',.8,('rule',),True,('review',),None,'HIGH',({'safe_url':'https://example.test/a'},),('p',),'test',(),True)
 return build_planner_draft_handoff_envelope_v1(p)
def response(e, duplicate=False, updated=False): return {'success':True,'draftId':'draft-id','status':'PENDING_OFFICE_REVIEW','duplicate':duplicate,'updated':updated,'acceptedSourceDocumentId':e.source_document_id,'acceptedSourceDraftVersion':e.source_draft_version,'acceptedPayloadFingerprint':e.payload_sha256,'contractVersion':'v1','correlationId':'c'}
@pytest.mark.parametrize('status,dup,upd,outcome',[(201,False,False,PlannerSendOutcome.CREATED),(200,True,False,PlannerSendOutcome.DUPLICATE),(200,False,True,PlannerSendOutcome.UPDATED)])
def test_sender_success(status,dup,upd,outcome):
 e=envelope();
 with PlannerFakeReceiver(status,response(e,dup,upd)) as fake:
  r=send_planner_handoff_v1(e,PlannerSenderConfig(fake.url,'issuer','secret',allow_insecure_loopback_for_tests=True)); assert r.outcome is outcome; assert len(fake.requests)==1; assert fake.requests[0][0:2]==('POST','/api/integrations/smartoffice/drafts'); assert json.loads(fake.requests[0][3])['canonicalPayload']['action_items']
def test_idempotency_and_security():
 assert derive_idempotency_key(' T ',' D ')==derive_idempotency_key('t','d'); assert derive_idempotency_key('t','d')!=derive_idempotency_key('t','x'); assert len(derive_idempotency_key('t','d'))==64
 assert 'secret' not in repr(PlannerSenderConfig('https://example.test/api/integrations/smartoffice/drafts','issuer','secret'))
 with pytest.raises(ValueError): PlannerSenderConfig('http://example.test/api/integrations/smartoffice/drafts','i','s')
def test_identity_redirect_and_size_rejected():
 e=envelope(); bad=response(e);bad['acceptedSourceDocumentId']='other'
 with PlannerFakeReceiver(201,bad) as f:
  with pytest.raises(PlannerSenderError) as x: send_planner_handoff_v1(e,PlannerSenderConfig(f.url,'i','s',allow_insecure_loopback_for_tests=True))
  assert x.value.code=='PLANNER_RESPONSE_IDENTITY_MISMATCH'
 with PlannerFakeReceiver(302,{}, {'Content-Type':'application/json','Location':'https://example.test'}) as f:
  with pytest.raises(PlannerSenderError) as x: send_planner_handoff_v1(e,PlannerSenderConfig(f.url,'i','s',allow_insecure_loopback_for_tests=True))
  assert x.value.code=='PLANNER_REDIRECT_REJECTED'
 with PlannerFakeReceiver(201,b'x'*100000,{'Content-Type':'application/json'}) as f:
  with pytest.raises(PlannerSenderError) as x: send_planner_handoff_v1(e,PlannerSenderConfig(f.url,'i','s',response_size_limit_bytes=32,allow_insecure_loopback_for_tests=True))
  assert x.value.code=='PLANNER_RESPONSE_TOO_LARGE'

@pytest.mark.parametrize('status,server_code,expected,retryable', [
 (400,None,'PLANNER_BAD_REQUEST',False),(401,'INVALID_AUTHENTICATION','INVALID_AUTHENTICATION',False),(403,'TENANT_MISMATCH','TENANT_MISMATCH',False),(404,None,'PLANNER_NOT_FOUND',False),(409,'SOURCE_VERSION_PAYLOAD_CONFLICT','SOURCE_VERSION_PAYLOAD_CONFLICT',False),(409,'STALE_SOURCE_VERSION','STALE_SOURCE_VERSION',False),(409,'SOURCE_DOCUMENT_ALREADY_FINALIZED','SOURCE_DOCUMENT_ALREADY_FINALIZED',False),(409,'IDEMPOTENCY_KEY_MISMATCH','IDEMPOTENCY_KEY_MISMATCH',False),(413,None,'PLANNER_PAYLOAD_TOO_LARGE',False),(415,None,'PLANNER_UNSUPPORTED_MEDIA_TYPE',False),(422,None,'PLANNER_VALIDATION_FAILED',False),(429,None,'PLANNER_RATE_LIMITED',True),(500,None,'PLANNER_TEMPORARY_FAILURE',True),(502,None,'PLANNER_TEMPORARY_FAILURE',True),(503,None,'PLANNER_TEMPORARY_FAILURE',True),(504,None,'PLANNER_TEMPORARY_FAILURE',True),(418,'UNTRUSTED','PLANNER_PERMANENT_FAILURE',False),(599,'UNTRUSTED','PLANNER_TEMPORARY_FAILURE',True)])
def test_http_error_matrix(status,server_code,expected,retryable):
 e=envelope(); body={'errorCode':server_code,'correlationId':'safe-correlation'} if server_code else {}
 with PlannerFakeReceiver(status,body) as f:
  with pytest.raises(PlannerSenderError) as x: send_planner_handoff_v1(e,PlannerSenderConfig(f.url,'issuer','secret',allow_insecure_loopback_for_tests=True))
  assert (x.value.code,x.value.retryable)==(expected,retryable); assert x.value.correlation_id == ('safe-correlation' if server_code else None); assert len(f.requests)==1; assert 'secret' not in str(x.value)

@pytest.mark.parametrize('body,headers,code',[(b'<html>private</html>',{'Content-Type':'text/html'},'PLANNER_BAD_REQUEST'),(b'{bad',{'Content-Type':'application/json'},'PLANNER_RESPONSE_JSON_INVALID')])
def test_non_json_and_malformed_error_safe(body,headers,code):
 with PlannerFakeReceiver(400,body,headers) as f:
  with pytest.raises(PlannerSenderError) as x: send_planner_handoff_v1(envelope(),PlannerSenderConfig(f.url,'i','s',allow_insecure_loopback_for_tests=True))
  assert x.value.code==code; assert 'private' not in str(x.value)

@pytest.mark.parametrize('body,headers,code',[(response(envelope()),{'Content-Type':'text/plain'},'PLANNER_RESPONSE_CONTENT_TYPE_INVALID'),(response(envelope()),{},'PLANNER_RESPONSE_CONTENT_TYPE_INVALID'),(b'{bad',{'Content-Type':'application/json'},'PLANNER_RESPONSE_JSON_INVALID'),([],{'Content-Type':'application/json'},'PLANNER_RESPONSE_SHAPE_INVALID'),({'success':False},{'Content-Type':'application/json'},'PLANNER_RESPONSE_SHAPE_INVALID'),({'success':True},{'Content-Type':'application/json'},'PLANNER_RESPONSE_IDENTITY_MISMATCH')])
def test_success_protocol_matrix(body,headers,code):
 with PlannerFakeReceiver(201,body,headers) as f:
  with pytest.raises(PlannerSenderError) as x: send_planner_handoff_v1(envelope(),PlannerSenderConfig(f.url,'i','s',allow_insecure_loopback_for_tests=True))
  assert x.value.code==code

def test_unsafe_correlation_omitted():
 e=envelope(); b=response(e); b['correlationId']='bad\nheader'
 with PlannerFakeReceiver(201,b) as f: assert send_planner_handoff_v1(e,PlannerSenderConfig(f.url,'i','s',allow_insecure_loopback_for_tests=True)).safe_correlation_id is None

@pytest.mark.parametrize('exc,code',[ (requests.ConnectTimeout('host:1'),'PLANNER_CONNECT_TIMEOUT'),(requests.ReadTimeout('host:1'),'PLANNER_READ_TIMEOUT'),(requests.Timeout('host:1'),'PLANNER_READ_TIMEOUT'),(requests.ConnectionError('host:1'),'PLANNER_CONNECTION_FAILED'),(requests.RequestException('host:1'),'PLANNER_TRANSPORT_FAILURE')])
def test_transport_errors_safe(exc,code):
 class Session:
  def __init__(self): self.calls=[]
  def post(self,*a,**kw): self.calls.append(kw); raise exc
 s=Session()
 with pytest.raises(PlannerSenderError) as x: send_planner_handoff_v1(envelope(),PlannerSenderConfig('http://127.0.0.1:1/api/integrations/smartoffice/drafts','issuer','secret',allow_insecure_loopback_for_tests=True),s)
 assert x.value.code==code and x.value.retryable and 'host' not in str(x.value) and 'secret' not in str(x.value); assert s.calls[0]['timeout']==(3,10) and s.calls[0]['allow_redirects'] is False

@pytest.mark.parametrize('value', [0,-1,float('nan'),float('inf')])
def test_invalid_timeouts_rejected(value):
 with pytest.raises(ValueError): PlannerSenderConfig('http://127.0.0.1:1/api/integrations/smartoffice/drafts','i','s',connect_timeout_seconds=value,allow_insecure_loopback_for_tests=True)

def test_tls_failure_and_https_policy():
 class Session:
  def __init__(self): self.calls=[]
  def post(self,*a,**kw): self.calls.append(kw); raise requests.exceptions.SSLError('certificate host secret')
 s=Session()
 with pytest.raises(PlannerSenderError) as x: send_planner_handoff_v1(envelope(),PlannerSenderConfig('https://example.test/api/integrations/smartoffice/drafts','issuer','secret'),s)
 assert x.value.code=='PLANNER_TLS_FAILURE' and not x.value.retryable and 'certificate' not in str(x.value) and s.calls[0]['verify'] is True
 for url,flag in [('http://example.test/api/integrations/smartoffice/drafts',False),('http://127.0.0.1:1/api/integrations/smartoffice/drafts',False),('http://example.test/api/integrations/smartoffice/drafts',True),('https://example.test/other',False),('https://user:pass@example.test/api/integrations/smartoffice/drafts',False),('https://example.test/api/integrations/smartoffice/drafts?q=1',False)]:
  with pytest.raises(ValueError): PlannerSenderConfig(url,'i','s',allow_insecure_loopback_for_tests=flag)

def test_real_loopback_read_timeout():
 e=envelope()
 with PlannerFakeReceiver(201,response(e),mode='HOLD_BEFORE_RESPONSE') as f:
  with pytest.raises(PlannerSenderError) as x: send_planner_handoff_v1(e,PlannerSenderConfig(f.url,'i','s',read_timeout_seconds=.05,allow_insecure_loopback_for_tests=True))
  assert f.request_received.is_set() and x.value.code=='PLANNER_READ_TIMEOUT' and x.value.retryable and len(f.requests)==1
  f.release_response.set()

def test_real_loopback_close_before_response():
 e=envelope()
 with PlannerFakeReceiver(201,response(e),mode='CLOSE_BEFORE_RESPONSE') as f:
  with pytest.raises(PlannerSenderError) as x: send_planner_handoff_v1(e,PlannerSenderConfig(f.url,'i','s',allow_insecure_loopback_for_tests=True))
  assert x.value.code=='PLANNER_CONNECTION_CLOSED' and x.value.retryable and len(f.requests)==1

def test_real_loopback_aborted_response_body():
 e=envelope()
 with PlannerFakeReceiver(201,b'{}',mode='ABORT_RESPONSE_BODY') as f:
  with pytest.raises(PlannerSenderError) as x: send_planner_handoff_v1(e,PlannerSenderConfig(f.url,'i','s',allow_insecure_loopback_for_tests=True))
  assert x.value.code=='PLANNER_CONNECTION_CLOSED' and x.value.retryable and len(f.requests)==1

def test_https_verify_is_fixed_and_config_repr_is_redacted():
 class Session:
  def __init__(self): self.calls=[]
  def post(self,*a,**kw): self.calls.append(kw); raise requests.exceptions.SSLError('CERTIFICATE_VERIFY_FAILED_SENTINEL')
 for flag in (False,True):
  config=PlannerSenderConfig('https://raw-host.example:65530/api/integrations/smartoffice/drafts','ISSUER_SENTINEL','SECRET_SENTINEL',allow_insecure_loopback_for_tests=flag)
  with pytest.raises(PlannerSenderError) as caught: send_planner_handoff_v1(envelope(),config,Session())
  assert caught.value.code=='PLANNER_TLS_FAILURE' and not caught.value.retryable
  assert 'raw-host.example' not in repr(config) and '65530' not in str(config) and 'ISSUER_SENTINEL' not in repr(config) and 'SECRET_SENTINEL' not in str(config)
  assert caught.value.__cause__ is None and caught.value.__context__ is None
  session=Session()
  with pytest.raises(PlannerSenderError): send_planner_handoff_v1(envelope(),config,session)
  assert len(session.calls)==1 and session.calls[0]['verify'] is True
 loopback=PlannerSenderConfig('http://127.0.0.1:1/api/integrations/smartoffice/drafts','i','s',allow_insecure_loopback_for_tests=True)
 assert loopback.allow_insecure_loopback_for_tests is True
 for url,flag in [('http://127.0.0.1:1/api/integrations/smartoffice/drafts',False),('http://example.test/api/integrations/smartoffice/drafts',True)]:
  with pytest.raises(ValueError): PlannerSenderConfig(url,'i','s',allow_insecure_loopback_for_tests=flag)
 assert 'verify' not in inspect.signature(send_planner_handoff_v1).parameters
 source=Path('tools/qlvb_downloader/planner_draft_handoff_v1_sender.py').read_text(encoding='utf-8')
 assert 'verify=False' not in source and 'verify=not' not in source

def test_transport_errors_have_no_exception_chain_or_traceback_leakage():
 class Session:
  def __init__(self,exc): self.exc=exc; self.calls=[]
  def post(self,*a,**kw): self.calls.append(kw); raise self.exc
 sentinels=('raw-host.example','65530','CERTIFICATE_VERIFY_FAILED_SENTINEL','SECRET_SENTINEL','ENDPOINT_SENTINEL','ISSUER_SENTINEL')
 for exc,code in ((requests.exceptions.SSLError('raw-host.example:65530 CERTIFICATE_VERIFY_FAILED_SENTINEL SECRET_SENTINEL ENDPOINT_SENTINEL ISSUER_SENTINEL'),'PLANNER_TLS_FAILURE'),(requests.ConnectionError('raw-host.example:65530 SECRET_SENTINEL'),'PLANNER_CONNECTION_FAILED')):
  session=Session(exc)
  config=PlannerSenderConfig('https://raw-host.example:65530/api/integrations/smartoffice/drafts','ISSUER_SENTINEL','SECRET_SENTINEL')
  with pytest.raises(PlannerSenderError) as caught: send_planner_handoff_v1(envelope(),config,session)
  error=caught.value; rendered=''.join(traceback.format_exception(error))
  assert error.code==code and error.__cause__ is None and error.__context__ is None and len(session.calls)==1
  assert all(value not in str(error)+repr(error)+repr(vars(error))+rendered for value in sentinels)
  assert all(not isinstance(value, (BaseException, requests.Response)) for value in vars(error).values())
