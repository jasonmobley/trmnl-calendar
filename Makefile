.PHONY: install local dry-run validate build deploy deploy-ci delete clean

# ── Local development ────────────────────────────────────────────────────────

## Install dependencies into the local .venv via uv
install:
	uv sync

## Run the Lambda handler locally (loads .env automatically)
local:
	uv run python main.py

## Fetch real calendar data and print the POST body — no webhook call made
dry-run:
	DRY_RUN=1 uv run python main.py

# ── AWS SAM ──────────────────────────────────────────────────────────────────

## Validate the SAM template
validate:
	sam validate --template template.yaml

## Build the Lambda package (installs src/requirements.txt into the build dir)
build:
	sam build

## First-time guided deploy — prompts for parameters and creates samconfig.toml
deploy:
	sam deploy --guided

## Non-interactive deploy (uses existing samconfig.toml from a previous guided deploy)
deploy-ci:
	sam deploy

## Delete the CloudFormation stack and all associated AWS resources
delete:
	sam delete

## Remove SAM build artifacts
clean:
	rm -rf .aws-sam/

# ── Utilities ────────────────────────────────────────────────────────────────

## Quick smoke-test of the payload builder (no network calls)
test-payload:
	uv run python -c "\
import sys, json; sys.path.insert(0, 'src'); \
from trmnl_client import build_payload; \
p = build_payload( \
  'Friday, Mar 27', 'Saturday, Mar 28', \
  [ \
    {'time': 'All day', 'title': 'Good Friday'}, \
    {'time': '9 AM', 'end_time': '9:30 AM', 'title': 'Team Standup'}, \
    {'time': '2 PM', 'end_time': '3 PM', 'title': '1:1 with Manager'}, \
  ], \
  [ \
    {'time': '10 AM', 'end_time': '11 AM', 'title': 'Dog Park'}, \
  ] \
); \
print(json.dumps(p, indent=2)); \
print(f'--- Payload size: {len(json.dumps(p).encode())} bytes ---')"
