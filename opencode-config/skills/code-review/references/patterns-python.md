# Common Python Anti-Patterns

Quick lookup during the review pass. Each entry: bad pattern → why → correct form.

---

## Correctness

### C-01 Mutable default argument
```python
# WRONG
def process(items: list = []):
    items.append(new_item)

# RIGHT
def process(items: list | None = None):
    if items is None:
        items = []
    items.append(new_item)
```
The default list is created once at definition time and shared across all
calls. Silent cross-call state corruption.

---

### C-02 Bare except
```python
# WRONG
try:
    result = call()
except:
    pass

# RIGHT
try:
    result = call()
except Exception as e:
    logger.error("call failed: %s", e)
    raise
```
Catches SystemExit and KeyboardInterrupt. Hides every error silently.

---

### C-03 Naive datetime
```python
# WRONG
ts = datetime.utcnow()

# RIGHT
from datetime import datetime, timezone
ts = datetime.now(tz=timezone.utc)
```
`utcnow()` is **deprecated since Python 3.12** and scheduled for removal.
It returns a naive datetime (no tzinfo), which raises `TypeError` when
compared or combined with timezone-aware datetimes. Always use
`datetime.now(tz=timezone.utc)` which returns an aware datetime.

---

### C-04 Resource leak
```python
# WRONG
f = open("data.json")
data = json.load(f)

# RIGHT
with open("data.json") as f:
    data = json.load(f)
```

---

### C-05 Blocking call in async function
```python
# WRONG
async def fetch(url: str) -> dict:
    resp = requests.get(url)     # blocks the event loop
    return resp.json()

# RIGHT
async def fetch(url: str) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.get(url)
    return resp.json()
```

---

### C-06 Unchecked None return
```python
# WRONG
result = collection.query(...)
doc = result["documents"][0]    # crashes if result is None or empty

# RIGHT
result = collection.query(...)
if not result or not result.get("documents"):
    return []
doc = result["documents"][0]
```

---

### C-07 Dict mutation during iteration
```python
# WRONG
for key in my_dict:
    if should_remove(key):
        del my_dict[key]        # RuntimeError

# RIGHT
for key in list(my_dict):
    if should_remove(key):
        del my_dict[key]
```

---

## Design

### D-01 Magic number
```python
# WRONG
if score < 0.42:
    retry()

# RIGHT
QUALITY_THRESHOLD = 0.42  # empirically tuned; see docs/calibration.md
if score < QUALITY_THRESHOLD:
    retry()
```

---

### D-02 Boolean flag argument (should be an enum)
```python
# WRONG
def process(data, verbose=True):
    ...

# ALTERNATIVE — two functions (risk: code duplication between them)
def process(data): ...
def process_verbose(data): ...

# RIGHT — explicit enum; self-documenting at the call site
class Mode(Enum):
    SILENT = "silent"
    VERBOSE = "verbose"

def process(data, mode: Mode = Mode.SILENT): ...
# call site: process(data, Mode.VERBOSE)  — intent is clear
```

---

### D-03 Function too long
Any function > 50 lines is a decomposition candidate. Extract cohesive
sub-steps into private helpers named after what they do:
_build_payload, _validate_response, _parse_result — not _helper1.

---

### D-04 Implicit invariant with no guard
```python
# WRONG — caller can pass chunk_size <= overlap with no feedback
def chunk_text(text, chunk_size, overlap):
    ...

# RIGHT
def chunk_text(text, chunk_size: int, overlap: int) -> list[str]:
    if overlap >= chunk_size:
        raise ValueError(f"overlap ({overlap}) must be < chunk_size ({chunk_size})")
    ...
```

---

### D-05 import-time side effects
```python
# WRONG — runs code at import, breaks testing and CLI tools
import expensive_module          # expensive_module/__init__.py does DB connection

# RIGHT — defer to explicit init function
def setup():
    global _db
    _db = connect_db()
```

---

## HTTP / IO

### H-01 requests without timeout
```python
# WRONG
resp = requests.post(url, json=payload)

# RIGHT
resp = requests.post(url, json=payload, timeout=30)
```
Default is no timeout. A hung remote blocks the calling thread forever.
Default severity: MEDIUM. Projects where calls happen in a UI thread or
worker pool should override to HIGH in AGENTS.md.

---

### H-02 subprocess shell injection
```python
# WRONG
subprocess.run(f"mytool --input {path}", shell=True)

# RIGHT
subprocess.run(["mytool", "--input", str(path)], shell=False)
```

---

### H-03 Hardcoded secret
```python
# WRONG
API_KEY = "sk-abc123..."

# RIGHT
import os
API_KEY = os.environ["MY_API_KEY"]   # use [] not .get() — fail loudly at startup
```

---

### H-04 yaml.load on untrusted input
```python
# WRONG
config = yaml.load(f)

# RIGHT
config = yaml.safe_load(f)
```
