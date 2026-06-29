import subprocess
import os

with open("ml_logs.txt", "w") as f:
    result = subprocess.run(["docker", "logs", "sage-ml"], capture_output=True, text=True)
    f.write("STDOUT:\n")
    f.write(result.stdout)
    f.write("\nSTDERR:\n")
    f.write(result.stderr)
