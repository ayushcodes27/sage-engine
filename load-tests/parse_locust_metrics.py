import os

def extract_tail(filepath, outpath, num_lines=200):
    try:
        with open(filepath, 'r', encoding='utf-16') as f:
            lines = f.readlines()
    except UnicodeError:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()

    tail = lines[-num_lines:]
    
    with open(outpath, 'w', encoding='utf-8') as out:
        out.writelines(tail)
        
    print(f"Dumped the last {len(tail)} lines to {outpath}")

if __name__ == "__main__":
    extract_tail("load-tests/locust_5m_gateway_balanced_v5.txt", "load-tests/locust_tail.txt")
