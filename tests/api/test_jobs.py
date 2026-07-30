import io,os
from pathlib import Path
from PIL import Image
import pytest
from fastapi.testclient import TestClient
from redis import Redis
from app.main import app
from app.workers import tasks
pytestmark=pytest.mark.skipif(not os.getenv("REDIS_TEST_URL"),reason="requires CI Redis")
class Allow:
 async def check(self,request):return None
 async def close(self):return None
def upload():
 stream=io.BytesIO();Image.new("RGB",(20,20),"white").save(stream,"PNG");return {"file":("scan.png",stream.getvalue(),"image/png")}
@pytest.fixture
def redis():
 client=Redis.from_url(os.environ["REDIS_URL"],decode_responses=True);client.flushdb();yield client;client.flushdb();client.close()
def test_create_status_cancel_delete(monkeypatch,redis):
 monkeypatch.setattr(tasks.recognize_job,"send",lambda job_id:None)
 with TestClient(app) as client:
  app.state.rate_limiter=Allow();headers={"X-API-Key":"change-me"};created=client.post("/v1/jobs",headers=headers,files=upload()).json();job=created["job_id"];assert created["status"]=="queued" and created["version"]==1
  assert client.get(f"/v1/jobs/{job}",headers=headers).json()["progress"]==0
  cancelled=client.post(f"/v1/jobs/{job}/cancel",headers=headers);assert cancelled.status_code==200 and cancelled.json()["status"]=="cancelled"
  assert client.delete(f"/v1/jobs/{job}",headers=headers).status_code==204;assert redis.zcard("ocr:queue:jobs")==0
def test_atomic_queue_full_and_dispatch_cleanup(monkeypatch,redis):
 from app.core.config import get_settings
 settings=get_settings();redis.zadd("ocr:queue:jobs",{f"full-{i}":i for i in range(settings.max_queue_size)})
 with TestClient(app) as client:
  app.state.rate_limiter=Allow();headers={"X-API-Key":"change-me"};assert client.post("/v1/jobs",headers=headers,files=upload()).status_code==429
 redis.flushdb();monkeypatch.setattr(tasks.recognize_job,"send",lambda job_id:(_ for _ in ()).throw(RuntimeError("broker")))
 with TestClient(app) as client:
  app.state.rate_limiter=Allow();before=set(Path(get_settings().temp_dir).glob("input-*"));response=client.post("/v1/jobs",headers={"X-API-Key":"change-me"},files=upload());after=set(Path(get_settings().temp_dir).glob("input-*"));assert response.status_code==503 and before==after and redis.zcard("ocr:queue:jobs")==0
