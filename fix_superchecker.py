with open("backend/superchecker.py", "r") as f:
    lines = f.readlines()

out = []
in_stub = False
for i, line in enumerate(lines):
    if "def _check_disk_latency(self):" in line and i < 500:
        in_stub = True
    
    if "def _check_missing_checkers(self):" in line and i < 500:
        in_stub = False
        
    if not in_stub:
        out.append(line)

with open("backend/superchecker.py", "w") as f:
    f.writelines(out)
