"""Day 2 packet-size profile with the unchanged strict Day 1 ledger/decoder."""
import os
from pathlib import Path

from ..common import read, require, write
from ..annotation.c1_v2_client import ledger_lock
from ..day1.client import Day1Client


class Day2Client(Day1Client):
    def __init__(self, directory, config, *, api_key=None, transport=None):
        require(config.get("authorization_status")=="AUTHORIZED" and config.get("authorization_ref"), "Day 2 authorization required")
        require(config.get("day2_protocol")=="c1-day2-feasibility-v01" and config.get("scope")=="DAY1_RESEARCH", "wrong protocol")
        require(config.get("budget_mode")=="UNLIMITED" and config.get("authorized_cap_cny") is None and config.get("max_calls") is None,
                "do not introduce a new call or fee ceiling")
        require(config["model"]=="qwen3.8-max" and config["base_url"]=="https://dashscope.aliyuncs.com/compatible-mode/v1", "unexpected endpoint/model")
        require(config["input_cny_per_million"]==12 and config["output_cny_per_million"]==36 and
                0<config["max_input_bytes"]<=320000 and 0<config["max_tokens"]<=3000, "unverified official packet/price profile")
        self.directory, self.config = Path(directory), config
        self.api_key = api_key or os.environ.get("DASHSCOPE_API_KEY")
        self.transport = transport or self._send
        self.directory.mkdir(parents=True,exist_ok=True)
        with ledger_lock(self.directory):
            budget=self.directory/"budget.json"
            if budget.exists():
                require(read(budget)==config, "use a new ledger for changed config")
            else:
                write(budget,config)
