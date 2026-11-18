"""Extract one explicitly named tokansh record from offline CLI list JSON."""
import importlib.util
import json
import sys
from pathlib import Path

spec=importlib.util.spec_from_file_location('deployment_checks',Path(__file__).with_name('deployment-checks.py'))
checks=importlib.util.module_from_spec(spec)
spec.loader.exec_module(checks)


def extract(value):
    checks.require(isinstance(value,dict) and 'chaincode_definitions' in value,
                   'Expected all-definitions response')
    definitions=value['chaincode_definitions']
    checks.require(isinstance(definitions,list), 'Expected definitions list')
    seen=set()
    selected=None
    for definition in definitions:
        checks.require(isinstance(definition,dict), 'Malformed definition entry')
        name=definition.get('name')
        checks.require(isinstance(name,str) and bool(name), 'Definition requires explicit name')
        checks.require(name not in seen, 'Duplicate chaincode definition name')
        seen.add(name)
        # Retain exact names and validate complete record shapes, including peers'
        # unrelated definitions. Never synthesize a name from a query argument.
        checks.named_definition(definition,name)
        if name=='tokansh':
            selected=definition
    checks.require(selected is not None, 'Missing tokansh definition')
    return selected


def main():
    checks.require(len(sys.argv)==3, 'Usage: ALL_DEFINITIONS OUTPUT_DEFINITION')
    try:
        result=extract(checks.load(sys.argv[1]))
        Path(sys.argv[2]).write_text(json.dumps(result,indent=2)+'\n')
    except (KeyError,TypeError,ValueError,AttributeError,OSError):
        raise SystemExit('Validation failed: malformed or incomplete definitions response') from None


if __name__=='__main__':main()
