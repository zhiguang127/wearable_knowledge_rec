"""Run the fixed Day 3 stages explicitly, without an API client."""
import argparse
import json
from .importer import prepare, import_labels
from .evaluate import execute

parser=argparse.ArgumentParser()
parser.add_argument('stage',choices=['prepare','import','evaluate'])
args=parser.parse_args()
result={'prepare':prepare,'import':import_labels,'evaluate':execute}[args.stage]()
print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
