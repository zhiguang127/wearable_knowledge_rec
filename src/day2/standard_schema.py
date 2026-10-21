"""Standards-valid equivalent of an empty evidence-ID domain, for offline QA.

The raw tool request schemas remain unchanged. JSON Schema requires nonempty
enum arrays, so an array whose only item domain was enum=[] is represented as
maxItems=0 instead. The permitted outputs are identical, including no foreign ID.
"""
from copy import deepcopy

from jsonschema import Draft202012Validator

from ..common import require


def standard_schema(schema):
    result=deepcopy(schema)
    def visit(node):
        if not isinstance(node,dict):return
        if node.get("type")=="array" and node.get("items",{}).get("enum")==[]:
            node["items"].pop("enum")
            node["maxItems"]=0
        require(node.get("enum")!=[],"unhandled empty scalar enum")
        for v in node.values():
            if isinstance(v,dict):visit(v)
            elif isinstance(v,list):
                for child in v:
                    if isinstance(child,dict):visit(child)
    visit(result)
    Draft202012Validator.check_schema(result)
    return result


def standard_errors(output,schema):
    return [str(e.message) for e in Draft202012Validator(standard_schema(schema)).iter_errors(output)]
