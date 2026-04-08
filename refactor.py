import re

with open("backend/superchecker.py", "r") as f:
    content = f.read()

# Split the content into three parts:
# 1. Before '    def _check_disk_latency(self):' (this is where the dummy methods start)
# 2. Between 'def compute_diff' and 'if False:'
# 3. Inside 'if False:'

part1 = content.split('    def _check_disk_latency(self):')[0]

# find compute_diff
diff_idx = content.find('def compute_diff')
diff_part = content[diff_idx:content.find('if False:')]

# find if False:
false_idx = content.find('if False:')
false_part = content[false_idx + len('if False:'):]

# Extract the helpers at the end
helpers_idx = false_part.find('def _to_float(value) -> float:')
helpers_part = false_part[helpers_idx:]

false_methods = false_part[:helpers_idx]

# Remove the extra 4 spaces from the false_methods?
# Wait, they are already indentimport re

with open("backend/superchecker.py", "r") as f:
    content = f.read()

# Split the content  a
with opck_    content = f.read()

# Split the content inpa
# Split the content se # 1. Before '    def _check_diskey# 2. Between 'def compute_diff' and 'if False:'
# 3. Inside 'if False:'_c# 3. Inside 'if False:'

part1 = content.split('  su
part1 = content.split('  
  
# find compute_diff
diff_idx = content.find('def compute_diff'ritdiff_idx = content.wdiff_part = content[diff_idx:content.find('"if ba