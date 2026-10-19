"""Bounded live transport isolated from historical cache-only SilverClient."""
from datetime import datetime, timezone
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import threading
import urllib.request
from ..common import Blocked, digest, read, require, write
from .client import SilverClient

_LOCK=threading.Lock()


@contextmanager
def ledger_lock(directory):
    """Fail closed for a second process; a crash leaves a visible lock to inspect."""
    with _LOCK:
        path=Path(directory)/".reservation.lock"
        try:
            with path.open("x",encoding="ascii") as stream:stream.write(str(os.getpid()))
        except FileExistsError:
            raise Blocked("BLOCKED_LEDGER_BUSY_OR_STALE_LOCK; do not launch concurrent budget writers") from None
        try:yield
        finally:path.unlink()


class V2Client:
    def __init__(self, directory, config, *, api_key=None, transport=None):
        self.directory=Path(directory); self.config=config
        self.api_key=api_key or os.environ.get("DASHSCOPE_API_KEY")
        self.transport=transport or self._send
        require(config.get("authorized_cap_cny",0)>0 and config.get("max_calls",0)>0,
                "BLOCKED_BUDGET_AUTHORIZATION_REQUIRED")
        require(config["base_url"]=="https://dashscope.aliyuncs.com/compatible-mode/v1", "unapproved endpoint")
        require(config["model"]=="qwen-plus", "new model requires separate budget/pricing configuration")
        require(config["input_cny_per_million"]==0.8 and config["output_cny_per_million"]==2,
                "pricing changed; recheck the official tier before authorizing a new ledger")
        require(0<config["max_input_bytes"]<=60000 and 0<config["max_tokens"]<=3000,"unverified token/price tier")
        self.directory.mkdir(parents=True,exist_ok=True)
        with ledger_lock(self.directory):
            budget=self.directory/"budget.json"
            if budget.exists(): require(read(budget)==config, "budget config changed; use a new ledger")
            else: write(budget,config)

    def _send(self, request):
        require(bool(self.api_key), "BLOCKED_API_KEY_REQUIRED")
        req=urllib.request.Request(self.config["base_url"]+"/chat/completions",
             data=json.dumps(request,ensure_ascii=False,separators=(",",":")).encode(),
             headers={"Content-Type":"application/json","Authorization":"Bearer "+self.api_key})
        with urllib.request.urlopen(req,timeout=90) as response:
            return json.loads(response.read())

    def call(self,messages,*,prompt_version):
        request={"model":self.config["model"],"messages":messages,"temperature":0,
                 "enable_thinking":False,"stream":False,"max_tokens":self.config["max_tokens"],
                 "response_format":{"type":"json_object"}}
        key=digest({"endpoint":self.config["base_url"],"prompt_version":prompt_version,"request":request})
        path=self.directory/"cache"/(key+".json")
        attempt=self.directory/"attempts"/(key+".json")
        with ledger_lock(self.directory):
            if path.exists():
                cached=read(path)
                require(cached["request_sha256"]==digest(request) and cached["response_sha256"]==digest(cached["response"]), "V2 cache integrity")
                require(cached["prompt_version"]==prompt_version and cached["cache_key"]==key, "V2 cache identity")
                return SilverClient.decode(cached["response"]), {**cached,"cache_hit":True}
            require(not attempt.exists(), "prior uncertain/failed attempt retained; no automatic retry")
            require(bool(self.api_key) or self.transport!=self._send, "BLOCKED_API_KEY_REQUIRED")
            payload_bytes=len(json.dumps(request,ensure_ascii=False,separators=(",",":")).encode())
            require(payload_bytes<=self.config["max_input_bytes"], "BLOCKED_INPUT_SIZE_CAP")
            # UTF-8 bytes + overhead is deliberately more pessimistic than a chars/4 token estimate.
            reserve=((payload_bytes+1024)*self.config["input_cny_per_million"]+
                     self.config["max_tokens"]*self.config["output_cny_per_million"])/1e6
            attempts=list((self.directory/"attempts").glob("*.json"))
            used=sum(read(p)["reserved_cny"] for p in attempts)
            require(len(attempts)<self.config["max_calls"] and used+reserve<=self.config["authorized_cap_cny"], "BLOCKED_BUDGET_CAP")
            write(attempt,{"cache_key":key,"request_sha256":digest(request),"reserved_cny":reserve,
                           "status":"RESERVED_MAY_HAVE_BEEN_CHARGED","prompt_version":prompt_version,
                           "created_at":datetime.now(timezone.utc).isoformat()})
            write(self.directory/"requests"/(key+".json"),request)
        try:
            body=self.transport(request)
            cached={"cache_key":key,"request_sha256":digest(request),"response_sha256":digest(body),
                    "prompt_version":prompt_version,"requested_model":self.config["model"],
                    "returned_model":body.get("model"),"usage":body.get("usage"),"response":body,
                    "reserved_cny":reserve,"label_provenance":"QWEN_PLUS_SILVER","human_gold":False}
            write(path,cached)
            return SilverClient.decode(body),{**cached,"cache_hit":False}
        except Exception as exc:
            # No exception body: remote errors may contain private payloads or account details.
            write(self.directory/"failures"/(key+".json"),{"cache_key":key,"exception_type":type(exc).__name__,
                  "http_status":getattr(exc,"code",None),"reserved_cny":reserve,"retry_authorized":False})
            raise Blocked("V2 request failed; raw/uncertain attempt retained: "+type(exc).__name__) from None

    def report(self):
        attempts=[read(p) for p in (self.directory/"attempts").glob("*.json")]
        caches=[read(p) for p in (self.directory/"cache").glob("*.json")]
        prompt=sum((c.get("usage") or {}).get("prompt_tokens",0) for c in caches)
        completion=sum((c.get("usage") or {}).get("completion_tokens",0) for c in caches)
        return {"attempts":len(attempts),"responses":len(caches),"failures":len(list((self.directory/"failures").glob("*.json"))),
                "reserved_cny":sum(a["reserved_cny"] for a in attempts),"cap_cny":self.config["authorized_cap_cny"],
                "prompt_tokens":prompt,"completion_tokens":completion,
                "usage_priced_cny":(prompt*self.config["input_cny_per_million"]+completion*self.config["output_cny_per_million"])/1e6,
                "actual_invoice_cny":None,"model_requested":self.config["model"],
                "models_returned":sorted({c["returned_model"] for c in caches if c.get("returned_model")}),
                "unknown_cost_attempts":len(attempts)-sum(bool(c.get("usage")) for c in caches),
                "accounting":"All attempts retain pessimistic reservations, even after success. Invoice not available."}


def combined_report(directories,task_cap_cny=200):
    reports=[]
    for directory in directories:
        directory=Path(directory)
        reports.append(V2Client(directory,read(directory/"budget.json")).report())
    fields=("attempts","responses","failures","reserved_cny","prompt_tokens","completion_tokens","usage_priced_cny","unknown_cost_attempts")
    result={key:sum(r[key] for r in reports) for key in fields}
    require(result["reserved_cny"]<=task_cap_cny,"combined task budget cap exceeded")
    result.update(cap_cny=task_cap_cny,actual_invoice_cny=None,model_requested="qwen-plus",
                  models_returned=sorted({m for r in reports for m in r["models_returned"]}),
                  ledger_count=len(reports),accounting="Combined task-level usage and retained pessimistic reservations; not an invoice")
    return result
